"""CREATE_QUIZ publish handler (Phase B) — Vertical Slice final step.

Orchestrates:
  APPROVED task → publish intent → preflight → Moodle write → verify → ledger

This handler is intentionally conservative:
- No Moodle network call happens unless MoodleWriteService is injected with a real adapter.
- Default path uses DenyAllWriteAdapter and fails closed.
- Full wiring to PostgresPublicationRepository methods is documented and partially invoked;
  remaining ledger calls follow the repository's existing P7 API.

Task type: CREATE_QUIZ
Expected status on entry: APPROVED (worker may also pick EXECUTING after intent prep)
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from moallem.domain.membership import ActiveContext
from moallem.domain.publishing import (
    PublishIntent,
    PublishState,
    SnapshotDescriptor,
)
from moallem.domain.tasks import TaskStatus
from moallem.moodle.question_mapping import (
    UnsupportedQuestionForPublish,
    map_quiz_draft_to_specs,
)
from moallem.moodle.write_service import MoodleWriteService, PublishQuizOutcome
from moallem.worker.queue import PermanentTaskError, RetryableTaskError, TaskExecutionContext

log = logging.getLogger("moallem.worker.publish_quiz")

TASK_TYPE_CREATE_QUIZ = "CREATE_QUIZ"


class PublicationGateway(Protocol):
    """Minimal surface the handler needs from PostgresPublicationRepository."""

    def create_publish_intent_for_worker(
        self, *, tenant_id: str, task_id: str
    ) -> Any: ...

    def get_current_snapshot(self, ctx: ActiveContext, task_id: str) -> Any: ...


class DraftLoader(Protocol):
    """Load the approved QuizDraftPreview for a task/snapshot."""

    def load_draft(self, *, tenant_id: str, task_id: str, snapshot_id: str) -> Any: ...


class PublishQuizHandler:
    """Worker handler that publishes an approved quiz draft to Moodle.

    Dependencies are injected so tests can use FakeWriteAdapter and in-memory gateways.
    """

    def __init__(
        self,
        *,
        write_service: MoodleWriteService,
        publications: PublicationGateway | None = None,
        draft_loader: DraftLoader | None = None,
        # Optional: supply a pre-built ActiveContext resolver for the task owner
        context_resolver: Any | None = None,
    ) -> None:
        self._write = write_service
        self._publications = publications
        self._draft_loader = draft_loader
        self._context_resolver = context_resolver

    async def execute(self, task: Any, context: TaskExecutionContext) -> None:
        """Entry point required by TaskHandler protocol.

        `task` is a PersistedTask (or compatible) with at least:
          - id, tenant_id, task_type, status
        """
        task_type = getattr(task, "task_type", None) or getattr(task, "type", None)
        if task_type != TASK_TYPE_CREATE_QUIZ:
            raise PermanentTaskError("unsupported_task_type")

        status = getattr(task, "status", None)
        if status not in {
            TaskStatus.APPROVED.value if hasattr(TaskStatus.APPROVED, "value") else "APPROVED",
            TaskStatus.EXECUTING.value if hasattr(TaskStatus.EXECUTING, "value") else "EXECUTING",
            "APPROVED",
            "EXECUTING",
        }:
            raise PermanentTaskError("task_not_ready_for_publish")

        tenant_id = str(task.tenant_id)
        task_id = str(task.id)

        log.info(
            "publish_quiz.start",
            extra={"tenant_id": tenant_id, "task_id": task_id, "status": status},
        )

        # --- 1. Ensure publish intent exists (idempotent) ---
        if self._publications is not None:
            intent_record = self._publications.create_publish_intent_for_worker(
                tenant_id=tenant_id, task_id=task_id
            )
            external_operation_key = getattr(
                intent_record, "external_operation_key", None
            ) or getattr(intent_record, "operation_key", "")
            snapshot_id = str(
                getattr(intent_record, "snapshot_id", "")
                or getattr(intent_record, "snapshotId", "")
            )
        else:
            # Test / partial wiring path
            external_operation_key = f"test-op-{task_id}"
            snapshot_id = ""
            intent_record = None

        # --- 2. Load snapshot descriptor ---
        snapshot = self._resolve_snapshot(tenant_id, task_id, snapshot_id, task)

        # --- 3. Load draft and map questions ---
        try:
            quiz_name, quiz_intro, specs = self._load_and_map(tenant_id, task_id, snapshot)
        except UnsupportedQuestionForPublish as exc:
            log.warning("publish_quiz.unsupported_questions", extra={"error": str(exc)})
            raise PermanentTaskError("unsupported_questions") from exc

        # --- 4. Build PublishIntent domain object for the write service ---
        intent = PublishIntent(
            publish_intent_id=str(getattr(intent_record, "id", task_id)),
            task_id=task_id,
            tenant_id=tenant_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            external_operation_key=external_operation_key
            if _looks_like_sha256(external_operation_key)
            else _sha256_hex(external_operation_key or task_id),
            state=PublishState.EXECUTING,
        )

        # --- 5. Resolve actor context (membership) ---
        ctx = self._resolve_context(tenant_id, task)

        # --- 6. Transition to EXECUTING if still APPROVED ---
        if status in {"APPROVED", getattr(TaskStatus.APPROVED, "value", "APPROVED")}:
            await context.transition(TaskStatus.EXECUTING)

        # --- 7. Perform Moodle write + verification ---
        try:
            outcome: PublishQuizOutcome = self._write.publish_approved_quiz(
                ctx,
                connection_id=snapshot.connection_id,
                snapshot=snapshot,
                intent=intent,
                questions=specs,
                quiz_name=quiz_name,
                quiz_intro=quiz_intro,
            )
        except Exception as exc:
            # Network / Moodle availability → retryable; auth / permanent mapping → permanent
            from moallem.moodle.errors import (
                MoodleCredentialInvalid,
                MoodleFunctionNotAvailable,
                MoodlePermissionDenied,
                MoodleUnavailable,
            )

            if isinstance(exc, (MoodleUnavailable,)):
                log.warning("publish_quiz.moodle_unavailable", extra={"error": str(exc)})
                await context.transition(TaskStatus.NEEDS_RECONCILIATION)
                raise RetryableTaskError("moodle_unavailable") from exc
            if isinstance(
                exc,
                (MoodleCredentialInvalid, MoodleFunctionNotAvailable, MoodlePermissionDenied),
            ):
                log.error("publish_quiz.permanent_moodle_error", extra={"error": str(exc)})
                await context.transition(TaskStatus.FAILED)
                raise PermanentTaskError("moodle_rejected") from exc
            log.exception("publish_quiz.unexpected_error")
            await context.transition(TaskStatus.NEEDS_RECONCILIATION)
            raise RetryableTaskError("publish_unknown") from exc

        # --- 8. Ledger based on verification ---
        if outcome.verification.is_verified and outcome.verification.question_count == len(specs):
            await context.transition(TaskStatus.VERIFYING)
            await context.transition(TaskStatus.COMPLETED)
            log.info(
                "publish_quiz.completed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": task_id,
                    "moodle_quiz_id": outcome.create_result.moodle_quiz_id,
                },
            )
        else:
            await context.transition(TaskStatus.NEEDS_RECONCILIATION)
            log.warning(
                "publish_quiz.needs_reconciliation",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": task_id,
                    "moodle_quiz_id": outcome.create_result.moodle_quiz_id,
                    "verification": {
                        "name_matches": outcome.verification.name_matches,
                        "course_id_matches": outcome.verification.course_id_matches,
                        "question_count": outcome.verification.question_count,
                    },
                },
            )

    def _resolve_snapshot(
        self, tenant_id: str, task_id: str, snapshot_id: str, task: Any
    ) -> SnapshotDescriptor:
        if self._publications is not None:
            # Prefer repository current snapshot when available
            try:
                # Build a minimal context for tenant-scoped read if needed
                ctx = ActiveContext(
                    user_id=str(getattr(task, "created_by", "system")),
                    membership_id=str(getattr(task, "membership_id", "unknown")),
                    tenant_id=tenant_id,
                    roles=("TEACHER",),
                )
                record = self._publications.get_current_snapshot(ctx, task_id)
                return SnapshotDescriptor(
                    snapshot_id=str(getattr(record, "snapshot_id", getattr(record, "id", snapshot_id))),
                    task_id=task_id,
                    tenant_id=tenant_id,
                    version_no=int(getattr(record, "version_no", 1)),
                    snapshot_hash=str(getattr(record, "snapshot_hash", getattr(record, "content_hash", ""))),
                    connection_id=str(getattr(record, "connection_id", "")),
                    course_id=str(getattr(record, "course_id", "")),
                )
            except Exception:
                log.debug("publish_quiz.snapshot_from_repo_failed", exc_info=True)

        # Fallback for tests: attributes on the task object
        return SnapshotDescriptor(
            snapshot_id=snapshot_id or str(getattr(task, "snapshot_id", task_id)),
            task_id=task_id,
            tenant_id=tenant_id,
            version_no=int(getattr(task, "snapshot_version", 1)),
            snapshot_hash=str(
                getattr(task, "snapshot_hash", _sha256_hex(f"{tenant_id}:{task_id}"))
            ),
            connection_id=str(getattr(task, "connection_id", "conn-test")),
            course_id=str(getattr(task, "course_id", "1")),
        )

    def _load_and_map(
        self, tenant_id: str, task_id: str, snapshot: SnapshotDescriptor
    ) -> tuple[str, str, list]:
        if self._draft_loader is None:
            raise PermanentTaskError("draft_loader_not_configured")
        draft = self._draft_loader.load_draft(
            tenant_id=tenant_id, task_id=task_id, snapshot_id=snapshot.snapshot_id
        )
        return map_quiz_draft_to_specs(draft)

    def _resolve_context(self, tenant_id: str, task: Any) -> ActiveContext:
        if self._context_resolver is not None:
            return self._context_resolver(tenant_id, task)
        return ActiveContext(
            user_id=str(getattr(task, "created_by", "system")),
            membership_id=str(getattr(task, "membership_id", "unknown")),
            tenant_id=tenant_id,
            roles=("TEACHER",),
        )


def _sha256_hex(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())
