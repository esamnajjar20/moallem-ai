from datetime import UTC, datetime, timedelta

import pytest

from moallem.domain import idempotency as idem
from moallem.domain.errors import TaskStateConflict

SK = b"k" * 32
KEY = "A" * 22
T0 = datetime(2026, 11, 16, tzinfo=UTC)
TTL = timedelta(hours=1)


def _begin(
    store: idem.InMemoryIdempotencyStore,
    *,
    h: str = "h1",
    key: str = KEY,
    op: str = "op-1",
    actor: str = "m",
    now: datetime = T0,
    ttl: timedelta = TTL,
) -> idem.Decision:
    return idem.begin(
        store,
        server_key=SK,
        tenant_id="t",
        actor_membership_id=actor,
        operation_code="CREATE",
        client_key=key,
        request_hash=h,
        operation_ref=op,
        now=now,
        ttl=ttl,
    )


def _complete(store: idem.InMemoryIdempotencyStore, rec: idem.Record, ref: str) -> idem.Record:
    return idem.complete(
        store, rec, final=idem.RecordState.COMPLETED, response_status=202, response_ref=ref
    )


def test_first_request_is_new_and_raw_key_not_stored() -> None:
    d = _begin(idem.InMemoryIdempotencyStore())
    assert d.outcome is idem.Outcome.NEW and KEY not in d.record.scope.key_hash


def test_same_key_same_hash_in_progress_returns_original_ref() -> None:
    s = idem.InMemoryIdempotencyStore()
    _begin(s, op="op-1")
    d = _begin(s, op="op-2")
    assert d.outcome is idem.Outcome.IN_PROGRESS and d.record.operation_ref == "op-1"


def test_terminal_state_replays_stored_response() -> None:
    s = idem.InMemoryIdempotencyStore()
    _complete(s, _begin(s).record, "task-1")
    d = _begin(s)
    assert d.outcome is idem.Outcome.REPLAY and d.record.response_ref == "task-1"


def test_different_hash_conflicts_in_every_state() -> None:
    s = idem.InMemoryIdempotencyStore()
    rec = _begin(s).record
    with pytest.raises(idem.IdempotencyKeyReused):
        _begin(s, h="other")
    idem.complete(
        s, rec, final=idem.RecordState.FAILED_FINAL, response_status=422, response_ref=None
    )
    with pytest.raises(idem.IdempotencyKeyReused):
        _begin(s, h="other")


def test_scope_isolation_between_actors() -> None:
    s = idem.InMemoryIdempotencyStore()
    _begin(s)
    assert _begin(s, actor="other", op="x").outcome is idem.Outcome.NEW


def test_complete_twice_and_stale_record_rejected() -> None:
    s = idem.InMemoryIdempotencyStore()
    rec = _begin(s).record
    done = _complete(s, rec, "r")
    with pytest.raises(TaskStateConflict):
        _complete(s, done, "r")
    with pytest.raises(TaskStateConflict):
        _complete(s, rec, "r")


def test_key_length_and_server_key_validation() -> None:
    s = idem.InMemoryIdempotencyStore()
    with pytest.raises(idem.IdempotencyKeyInvalid):
        _begin(s, key="short")
    with pytest.raises(ValueError):
        idem.hash_key(b"short", KEY)


def test_unresolved_external_record_never_expires() -> None:
    s = idem.InMemoryIdempotencyStore()
    rec = _begin(s).record
    idem.set_external_unresolved(s, rec, True)
    assert s.delete_expired(T0 + TTL * 10) == 0
    other = idem.Record(
        idem.Scope("t", "m", "OTHER", "x"), "h", idem.RecordState.COMPLETED, "o", T0, T0 + TTL
    )
    s.put_if_absent(other)
    assert s.delete_expired(T0 + TTL * 10) == 1


def test_naive_datetime_and_nonpositive_ttl_rejected() -> None:
    s = idem.InMemoryIdempotencyStore()
    with pytest.raises(ValueError):
        _begin(s, now=datetime(2026, 11, 16))  # naive on purpose
    with pytest.raises(ValueError):
        _begin(s, ttl=timedelta(0))
