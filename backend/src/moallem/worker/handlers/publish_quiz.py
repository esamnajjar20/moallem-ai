"""CREATE_QUIZ publish handler (Phase B) — Vertical Slice final step.

Flow (every external effect is recorded in the P7 publish ledger):

  APPROVED task
    -> publish intent (idempotent)            create_publish_intent_for_worker
    -> plan the single CREATE_QUIZ step       plan_external_step
    -> dispatch (preflight + EXECUTING)       mark_step_dispatched
    -> Moodle create                          MoodleWriteService.create_approved_quiz
    -> outcome in the ledger                  record_step_outcome
    -> VERIFYING                              begin_verification
    -> Moodle read-back                       MoodleWriteService.verify_created_quiz
    -> COMPLETED only if the read-back matches   complete_verified_publish

The repository performs the task status transitions for every step above; the handler only
transitions to NEEDS_RECONCILIATION when verification fails.

An ambiguous create (timeout, partial write, unexpected error) is recorded as UNKNOWN and is
NEVER retried automatically: only reconciliation may prove the quiz is absent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from moallem.domain.canonical import canonical_hash
from moallem.domain.errors import (
    DomainError,
    MembershipContextInvalid,
    PermissionDenied,
    ResourceNotFound,
    TaskStateConflict,
)
from moallem.domain.membership import ActiveContext
from moallem.domain.publishing import PublishIntent, SnapshotDescriptor
from moallem.domain.tasks import TaskStatus
from moallem.moodle.errors import (
    ConnectionNotActive,
    MoodleCredentialInvalid,
    MoodleFunctionNotAvailable,
    MoodlePermissionDenied,
)
from moallem.moodle.question_mapping import (
    UnsupportedQuestionForPublish,
    map_quiz_draft_to_specs,
)
from moallem.moodle.write_service import MoodleWriteService
from moallem.persistence.publishing_repository import PublishIntentRecord, SnapshotRecord
from moallem.persistence.task_repository import PersistedTask
from moallem.worker.draft_loader import draft_from_snapshot_content
from moallem.worker.queue import PermanentTaskError, RetryableTaskError, TaskExecutionContext

log = logging.getLogger("moallem.worker.publish_quiz")

TASK_TYPE_CREATE_QUIZ = "CREATE_QUIZ"
STEP_KIND = "CREATE_QUIZ"

# Failures raised before any byte can have reached Moodle, or that Moodle rejected outright.
_DEFINITE_FAILURES: tuple[type[Exception], ...] = (
    PermissionDenied,
    ResourceNotFound,
    TaskStateConflict,
    ConnectionNotActive,
    MoodleCredentialInvalid,
    MoodleFunctionNotAvailable,
    MoodlePermissionDenied,
)


class PublicationGateway(Protocol):
    """Surface the handler needs from PostgresPublicationRepository."""

    def create_publish_intent_for_worker(
        self, *, tenant_id: str, task_id: str
    ) -> PublishIntentRecord: ...

    def get_current_snapshot(self, ctx: ActiveContext, task_id: str) -> SnapshotRecord: ...

    def plan_external_step(
        self,
        *,
        tenant_id: str,
        publish_intent_id: str,
        step_kind: str,
        ordinal: int,
        request: dict[str, object],
    ) -> str: ...

    def mark_step_dispatched(
        self, *, tenant_id: str, task_id: str, publish_intent_id: str, step_key: str
    ) -> int: ...

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
    ) -> object: ...

    def begin_verification(
        self, *, tenant_id: str, task_id: str, publish_intent_id: str
    ) -> None: ...

    def complete_verified_publish(
        self,
        *,
        tenant_id: str,
        task_id: str,
        publish_intent_id: str,
        snapshot_hash_value: str,
        verification: dict[str, object],
    ) -> None: ...


class ActorResolver(Protocol):
    def resolve(self, tenant_id: str, membership_id: str) -> ActiveContext: ...


class PublishQuizHandler:
    """Worker handler that publishes an approved quiz draft to Moodle."""

    def __init__(
        self,
        *,
        write_service: MoodleWriteService,
        publications: PublicationGateway,
        actors: ActorResolver,
    ) -> None:
        self._write = write_service
        self._pubs = publications
        self._actors = actors

    async def execute(self, task: PersistedTask, context: TaskExecutionContext) -> None:
        if task.task_type != TASK_TYPE_CREATE_QUIZ:
            raise PermanentTaskError("UNSUPPORTED_TASK_TYPE")
        if task.status is not TaskStatus.APPROVED:
            # Any other state already has (or may have) a ledger entry: never re-run blindly.
            raise PermanentTaskError("TASK_NOT_READY_FOR_PUBLISH")

        tenant_id, task_id = task.tenant_id, task.task_id
        actor = await self._resolve_actor(tenant_id, task.actor_membership_id)

        try:
            intent_record = await asyncio.to_thread(
                self._pubs.create_publish_intent_for_worker,
                tenant_id=tenant_id,
                task_id=task_id,
            )
            record = await asyncio.to_thread(self._pubs.get_current_snapshot, actor, task_id)
        except (TaskStateConflict, ResourceNotFound) as exc:
            raise PermanentTaskError("APPROVAL_NOT_USABLE") from exc

        snapshot = _descriptor(record)
        if (
            snapshot.snapshot_id != intent_record.snapshot_id
            or snapshot.snapshot_hash != intent_record.snapshot_hash
        ):
            raise PermanentTaskError("SNAPSHOT_CHANGED")

        try:
            quiz_name, quiz_intro, specs = map_quiz_draft_to_specs(
                draft_from_snapshot_content(record.content)
            )
            intent = PublishIntent(
                publish_intent_id=intent_record.publish_intent_id,
                task_id=task_id,
                tenant_id=tenant_id,
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                external_operation_key=intent_record.external_operation_key,
                state=intent_record.state,
            )
        except (UnsupportedQuestionForPublish, TaskStateConflict, ValueError) as exc:
            log.warning("publish_quiz.not_publishable", extra={"task_id": task_id})
            raise PermanentTaskError("UNSUPPORTED_QUESTIONS") from exc

        ledger = {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "publish_intent_id": intent.publish_intent_id,
        }

        step_key = await asyncio.to_thread(
            self._pubs.plan_external_step,
            tenant_id=tenant_id,
            publish_intent_id=intent.publish_intent_id,
            step_kind=STEP_KIND,
            ordinal=0,
            request={
                "course_id": snapshot.course_id,
                "quiz_name": quiz_name,
                "question_count": len(specs),
                "snapshot_hash": snapshot.snapshot_hash,
            },
        )
        try:
            await asyncio.to_thread(self._pubs.mark_step_dispatched, step_key=step_key, **ledger)
        except TaskStateConflict as exc:
            # Preflight / approval / cancellation blocked the dispatch; nothing was sent.
            raise RetryableTaskError("PUBLISH_BLOCKED") from exc

        # --- external write: from here on every outcome is recorded in the ledger ---
        try:
            create_result = await asyncio.to_thread(
                self._write.create_approved_quiz,
                actor,
                connection_id=snapshot.connection_id,
                snapshot=snapshot,
                intent=intent,
                questions=specs,
                quiz_name=quiz_name,
                quiz_intro=quiz_intro,
            )
        except _DEFINITE_FAILURES as exc:
            await self._record(step_key, ledger, "FAILED_DEFINITE")
            log.error("publish_quiz.rejected", extra={"task_id": task_id})
            raise PermanentTaskError("MOODLE_REJECTED") from exc
        except Exception as exc:
            await self._record(step_key, ledger, "UNKNOWN")
            log.warning("publish_quiz.outcome_unknown", extra={"task_id": task_id})
            raise PermanentTaskError("OUTCOME_UNKNOWN") from exc

        await self._record(
            step_key,
            ledger,
            "SUCCEEDED",
            response_hash=canonical_hash(
                {
                    "quiz_id": create_result.moodle_quiz_id,
                    "cmid": create_result.moodle_cmid,
                    "operation_key": intent.external_operation_key,
                }
            ),
            external_ref=str(create_result.moodle_quiz_id),
        )

        await asyncio.to_thread(self._pubs.begin_verification, **ledger)
        try:
            verification = await asyncio.to_thread(
                self._write.verify_created_quiz,
                actor,
                connection_id=snapshot.connection_id,
                snapshot=snapshot,
                create_result=create_result,
                quiz_name=quiz_name,
                expected_question_count=len(specs),
            )
        except Exception as exc:
            await context.transition(TaskStatus.NEEDS_RECONCILIATION)
            raise PermanentTaskError("VERIFICATION_UNAVAILABLE") from exc

        if not verification.matches(len(specs)):
            await context.transition(TaskStatus.NEEDS_RECONCILIATION)
            log.warning(
                "publish_quiz.verification_mismatch",
                extra={
                    "task_id": task_id,
                    "name_matches": verification.name_matches,
                    "course_id_matches": verification.course_id_matches,
                    "question_count": verification.question_count,
                    "expected_question_count": len(specs),
                },
            )
            raise PermanentTaskError("VERIFICATION_MISMATCH")

        await asyncio.to_thread(
            self._pubs.complete_verified_publish,
            snapshot_hash_value=snapshot.snapshot_hash,
            verification={
                "verified": True,
                "expected_content_match": True,
                "external_object_type": "QUIZ",
                "external_object_id": str(create_result.moodle_quiz_id),
                "snapshot_hash": snapshot.snapshot_hash,
                "course_id": snapshot.course_id,
            },
            **ledger,
        )
        log.info(
            "publish_quiz.completed",
            extra={"task_id": task_id, "moodle_quiz_id": create_result.moodle_quiz_id},
        )

    async def _resolve_actor(self, tenant_id: str, membership_id: str) -> ActiveContext:
        try:
            return await asyncio.to_thread(self._actors.resolve, tenant_id, membership_id)
        except MembershipContextInvalid as exc:
            raise PermanentTaskError("ACTOR_NOT_ACTIVE") from exc

    async def _record(
        self,
        step_key: str,
        ledger: dict[str, str],
        outcome: str,
        *,
        response_hash: str | None = None,
        external_ref: str | None = None,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._pubs.record_step_outcome,
                step_key=step_key,
                outcome=outcome,
                response_hash=response_hash,
                external_ref=external_ref,
                **ledger,
            )
        except DomainError as exc:
            # Moodle may already hold the quiz while the ledger is behind: manual reconciliation.
            log.error("publish_quiz.ledger_write_failed", extra={"outcome": outcome})
            raise PermanentTaskError("LEDGER_WRITE_FAILED") from exc


def _descriptor(record: SnapshotRecord) -> SnapshotDescriptor:
    destination = record.destination
    try:
        return SnapshotDescriptor(
            snapshot_id=record.snapshot_id,
            task_id=record.task_id,
            tenant_id=record.tenant_id,
            version_no=record.version_no,
            snapshot_hash=record.snapshot_hash,
            connection_id=str(destination["connection_id"]),
            course_id=str(destination["course_id"]),
        )
    except (KeyError, ValueError) as exc:
        raise PermanentTaskError("SNAPSHOT_DESTINATION_INVALID") from exc
