"""MoodleWriteService with a real MoodleClient and the in-memory fake adapter."""

import pytest

from moallem.domain.authorization import DenyAllPolicy
from moallem.domain.errors import PermissionDenied, ResourceNotFound, TaskStateConflict
from moallem.domain.publishing import PublishIntent, PublishState, SnapshotDescriptor
from moallem.moodle.errors import ConnectionNotActive
from moallem.moodle.fake_write_adapter import FakeWriteAdapter
from moallem.moodle.question_mapping import map_quiz_draft_to_specs
from moallem.moodle.service import ConnectionStatus
from tests.worker.support import (
    ACTOR,
    CONNECTION_ID,
    COURSE_ID,
    OPERATION_KEY,
    SNAPSHOT_HASH,
    SNAPSHOT_ID,
    TASK_ID,
    TENANT,
    make_draft,
    make_service,
)


def _snapshot(**overrides: str) -> SnapshotDescriptor:
    fields = {
        "snapshot_id": SNAPSHOT_ID,
        "task_id": TASK_ID,
        "tenant_id": TENANT,
        "snapshot_hash": SNAPSHOT_HASH,
        "connection_id": CONNECTION_ID,
        "course_id": COURSE_ID,
    }
    fields.update(overrides)
    return SnapshotDescriptor(version_no=1, **fields)  # type: ignore[arg-type]


def _intent() -> PublishIntent:
    return PublishIntent(
        publish_intent_id="i1",
        task_id=TASK_ID,
        tenant_id=TENANT,
        snapshot_id=SNAPSHOT_ID,
        snapshot_hash=SNAPSHOT_HASH,
        external_operation_key=OPERATION_KEY,
        state=PublishState.EXECUTING,
    )


def _publish(service, snapshot=None, questions=None):  # type: ignore[no-untyped-def]
    name, intro, specs = map_quiz_draft_to_specs(make_draft())
    return service.publish_approved_quiz(
        ACTOR,
        connection_id=CONNECTION_ID,
        snapshot=snapshot or _snapshot(),
        intent=_intent(),
        questions=specs if questions is None else questions,
        quiz_name=name,
        quiz_intro=intro,
    )


def test_publish_creates_and_verifies_with_real_client_construction() -> None:
    adapter = FakeWriteAdapter()
    outcome = _publish(make_service(adapter))
    assert outcome.verification.matches(2)
    assert len(adapter.created) == 1


def test_create_is_idempotent_on_operation_key() -> None:
    adapter = FakeWriteAdapter()
    service = make_service(adapter)
    first = _publish(service).create_result.moodle_quiz_id
    second = _publish(service).create_result.moodle_quiz_id
    assert first == second
    assert len(adapter.created) == 1


def test_dropped_question_is_detected_by_read_back() -> None:
    outcome = _publish(make_service(FakeWriteAdapter(drop_questions=1)))
    assert not outcome.verification.matches(2)


def test_snapshot_of_another_tenant_is_not_found() -> None:
    with pytest.raises(ResourceNotFound):
        _publish(make_service(FakeWriteAdapter()), snapshot=_snapshot(tenant_id="other"))


def test_snapshot_connection_mismatch_is_conflict() -> None:
    with pytest.raises(TaskStateConflict):
        _publish(make_service(FakeWriteAdapter()), snapshot=_snapshot(connection_id="x"))


def test_default_policy_denies_publish() -> None:
    adapter = FakeWriteAdapter()
    with pytest.raises(PermissionDenied):
        _publish(make_service(adapter, policy=DenyAllPolicy()))
    assert adapter.created == []


def test_inactive_connection_blocks_write() -> None:
    adapter = FakeWriteAdapter()
    with pytest.raises(ConnectionNotActive):
        _publish(make_service(adapter, status=ConnectionStatus.DISCONNECTED))
    assert adapter.created == []


def test_zero_questions_is_rejected() -> None:
    adapter = FakeWriteAdapter()
    with pytest.raises(TaskStateConflict):
        _publish(make_service(adapter), questions=[])
    assert adapter.created == []
