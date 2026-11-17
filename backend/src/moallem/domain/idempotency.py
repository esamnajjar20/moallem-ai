"""Idempotency records (P4-02; Reliability Addendum v2.4 §2-3, GAP-API-003, GAP-DATA-003).

Pure domain logic. Concurrency authority is the store's UNIQUE scope constraint (``put_if_absent``);
there is deliberately no check-then-insert. Retention (``ttl``) and the HMAC server key are caller
inputs with NO defaults: the spec defines no retention value (open with the retention policy).
"""

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from moallem.domain.errors import DomainError, TaskStateConflict
from moallem.errors import ErrorCode

KEY_MIN_LEN = 22  # openapi.draft.yaml IdempotencyKey.minLength (>=128 bits as base64url)
KEY_MAX_LEN = 200
MIN_SERVER_KEY_BYTES = 32


class IdempotencyKeyReused(DomainError):
    code = ErrorCode.IDEMPOTENCY_KEY_REUSED
    http_status = 409


class IdempotencyKeyInvalid(DomainError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = 400


class RecordState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED_FINAL = "FAILED_FINAL"


class Outcome(StrEnum):
    NEW = "NEW"  # caller proceeds: create Task/outbox/event in the SAME transaction as the record
    IN_PROGRESS = "IN_PROGRESS"  # return the original operation ref (202)
    REPLAY = "REPLAY"  # return the stored terminal response


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    actor_membership_id: str
    operation_code: str
    key_hash: str


@dataclass(frozen=True)
class Record:
    scope: Scope
    request_hash: str
    state: RecordState
    operation_ref: str
    created_at: datetime
    expires_at: datetime
    response_status: int | None = None
    response_ref: str | None = None
    external_unresolved: bool = False  # True => must not expire until reconciliation completes


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    record: Record


class IdempotencyStore(Protocol):
    def put_if_absent(self, record: Record) -> tuple[Record, bool]:
        """Atomically insert; return (stored_record, created). Must be backed by a UNIQUE scope."""
        ...

    def compare_and_set(self, old: Record, new: Record) -> bool: ...

    def delete_expired(self, now: datetime) -> int: ...


class InMemoryIdempotencyStore:
    """Test/dev double. Production needs a PostgreSQL UNIQUE constraint (DEC-031 pending)."""

    def __init__(self) -> None:
        self._rows: dict[Scope, Record] = {}
        self._lock = threading.Lock()

    def put_if_absent(self, record: Record) -> tuple[Record, bool]:
        with self._lock:
            existing = self._rows.get(record.scope)
            if existing is not None:
                return existing, False
            self._rows[record.scope] = record
            return record, True

    def compare_and_set(self, old: Record, new: Record) -> bool:
        with self._lock:
            if self._rows.get(old.scope) != old:
                return False
            self._rows[new.scope] = new
            return True

    def delete_expired(self, now: datetime) -> int:
        with self._lock:
            dead = [
                s
                for s, r in self._rows.items()
                if r.expires_at <= now and not r.external_unresolved
            ]
            for s in dead:
                del self._rows[s]
            return len(dead)


def _aware(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")


def hash_key(server_key: bytes, client_key: str) -> str:
    """HMAC-SHA256 of the client key. The raw key is never stored."""
    if len(server_key) < MIN_SERVER_KEY_BYTES:
        raise ValueError("server HMAC key too short")
    if not KEY_MIN_LEN <= len(client_key) <= KEY_MAX_LEN:
        raise IdempotencyKeyInvalid("Idempotency-Key length out of range")
    return hmac.new(server_key, client_key.encode("utf-8"), hashlib.sha256).hexdigest()


def canonical_request_hash(payload: object) -> str:
    """Hash a JSON-compatible request independent of object key order."""
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("request payload must be finite JSON data") from exc
    return hashlib.sha256(canonical).hexdigest()


def begin(
    store: IdempotencyStore,
    *,
    server_key: bytes,
    tenant_id: str,
    actor_membership_id: str,
    operation_code: str,
    client_key: str,
    request_hash: str,
    operation_ref: str,
    now: datetime,
    ttl: timedelta,
) -> Decision:
    _aware(now)
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive (no default retention is defined)")
    scope = Scope(tenant_id, actor_membership_id, operation_code, hash_key(server_key, client_key))
    candidate = Record(scope, request_hash, RecordState.IN_PROGRESS, operation_ref, now, now + ttl)
    stored, created = store.put_if_absent(candidate)
    if created:
        return Decision(Outcome.NEW, stored)
    # Constant-time compare; a different canonical hash is a conflict in EVERY state.
    if not hmac.compare_digest(stored.request_hash, request_hash):
        raise IdempotencyKeyReused()
    # Expired-but-unpurged rows are still honored (conservative); purge via store.delete_expired.
    if stored.state is RecordState.IN_PROGRESS:
        return Decision(Outcome.IN_PROGRESS, stored)
    return Decision(Outcome.REPLAY, stored)


def complete(
    store: IdempotencyStore,
    record: Record,
    *,
    final: RecordState,
    response_status: int,
    response_ref: str | None,
) -> Record:
    if final is RecordState.IN_PROGRESS:
        raise ValueError("final state must be terminal")
    if record.state is not RecordState.IN_PROGRESS:
        raise TaskStateConflict("idempotency record is already terminal")
    new = replace(record, state=final, response_status=response_status, response_ref=response_ref)
    if not store.compare_and_set(record, new):
        raise TaskStateConflict("idempotency record changed concurrently")
    return new


def set_external_unresolved(store: IdempotencyStore, record: Record, unresolved: bool) -> Record:
    new = replace(record, external_unresolved=unresolved)
    if not store.compare_and_set(record, new):
        raise TaskStateConflict("idempotency record changed concurrently")
    return new
