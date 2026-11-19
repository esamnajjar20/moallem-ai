"""PublishQuizHandler: ledger order, fail-closed outcomes, no blind retries."""

import asyncio

import pytest

from moallem.domain.authorization import DenyAllPolicy
from moallem.domain.errors import TaskStateConflict
from moallem.domain.membership import MembershipStatus
from moallem.domain.tasks import TaskStatus
from moallem.moodle.fake_write_adapter import FakeWriteAdapter
from moallem.worker.queue import PermanentTaskError, RetryableTaskError
from tests.worker.support import (
    SNAPSHOT_HASH,
    FakeContext,
    FakeGateway,
    make_handler,
    make_snapshot,
    make_task,
)


def _run(handler, task=None, context=None):  # type: ignore[no-untyped-def]
    ctx = context or FakeContext()
    asyncio.run(handler.execute(task or make_task(), ctx))
    return ctx


def _fails(  # type: ignore[no-untyped-def]
    handler, code: str, *, task=None, expected=PermanentTaskError
):
    ctx = FakeContext()
    with pytest.raises(expected) as info:
        asyncio.run(handler.execute(task or make_task(), ctx))
    assert info.value.error_code == code
    return ctx


def test_happy_path_follows_the_ledger_order_and_completes() -> None:
    gateway, adapter = FakeGateway(), FakeWriteAdapter()
    ctx = _run(make_handler(gateway, adapter))
    assert gateway.calls == [
        "intent",
        "snapshot",
        "plan",
        "dispatch",
        "outcome:SUCCEEDED",
        "verifying",
        "completed",
    ]
    assert gateway.completed is not None
    verification = gateway.completed["verification"]
    assert verification["external_object_type"] == "QUIZ"
    assert verification["external_object_id"] == gateway.outcomes[0]["external_ref"]
    assert verification["snapshot_hash"] == SNAPSHOT_HASH
    assert verification["course_id"] == "12"
    assert gateway.outcomes[0]["response_hash"] is not None
    # The repository owns the task transitions on the happy path.
    assert ctx.transitions == []
    assert len(adapter.created) == 1


def test_destination_comes_from_the_snapshot_not_from_defaults() -> None:
    gateway, adapter = FakeGateway(), FakeWriteAdapter()
    _run(make_handler(gateway, adapter))
    request, questions = adapter.created[0]
    assert request.course_id == "12"
    assert len(questions) == 2


def test_snapshot_without_destination_fails_instead_of_using_defaults() -> None:
    gateway = FakeGateway(snapshot=make_snapshot(destination={}))
    adapter = FakeWriteAdapter()
    _fails(make_handler(gateway, adapter), "SNAPSHOT_DESTINATION_INVALID")
    assert adapter.created == []
    assert "dispatch" not in gateway.calls


def test_verification_mismatch_needs_reconciliation_and_is_not_completed() -> None:
    gateway = FakeGateway()
    ctx = _fails(
        make_handler(gateway, FakeWriteAdapter(drop_questions=1)), "VERIFICATION_MISMATCH"
    )
    assert ctx.transitions == [TaskStatus.NEEDS_RECONCILIATION]
    assert "completed" not in gateway.calls


def test_failed_read_back_is_never_reported_as_success() -> None:
    gateway = FakeGateway()
    ctx = _fails(make_handler(gateway, FakeWriteAdapter(fail_verify=True)), "VERIFICATION_MISMATCH")
    assert ctx.transitions == [TaskStatus.NEEDS_RECONCILIATION]
    assert "completed" not in gateway.calls


def test_ambiguous_create_is_recorded_unknown_and_not_retried() -> None:
    gateway = FakeGateway()
    _fails(make_handler(gateway, FakeWriteAdapter(fail_create=True)), "OUTCOME_UNKNOWN")
    assert gateway.calls[-1] == "outcome:UNKNOWN"


def test_denied_permission_is_a_definite_failure_without_any_write() -> None:
    gateway, adapter = FakeGateway(), FakeWriteAdapter()
    _fails(make_handler(gateway, adapter, policy=DenyAllPolicy()), "MOODLE_REJECTED")
    assert gateway.calls[-1] == "outcome:FAILED_DEFINITE"
    assert adapter.created == []


def test_blocked_dispatch_is_retryable_and_writes_nothing() -> None:
    gateway = FakeGateway(dispatch_error=TaskStateConflict("preflight blocked"))
    adapter = FakeWriteAdapter()
    _fails(make_handler(gateway, adapter), "PUBLISH_BLOCKED", expected=RetryableTaskError)
    assert adapter.created == []
    assert not any(call.startswith("outcome") for call in gateway.calls)


@pytest.mark.parametrize(
    "status", [TaskStatus.EXECUTING, TaskStatus.NEEDS_RECONCILIATION, TaskStatus.COMPLETED]
)
def test_only_a_fresh_approved_task_may_start_a_publish(status: TaskStatus) -> None:
    gateway = FakeGateway()
    _fails(
        make_handler(gateway, FakeWriteAdapter()),
        "TASK_NOT_READY_FOR_PUBLISH",
        task=make_task(status),
    )
    assert gateway.calls == []


def test_suspended_actor_cannot_publish() -> None:
    gateway = FakeGateway()
    handler = make_handler(
        gateway, FakeWriteAdapter(), membership_status=MembershipStatus.SUSPENDED
    )
    _fails(handler, "ACTOR_NOT_ACTIVE")
    assert gateway.calls == []


def test_snapshot_that_moved_after_the_intent_is_rejected() -> None:
    gateway = FakeGateway(intent_hash="c" * 64)
    adapter = FakeWriteAdapter()
    _fails(make_handler(gateway, adapter), "SNAPSHOT_CHANGED")
    assert adapter.created == []
