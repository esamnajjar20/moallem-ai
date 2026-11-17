"""Transactional outbox + inbox dedup rules (P4-03; Reliability Addendum v2.4 §2, §5).

Provider-independent semantics. PostgreSQL ``SKIP LOCKED`` is approved for the MVP (DEC-030);
retry ceilings and backoff values remain explicit caller inputs. Fencing: every claim bumps
``lease_generation``; a worker may commit only while its token is current.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from moallem.domain.errors import TaskStateConflict


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    aggregate_id: str
    event_type: str
    next_attempt_at: datetime
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    lease_generation: int = 0
    published_at: datetime | None = None
    last_error_code: str | None = None


def _aware(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")


def claim(event: OutboxEvent, *, owner: str, now: datetime, lease: timedelta) -> OutboxEvent:
    """PENDING (due) -> LEASED, or reclaim a LEASED row only after its lease expired."""
    _aware(now)
    if lease <= timedelta(0):
        raise ValueError("lease must be positive")
    if event.status is OutboxStatus.PENDING:
        if event.next_attempt_at > now:
            raise TaskStateConflict("event not due yet")
    elif event.status is OutboxStatus.LEASED:
        if event.lease_expires_at is None or event.lease_expires_at > now:
            raise TaskStateConflict("lease still valid")
    else:
        raise TaskStateConflict(f"cannot claim a {event.status} event")
    return replace(
        event,
        status=OutboxStatus.LEASED,
        attempts=event.attempts + 1,
        lease_owner=owner,
        lease_expires_at=now + lease,
        lease_generation=event.lease_generation + 1,
    )


def _check_token(event: OutboxEvent, token: int) -> None:
    if event.status is not OutboxStatus.LEASED:
        raise TaskStateConflict(f"event is {event.status}, not LEASED")
    if token != event.lease_generation:
        raise TaskStateConflict("stale lease token (fenced out)")


def mark_published(event: OutboxEvent, *, token: int, now: datetime) -> OutboxEvent:
    _aware(now)
    _check_token(event, token)
    return replace(
        event,
        status=OutboxStatus.PUBLISHED,
        published_at=now,
        lease_owner=None,
        lease_expires_at=None,
    )


def release_failed(
    event: OutboxEvent,
    *,
    token: int,
    now: datetime,
    error_code: str,
    retryable: bool,
    max_attempts: int,
    retry_after: timedelta,
) -> OutboxEvent:
    """Transient failure -> PENDING with backoff; permanent or exhausted -> DEAD_LETTER."""
    _aware(now)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1 (no default; DEC-030 open)")
    _check_token(event, token)
    base = replace(event, lease_owner=None, lease_expires_at=None, last_error_code=error_code)
    if not retryable or event.attempts >= max_attempts:
        return replace(base, status=OutboxStatus.DEAD_LETTER)
    return replace(base, status=OutboxStatus.PENDING, next_attempt_at=now + retry_after)


class InboxState(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class InboxReceipt:
    first_delivery: bool
    state: InboxState
    processed_result_ref: str | None


class InMemoryInbox:
    """Unique (consumer, message_id). In PostgreSQL the insert and the short business mutation
    commit in one transaction; this double only models the dedup decision."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], tuple[InboxState, str | None]] = {}

    def receive(self, consumer: str, message_id: str) -> InboxReceipt:
        key = (consumer, message_id)
        if key in self._rows:
            state, ref = self._rows[key]
            return InboxReceipt(False, state, ref)
        self._rows[key] = (InboxState.RECEIVED, None)
        return InboxReceipt(True, InboxState.RECEIVED, None)

    def complete(self, consumer: str, message_id: str, result_ref: str) -> None:
        key = (consumer, message_id)
        if key not in self._rows:
            raise TaskStateConflict("message was never received")
        if self._rows[key][0] is InboxState.PROCESSED:
            raise TaskStateConflict("message already completed")
        self._rows[key] = (InboxState.PROCESSED, result_ref)
