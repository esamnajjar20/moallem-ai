"""PostgreSQL outbox claims with expiring leases and fencing generations."""

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from moallem.domain.errors import TaskStateConflict
from moallem.domain.tasks import TERMINAL, Task, TaskStatus
from moallem.domain.tasks import transition as transition_task
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import (
    IdempotencyRecordModel,
    OutboxEventModel,
    TaskEventModel,
    TaskModel,
)

_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_YIELDED = frozenset(
    {
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.NEEDS_INPUT,
        TaskStatus.NEEDS_REVISION,
    }
)


class LeaseLost(RuntimeError):
    """The claim is stale or no longer owned by this worker."""


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    event_id: str
    tenant_id: str
    task_id: str
    owner: str
    generation: int
    attempts: int
    lease_expires_at: datetime
    created_at: datetime


def _aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")


def _claim_matches(row: OutboxEventModel, claim: OutboxClaim, now: datetime) -> bool:
    return (
        row.status == "LEASED"
        and row.lease_owner == claim.owner
        and row.lease_generation == claim.generation
        and row.lease_expires_at is not None
        and row.lease_expires_at > now
    )


def _complete_idempotency(session: Session, task: TaskModel, *, completed: bool) -> None:
    record = session.scalar(
        select(IdempotencyRecordModel)
        .where(
            IdempotencyRecordModel.tenant_id == task.tenant_id,
            IdempotencyRecordModel.operation_ref == task.id,
            IdempotencyRecordModel.state == "IN_PROGRESS",
        )
        .with_for_update()
    )
    if record is not None:
        record.state = "COMPLETED" if completed else "FAILED_FINAL"
        record.response_status = 202
        record.response_ref = str(task.id)


class PostgresOutboxRepository:
    """Claim, heartbeat, ACK, retry, and dead-letter using PostgreSQL row locks."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def claim_batch(
        self,
        *,
        owner: str,
        limit: int,
        lease: timedelta,
        supported_task_types: Collection[str] | None = None,
        now: datetime | None = None,
    ) -> list[OutboxClaim]:
        timestamp = now or datetime.now(UTC)
        _aware(timestamp)
        if not owner or len(owner) > 128:
            raise ValueError("worker owner must contain 1..128 characters")
        if limit < 1 or lease <= timedelta(0):
            raise ValueError("claim limit and lease must be positive")
        if supported_task_types is not None and not supported_task_types:
            return []

        with session_scope(self._sessions) as session:
            conditions = [
                or_(
                    and_(
                        OutboxEventModel.status == "PENDING",
                        OutboxEventModel.next_attempt_at <= timestamp,
                    ),
                    and_(
                        OutboxEventModel.status == "LEASED",
                        OutboxEventModel.lease_expires_at <= timestamp,
                    ),
                )
            ]
            if supported_task_types is not None:
                conditions.append(
                    OutboxEventModel.payload["task_type"].astext.in_(supported_task_types)
                )
            rows = list(
                session.scalars(
                    select(OutboxEventModel)
                    .where(*conditions)
                    .order_by(
                        OutboxEventModel.next_attempt_at,
                        OutboxEventModel.created_at,
                        OutboxEventModel.event_id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            claims: list[OutboxClaim] = []
            for row in rows:
                row.status = "LEASED"
                row.attempts += 1
                row.lease_owner = owner
                row.lease_generation += 1
                row.lease_expires_at = timestamp + lease
                claims.append(
                    OutboxClaim(
                        event_id=str(row.event_id),
                        tenant_id=str(row.tenant_id),
                        task_id=str(row.task_id),
                        owner=owner,
                        generation=row.lease_generation,
                        attempts=row.attempts,
                        lease_expires_at=timestamp + lease,
                        created_at=row.created_at,
                    )
                )
            session.flush()
            return claims

    def unhandled_task_types(self, supported_task_types: Collection[str]) -> list[str]:
        with session_scope(self._sessions) as session:
            task_type = func.coalesce(OutboxEventModel.payload["task_type"].astext, "<missing>")
            rows: list[str] = list(
                session.scalars(
                    select(task_type)
                    .where(
                        OutboxEventModel.status.in_(("PENDING", "LEASED")),
                        task_type.not_in(supported_task_types),
                    )
                    .distinct()
                    .order_by(task_type)
                )
            )
            return rows

    def renew(
        self,
        claim: OutboxClaim,
        *,
        lease: timedelta,
        now: datetime | None = None,
    ) -> bool:
        timestamp = now or datetime.now(UTC)
        _aware(timestamp)
        if lease <= timedelta(0):
            raise ValueError("lease must be positive")
        with session_scope(self._sessions) as session:
            updated_id = session.scalar(
                update(OutboxEventModel)
                .where(
                    OutboxEventModel.event_id == uuid.UUID(claim.event_id),
                    OutboxEventModel.tenant_id == uuid.UUID(claim.tenant_id),
                    OutboxEventModel.task_id == uuid.UUID(claim.task_id),
                    OutboxEventModel.status == "LEASED",
                    OutboxEventModel.lease_owner == claim.owner,
                    OutboxEventModel.lease_generation == claim.generation,
                    OutboxEventModel.lease_expires_at > timestamp,
                )
                .values(lease_expires_at=timestamp + lease)
                .returning(OutboxEventModel.event_id)
            )
            return updated_id is not None

    def acknowledge(self, claim: OutboxClaim, *, now: datetime | None = None) -> bool:
        timestamp = now or datetime.now(UTC)
        _aware(timestamp)
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.event_id == uuid.UUID(claim.event_id),
                    OutboxEventModel.tenant_id == uuid.UUID(claim.tenant_id),
                    OutboxEventModel.task_id == uuid.UUID(claim.task_id),
                )
                .with_for_update()
            )
            if row is None or not _claim_matches(row, claim, timestamp):
                return False
            row.status = "PUBLISHED"
            row.published_at = timestamp
            row.lease_owner = None
            row.lease_expires_at = None
            task = session.scalar(
                select(TaskModel).where(
                    TaskModel.id == uuid.UUID(claim.task_id),
                    TaskModel.tenant_id == uuid.UUID(claim.tenant_id),
                )
            )
            if task is not None and TaskStatus(task.status) in TERMINAL:
                _complete_idempotency(
                    session,
                    task,
                    completed=task.status == TaskStatus.COMPLETED.value,
                )
            session.flush()
            return True

    def fail(
        self,
        claim: OutboxClaim,
        *,
        error_code: str,
        retryable: bool,
        max_attempts: int,
        retry_at: datetime,
        now: datetime | None = None,
    ) -> str | None:
        timestamp = now or datetime.now(UTC)
        _aware(timestamp)
        _aware(retry_at)
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a non-sensitive stable code")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        with session_scope(self._sessions) as session:
            outbox = session.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.event_id == uuid.UUID(claim.event_id),
                    OutboxEventModel.tenant_id == uuid.UUID(claim.tenant_id),
                    OutboxEventModel.task_id == uuid.UUID(claim.task_id),
                )
                .with_for_update()
            )
            if outbox is None or not _claim_matches(outbox, claim, timestamp):
                return None

            task = session.scalar(
                select(TaskModel)
                .where(
                    TaskModel.id == uuid.UUID(claim.task_id),
                    TaskModel.tenant_id == uuid.UUID(claim.tenant_id),
                )
                .with_for_update()
            )
            if task is None:
                outbox.status = "DEAD_LETTER"
                disposition = "DEAD_LETTER"
            else:
                current = TaskStatus(task.status)
                if current in TERMINAL or current in _YIELDED:
                    outbox.status = "PUBLISHED"
                    outbox.published_at = timestamp
                    if current in TERMINAL:
                        _complete_idempotency(
                            session, task, completed=current is TaskStatus.COMPLETED
                        )
                    disposition = "PUBLISHED"
                elif retryable and outbox.attempts < max_attempts:
                    outbox.status = "PENDING"
                    outbox.next_attempt_at = retry_at
                    disposition = "PENDING"
                else:
                    try:
                        updated = transition_task(
                            Task(
                                status=current,
                                cancel_requested=task.cancel_requested,
                                external_dispatched=task.external_dispatched,
                            ),
                            TaskStatus.FAILED,
                        )
                    except TaskStateConflict:
                        outbox.status = "DEAD_LETTER"
                        disposition = "DEAD_LETTER"
                    else:
                        sequence = task.latest_event_sequence + 1
                        task.status = updated.status.value
                        task.latest_event_sequence = sequence
                        task.updated_at = timestamp
                        session.add(
                            TaskEventModel(
                                event_id=uuid.uuid4(),
                                tenant_id=task.tenant_id,
                                task_id=task.id,
                                sequence=sequence,
                                event_type="TASK_FAILED",
                                from_status=current.value,
                                to_status=TaskStatus.FAILED.value,
                                message_code=error_code,
                                payload={},
                                occurred_at=timestamp,
                            )
                        )
                        _complete_idempotency(session, task, completed=False)
                        outbox.status = "DEAD_LETTER"
                        disposition = "DEAD_LETTER"

            outbox.last_error_code = error_code
            outbox.lease_owner = None
            outbox.lease_expires_at = None
            session.flush()
            return disposition
