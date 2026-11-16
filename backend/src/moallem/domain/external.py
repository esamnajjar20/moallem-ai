"""External write identities and step ledger rules (DEC-041, Reliability Addendum §4).

Identities are derived deterministically from publish_intent_id, so a retry, a worker restart or a
second worker computes the SAME keys. attempt_no is a transport counter and never part of identity.
"""

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum

from moallem.domain.errors import TaskStateConflict

MAX_EXTERNAL_STEPS_PER_PUBLISH = 256  # agent_runtime_limits.v2.4 (PROPOSED); parity-tested


def external_operation_key(publish_intent_id: str) -> str:
    return hashlib.sha256(f"moallem:op:v1:{publish_intent_id}".encode()).hexdigest()


def external_step_key(operation_key: str, step_kind: str, ordinal: int) -> str:
    if ordinal < 0:
        raise ValueError("ordinal must be >= 0")
    raw = f"moallem:step:v1:{operation_key}:{step_kind}:{ordinal}"
    return hashlib.sha256(raw.encode()).hexdigest()


def assert_step_envelope(step_count: int) -> None:
    if step_count > MAX_EXTERNAL_STEPS_PER_PUBLISH:
        raise TaskStateConflict("composite publish exceeds the external-step envelope")


class StepState(StrEnum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"  # committed BEFORE network I/O
    SUCCEEDED = "SUCCEEDED"
    FAILED_DEFINITE = "FAILED_DEFINITE"  # explicit, trusted failure response
    UNKNOWN = "UNKNOWN"  # dispatched, response lost
    RECONCILED_PRESENT = "RECONCILED_PRESENT"
    RECONCILED_ABSENT = "RECONCILED_ABSENT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class LookupResult(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    NO_TRUSTED_LOOKUP = "NO_TRUSTED_LOOKUP"


@dataclass(frozen=True, slots=True)
class Step:
    step_key: str
    state: StepState = StepState.PLANNED
    attempt_no: int = 0


def _need(step: Step, *allowed: StepState) -> None:
    if step.state not in allowed:
        raise TaskStateConflict(f"step {step.state} cannot do this")


def begin_dispatch(step: Step) -> Step:
    """Only a never-dispatched step, or one PROVEN absent, may be (re)dispatched."""
    _need(step, StepState.PLANNED, StepState.RECONCILED_ABSENT)
    return replace(step, state=StepState.DISPATCHED, attempt_no=step.attempt_no + 1)


def record_success(step: Step) -> Step:
    _need(step, StepState.DISPATCHED)
    return replace(step, state=StepState.SUCCEEDED)


def record_definite_failure(step: Step) -> Step:
    _need(step, StepState.DISPATCHED)
    return replace(step, state=StepState.FAILED_DEFINITE)


def record_response_lost(step: Step) -> Step:
    _need(step, StepState.DISPATCHED)
    return replace(step, state=StepState.UNKNOWN)


def reconcile(step: Step, result: LookupResult) -> Step:
    _need(step, StepState.UNKNOWN)
    nxt = {
        LookupResult.PRESENT: StepState.RECONCILED_PRESENT,
        LookupResult.ABSENT: StepState.RECONCILED_ABSENT,
        LookupResult.NO_TRUSTED_LOOKUP: StepState.MANUAL_REVIEW,
    }[result]
    return replace(step, state=nxt)


def can_auto_retry(step: Step) -> bool:
    return step.state in {StepState.PLANNED, StepState.RECONCILED_ABSENT}
