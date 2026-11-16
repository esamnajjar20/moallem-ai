import json
from pathlib import Path

import pytest

from moallem.domain import external as ex
from moallem.domain.errors import TaskStateConflict

LIMITS = Path(__file__).resolve().parents[3] / "contracts" / "agent_runtime_limits.v2.4.json"


def test_keys_deterministic_and_attempt_independent() -> None:
    op = ex.external_operation_key("intent-1")
    assert op == ex.external_operation_key("intent-1") != ex.external_operation_key("intent-2")
    k = ex.external_step_key(op, "question", 3)
    assert k == ex.external_step_key(op, "question", 3)
    others = {ex.external_step_key(op, "question", 4), ex.external_step_key(op, "slot", 3)}
    assert len({k, *others}) == 3


def test_attempt_counter_does_not_change_identity() -> None:
    s = ex.Step("k")
    s2 = ex.begin_dispatch(s)
    assert s2.step_key == s.step_key and s2.attempt_no == 1


def test_timeout_after_dispatch_is_unknown_and_not_auto_retried() -> None:  # MDL-013 logic only
    s = ex.record_response_lost(ex.begin_dispatch(ex.Step("k")))
    assert s.state is ex.StepState.UNKNOWN and not ex.can_auto_retry(s)
    with pytest.raises(TaskStateConflict):
        ex.begin_dispatch(s)


def test_reconcile_outcomes() -> None:
    unknown = ex.record_response_lost(ex.begin_dispatch(ex.Step("k")))
    assert ex.reconcile(unknown, ex.LookupResult.PRESENT).state is ex.StepState.RECONCILED_PRESENT
    assert not ex.can_auto_retry(ex.reconcile(unknown, ex.LookupResult.PRESENT))
    no_lookup = ex.reconcile(unknown, ex.LookupResult.NO_TRUSTED_LOOKUP)
    assert no_lookup.state is ex.StepState.MANUAL_REVIEW
    absent = ex.reconcile(unknown, ex.LookupResult.ABSENT)
    assert ex.can_auto_retry(absent)
    assert ex.begin_dispatch(absent).attempt_no == 2


def test_definite_failure_and_success_are_not_auto_retried() -> None:
    d = ex.begin_dispatch(ex.Step("k"))
    assert not ex.can_auto_retry(ex.record_definite_failure(d))
    assert not ex.can_auto_retry(ex.record_success(d))


def test_reconcile_only_from_unknown() -> None:
    with pytest.raises(TaskStateConflict):
        ex.reconcile(ex.Step("k"), ex.LookupResult.ABSENT)


def test_step_envelope_matches_contract_json() -> None:
    limits = json.loads(LIMITS.read_text(encoding="utf-8"))["limits"]
    assert limits["max_external_steps_per_publish"] == ex.MAX_EXTERNAL_STEPS_PER_PUBLISH
    ex.assert_step_envelope(ex.MAX_EXTERNAL_STEPS_PER_PUBLISH)
    with pytest.raises(TaskStateConflict):
        ex.assert_step_envelope(ex.MAX_EXTERNAL_STEPS_PER_PUBLISH + 1)
