"""Transactional PostgreSQL persistence for task state and its append-only event stream."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select

from moallem.domain.errors import ResourceNotFound, TaskStateConflict
from moallem.domain.events import select_page
from moallem.domain.idempotency import Outcome, begin, canonical_request_hash
from moallem.domain.membership import ActiveContext
from moallem.domain.tasks import Task, TaskStatus
from moallem.domain.tasks import transition as transition_task
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.idempotency_repository import PostgresIdempotencyStore
from moallem.persistence.models import OutboxEventModel, TaskEventModel, TaskModel
from moallem.persistence.outbox_repository import LeaseLost, OutboxClaim


@dataclass(frozen=True, slots=True)
class PersistedTask:
    task_id: str
    tenant_id: str
    actor_membership_id: str
    task_type: str
    connection_id: str
    course_id: str
    prompt: str
    request_payload: dict[str, object]
    status: TaskStatus
    cancel_requested: bool
    external_dispatched: bool
    latest_event_sequence: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PersistedTaskEvent:
    event_id: str
    sequence: int
    event_type: str
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    message_code: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class PersistedTaskEventPage:
    items: list[PersistedTaskEvent]
    has_more: bool
    last_sequence: int
    oldest_available_sequence: int


@dataclass(frozen=True, slots=True)
class IdempotentTaskResult:
    outcome: Outcome
    task: PersistedTask


@dataclass(frozen=True, slots=True)
class DeadLetterTask:
    task: PersistedTask
    attempts: int
    last_error_code: str | None


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ResourceNotFound("resource not found") from exc


def _domain(row: TaskModel) -> PersistedTask:
    return PersistedTask(
        task_id=str(row.id),
        tenant_id=str(row.tenant_id),
        actor_membership_id=str(row.actor_membership_id),
        task_type=row.task_type,
        connection_id=str(row.connection_id),
        course_id=row.course_id,
        prompt=row.prompt,
        request_payload=row.request_payload,
        status=TaskStatus(row.status),
        cancel_requested=row.cancel_requested,
        external_dispatched=row.external_dispatched,
        latest_event_sequence=row.latest_event_sequence,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresTaskRepository:
    """Persist task changes and their ordered events in the same database transaction.

    Access is restricted to the active tenant and the membership that created the task. This
    intentionally applies the narrowest owner-only behavior while the permission matrix is open.
    """

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def create(
        self,
        ctx: ActiveContext,
        *,
        task_id: str,
        task_type: str,
        connection_id: str,
        course_id: str,
        prompt: str,
        request_payload: dict[str, object],
        occurred_at: datetime | None = None,
    ) -> PersistedTask:
        task_uuid = _uuid(task_id)
        tenant_uuid = _uuid(ctx.tenant_id)
        membership_uuid = _uuid(ctx.membership_id)
        connection_uuid = _uuid(connection_id)
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            row = TaskModel(
                id=task_uuid,
                tenant_id=tenant_uuid,
                actor_membership_id=membership_uuid,
                task_type=task_type,
                connection_id=connection_uuid,
                course_id=course_id,
                prompt=prompt,
                request_payload=request_payload,
                status=TaskStatus.RECEIVED.value,
                latest_event_sequence=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
            session.flush()
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=1,
                    event_type="TASK_CREATED",
                    to_status=TaskStatus.RECEIVED.value,
                    payload={},
                    occurred_at=timestamp,
                )
            )
            session.add(
                OutboxEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    event_type="TASK_CREATED",
                    payload={"task_id": str(task_uuid), "task_type": task_type},
                )
            )
            session.flush()
            return _domain(row)

    def create_idempotent(
        self,
        ctx: ActiveContext,
        *,
        task_id: str,
        task_type: str,
        connection_id: str,
        course_id: str,
        prompt: str,
        request_payload: dict[str, object],
        idempotency_key: str,
        idempotency_hmac_key: bytes,
        idempotency_retention_seconds: int,
        occurred_at: datetime | None = None,
    ) -> IdempotentTaskResult:
        task_uuid = _uuid(task_id)
        tenant_uuid = _uuid(ctx.tenant_id)
        membership_uuid = _uuid(ctx.membership_id)
        connection_uuid = _uuid(connection_id)
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if idempotency_retention_seconds < 1:
            raise ValueError("idempotency retention must be positive")

        with session_scope(self._sessions) as session:
            decision = begin(
                PostgresIdempotencyStore(session),
                server_key=idempotency_hmac_key,
                tenant_id=ctx.tenant_id,
                actor_membership_id=ctx.membership_id,
                operation_code="TASK_CREATE",
                client_key=idempotency_key,
                request_hash=canonical_request_hash(
                    {
                        "task_type": task_type,
                        "connection_id": connection_id,
                        "course_id": course_id,
                        "prompt": prompt,
                        "request_payload": request_payload,
                    }
                ),
                operation_ref=str(task_uuid),
                now=timestamp,
                ttl=timedelta(seconds=idempotency_retention_seconds),
            )
            if decision.outcome is Outcome.NEW:
                row = TaskModel(
                    id=task_uuid,
                    tenant_id=tenant_uuid,
                    actor_membership_id=membership_uuid,
                    task_type=task_type,
                    connection_id=connection_uuid,
                    course_id=course_id,
                    prompt=prompt,
                    request_payload=request_payload,
                    status=TaskStatus.RECEIVED.value,
                    latest_event_sequence=1,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                session.flush()
                session.add(
                    TaskEventModel(
                        event_id=uuid.uuid4(),
                        tenant_id=tenant_uuid,
                        task_id=task_uuid,
                        sequence=1,
                        event_type="TASK_CREATED",
                        to_status=TaskStatus.RECEIVED.value,
                        payload={},
                        occurred_at=timestamp,
                    )
                )
                session.add(
                    OutboxEventModel(
                        event_id=uuid.uuid4(),
                        tenant_id=tenant_uuid,
                        task_id=task_uuid,
                        event_type="TASK_CREATED",
                        payload={"task_id": str(task_uuid), "task_type": task_type},
                    )
                )
                session.flush()
                return IdempotentTaskResult(Outcome.NEW, _domain(row))

            existing = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == _uuid(decision.record.operation_ref),
                    TaskModel.tenant_id == tenant_uuid,
                    TaskModel.actor_membership_id == membership_uuid,
                )
            )
            if existing is None:
                raise RuntimeError("idempotency record references a missing task")
            return IdempotentTaskResult(decision.outcome, _domain(existing))

    def list_dead_letters(self, ctx: ActiveContext, *, limit: int = 100) -> list[DeadLetterTask]:
        tenant_uuid = _uuid(ctx.tenant_id)
        if not 1 <= limit <= 500:
            raise ValueError("dead-letter limit must be between 1 and 500")
        with session_scope(self._sessions) as session:
            rows = session.execute(
                select(TaskModel, OutboxEventModel)
                .join(
                    OutboxEventModel,
                    (OutboxEventModel.tenant_id == TaskModel.tenant_id)
                    & (OutboxEventModel.task_id == TaskModel.id),
                )
                .where(
                    TaskModel.tenant_id == tenant_uuid,
                    TaskModel.status == TaskStatus.FAILED.value,
                    OutboxEventModel.status == "DEAD_LETTER",
                )
                .order_by(OutboxEventModel.created_at.desc(), TaskModel.id)
                .limit(limit)
            )
            return [
                DeadLetterTask(
                    task=_domain(task),
                    attempts=outbox.attempts,
                    last_error_code=outbox.last_error_code,
                )
                for task, outbox in rows
            ]

    def recover_dead_letter(
        self,
        ctx: ActiveContext,
        *,
        task_id: str,
        recovery_task_id: str,
        idempotency_key: str,
        idempotency_hmac_key: bytes,
        idempotency_retention_seconds: int,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> IdempotentTaskResult:
        parent_uuid = _uuid(task_id)
        child_uuid = _uuid(recovery_task_id)
        tenant_uuid = _uuid(ctx.tenant_id)
        membership_uuid = _uuid(ctx.membership_id)
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if idempotency_retention_seconds < 1:
            raise ValueError("idempotency retention must be positive")
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise ValueError("recovery reason must contain 1..500 characters")

        with session_scope(self._sessions) as session:
            parent = session.scalar(
                select(TaskModel)
                .where(TaskModel.tenant_id == tenant_uuid, TaskModel.id == parent_uuid)
                .with_for_update()
            )
            if parent is None:
                raise ResourceNotFound("resource not found")

            decision = begin(
                PostgresIdempotencyStore(session),
                server_key=idempotency_hmac_key,
                tenant_id=ctx.tenant_id,
                actor_membership_id=ctx.membership_id,
                operation_code="TASK_RECOVERY",
                client_key=idempotency_key,
                request_hash=canonical_request_hash(
                    {
                        "parent_task_id": str(parent_uuid),
                        "reason": normalized_reason,
                    }
                ),
                operation_ref=str(child_uuid),
                now=timestamp,
                ttl=timedelta(seconds=idempotency_retention_seconds),
            )
            if decision.outcome is not Outcome.NEW:
                existing = session.scalar(
                    select(TaskModel).where(
                        TaskModel.id == _uuid(decision.record.operation_ref),
                        TaskModel.tenant_id == tenant_uuid,
                        TaskModel.actor_membership_id == membership_uuid,
                    )
                )
                if existing is None:
                    raise RuntimeError("recovery idempotency record references a missing task")
                return IdempotentTaskResult(decision.outcome, _domain(existing))

            dead_letter = session.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.tenant_id == tenant_uuid,
                    OutboxEventModel.task_id == parent_uuid,
                    OutboxEventModel.status == "DEAD_LETTER",
                )
                .with_for_update()
            )
            possible_external_effect = session.scalar(
                select(
                    exists().where(
                        TaskEventModel.tenant_id == tenant_uuid,
                        TaskEventModel.task_id == parent_uuid,
                        TaskEventModel.to_status.in_(
                            (
                                TaskStatus.EXECUTING.value,
                                TaskStatus.VERIFYING.value,
                                TaskStatus.NEEDS_RECONCILIATION.value,
                            )
                        ),
                    )
                )
            )
            if (
                parent.status != TaskStatus.FAILED.value
                or parent.external_dispatched
                or dead_letter is None
                or possible_external_effect
            ):
                raise TaskStateConflict("task is not safe to recover")

            previous_recovery = session.scalar(
                select(TaskModel.id)
                .where(
                    TaskModel.tenant_id == tenant_uuid,
                    TaskModel.retry_of_task_id == parent_uuid,
                )
                .with_for_update()
            )
            if previous_recovery is not None:
                raise TaskStateConflict("task already has a recovery attempt")

            row = TaskModel(
                id=child_uuid,
                tenant_id=tenant_uuid,
                actor_membership_id=membership_uuid,
                task_type=parent.task_type,
                connection_id=parent.connection_id,
                retry_of_task_id=parent_uuid,
                course_id=parent.course_id,
                prompt=parent.prompt,
                request_payload=parent.request_payload,
                status=TaskStatus.RECEIVED.value,
                latest_event_sequence=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
            session.flush()
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=child_uuid,
                    sequence=1,
                    event_type="TASK_RECOVERED",
                    to_status=TaskStatus.RECEIVED.value,
                    payload={
                        "parent_task_id": str(parent_uuid),
                        "requested_by_user_id": ctx.user_id,
                        "requested_by_membership_id": ctx.membership_id,
                        "reason": normalized_reason,
                    },
                    occurred_at=timestamp,
                )
            )
            session.add(
                OutboxEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=child_uuid,
                    event_type="TASK_CREATED",
                    payload={
                        "task_id": str(child_uuid),
                        "task_type": parent.task_type,
                        "retry_of_task_id": str(parent_uuid),
                    },
                )
            )
            session.flush()
            return IdempotentTaskResult(Outcome.NEW, _domain(row))

    def get(self, ctx: ActiveContext, task_id: str) -> PersistedTask:
        row_id, tenant_id, membership_id = (
            _uuid(task_id),
            _uuid(ctx.tenant_id),
            _uuid(ctx.membership_id),
        )
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == row_id,
                    TaskModel.tenant_id == tenant_id,
                    TaskModel.actor_membership_id == membership_id,
                )
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            return _domain(row)

    def get_for_worker(self, tenant_id: str, task_id: str) -> PersistedTask:
        tenant_uuid, task_uuid = _uuid(tenant_id), _uuid(task_id)
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == task_uuid,
                    TaskModel.tenant_id == tenant_uuid,
                )
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            return _domain(row)

    def transition_for_worker(
        self,
        claim: OutboxClaim,
        to_status: TaskStatus,
        *,
        event_type: str = "STATUS_CHANGED",
        message_code: str | None = None,
        occurred_at: datetime | None = None,
    ) -> PersistedTask:
        if occurred_at is not None and occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        tenant_uuid, task_uuid = _uuid(claim.tenant_id), _uuid(claim.task_id)
        with session_scope(self._sessions) as session:
            outbox = session.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.event_id == _uuid(claim.event_id),
                    OutboxEventModel.tenant_id == tenant_uuid,
                    OutboxEventModel.task_id == task_uuid,
                    OutboxEventModel.status == "LEASED",
                    OutboxEventModel.lease_owner == claim.owner,
                    OutboxEventModel.lease_generation == claim.generation,
                )
                .with_for_update()
            )
            if outbox is None:
                raise LeaseLost("worker claim is no longer current")
            row = session.scalar(
                select(TaskModel)
                .where(
                    TaskModel.id == task_uuid,
                    TaskModel.tenant_id == tenant_uuid,
                )
                .with_for_update()
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            # Both the Outbox and Task rows may block on another transaction. Evaluate
            # expiration only after both locks are held so an old worker cannot mutate a
            # task using a timestamp captured before a lock wait.
            timestamp = occurred_at or datetime.now(UTC)
            if (
                outbox.lease_expires_at is None
                or outbox.lease_expires_at <= timestamp
                or outbox.lease_owner != claim.owner
                or outbox.lease_generation != claim.generation
                or outbox.status != "LEASED"
            ):
                raise LeaseLost("worker claim expired while waiting for database locks")
            current_status = TaskStatus(row.status)
            updated = transition_task(
                Task(
                    status=current_status,
                    cancel_requested=row.cancel_requested,
                    external_dispatched=row.external_dispatched,
                ),
                to_status,
            )
            next_sequence = row.latest_event_sequence + 1
            row.status = updated.status.value
            row.cancel_requested = updated.cancel_requested
            row.external_dispatched = updated.external_dispatched
            row.latest_event_sequence = next_sequence
            row.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    task_id=task_uuid,
                    sequence=next_sequence,
                    event_type=event_type,
                    from_status=current_status.value,
                    to_status=updated.status.value,
                    message_code=message_code,
                    payload={},
                    occurred_at=timestamp,
                )
            )
            session.flush()
            # Catch a lease that expires while the task/event changes are being flushed.
            if outbox.lease_expires_at <= datetime.now(UTC) and occurred_at is None:
                raise LeaseLost("worker claim expired before task transition commit")
            return _domain(row)

    def transition(
        self,
        ctx: ActiveContext,
        task_id: str,
        to_status: TaskStatus,
        *,
        event_type: str,
        message_code: str | None = None,
        occurred_at: datetime | None = None,
    ) -> PersistedTask:
        row_id, tenant_id, membership_id = (
            _uuid(task_id),
            _uuid(ctx.tenant_id),
            _uuid(ctx.membership_id),
        )
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(TaskModel)
                .where(
                    TaskModel.id == row_id,
                    TaskModel.tenant_id == tenant_id,
                    TaskModel.actor_membership_id == membership_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            current_status = TaskStatus(row.status)
            updated = transition_task(
                Task(
                    status=current_status,
                    cancel_requested=row.cancel_requested,
                    external_dispatched=row.external_dispatched,
                ),
                to_status,
            )
            next_sequence = row.latest_event_sequence + 1
            row.status = updated.status.value
            row.cancel_requested = updated.cancel_requested
            row.external_dispatched = updated.external_dispatched
            row.latest_event_sequence = next_sequence
            row.updated_at = timestamp
            session.add(
                TaskEventModel(
                    event_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    task_id=row_id,
                    sequence=next_sequence,
                    event_type=event_type,
                    from_status=current_status.value,
                    to_status=updated.status.value,
                    message_code=message_code,
                    payload={},
                    occurred_at=timestamp,
                )
            )
            session.flush()
            return _domain(row)

    def list_events(
        self, ctx: ActiveContext, task_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> list[PersistedTaskEvent]:
        if after_sequence < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid event page bounds")
        task = self.get(ctx, task_id)
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(TaskEventModel)
                .where(
                    TaskEventModel.tenant_id == _uuid(task.tenant_id),
                    TaskEventModel.task_id == _uuid(task.task_id),
                    TaskEventModel.sequence > after_sequence,
                )
                .order_by(TaskEventModel.sequence)
                .limit(limit)
            )
            return [
                PersistedTaskEvent(
                    event_id=str(row.event_id),
                    sequence=row.sequence,
                    event_type=row.event_type,
                    from_status=TaskStatus(row.from_status) if row.from_status else None,
                    to_status=TaskStatus(row.to_status) if row.to_status else None,
                    message_code=row.message_code,
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    def list_event_page(
        self,
        ctx: ActiveContext,
        task_id: str,
        *,
        after_sequence: int | None,
        limit: int,
    ) -> PersistedTaskEventPage:
        if (after_sequence is not None and after_sequence < 0) or not 1 <= limit <= 100:
            raise ValueError("invalid event page bounds")
        row_id, tenant_id, membership_id = (
            _uuid(task_id),
            _uuid(ctx.tenant_id),
            _uuid(ctx.membership_id),
        )
        with session_scope(self._sessions) as session:
            task = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == row_id,
                    TaskModel.tenant_id == tenant_id,
                    TaskModel.actor_membership_id == membership_id,
                )
            )
            if task is None:
                raise ResourceNotFound("resource not found")
            oldest = session.scalar(
                select(func.min(TaskEventModel.sequence)).where(
                    TaskEventModel.tenant_id == tenant_id,
                    TaskEventModel.task_id == row_id,
                )
            )
            oldest_sequence = int(oldest or 1)
            query_after = oldest_sequence - 1 if after_sequence is None else after_sequence
            rows = list(
                session.scalars(
                    select(TaskEventModel)
                    .where(
                        TaskEventModel.tenant_id == tenant_id,
                        TaskEventModel.task_id == row_id,
                        TaskEventModel.sequence > query_after,
                    )
                    .order_by(TaskEventModel.sequence)
                    .limit(limit + 1)
                )
            )
            page = select_page(
                [row.sequence for row in rows],
                after=after_sequence,
                oldest_available=oldest_sequence,
                limit=limit,
            )
            if page.has_more:
                selected_sequences = set(page.items)
                rows = [row for row in rows if row.sequence in selected_sequences]
            return PersistedTaskEventPage(
                items=[
                    PersistedTaskEvent(
                        event_id=str(row.event_id),
                        sequence=row.sequence,
                        event_type=row.event_type,
                        from_status=TaskStatus(row.from_status) if row.from_status else None,
                        to_status=TaskStatus(row.to_status) if row.to_status else None,
                        message_code=row.message_code,
                        occurred_at=row.occurred_at,
                    )
                    for row in rows
                ],
                has_more=page.has_more,
                last_sequence=page.last_sequence,
                oldest_available_sequence=page.oldest_available_sequence,
            )
