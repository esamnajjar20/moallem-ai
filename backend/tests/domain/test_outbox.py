from datetime import UTC, datetime, timedelta

import pytest

from moallem.domain import outbox as ob
from moallem.domain.errors import TaskStateConflict

T0 = datetime(2026, 11, 16, tzinfo=UTC)
LEASE = timedelta(seconds=30)


def _ev() -> ob.OutboxEvent:
    return ob.OutboxEvent("e1", "agg", "TASK_CREATED", T0)


def _fail(
    e: ob.OutboxEvent, token: int, *, retryable: bool, max_attempts: int = 2
) -> ob.OutboxEvent:
    return ob.release_failed(
        e,
        token=token,
        now=T0,
        error_code="NET",
        retryable=retryable,
        max_attempts=max_attempts,
        retry_after=timedelta(seconds=5),
    )


def test_claim_then_publish() -> None:
    c = ob.claim(_ev(), owner="w1", now=T0, lease=LEASE)
    assert c.status is ob.OutboxStatus.LEASED and c.lease_generation == 1 and c.attempts == 1
    p = ob.mark_published(c, token=1, now=T0)
    assert p.status is ob.OutboxStatus.PUBLISHED and p.lease_owner is None


def test_not_due_and_live_lease_cannot_be_claimed() -> None:
    with pytest.raises(TaskStateConflict):
        ob.claim(_ev(), owner="w", now=T0 - timedelta(seconds=1), lease=LEASE)
    c = ob.claim(_ev(), owner="w1", now=T0, lease=LEASE)
    with pytest.raises(TaskStateConflict):
        ob.claim(c, owner="w2", now=T0 + timedelta(seconds=29), lease=LEASE)


def test_expired_lease_reclaimed_and_stale_worker_fenced_out() -> None:
    c1 = ob.claim(_ev(), owner="w1", now=T0, lease=LEASE)
    c2 = ob.claim(c1, owner="w2", now=T0 + LEASE, lease=LEASE)
    assert c2.lease_generation == 2 and c2.lease_owner == "w2"
    with pytest.raises(TaskStateConflict):
        ob.mark_published(c2, token=1, now=T0 + LEASE)
    with pytest.raises(TaskStateConflict):
        _fail(c2, 1, retryable=True)
    assert ob.mark_published(c2, token=2, now=T0 + LEASE).status is ob.OutboxStatus.PUBLISHED


def test_transient_failure_backs_off_then_exhausts_to_dead_letter() -> None:
    c = ob.claim(_ev(), owner="w", now=T0, lease=LEASE)
    r = _fail(c, 1, retryable=True)
    assert r.status is ob.OutboxStatus.PENDING and r.next_attempt_at == T0 + timedelta(seconds=5)
    c2 = ob.claim(r, owner="w", now=T0 + timedelta(seconds=5), lease=LEASE)
    d = _fail(c2, 2, retryable=True)
    assert d.status is ob.OutboxStatus.DEAD_LETTER and d.last_error_code == "NET"


def test_permanent_failure_goes_straight_to_dead_letter() -> None:
    c = ob.claim(_ev(), owner="w", now=T0, lease=LEASE)
    d = _fail(c, 1, retryable=False, max_attempts=5)
    assert d.status is ob.OutboxStatus.DEAD_LETTER
    with pytest.raises(TaskStateConflict):
        ob.claim(d, owner="w", now=T0, lease=LEASE)
    with pytest.raises(ValueError):
        _fail(c, 1, retryable=True, max_attempts=0)


def test_inbox_dedup_and_completion() -> None:
    ib = ob.InMemoryInbox()
    assert ib.receive("c", "m1").first_delivery
    dup = ib.receive("c", "m1")
    assert not dup.first_delivery and dup.state is ob.InboxState.RECEIVED
    ib.complete("c", "m1", "res")
    assert ib.receive("c", "m1").processed_result_ref == "res"
    assert ib.receive("c2", "m1").first_delivery  # unique per consumer
    with pytest.raises(TaskStateConflict):
        ib.complete("c", "m1", "res")
    with pytest.raises(TaskStateConflict):
        ib.complete("c", "never", "res")
