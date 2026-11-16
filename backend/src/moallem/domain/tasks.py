"""Task state machine (04_Agent_Workflow §states; DEC-042 cancel semantics).

Pure and immutable: every function returns a NEW Task or raises TaskStateConflict.
The caller persists the result together with its task_events row in ONE transaction.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

from moallem.domain.errors import TaskStateConflict


class TaskStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PLANNING = "PLANNING"
    CONTEXT_GATHERING = "CONTEXT_GATHERING"
    DRAFTING = "DRAFTING"
    VALIDATING = "VALIDATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    NEEDS_REVISION = "NEEDS_REVISION"
    NEEDS_INPUT = "NEEDS_INPUT"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


S = TaskStatus
TERMINAL = frozenset({S.COMPLETED, S.REJECTED, S.FAILED, S.CANCELLED, S.EXPIRED})

# Verbatim from the v2.0 workflow table.
TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    S.RECEIVED: frozenset({S.PLANNING, S.FAILED, S.CANCELLED}),
    S.PLANNING: frozenset({S.CONTEXT_GATHERING, S.NEEDS_INPUT, S.FAILED}),
    S.CONTEXT_GATHERING: frozenset({S.DRAFTING, S.FAILED, S.CANCELLED}),
    S.DRAFTING: frozenset({S.VALIDATING, S.FAILED}),
    S.VALIDATING: frozenset({S.AWAITING_APPROVAL, S.EXECUTING, S.NEEDS_REVISION, S.FAILED}),
    S.AWAITING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.EXPIRED, S.CANCELLED}),
    S.APPROVED: frozenset({S.EXECUTING}),
    S.EXECUTING: frozenset({S.VERIFYING, S.FAILED, S.NEEDS_RECONCILIATION}),
    S.VERIFYING: frozenset({S.COMPLETED, S.NEEDS_RECONCILIATION, S.FAILED}),
    S.NEEDS_REVISION: frozenset({S.DRAFTING}),
    S.NEEDS_INPUT: frozenset({S.PLANNING, S.CANCELLED, S.EXPIRED}),
    S.NEEDS_RECONCILIATION: frozenset({S.VERIFYING, S.EXECUTING}),
}

# CANCELLED edges that DEC-042 implies but the v2.0 table does not list. PROPOSED extension:
# needs owner confirmation (GAP-TASK-001). Kept separate so the verbatim table stays auditable.
CANCEL_EXTENSIONS: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset(
    (s, S.CANCELLED)
    for s in (
        S.PLANNING,
        S.DRAFTING,
        S.VALIDATING,
        S.NEEDS_REVISION,
        S.APPROVED,
        S.EXECUTING,  # only while nothing was dispatched
        S.NEEDS_RECONCILIATION,  # only after absence of external effect is proven
    )
)
# States where an external write may already have happened.
POST_DISPATCH_ONLY = frozenset({S.VERIFYING, S.NEEDS_RECONCILIATION})


@dataclass(frozen=True, slots=True)
class Task:
    status: TaskStatus
    cancel_requested: bool = False
    external_dispatched: bool = False  # true once ANY external write step reached DISPATCHED


def _conflict(task: Task, to: TaskStatus) -> TaskStateConflict:
    return TaskStateConflict(f"transition {task.status} -> {to} not allowed")


def transition(task: Task, to: TaskStatus, *, absence_proven: bool = False) -> Task:
    if task.status in TERMINAL:
        raise _conflict(task, to)
    if to is S.CANCELLED:
        raise TaskStateConflict("use request_cancel / settle_cancel for CANCELLED")
    if to not in TRANSITIONS.get(task.status, frozenset()):
        raise _conflict(task, to)
    # Re-running an external write after an unknown outcome needs proof the effect is absent.
    if task.status is S.NEEDS_RECONCILIATION and to is S.EXECUTING and not absence_proven:
        raise TaskStateConflict("absence of external effect not proven")
    return replace(task, status=to)


def mark_dispatched(task: Task) -> Task:
    if task.status is not S.EXECUTING:
        raise TaskStateConflict("dispatch only while EXECUTING")
    return replace(task, external_dispatched=True)


def request_cancel(task: Task) -> Task:
    """Cancel is an intent (DEC-042). Never turns UNKNOWN into CANCELLED."""
    if task.status in TERMINAL:
        raise TaskStateConflict("task already terminal")
    if task.cancel_requested:
        return task  # idempotent
    # Nothing external can exist yet -> cancel immediately. Every non-terminal pre-dispatch state
    # has a CANCELLED edge either in TRANSITIONS or in CANCEL_EXTENSIONS (asserted by tests).
    if not task.external_dispatched and task.status not in POST_DISPATCH_ONLY:
        return replace(task, status=S.CANCELLED, cancel_requested=True)
    return replace(task, cancel_requested=True)


def settle_cancel(task: Task, *, absence_proven: bool, compensation_verified: bool = False) -> Task:
    """Finish a pending cancel after dispatch, only with evidence (manual settlement path)."""
    if not task.cancel_requested or task.status in TERMINAL:
        raise TaskStateConflict("no pending cancel to settle")
    if task.status not in {S.EXECUTING, S.NEEDS_RECONCILIATION}:
        raise TaskStateConflict("nothing to settle in this state")
    if not (absence_proven or compensation_verified):
        raise TaskStateConflict("CANCELLED requires proof of no effect or verified compensation")
    return replace(task, status=S.CANCELLED)
