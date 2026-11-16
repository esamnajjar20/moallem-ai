import pytest

from moallem.domain.errors import TaskStateConflict
from moallem.domain.tasks import (
    CANCEL_EXTENSIONS,
    POST_DISPATCH_ONLY,
    TERMINAL,
    TRANSITIONS,
    Task,
    TaskStatus,
    mark_dispatched,
    request_cancel,
    settle_cancel,
    transition,
)

S = TaskStatus


def test_every_status_is_terminal_or_has_an_exit() -> None:
    for s in TaskStatus:
        assert (s in TERMINAL) != (s in TRANSITIONS), s
    for s in TERMINAL:
        assert s not in TRANSITIONS


def test_happy_path() -> None:
    t = Task(S.RECEIVED)
    for nxt in (
        S.PLANNING,
        S.CONTEXT_GATHERING,
        S.DRAFTING,
        S.VALIDATING,
        S.AWAITING_APPROVAL,
        S.APPROVED,
        S.EXECUTING,
        S.VERIFYING,
        S.COMPLETED,
    ):
        t = transition(t, nxt)
    assert t.status is S.COMPLETED


def test_invalid_and_terminal_transitions_conflict() -> None:
    with pytest.raises(TaskStateConflict):
        transition(Task(S.RECEIVED), S.EXECUTING)
    with pytest.raises(TaskStateConflict):
        transition(Task(S.COMPLETED), S.PLANNING)
    with pytest.raises(TaskStateConflict):
        transition(Task(S.APPROVED), S.VERIFYING)  # APPROVED -> EXECUTING only


def test_cancelled_only_through_cancel_functions() -> None:
    with pytest.raises(TaskStateConflict):
        transition(Task(S.RECEIVED), S.CANCELLED)


def test_reexecute_after_unknown_needs_proof_of_absence() -> None:
    t = Task(S.NEEDS_RECONCILIATION, external_dispatched=True)
    with pytest.raises(TaskStateConflict):
        transition(t, S.EXECUTING)
    assert transition(t, S.EXECUTING, absence_proven=True).status is S.EXECUTING
    assert transition(t, S.VERIFYING).status is S.VERIFYING


def test_cancel_before_dispatch_is_immediate_for_every_pre_dispatch_state() -> None:
    for s in TaskStatus:
        if s in TERMINAL or s in POST_DISPATCH_ONLY:
            continue
        out = request_cancel(Task(s))
        assert out.status is S.CANCELLED, s
        assert S.CANCELLED in TRANSITIONS[s] or (s, S.CANCELLED) in CANCEL_EXTENSIONS, s


def test_cancel_after_dispatch_stays_executing_with_intent() -> None:  # AT-044
    t = mark_dispatched(Task(S.EXECUTING))
    out = request_cancel(t)
    assert out.status is S.EXECUTING and out.cancel_requested
    assert request_cancel(out) == out  # idempotent


def test_unknown_outcome_is_never_cancelled_by_request() -> None:
    for s in (S.NEEDS_RECONCILIATION, S.VERIFYING):
        out = request_cancel(Task(s, external_dispatched=True))
        assert out.status is s and out.cancel_requested


def test_settle_cancel_requires_evidence() -> None:
    t = request_cancel(Task(S.NEEDS_RECONCILIATION, external_dispatched=True))
    with pytest.raises(TaskStateConflict):
        settle_cancel(t, absence_proven=False)
    assert settle_cancel(t, absence_proven=True).status is S.CANCELLED
    assert settle_cancel(t, absence_proven=False, compensation_verified=True).status is S.CANCELLED


def test_settle_cancel_without_pending_intent_conflicts() -> None:
    with pytest.raises(TaskStateConflict):
        settle_cancel(Task(S.EXECUTING, external_dispatched=True), absence_proven=True)


def test_cancel_terminal_conflicts_and_dispatch_only_while_executing() -> None:
    with pytest.raises(TaskStateConflict):
        request_cancel(Task(S.COMPLETED))
    with pytest.raises(TaskStateConflict):
        mark_dispatched(Task(S.DRAFTING))
