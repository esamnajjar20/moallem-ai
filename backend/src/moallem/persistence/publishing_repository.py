"""Transactional PostgreSQL persistence for P7 snapshots, approvals and publish effects.

This repository deliberately has no Moodle network client. It persists the business decision and
external-effect ledger; a separately approved worker adapter must perform the actual Moodle write.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moallem.ai.quiz.generation import QuizDraft
from moallem.ai.quiz.quality import QualityDecision, QuizQualityReport
from moallem.domain.canonical import canonical_hash
from moallem.domain.errors import ResourceNotFound, TaskStateConflict
from moallem.domain.external import (
    LookupResult,
    Step,
    StepState,
    MAX_EXTERNAL_STEPS_PER_PUBLISH,
    begin_dispatch,
    can_auto_retry,
    external_operation_key,
    external_step_key,
    record_definite_failure,
    record_response_lost,
    record_success,
    reconcile,
)
from moallem.domain.membership import ActiveContext
from moallem.domain.publishing import (
    ApprovalDecision,
    DenyAllPublishAuthorizer,
    PublishAuthorizer,
    PublishState,
    SnapshotDescriptor,
    snapshot_hash,
)
from moallem.domain.tasks import Task, TaskStatus, transition
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import (
    MembershipModel,
    MoodleConnectionModel,
    OutboxEventModel,
    PublishIntentModel,
    QuizApprovalModel,
    QuizDraftSnapshotModel,
    TaskEventModel,
    TaskModel,
    ToolInvocationModel,
)


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    snapshot_id: str
    tenant_id: str
    task_id: str
    version_no: int
    snapshot_hash: str
    schema_version: str
    destination: dict[str, object]
    content: dict[str, object]
    quality_report: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    approval_id: str
    task_id: str
    snapshot_id: str
    snapshot_hash: str
    decision: ApprovalDecision
    decided_at: datetime
    expires_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PublishIntentRecord:
    publish_intent_id: str
    tenant_id: str
    task_id: str
    snapshot_id: str
    snapshot_hash: str
    external_operation_key: str
    state: PublishState


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ResourceNotFound("resource not found") from exc


def _assert_snapshot_integrity(row: QuizDraftSnapshotModel) -> None:
    calculated = snapshot_hash(
        destination=dict(row.destination),
        content={**dict(row.content), "quality_report": dict(row.quality_report)},
        schema_version=row.schema_version,
    )
    if not hmac.compare_digest(calculated, row.snapshot_hash):
        raise TaskStateConflict("immutable snapshot hash does not match its stored content")


def _snapshot_record(row: QuizDraftSnapshotModel) -> SnapshotRecord:
    _assert_snapshot_integrity(row)
    return SnapshotRecord(
        snapshot_id=str(row.id),
        tenant_id=str(row.tenant_id),
        task_id=str(row.task_id),
        version_no=row.version_no,
        snapshot_hash=row.snapshot_hash,
        schema_version=row.schema_version,
        destination=dict(row.destination),
        content=dict(row.content),
        quality_report=dict(row.quality_report),
        created_at=row.created_at,
    )


def _publish_record(row: PublishIntentModel) -> PublishIntentRecord:
    return PublishIntentRecord(
        publish_intent_id=str(row.id),
        tenant_id=str(row.tenant_id),
        task_id=str(row.task_id),
        snapshot_id=str(row.snapshot_id),
        snapshot_hash=row.snapshot_hash,
        external_operation_key=row.external_operation_key,
        state=PublishState(row.state),
    )


def _draft_content(draft: QuizDraft) -> dict[str, object]:
    """Serialize the full immutable draft, including type payload and source provenance."""
    return {
        "draft_id": str(draft.draft_id),
        "spec": draft.spec.model_dump(mode="json"),
        "educational_scope": draft.educational_scope.model_dump(mode="json"),
        "preview": draft.preview.model_dump(mode="json"),
        "questions": [
            {
                "question_id": str(item.question_id),
                "question_type_code": item.question_type_code,
                "question_type_schema_version": item.question_type_schema_version,
                # Preserve the exact canonical JSON text rather than decoding floats into
                # cross-language numbers before hashing.
                "payload_json": item.payload_json,
                "source_evidence": [
                    {"source_ref": str(ref), "quote": quote}
                    for ref, quote in item.source_evidence
                ],
                "unsupported": item.unsupported,
                "unsupported_reason": item.unsupported_reason,
                "preview": item.preview.model_dump(mode="json"),
            }
            for item in draft.questions
        ],
        "source_citations": [
            {
                "source_ref": str(item.source_ref),
                "file_id": str(item.file_id),
                "file_version": item.file_version,
                "content_hash": item.content_hash,
                "page_number": item.page_number,
                "section_path": item.section_path,
            }
            for item in draft.source_citations
        ],
        "context_source_hashes": [
            {"source_ref": str(ref), "content_hash": digest}
            for ref, digest in draft.context_source_hashes
        ],
        "provider_identity": {
            "provider_id": draft.provider_identity.provider_id,
            "model_id": draft.provider_identity.model_id,
            "model_version": draft.provider_identity.model_version,
            "region": draft.provider_identity.region,
        },
        "prompt_version": draft.prompt_version,
        "request_hash": draft.request_hash,
        "input_tokens": draft.input_tokens,
        "output_tokens": draft.output_tokens,
        "created_at": draft.created_at.isoformat(),
        "draft_content_hash": draft.content_hash,
    }


def _quality_payload(report: QuizQualityReport) -> dict[str, object]:
    return {
        "validation_id": str(report.validation_id),
        "draft_id": str(report.draft_id),
        "draft_hash": report.draft_hash,
        "rubric_version": report.rubric_version,
        "validator_version": report.validator_version,
        "decision": report.decision.value,
        "hard_failures": [
            {"code": item.code, "question_id": str(item.question_id) if item.question_id else None}
            for item in report.hard_failures
        ],
        "warnings": [
            {"code": item.code, "question_id": str(item.question_id) if item.question_id else None}
            for item in report.warnings
        ],
        "validated_at": report.validated_at.isoformat(),
        "human_review_required": True,
        "publish_allowed_by_validator": False,
    }


def _descriptor(row: QuizDraftSnapshotModel) -> SnapshotDescriptor:
    _assert_snapshot_integrity(row)
    return SnapshotDescriptor(
        snapshot_id=str(row.id),
        tenant_id=str(row.tenant_id),
        task_id=str(row.task_id),
        version_no=row.version_no,
        snapshot_hash=row.snapshot_hash,
        connection_id=str(row.destination["connection_id"]),
        course_id=str(row.destination["course_id"]),
    )


class PostgresPublicationRepository:
    """Owns P7 transaction boundaries; every state/event/ledger change commits atomically."""

    def __init__(
        self,
        sessions: SessionFactory,
        *,
        publish_authorizer: PublishAuthorizer | None = None,
    ) -> None:
        self._sessions = sessions
        # A caller cannot manufacture all-true preflight flags. Only a trusted, server-side
        # authorizer injected into the worker composition can permit an external write.
        self._publish_authorizer = publish_authorizer or DenyAllPublishAuthorizer()

    def create_initial_snapshot(
        self,
        ctx: ActiveContext,
        task_id: str,
        draft: QuizDraft,
        quality_report: QuizQualityReport,
        *,
        occurred_at: datetime | None = None,
    ) -> SnapshotRecord:
        """Persist the validated P6 output as version 1 and move VALIDATING -> AWAITING_APPROVAL.

        This is an internal application/worker method, not a client-supplied destination API.
        """
        return self._create_snapshot(
            ctx,
            task_id,
            draft,
            quality_report,
            base_snapshot_id=None,
            base_snapshot_hash=None,
            expected_status=TaskStatus.VALIDATING,
            occurred_at=occurred_at,
        )

    def create_revision_snapshot(
        self,
        ctx: ActiveContext,
        task_id: str,
        draft: QuizDraft,
        quality_report: QuizQualityReport,
        *,
        base_snapshot_id: str,
        base_snapshot_hash: str,
        occurred_at: datetime | None = None,
    ) -> SnapshotRecord:
        """Append a freshly validated revision; prior approvals remain bound to old hashes."""
        return self._create_snapshot(
            ctx,
            task_id,
            draft,
            quality_report,
            base_snapshot_id=base_snapshot_id,
            base_snapshot_hash=base_snapshot_hash,
            expected_status=TaskStatus.AWAITING_APPROVAL,
            occurred_at=occurred_at,
        )

    def _create_snapshot(
        self,
        ctx: ActiveContext,
        task_id: str,
        draft: QuizDraft,
        quality_report: QuizQualityReport,
        *,
        base_snapshot_id: str | None,
        base_snapshot_hash: str | None,
        expected_status: TaskStatus,
        occurred_at: datetime | None,
    ) -> SnapshotRecord:
        task_uuid = _uuid(task_id)
        tenant_uuid = _uuid(ctx.tenant_id)
        membership_uuid = _uuid(ctx.membership_id)
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if (
            str(draft.tenant_id) != ctx.tenant_id
            or str(draft.task_id) != task_id
            or str(draft.actor_membership_id) != ctx.membership_id
        ):
            raise TaskStateConflict("generated draft scope does not match the trusted task context")
        if quality_report.draft_id != draft.draft_id or quality_report.draft_hash != draft.content_hash:
            raise TaskStateConflict("quality report is not bound to this exact draft")
        if quality_report.decision is QualityDecision.BLOCKED or quality_report.hard_failures:
            raise TaskStateConflict("blocked quality report cannot be snapshotted for approval")

        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(
                    TaskModel.id == task_uuid,
                    TaskModel.tenant_id == tenant_uuid,
                    TaskModel.actor_membership_id == membership_uuid,
                )
                .with_for_update()
            )
            if task is None:
                raise ResourceNotFound("resource not found")
            if task.status != expected_status.value:
                raise TaskStateConflict("task is not in the required draft state")
            if task.task_type != "CREATE_QUIZ":
                raise TaskStateConflict("P7 approval/publish currently supports CREATE_QUIZ only")
            if task.course_id != draft.course_id:
                raise TaskStateConflict("draft course does not match the server-owned task course")
            connection = session.scalar(
                select(MoodleConnectionModel).where(
                    MoodleConnectionModel.id == task.connection_id,
                    MoodleConnectionModel.tenant_id == tenant_uuid,
                )
            )
            if connection is None:
                raise ResourceNotFound("resource not found")
            if connection.status != "ACTIVE" or connection.moodle_user_id is None:
                raise TaskStateConflict("Moodle connection must be active and validated")

            latest = session.scalar(
                select(QuizDraftSnapshotModel)
                .where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
                .order_by(QuizDraftSnapshotModel.version_no.desc())
                .limit(1)
                .with_for_update()
            )
            if expected_status is TaskStatus.VALIDATING:
                if latest is not None:
                    raise TaskStateConflict("task already has a snapshot")
                version_no = 1
            else:
                if latest is None:
                    raise TaskStateConflict("base snapshot is missing")
                _assert_snapshot_integrity(latest)
                if (
                    str(latest.id) != base_snapshot_id
                    or latest.snapshot_hash != base_snapshot_hash
                ):
                    raise TaskStateConflict("base snapshot is stale")
                version_no = latest.version_no + 1

            destination: dict[str, object] = {
                "connection_id": str(connection.id),
                "course_id": task.course_id,
                "site_url": connection.site_url,
            }
            content = _draft_content(draft)
            report_payload = _quality_payload(quality_report)
            digest = snapshot_hash(
                destination=destination,
                content={**content, "quality_report": report_payload},
                schema_version=draft.preview.schema_version,
            )
            row = QuizDraftSnapshotModel(
                id=uuid.uuid4(),
                tenant_id=tenant_uuid,
                task_id=task_uuid,
                version_no=version_no,
                snapshot_hash=digest,
                schema_version=draft.preview.schema_version,
                destination=destination,
                content=content,
                quality_report=report_payload,
                created_by_membership_id=membership_uuid,
                created_at=timestamp,
            )
            session.add(row)
            session.flush()

            old_status = TaskStatus(task.status)
            if expected_status is TaskStatus.VALIDATING:
                new_task = transition(Task(TaskStatus(task.status)), TaskStatus.AWAITING_APPROVAL)
                task.status = new_task.status.value
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="DRAFT_READY",
                    from_status=old_status.value if old_status is not TaskStatus.AWAITING_APPROVAL else None,
                    to_status=task.status,
                    message_code="QUIZ_DRAFT_SNAPSHOT_CREATED",
                    payload={
                        "snapshot_id": str(row.id),
                        "snapshot_hash": digest,
                        "version_no": version_no,
                    },
                    occurred_at=timestamp,
                )
            )
            session.add(
                OutboxEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    event_type="DRAFT_READY",
                    payload={
                        "task_id": str(task_uuid),
                        "snapshot_id": str(row.id),
                        "snapshot_hash": digest,
                    },
                )
            )
            session.flush()
            return _snapshot_record(row)

    def get_current_snapshot(self, ctx: ActiveContext, task_id: str) -> SnapshotRecord:
        task_uuid, tenant_uuid = _uuid(task_id), _uuid(ctx.tenant_id)
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == task_uuid,
                    TaskModel.tenant_id == tenant_uuid,
                )
            )
            if task is None:
                raise ResourceNotFound("resource not found")
            row = session.scalar(
                select(QuizDraftSnapshotModel)
                .where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
                .order_by(QuizDraftSnapshotModel.version_no.desc())
                .limit(1)
            )
            if row is None:
                raise ResourceNotFound("snapshot not found")
            return _snapshot_record(row)

    def get_verified_result(self, ctx: ActiveContext, task_id: str) -> dict[str, object]:
        """Return only a result still backed by a completed, verified publish ledger."""
        task_uuid, tenant_uuid = _uuid(task_id), _uuid(ctx.tenant_id)
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == task_uuid,
                    TaskModel.tenant_id == tenant_uuid,
                )
            )
            if task is None:
                raise ResourceNotFound("resource not found")
            payload = task.result_payload if isinstance(task.result_payload, dict) else {}
            if (
                task.status != TaskStatus.COMPLETED.value
                or payload.get("verification_status") != "VERIFIED"
                or payload.get("external_object_type") != "QUIZ"
                or payload.get("expected_content_match") is not True
            ):
                raise ResourceNotFound("verified result not found")
            intent = session.scalar(
                select(PublishIntentModel).where(
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                    PublishIntentModel.state == PublishState.COMPLETED.value,
                )
            )
            if intent is None:
                raise TaskStateConflict("verified result is missing its completed publish intent")
            snapshot = session.scalar(
                select(QuizDraftSnapshotModel).where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.id == intent.snapshot_id,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
            )
            if snapshot is None:
                raise TaskStateConflict("verified result is missing its immutable snapshot")
            _assert_snapshot_integrity(snapshot)
            create_step = session.scalar(
                select(ToolInvocationModel).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent.id,
                    ToolInvocationModel.step_kind == "CREATE_QUIZ",
                    ToolInvocationModel.state.in_(
                        (StepState.SUCCEEDED.value, StepState.RECONCILED_PRESENT.value)
                    ),
                ).limit(1)
            )
            if (
                intent.snapshot_hash != snapshot.snapshot_hash
                or payload.get("snapshot_hash") != snapshot.snapshot_hash
                or payload.get("course_id") != snapshot.destination.get("course_id")
                or create_step is None
                or payload.get("external_object_id") != create_step.external_ref
            ):
                raise TaskStateConflict("verified result does not match its publish evidence")
            return payload

    def record_approval(
        self,
        ctx: ActiveContext,
        *,
        task_id: str,
        snapshot_id: str,
        snapshot_hash_value: str,
        decision: ApprovalDecision,
        comment: str | None,
        idempotency_key: str,
        idempotency_hmac_key: bytes,
        approval_ttl_seconds: int,
        decided_at: datetime | None = None,
    ) -> ApprovalResult:
        task_uuid, snapshot_uuid = _uuid(task_id), _uuid(snapshot_id)
        tenant_uuid, membership_uuid = _uuid(ctx.tenant_id), _uuid(ctx.membership_id)
        timestamp = decided_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        if not 60 <= approval_ttl_seconds <= 86_400:
            raise ValueError("approval_ttl_seconds must be configured between 60 and 86400")
        if not idempotency_key or len(idempotency_key) < 22 or len(idempotency_key) > 200:
            raise ValueError("Idempotency-Key must contain 22..200 characters")
        if (
            len(snapshot_hash_value) != 64
            or any(ch not in "0123456789abcdef" for ch in snapshot_hash_value)
        ):
            raise ValueError("snapshot_hash must be lowercase SHA-256")
        normalized_comment = comment.strip() if comment is not None else None
        if normalized_comment == "":
            normalized_comment = None
        if normalized_comment is not None and len(normalized_comment) > 2000:
            raise ValueError("approval comment exceeds 2000 characters")
        key_hash = hmac.new(idempotency_hmac_key, idempotency_key.encode(), hashlib.sha256).hexdigest()
        request_hash = canonical_hash(
            {
                "task_id": task_id,
                "snapshot_id": snapshot_id,
                "snapshot_hash": snapshot_hash_value,
                "decision": decision.value,
                "comment": normalized_comment,
            }
        )

        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(
                    TaskModel.id == task_uuid,
                    TaskModel.tenant_id == tenant_uuid,
                )
                .with_for_update()
            )
            if task is None:
                raise ResourceNotFound("resource not found")

            active_membership = session.scalar(
                select(MembershipModel).where(
                    MembershipModel.id == membership_uuid,
                    MembershipModel.tenant_id == tenant_uuid,
                    MembershipModel.status == "ACTIVE",
                )
            )
            if active_membership is None:
                raise TaskStateConflict("active membership is required to approve this snapshot")

            current = session.scalar(
                select(QuizDraftSnapshotModel)
                .where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
                .order_by(QuizDraftSnapshotModel.version_no.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                current is None
                or current.id != snapshot_uuid
                or current.snapshot_hash != snapshot_hash_value
            ):
                raise TaskStateConflict("approval refers to a stale snapshot")
            _assert_snapshot_integrity(current)

            idem = session.scalar(
                select(QuizApprovalModel).where(
                    QuizApprovalModel.tenant_id == tenant_uuid,
                    QuizApprovalModel.approver_membership_id == membership_uuid,
                    QuizApprovalModel.idempotency_key_hash == key_hash,
                )
            )
            if idem is not None:
                if idem.request_hash != request_hash:
                    raise TaskStateConflict("idempotency key was reused with a different approval")
                if idem.snapshot_id != current.id or idem.snapshot_hash != current.snapshot_hash:
                    raise TaskStateConflict("idempotent approval refers to a stale snapshot")
                return _approval_result(idem, replayed=True)

            if task.status != TaskStatus.AWAITING_APPROVAL.value:
                raise TaskStateConflict("task is not awaiting approval")

            existing_actor_decision = session.scalar(
                select(QuizApprovalModel).where(
                    QuizApprovalModel.tenant_id == tenant_uuid,
                    QuizApprovalModel.task_id == task_uuid,
                    QuizApprovalModel.snapshot_id == snapshot_uuid,
                    QuizApprovalModel.approver_membership_id == membership_uuid,
                )
            )
            if existing_actor_decision is not None:
                if (
                    existing_actor_decision.request_hash == request_hash
                    and existing_actor_decision.decision == decision.value
                ):
                    return _approval_result(existing_actor_decision, replayed=True)
                raise TaskStateConflict("this membership already decided on this snapshot")

            expires_at = timestamp + timedelta(seconds=approval_ttl_seconds)
            approval = QuizApprovalModel(
                id=uuid.uuid4(),
                tenant_id=tenant_uuid,
                task_id=task_uuid,
                snapshot_id=snapshot_uuid,
                snapshot_hash=snapshot_hash_value,
                approver_membership_id=membership_uuid,
                decision=decision.value,
                comment=normalized_comment,
                idempotency_key_hash=key_hash,
                request_hash=request_hash,
                decided_at=timestamp,
                expires_at=expires_at,
            )
            session.add(approval)
            old_status = TaskStatus(task.status)
            new_status = TaskStatus.APPROVED if decision is ApprovalDecision.APPROVED else TaskStatus.REJECTED
            updated = transition(Task(status=old_status), new_status)
            task.status = updated.status.value
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="APPROVAL_RECORDED",
                    from_status=old_status.value,
                    to_status=new_status.value,
                    message_code=f"QUIZ_{decision.value}",
                    payload={
                        "approval_id": str(approval.id),
                        "snapshot_id": str(snapshot_uuid),
                        "snapshot_hash": snapshot_hash_value,
                        "decision": decision.value,
                        "approver_membership_id": str(membership_uuid),
                    },
                    occurred_at=timestamp,
                )
            )
            session.add(
                OutboxEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    event_type="APPROVAL_RECORDED",
                    payload={
                        "task_id": str(task_uuid),
                        "approval_id": str(approval.id),
                        "snapshot_id": str(snapshot_uuid),
                        "snapshot_hash": snapshot_hash_value,
                        "decision": decision.value,
                    },
                )
            )
            session.flush()
            return _approval_result(approval)

    def create_publish_intent_for_worker(
        self, *, tenant_id: str, task_id: str, occurred_at: datetime | None = None
    ) -> PublishIntentRecord:
        """Prepare one durable publish intent after approval; does not contact Moodle."""
        tenant_uuid, task_uuid = _uuid(tenant_id), _uuid(task_id)
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(TaskModel.id == task_uuid, TaskModel.tenant_id == tenant_uuid)
                .with_for_update()
            )
            if task is None:
                raise ResourceNotFound("resource not found")
            if task.status != TaskStatus.APPROVED.value:
                raise TaskStateConflict("task must be approved before publish preparation")
            if task.task_type != "CREATE_QUIZ":
                raise TaskStateConflict("P7 publish currently supports CREATE_QUIZ only")
            snapshot = session.scalar(
                select(QuizDraftSnapshotModel)
                .where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
                .order_by(QuizDraftSnapshotModel.version_no.desc())
                .limit(1)
                .with_for_update()
            )
            if snapshot is None:
                raise TaskStateConflict("current snapshot is missing")
            _assert_snapshot_integrity(snapshot)
            existing = session.scalar(
                select(PublishIntentModel).where(
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                    PublishIntentModel.snapshot_id == snapshot.id,
                )
            )
            if existing is not None:
                return _publish_record(existing)
            approval = session.scalar(
                select(QuizApprovalModel)
                .where(
                    QuizApprovalModel.tenant_id == tenant_uuid,
                    QuizApprovalModel.task_id == task_uuid,
                    QuizApprovalModel.snapshot_id == snapshot.id,
                    QuizApprovalModel.snapshot_hash == snapshot.snapshot_hash,
                    QuizApprovalModel.decision == ApprovalDecision.APPROVED.value,
                    QuizApprovalModel.decided_at <= timestamp,
                    QuizApprovalModel.expires_at > timestamp,
                )
                .order_by(QuizApprovalModel.decided_at.desc())
                .limit(1)
                .with_for_update()
            )
            if approval is None:
                raise TaskStateConflict("no valid approval exists for the current snapshot")
            intent_id = uuid.uuid4()
            op_key = external_operation_key(str(intent_id))
            intent = PublishIntentModel(
                id=intent_id,
                tenant_id=tenant_uuid,
                task_id=task_uuid,
                snapshot_id=snapshot.id,
                approval_id=approval.id,
                snapshot_hash=snapshot.snapshot_hash,
                external_operation_key=op_key,
                state=PublishState.PREPARED.value,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(intent)
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="PUBLISH_PREPARED",
                    from_status=TaskStatus.APPROVED.value,
                    to_status=TaskStatus.APPROVED.value,
                    message_code="PUBLISH_INTENT_PREPARED",
                    payload={
                        "publish_intent_id": str(intent_id),
                        "snapshot_id": str(snapshot.id),
                        "snapshot_hash": snapshot.snapshot_hash,
                    },
                    occurred_at=timestamp,
                )
            )
            session.add(
                OutboxEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    event_type="PUBLISH_PREPARED",
                    payload={
                        "task_id": str(task_uuid),
                        "publish_intent_id": str(intent_id),
                        "snapshot_id": str(snapshot.id),
                        "snapshot_hash": snapshot.snapshot_hash,
                        "external_operation_key": op_key,
                    },
                )
            )
            session.flush()
            return _publish_record(intent)

    def plan_external_step(
        self,
        *,
        tenant_id: str,
        publish_intent_id: str,
        step_kind: str,
        ordinal: int,
        request: dict[str, object],
        occurred_at: datetime | None = None,
    ) -> str:
        """Create/replay a deterministic step plan before any external dispatch."""
        tenant_uuid, intent_uuid = _uuid(tenant_id), _uuid(publish_intent_id)
        if not step_kind or step_kind != step_kind.strip() or len(step_kind) > 64:
            raise ValueError("step_kind must be 1..64 trimmed characters")
        if step_kind != "CREATE_QUIZ":
            raise TaskStateConflict("P7 external-step registry currently permits CREATE_QUIZ only")
        if ordinal != 0:
            raise TaskStateConflict("P7 permits exactly one CREATE_QUIZ step per publish")
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            intent = session.scalar(
                select(PublishIntentModel)
                .where(
                    PublishIntentModel.id == intent_uuid,
                    PublishIntentModel.tenant_id == tenant_uuid,
                )
                .with_for_update()
            )
            if intent is None:
                raise ResourceNotFound("resource not found")
            if intent.state != PublishState.PREPARED.value:
                raise TaskStateConflict("the complete external-step plan must be frozen before dispatch")
            count = session.scalar(
                select(func.count()).select_from(ToolInvocationModel).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                )
            ) or 0
            if count >= MAX_EXTERNAL_STEPS_PER_PUBLISH and session.scalar(
                select(ToolInvocationModel.id).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.step_kind == step_kind,
                    ToolInvocationModel.ordinal == ordinal,
                )
            ) is None:
                raise TaskStateConflict("publish external-step envelope exceeded")
            step_key = external_step_key(intent.external_operation_key, step_kind, ordinal)
            request_hash_value = canonical_hash(request)
            existing = session.scalar(
                select(ToolInvocationModel).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.external_step_key == step_key,
                )
            )
            if existing is not None:
                if existing.request_hash != request_hash_value:
                    raise TaskStateConflict("external step key reused with a different request")
                return existing.external_step_key
            session.add(
                ToolInvocationModel(
                    id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    publish_intent_id=intent_uuid,
                    external_step_key=step_key,
                    step_kind=step_kind,
                    ordinal=ordinal,
                    attempt_no=0,
                    request_hash=request_hash_value,
                    state=StepState.PLANNED.value,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            session.flush()
            return step_key

    def mark_step_dispatched(
        self,
        *,
        tenant_id: str,
        task_id: str,
        publish_intent_id: str,
        step_key: str,
        occurred_at: datetime | None = None,
    ) -> int:
        """Persist DISPATCHED before network I/O; stale approval/snapshot blocks the write."""
        tenant_uuid, task_uuid, intent_uuid = (
            _uuid(tenant_id),
            _uuid(task_id),
            _uuid(publish_intent_id),
        )
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(TaskModel.id == task_uuid, TaskModel.tenant_id == tenant_uuid)
                .with_for_update()
            )
            intent = session.scalar(
                select(PublishIntentModel)
                .where(
                    PublishIntentModel.id == intent_uuid,
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                )
                .with_for_update()
            )
            if task is None or intent is None:
                raise ResourceNotFound("resource not found")
            if task.task_type != "CREATE_QUIZ":
                raise TaskStateConflict("P7 dispatch currently supports CREATE_QUIZ only")
            if task.cancel_requested:
                raise TaskStateConflict("publish dispatch is blocked by a pending cancellation")
            if intent.state not in {
                PublishState.PREPARED.value,
                PublishState.EXECUTING.value,
                PublishState.NEEDS_RECONCILIATION.value,
            }:
                raise TaskStateConflict("publish intent is not dispatchable")
            current_snapshot = session.scalar(
                select(QuizDraftSnapshotModel)
                .where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
                .order_by(QuizDraftSnapshotModel.version_no.desc())
                .limit(1)
            )
            if current_snapshot is None or current_snapshot.id != intent.snapshot_id or current_snapshot.snapshot_hash != intent.snapshot_hash:
                raise TaskStateConflict("publish intent does not refer to the current snapshot")
            preflight = self._publish_authorizer.preflight(
                task_id=str(task_uuid), snapshot=_descriptor(current_snapshot)
            )
            preflight.require_ready()
            approval = session.scalar(
                select(QuizApprovalModel).where(
                    QuizApprovalModel.id == intent.approval_id,
                    QuizApprovalModel.tenant_id == tenant_uuid,
                )
            )
            if (
                current_snapshot is None
                or current_snapshot.id != intent.snapshot_id
                or current_snapshot.snapshot_hash != intent.snapshot_hash
                or approval is None
                or approval.decision != ApprovalDecision.APPROVED.value
                or approval.snapshot_hash != intent.snapshot_hash
                or approval.decided_at > timestamp
                or approval.expires_at <= timestamp
            ):
                raise TaskStateConflict("snapshot or approval is no longer valid")
            approver_membership = session.scalar(
                select(MembershipModel).where(
                    MembershipModel.id == approval.approver_membership_id,
                    MembershipModel.tenant_id == tenant_uuid,
                )
            )
            connection = session.scalar(
                select(MoodleConnectionModel).where(
                    MoodleConnectionModel.id == current_snapshot.destination["connection_id"],
                    MoodleConnectionModel.tenant_id == tenant_uuid,
                )
            )
            if approver_membership is None or approver_membership.status != "ACTIVE":
                raise TaskStateConflict("approving membership is no longer active")
            if connection is None or connection.status != "ACTIVE" or connection.moodle_user_id is None:
                raise TaskStateConflict("Moodle connection is no longer active")
            step = session.scalar(
                select(ToolInvocationModel)
                .where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.external_step_key == step_key,
                )
                .with_for_update()
            )
            if step is None:
                raise ResourceNotFound("external step not found")
            other_dispatched = session.scalar(
                select(ToolInvocationModel.id).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.state == StepState.DISPATCHED.value,
                    ToolInvocationModel.id != step.id,
                ).limit(1)
            )
            if other_dispatched is not None:
                raise TaskStateConflict("only one external write step may be dispatched at a time")
            state = StepState(step.state)
            domain_step = Step(step_key, state, step.attempt_no)
            if not can_auto_retry(domain_step):
                raise TaskStateConflict("external step is not safe to dispatch")
            if task.status == TaskStatus.NEEDS_RECONCILIATION.value:
                unresolved = session.scalar(
                    select(ToolInvocationModel.id).where(
                        ToolInvocationModel.tenant_id == tenant_uuid,
                        ToolInvocationModel.publish_intent_id == intent_uuid,
                        ToolInvocationModel.state.in_((StepState.UNKNOWN.value, StepState.MANUAL_REVIEW.value)),
                        ToolInvocationModel.id != step.id,
                    ).limit(1)
                )
                if unresolved is not None:
                    raise TaskStateConflict("other external steps still require reconciliation")
                task_update = transition(
                    Task(TaskStatus(task.status), task.cancel_requested, task.external_dispatched),
                    TaskStatus.EXECUTING,
                    absence_proven=state is StepState.RECONCILED_ABSENT,
                )
            elif task.status == TaskStatus.APPROVED.value:
                task_update = transition(Task(TaskStatus(task.status)), TaskStatus.EXECUTING)
            elif task.status == TaskStatus.EXECUTING.value:
                task_update = Task(TaskStatus.EXECUTING, task.cancel_requested, True)
            else:
                raise TaskStateConflict("task is not in an executable publish state")
            dispatched = begin_dispatch(domain_step)
            old_status = TaskStatus(task.status)
            task.status = task_update.status.value
            task.external_dispatched = True
            task.cancel_requested = task_update.cancel_requested
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            step.state = dispatched.state.value
            step.attempt_no = dispatched.attempt_no
            step.dispatched_at = timestamp
            step.updated_at = timestamp
            intent.state = PublishState.EXECUTING.value
            intent.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="EXTERNAL_DISPATCHED",
                    from_status=old_status.value,
                    to_status=TaskStatus.EXECUTING.value,
                    message_code="MOODLE_WRITE_DISPATCHED",
                    payload={
                        "publish_intent_id": str(intent_uuid),
                        "external_step_key": step_key,
                        "step_kind": step.step_kind,
                        "attempt_no": dispatched.attempt_no,
                    },
                    occurred_at=timestamp,
                )
            )
            session.flush()
            return dispatched.attempt_no

    def record_step_outcome(
        self,
        *,
        tenant_id: str,
        task_id: str,
        publish_intent_id: str,
        step_key: str,
        outcome: str,
        response_hash: str | None = None,
        external_ref: str | None = None,
        occurred_at: datetime | None = None,
    ) -> StepState:
        """Record success/definite failure/ambiguous response; UNKNOWN never auto-retries."""
        if outcome not in {"SUCCEEDED", "FAILED_DEFINITE", "UNKNOWN"}:
            raise ValueError("outcome must be SUCCEEDED, FAILED_DEFINITE or UNKNOWN")
        tenant_uuid, task_uuid, intent_uuid = (
            _uuid(tenant_id),
            _uuid(task_id),
            _uuid(publish_intent_id),
        )
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(TaskModel.id == task_uuid, TaskModel.tenant_id == tenant_uuid)
                .with_for_update()
            )
            intent = session.scalar(
                select(PublishIntentModel)
                .where(
                    PublishIntentModel.id == intent_uuid,
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                )
                .with_for_update()
            )
            step = session.scalar(
                select(ToolInvocationModel)
                .where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.external_step_key == step_key,
                )
                .with_for_update()
            )
            if task is None or intent is None or step is None:
                raise ResourceNotFound("resource not found")
            if response_hash is not None and (
                len(response_hash) != 64 or any(ch not in "0123456789abcdef" for ch in response_hash)
            ):
                raise ValueError("response_hash must be lowercase SHA-256")
            if external_ref is not None and (not external_ref.strip() or len(external_ref) > 512):
                raise ValueError("external_ref must be non-empty and <= 512 characters")
            if outcome == "UNKNOWN" and (response_hash is not None or external_ref is not None):
                raise ValueError("UNKNOWN outcomes cannot contain an untrusted response")
            # A worker may lose the database commit acknowledgement after persisting an outcome.
            # Accept an exact replay, but never let the same step key acquire a different result.
            expected_state = StepState(outcome)
            if StepState(step.state) is expected_state:
                if step.response_hash != response_hash or step.external_ref != external_ref:
                    raise TaskStateConflict("external-step outcome replay does not match the stored result")
                return expected_state
            domain_step = Step(step_key, StepState(step.state), step.attempt_no)
            old_status = TaskStatus(task.status)
            if outcome == "SUCCEEDED":
                if response_hash is None:
                    raise ValueError("successful external step requires a response_hash")
                if step.step_kind == "CREATE_QUIZ" and external_ref is None:
                    raise ValueError("CREATE_QUIZ success requires an external_ref")
                updated_step = record_success(domain_step)
                step.response_hash = response_hash
                step.external_ref = external_ref
            elif outcome == "FAILED_DEFINITE":
                updated_step = record_definite_failure(domain_step)
                step.response_hash = response_hash
                step.external_ref = external_ref
                prior_effect = session.scalar(
                    select(ToolInvocationModel.id).where(
                        ToolInvocationModel.tenant_id == tenant_uuid,
                        ToolInvocationModel.publish_intent_id == intent_uuid,
                        ToolInvocationModel.id != step.id,
                        ToolInvocationModel.state.in_(
                            (StepState.SUCCEEDED.value, StepState.RECONCILED_PRESENT.value)
                        ),
                    ).limit(1)
                )
                if prior_effect is not None:
                    intent.state = PublishState.NEEDS_RECONCILIATION.value
                    task.status = transition(
                        Task(TaskStatus(task.status), task.cancel_requested, task.external_dispatched),
                        TaskStatus.NEEDS_RECONCILIATION,
                    ).status.value
                else:
                    intent.state = PublishState.FAILED.value
                    task.status = transition(
                        Task(TaskStatus(task.status), task.cancel_requested, task.external_dispatched),
                        TaskStatus.FAILED,
                    ).status.value
            else:
                updated_step = record_response_lost(domain_step)
                intent.state = PublishState.NEEDS_RECONCILIATION.value
                task.status = transition(
                    Task(TaskStatus(task.status), task.cancel_requested, task.external_dispatched),
                    TaskStatus.NEEDS_RECONCILIATION,
                ).status.value
            step.state = updated_step.state.value
            step.updated_at = timestamp
            intent.updated_at = timestamp
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            event_type = {
                "SUCCEEDED": "EXTERNAL_STEP_SUCCEEDED",
                "FAILED_DEFINITE": "EXTERNAL_STEP_FAILED",
                "UNKNOWN": "EXTERNAL_OUTCOME_UNKNOWN",
            }[outcome]
            message_code = {
                "SUCCEEDED": "EXTERNAL_STEP_SUCCEEDED",
                "FAILED_DEFINITE": "EXTERNAL_STEP_FAILED",
                "UNKNOWN": "EXTERNAL_OUTCOME_UNKNOWN",
            }[outcome]
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type=event_type,
                    from_status=old_status.value,
                    to_status=TaskStatus(task.status).value,
                    message_code=message_code,
                    payload={
                        "publish_intent_id": str(intent_uuid),
                        "external_step_key": step_key,
                        "step_kind": step.step_kind,
                        "step_state": updated_step.state.value,
                        "response_hash": response_hash,
                        "external_ref": external_ref,
                    },
                    occurred_at=timestamp,
                )
            )
            session.flush()
            return updated_step.state

    def reconcile_step(
        self,
        *,
        tenant_id: str,
        task_id: str,
        publish_intent_id: str,
        step_key: str,
        lookup_result: LookupResult,
        external_ref: str | None = None,
        response_hash: str | None = None,
        occurred_at: datetime | None = None,
    ) -> StepState:
        """Only a trusted lookup may establish presence/absence; otherwise require manual review."""
        tenant_uuid, task_uuid, intent_uuid = (
            _uuid(tenant_id),
            _uuid(task_id),
            _uuid(publish_intent_id),
        )
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(TaskModel.id == task_uuid, TaskModel.tenant_id == tenant_uuid)
                .with_for_update()
            )
            intent = session.scalar(
                select(PublishIntentModel)
                .where(
                    PublishIntentModel.id == intent_uuid,
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                )
                .with_for_update()
            )
            step = session.scalar(
                select(ToolInvocationModel)
                .where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.external_step_key == step_key,
                )
                .with_for_update()
            )
            if task is None or intent is None or step is None:
                raise ResourceNotFound("resource not found")
            if response_hash is not None and (
                len(response_hash) != 64 or any(ch not in "0123456789abcdef" for ch in response_hash)
            ):
                raise ValueError("response_hash must be lowercase SHA-256")
            if external_ref is not None and (not external_ref.strip() or len(external_ref) > 512):
                raise ValueError("external_ref must be non-empty and <= 512 characters")
            if lookup_result is LookupResult.PRESENT and step.step_kind == "CREATE_QUIZ" and not external_ref:
                raise TaskStateConflict("trusted quiz lookup must return the external quiz identifier")
            if lookup_result is not LookupResult.PRESENT and (
                external_ref is not None or response_hash is not None
            ):
                raise ValueError("absence/manual reconciliation cannot contain external evidence")
            expected_state = {
                LookupResult.PRESENT: StepState.RECONCILED_PRESENT,
                LookupResult.ABSENT: StepState.RECONCILED_ABSENT,
                LookupResult.NO_TRUSTED_LOOKUP: StepState.MANUAL_REVIEW,
            }[lookup_result]
            if StepState(step.state) is expected_state:
                if lookup_result is LookupResult.PRESENT:
                    if step.external_ref != external_ref or step.response_hash != response_hash:
                        raise TaskStateConflict("reconciliation replay does not match the stored evidence")
                elif external_ref is not None or response_hash is not None:
                    raise TaskStateConflict("absence/manual reconciliation cannot contain external evidence")
                return expected_state
            updated_step = reconcile(
                Step(step_key, StepState(step.state), step.attempt_no), lookup_result
            )
            step.state = updated_step.state.value
            if lookup_result is LookupResult.PRESENT:
                step.external_ref = external_ref
                step.response_hash = response_hash
            step.reconciled_at = timestamp
            step.updated_at = timestamp
            old_status = TaskStatus(task.status)
            if lookup_result is LookupResult.PRESENT:
                # Keep the aggregate in reconciliation until every sibling step is settled;
                # begin_verification performs the single legal transition afterwards.
                intent.state = PublishState.NEEDS_RECONCILIATION.value
            elif lookup_result is LookupResult.ABSENT:
                # Preserve NEEDS_RECONCILIATION until mark_step_dispatched proves all unknown
                # sibling steps are settled and atomically records the next dispatch.
                intent.state = PublishState.NEEDS_RECONCILIATION.value
            else:
                intent.state = PublishState.MANUAL_REVIEW.value
            intent.updated_at = timestamp
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="RECONCILIATION_UPDATED",
                    from_status=old_status.value,
                    to_status=TaskStatus(task.status).value,
                    message_code=f"RECONCILIATION_{lookup_result.value}",
                    payload={
                        "publish_intent_id": str(intent_uuid),
                        "external_step_key": step_key,
                        "step_state": updated_step.state.value,
                    },
                    occurred_at=timestamp,
                )
            )
            session.flush()
            return updated_step.state

    def begin_verification(
        self,
        *,
        tenant_id: str,
        task_id: str,
        publish_intent_id: str,
        occurred_at: datetime | None = None,
    ) -> None:
        """Move to verification only after every planned external step is settled successfully."""
        tenant_uuid, task_uuid, intent_uuid = (
            _uuid(tenant_id),
            _uuid(task_id),
            _uuid(publish_intent_id),
        )
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(TaskModel.id == task_uuid, TaskModel.tenant_id == tenant_uuid)
                .with_for_update()
            )
            intent = session.scalar(
                select(PublishIntentModel)
                .where(
                    PublishIntentModel.id == intent_uuid,
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                )
                .with_for_update()
            )
            if task is None or intent is None:
                raise ResourceNotFound("resource not found")
            if (
                task.status == TaskStatus.VERIFYING.value
                and intent.state == PublishState.VERIFYING.value
            ):
                return
            any_step = session.scalar(
                select(ToolInvocationModel.id).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                ).limit(1)
            )
            create_step = session.scalar(
                select(ToolInvocationModel.id).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.step_kind == "CREATE_QUIZ",
                    ToolInvocationModel.state.in_((StepState.SUCCEEDED.value, StepState.RECONCILED_PRESENT.value)),
                    ToolInvocationModel.external_ref.is_not(None),
                ).limit(1)
            )
            if any_step is None or create_step is None:
                raise TaskStateConflict("verified quiz creation evidence is missing")
            pending = session.scalar(
                select(ToolInvocationModel.id).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.state.not_in((
                        StepState.SUCCEEDED.value, StepState.RECONCILED_PRESENT.value
                    )),
                ).limit(1)
            )
            if pending is not None:
                raise TaskStateConflict("publish still has unsettled external steps")
            if task.status not in {
                TaskStatus.EXECUTING.value,
                TaskStatus.NEEDS_RECONCILIATION.value,
            }:
                raise TaskStateConflict("task is not ready for verification")
            old_status = TaskStatus(task.status)
            task.status = transition(Task(TaskStatus(task.status)), TaskStatus.VERIFYING).status.value
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            intent.state = PublishState.VERIFYING.value
            intent.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="STATUS_CHANGED",
                    from_status=old_status.value,
                    to_status=TaskStatus.VERIFYING.value,
                    message_code="EXTERNAL_STEPS_SETTLED_VERIFY_REQUIRED",
                    payload={"publish_intent_id": str(intent_uuid)},
                    occurred_at=timestamp,
                )
            )
            session.flush()

    def complete_verified_publish(
        self,
        *,
        tenant_id: str,
        task_id: str,
        publish_intent_id: str,
        snapshot_hash_value: str,
        verification: dict[str, object],
        occurred_at: datetime | None = None,
    ) -> None:
        """Complete only after a trusted Moodle verifier has matched the created quiz."""
        if verification.get("verified") is not True or verification.get("expected_content_match") is not True:
            raise TaskStateConflict("Moodle verifier did not confirm the expected quiz content")
        verified_hash = verification.get("snapshot_hash")
        if not isinstance(verified_hash, str) or len(verified_hash) != 64:
            raise TaskStateConflict("Moodle verification is not bound to a snapshot hash")
        if verification.get("external_object_type") != "QUIZ":
            raise TaskStateConflict("Moodle verifier returned an unexpected resource type")
        external_id = verification.get("external_object_id")
        if not isinstance(external_id, str) or not external_id.strip() or len(external_id) > 512:
            raise ValueError("verified external_object_id is required")
        tenant_uuid, task_uuid, intent_uuid = (
            _uuid(tenant_id),
            _uuid(task_id),
            _uuid(publish_intent_id),
        )
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel)
                .where(TaskModel.id == task_uuid, TaskModel.tenant_id == tenant_uuid)
                .with_for_update()
            )
            intent = session.scalar(
                select(PublishIntentModel)
                .where(
                    PublishIntentModel.id == intent_uuid,
                    PublishIntentModel.tenant_id == tenant_uuid,
                    PublishIntentModel.task_id == task_uuid,
                )
                .with_for_update()
            )
            if task is None or intent is None:
                raise ResourceNotFound("resource not found")
            snapshot = session.scalar(
                select(QuizDraftSnapshotModel).where(
                    QuizDraftSnapshotModel.tenant_id == tenant_uuid,
                    QuizDraftSnapshotModel.id == intent.snapshot_id,
                    QuizDraftSnapshotModel.task_id == task_uuid,
                )
            )
            if snapshot is not None and task.status == TaskStatus.COMPLETED.value and intent.state == PublishState.COMPLETED.value:
                stored = task.result_payload or {}
                if (
                    snapshot.snapshot_hash == snapshot_hash_value
                    and stored.get("external_object_type") == "QUIZ"
                    and stored.get("external_object_id") == external_id
                    and stored.get("verification_status") == "VERIFIED"
                    and stored.get("snapshot_hash") == snapshot_hash_value
                    and stored.get("course_id") == verification.get("course_id")
                    and stored.get("expected_content_match") is True
                ):
                    return
                raise TaskStateConflict("completed publish replay does not match the verified result")
            if snapshot is not None:
                _assert_snapshot_integrity(snapshot)
            if (
                snapshot is None
                or snapshot.snapshot_hash != snapshot_hash_value
                or intent.snapshot_hash != snapshot_hash_value
                or verified_hash != snapshot_hash_value
                or verification.get("course_id") != snapshot.destination.get("course_id")
                or intent.state != PublishState.VERIFYING.value
                or task.status != TaskStatus.VERIFYING.value
            ):
                raise TaskStateConflict("publish intent is not ready for verified completion")
            unsettled = session.scalar(
                select(ToolInvocationModel.id).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.state.not_in((
                        StepState.SUCCEEDED.value, StepState.RECONCILED_PRESENT.value
                    )),
                ).limit(1)
            )
            create_step = session.scalar(
                select(ToolInvocationModel).where(
                    ToolInvocationModel.tenant_id == tenant_uuid,
                    ToolInvocationModel.publish_intent_id == intent_uuid,
                    ToolInvocationModel.step_kind == "CREATE_QUIZ",
                    ToolInvocationModel.state.in_((StepState.SUCCEEDED.value, StepState.RECONCILED_PRESENT.value)),
                ).limit(1)
            )
            if unsettled is not None:
                raise TaskStateConflict("publish still has unsettled external steps")
            if create_step is None or create_step.external_ref != external_id:
                raise TaskStateConflict("verified quiz identifier does not match the external-step ledger")
            updated = transition(Task(TaskStatus(task.status)), TaskStatus.COMPLETED)
            task.status = updated.status.value
            task.result_payload = {
                "external_object_type": "QUIZ",
                "external_object_id": external_id,
                "verification_status": "VERIFIED",
                "verified_at": timestamp.isoformat(),
                "snapshot_hash": snapshot_hash_value,
                "course_id": verification["course_id"],
                "expected_content_match": True,
            }
            task.latest_event_sequence += 1
            task.updated_at = timestamp
            intent.state = PublishState.COMPLETED.value
            intent.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=task.latest_event_sequence,
                    event_type="TASK_COMPLETED",
                    from_status=TaskStatus.VERIFYING.value,
                    to_status=TaskStatus.COMPLETED.value,
                    message_code="MOODLE_QUIZ_VERIFIED",
                    payload={
                        "publish_intent_id": str(intent_uuid),
                        "external_object_id": external_id,
                        "snapshot_hash": snapshot_hash_value,
                    },
                    occurred_at=timestamp,
                )
            )
            session.flush()


def _approval_result(row: QuizApprovalModel, *, replayed: bool = False) -> ApprovalResult:
    return ApprovalResult(
        approval_id=str(row.id),
        task_id=str(row.task_id),
        snapshot_id=str(row.snapshot_id),
        snapshot_hash=row.snapshot_hash,
        decision=ApprovalDecision(row.decision),
        decided_at=row.decided_at,
        expires_at=row.expires_at,
        replayed=replayed,
    )
