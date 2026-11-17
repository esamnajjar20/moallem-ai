from datetime import UTC, datetime, timedelta

import pytest

from moallem.domain.errors import NotCanonicalizable, TaskStateConflict
from moallem.domain.publishing import (
    ApprovalDecision,
    ApprovalRecord,
    DenyAllPublishAuthorizer,
    PreflightCode,
    PublishPreflight,
    SnapshotDescriptor,
    approval_is_valid,
    derive_operation_key,
    snapshot_hash,
)

_NOW = datetime(2026, 11, 17, 19, 0, tzinfo=UTC)
_SNAPSHOT_HASH = "a" * 64


def _snapshot(*, snapshot_hash_value: str = _SNAPSHOT_HASH) -> SnapshotDescriptor:
    return SnapshotDescriptor(
        snapshot_id="00000000-0000-0000-0000-000000000010",
        task_id="00000000-0000-0000-0000-000000000020",
        tenant_id="00000000-0000-0000-0000-000000000030",
        version_no=1,
        snapshot_hash=snapshot_hash_value,
        connection_id="00000000-0000-0000-0000-000000000040",
        course_id="course-1",
    )


def _approval(*, snapshot_hash_value: str = _SNAPSHOT_HASH) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="00000000-0000-0000-0000-000000000050",
        tenant_id="00000000-0000-0000-0000-000000000030",
        task_id="00000000-0000-0000-0000-000000000020",
        snapshot_id="00000000-0000-0000-0000-000000000010",
        snapshot_hash=snapshot_hash_value,
        approver_membership_id="00000000-0000-0000-0000-000000000060",
        decision=ApprovalDecision.APPROVED,
        decided_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )


def test_snapshot_hash_binds_destination_and_content() -> None:
    destination = {"connection_id": "c1", "course_id": "course-1"}
    content = {"title": "اختبار", "question_ids": ["q1"]}
    digest = snapshot_hash(destination=destination, content=content, schema_version="v1")
    assert len(digest) == 64
    assert digest != snapshot_hash(
        destination={"connection_id": "c2", "course_id": "course-1"},
        content=content,
        schema_version="v1",
    )
    assert digest != snapshot_hash(
        destination=destination,
        content={"title": "اختبار معدّل", "question_ids": ["q1"]},
        schema_version="v1",
    )


def test_snapshot_hash_rejects_float_payloads() -> None:
    with pytest.raises(NotCanonicalizable):
        snapshot_hash(
            destination={"connection_id": "c1", "course_id": "course-1"},
            content={"points": 0.1},
            schema_version="v1",
        )


def test_approval_is_bound_to_actor_tenant_task_and_exact_snapshot() -> None:
    approval = _approval()
    snapshot = _snapshot()
    assert approval_is_valid(
        approval,
        snapshot,
        tenant_id=snapshot.tenant_id,
        approver_membership_id=approval.approver_membership_id,
        now=_NOW + timedelta(minutes=5),
    )
    assert not approval_is_valid(
        approval,
        snapshot,
        tenant_id=snapshot.tenant_id,
        approver_membership_id="another-membership",
        now=_NOW + timedelta(minutes=5),
    )
    assert not approval_is_valid(
        approval,
        _snapshot(snapshot_hash_value="b" * 64),
        tenant_id=snapshot.tenant_id,
        approver_membership_id=approval.approver_membership_id,
        now=_NOW + timedelta(minutes=5),
    )


def test_approval_expiration_is_exclusive() -> None:
    approval = _approval()
    snapshot = _snapshot()
    assert not approval_is_valid(
        approval,
        snapshot,
        tenant_id=snapshot.tenant_id,
        approver_membership_id=approval.approver_membership_id,
        now=approval.expires_at,
    )


def test_publish_preflight_reports_each_missing_gate() -> None:
    authorizer = DenyAllPublishAuthorizer()
    result = authorizer.preflight(task_id="task-1", snapshot=_snapshot())
    assert set(result.blockers) == set(PreflightCode)
    with pytest.raises(TaskStateConflict):
        result.require_ready()


def test_preflight_accepts_only_explicit_true_values() -> None:
    evidence = PublishPreflight(
        membership_active=True,
        permission_granted=True,
        connection_active=True,
        course_access_verified=True,
        create_capability_verified=True,
        credential_valid=True,
        quota_reserved=True,
        site_profile_approved=True,
        approval_valid=True,
        snapshot_current=True,
    )
    evidence.require_ready()
    bad = PublishPreflight(
        membership_active=True,
        permission_granted=True,
        connection_active=True,
        course_access_verified=True,
        create_capability_verified=True,
        credential_valid=True,
        quota_reserved=1,  # type: ignore[arg-type]
        site_profile_approved=True,
        approval_valid=True,
        snapshot_current=True,
    )
    assert PreflightCode.QUOTA_NOT_RESERVED in bad.blockers


def test_operation_key_is_stable_for_one_publish_intent() -> None:
    intent = "00000000-0000-0000-0000-000000000010"
    assert derive_operation_key(intent) == derive_operation_key(intent)
    assert derive_operation_key(intent) != derive_operation_key("different-intent")
