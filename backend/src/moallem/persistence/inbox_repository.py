"""Tenant-scoped PostgreSQL Inbox processing with transactional effects and leases."""

import hmac
import logging
import random
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from moallem.domain.idempotency import canonical_request_hash
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import InboxReceiptModel

log = logging.getLogger("moallem.persistence.inbox")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class InboxMessageConflict(ValueError):
    """A message identifier was reused with a different payload."""


class InboxLegacyReceiptConflict(InboxMessageConflict):
    """A message id is reserved by a pre-tenant receipt that cannot be safely attributed."""


class InboxLeaseLost(RuntimeError):
    """The Inbox receipt lease is stale or no longer owned by this consumer."""


class PermanentInboxError(Exception):
    def __init__(self, error_code: str) -> None:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a non-sensitive stable code")
        self.error_code = error_code


class RetryableInboxError(Exception):
    def __init__(self, error_code: str) -> None:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a non-sensitive stable code")
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class InboxMessage:
    tenant_id: str
    consumer: str
    message_id: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class InboxClaim:
    receipt_id: str
    tenant_id: str
    consumer: str
    message_id: str
    payload_hash: str
    owner: str
    generation: int
    attempts: int
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class InboxResult:
    state: str
    acknowledge: bool
    duplicate: bool = False
    result_ref: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class InboxRetryPolicy:
    max_attempts: int
    base_delay_seconds: int
    max_delay_seconds: int

    def __post_init__(self) -> None:
        if (
            self.max_attempts < 1
            or self.base_delay_seconds < 1
            or self.max_delay_seconds < self.base_delay_seconds
        ):
            raise ValueError("invalid Inbox retry policy")

    def delay_seconds(self, attempt: int, *, jitter: Callable[[], float] = random.random) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        fraction = float(jitter())
        if not 0 <= fraction <= 1:
            raise ValueError("jitter must be in [0, 1]")
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** min(attempt - 1, 62)))
        return float(ceiling * (0.5 + 0.5 * fraction))


class InboxHandler(Protocol):
    """Handlers may mutate the supplied Session; external effects must use an Outbox."""

    def process(self, session: Session, message: InboxMessage) -> str | None: ...


class PostgresInboxConsumer:
    """Deduplicate, lease, and process receipts without acknowledging before commit.

    A source adapter must ACK only when ``InboxResult.acknowledge`` is true. Retryable failures
    remain unacknowledged for source redelivery after ``next_attempt_at``.
    """

    def __init__(
        self,
        sessions: SessionFactory,
        *,
        lease_seconds: int,
        retry_policy: InboxRetryPolicy,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self._sessions = sessions
        self._lease_seconds = lease_seconds
        self._retry_policy = retry_policy

    def consume(
        self,
        message: InboxMessage,
        handler: InboxHandler,
        *,
        owner: str,
        now: datetime | None = None,
    ) -> InboxResult:
        claimed = self.claim(message, owner=owner, now=now)
        if isinstance(claimed, InboxResult):
            return claimed
        return self.process(claimed, message, handler, now=now)

    def claim(
        self,
        message: InboxMessage,
        *,
        owner: str,
        now: datetime | None = None,
    ) -> InboxClaim | InboxResult:
        _validate_message(message, owner, now or datetime.now(UTC))
        tenant_id = uuid.UUID(message.tenant_id)
        payload_hash = canonical_request_hash(message.payload)

        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(InboxReceiptModel)
                .where(
                    InboxReceiptModel.tenant_id == tenant_id,
                    InboxReceiptModel.consumer == message.consumer,
                    InboxReceiptModel.message_id == message.message_id,
                )
                .with_for_update()
            )
            if row is None:
                # The pre-tenant schema used a global (consumer, message_id) key. An old
                # receipt has no reliable tenant attribution, so never infer one or create a
                # fresh tenant-scoped receipt for the same source identity. Keep the legacy
                # row untouched and let the source adapter route this conflict to quarantine.
                legacy_row = session.scalar(
                    select(InboxReceiptModel)
                    .where(
                        InboxReceiptModel.tenant_id.is_(None),
                        InboxReceiptModel.consumer == message.consumer,
                        InboxReceiptModel.message_id == message.message_id,
                    )
                    .with_for_update()
                )
                if legacy_row is not None:
                    raise InboxLegacyReceiptConflict(
                        "message identifier belongs to an unscoped legacy receipt; "
                        "manual tenant reconciliation is required"
                    )
                try:
                    with session.begin_nested():
                        row = InboxReceiptModel(
                            id=uuid.uuid4(),
                            tenant_id=tenant_id,
                            consumer=message.consumer,
                            message_id=message.message_id,
                            payload_hash=payload_hash,
                            state="RECEIVED",
                        )
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    row = session.scalar(
                        select(InboxReceiptModel)
                        .where(
                            InboxReceiptModel.tenant_id == tenant_id,
                            InboxReceiptModel.consumer == message.consumer,
                            InboxReceiptModel.message_id == message.message_id,
                        )
                        .with_for_update()
                    )
                    if row is None:
                        raise

            # The initial SELECT may have waited on another transaction's row lock. Only
            # decide whether a PROCESSING lease is live after the lock is ours.
            timestamp = now or datetime.now(UTC)
            if row.payload_hash is not None and not hmac.compare_digest(
                row.payload_hash, payload_hash
            ):
                raise InboxMessageConflict("message identifier reused with a different payload")
            row.payload_hash = payload_hash

            if row.state == "PROCESSED":
                return InboxResult(
                    "PROCESSED",
                    acknowledge=True,
                    duplicate=True,
                    result_ref=row.processed_result_ref,
                )
            if row.state == "FAILED":
                if not row.retryable or row.attempts >= self._retry_policy.max_attempts:
                    return InboxResult(
                        "FAILED",
                        acknowledge=True,
                        duplicate=True,
                        error_code=row.last_error_code,
                    )
                if row.next_attempt_at > timestamp:
                    return InboxResult(
                        "FAILED",
                        acknowledge=False,
                        duplicate=True,
                        error_code=row.last_error_code,
                    )
            if row.state == "PROCESSING":
                if row.lease_expires_at is not None and row.lease_expires_at > timestamp:
                    return InboxResult("PROCESSING", acknowledge=False, duplicate=True)
                if row.attempts >= self._retry_policy.max_attempts:
                    row.state = "FAILED"
                    row.retryable = False
                    row.last_error_code = "ATTEMPTS_EXHAUSTED"
                    row.completed_at = timestamp
                    row.lease_owner = None
                    row.lease_expires_at = None
                    return InboxResult("FAILED", acknowledge=True, error_code="ATTEMPTS_EXHAUSTED")

            row.state = "PROCESSING"
            row.attempts += 1
            row.lease_owner = owner
            row.lease_generation += 1
            row.lease_expires_at = timestamp + timedelta(seconds=self._lease_seconds)
            row.retryable = False
            row.completed_at = None
            session.flush()
            return InboxClaim(
                receipt_id=str(row.id),
                tenant_id=message.tenant_id,
                consumer=message.consumer,
                message_id=message.message_id,
                payload_hash=payload_hash,
                owner=owner,
                generation=row.lease_generation,
                attempts=row.attempts,
                lease_expires_at=row.lease_expires_at,
            )

    def process(
        self,
        claim: InboxClaim,
        message: InboxMessage,
        handler: InboxHandler,
        *,
        now: datetime | None = None,
    ) -> InboxResult:
        if canonical_request_hash(message.payload) != claim.payload_hash:
            raise InboxMessageConflict("claim does not belong to this message payload")
        try:
            with session_scope(self._sessions) as session:
                row = _locked_claim(session, claim, now)
                result_ref = handler.process(session, message)
                if result_ref is not None and (
                    not isinstance(result_ref, str) or len(result_ref) > 512
                ):
                    raise PermanentInboxError("RESULT_REFERENCE_INVALID")
                # The handler can itself take time. It runs inside this transaction, so a
                # lease that expires before completion must roll back both its DB effects and
                # the attempted PROCESSED transition.
                completed_at = now or datetime.now(UTC)
                _assert_claim_current(row, claim, completed_at)
                lease_expires_at = row.lease_expires_at
                row.state = "PROCESSED"
                row.processed_result_ref = result_ref
                row.completed_at = completed_at
                row.retryable = False
                row.last_error_code = None
                row.lease_owner = None
                row.lease_expires_at = None
                session.flush()
                if (
                    now is None
                    and lease_expires_at is not None
                    and lease_expires_at <= datetime.now(UTC)
                ):
                    raise InboxLeaseLost("Inbox receipt lease expired before commit")
            return InboxResult("PROCESSED", acknowledge=True, result_ref=result_ref)
        except InboxLeaseLost:
            raise
        except PermanentInboxError as exc:
            return self._record_failure(
                claim, exc.error_code, retryable=False, now=now
            )
        except RetryableInboxError as exc:
            return self._record_failure(
                claim, exc.error_code, retryable=True, now=now
            )
        except Exception as exc:
            log.error(
                "inbox.handler_failed",
                extra={
                    "consumer": message.consumer,
                    "error_type": type(exc).__name__,
                },
            )
            return self._record_failure(
                claim,
                "INBOX_HANDLER_UNEXPECTED",
                retryable=True,
                now=now,
            )

    def _record_failure(
        self,
        claim: InboxClaim,
        error_code: str,
        *,
        retryable: bool,
        now: datetime | None,
    ) -> InboxResult:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(InboxReceiptModel)
                .where(
                    InboxReceiptModel.id == uuid.UUID(claim.receipt_id),
                    InboxReceiptModel.tenant_id == uuid.UUID(claim.tenant_id),
                    InboxReceiptModel.consumer == claim.consumer,
                    InboxReceiptModel.message_id == claim.message_id,
                    InboxReceiptModel.state == "PROCESSING",
                    InboxReceiptModel.lease_owner == claim.owner,
                    InboxReceiptModel.lease_generation == claim.generation,
                )
                .with_for_update()
            )
            if row is None:
                raise InboxLeaseLost("Inbox receipt lease is no longer current")
            # Lock waits must not extend an old worker's authority to record failure.
            timestamp = now or datetime.now(UTC)
            _assert_claim_current(row, claim, timestamp)
            exhausted = row.attempts >= self._retry_policy.max_attempts
            retrying = retryable and not exhausted
            row.state = "FAILED"
            row.retryable = retrying
            row.last_error_code = error_code if not exhausted else "ATTEMPTS_EXHAUSTED"
            row.next_attempt_at = timestamp + timedelta(
                seconds=self._retry_policy.delay_seconds(row.attempts)
            )
            row.completed_at = None if retrying else timestamp
            row.lease_owner = None
            row.lease_expires_at = None
            session.flush()
            return InboxResult(
                "FAILED",
                acknowledge=not retrying,
                error_code=row.last_error_code,
            )


def _validate_message(message: InboxMessage, owner: str, now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    try:
        uuid.UUID(message.tenant_id)
    except ValueError as exc:
        raise ValueError("tenant_id must be a UUID") from exc
    if not _IDENTIFIER.fullmatch(message.consumer) or not _IDENTIFIER.fullmatch(message.message_id):
        raise ValueError("consumer and message_id must be stable identifiers")
    if not _IDENTIFIER.fullmatch(owner):
        raise ValueError("owner must be a stable identifier")


def _locked_claim(
    session: Session, claim: InboxClaim, now: datetime | None
) -> InboxReceiptModel:
    row = session.scalar(
        select(InboxReceiptModel)
        .where(
            InboxReceiptModel.id == uuid.UUID(claim.receipt_id),
            InboxReceiptModel.tenant_id == uuid.UUID(claim.tenant_id),
            InboxReceiptModel.consumer == claim.consumer,
            InboxReceiptModel.message_id == claim.message_id,
            InboxReceiptModel.payload_hash == claim.payload_hash,
            InboxReceiptModel.state == "PROCESSING",
            InboxReceiptModel.lease_owner == claim.owner,
            InboxReceiptModel.lease_generation == claim.generation,
        )
        .with_for_update()
    )
    if row is None:
        raise InboxLeaseLost("Inbox receipt lease is no longer current")
    _assert_claim_current(row, claim, now or datetime.now(UTC))
    return row


def _assert_claim_current(
    row: InboxReceiptModel, claim: InboxClaim, now: datetime
) -> None:
    if (
        now.tzinfo is None
        or row.state != "PROCESSING"
        or row.lease_owner != claim.owner
        or row.lease_generation != claim.generation
        or row.payload_hash != claim.payload_hash
        or row.lease_expires_at is None
        or row.lease_expires_at <= now
    ):
        raise InboxLeaseLost("Inbox receipt lease is no longer current")
