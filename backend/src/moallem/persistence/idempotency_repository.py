"""PostgreSQL idempotency adapter for use inside an existing transaction."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from moallem.domain.idempotency import IdempotencyStore, Record, RecordState, Scope
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import IdempotencyRecordModel


def _domain(row: IdempotencyRecordModel) -> Record:
    return Record(
        scope=Scope(
            tenant_id=str(row.tenant_id),
            actor_membership_id=str(row.actor_membership_id),
            operation_code=row.operation_code,
            key_hash=row.key_hash,
        ),
        request_hash=row.request_hash,
        state=RecordState(row.state),
        operation_ref=str(row.operation_ref),
        created_at=row.created_at,
        expires_at=row.expires_at,
        response_status=row.response_status,
        response_ref=row.response_ref,
        external_unresolved=row.external_unresolved,
    )


class PostgresIdempotencyStore(IdempotencyStore):
    """Uses a caller-owned Session so idempotency and business rows commit atomically."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _scope_filter(scope: Scope) -> tuple[ColumnElement[bool], ...]:
        return (
            IdempotencyRecordModel.tenant_id == uuid.UUID(scope.tenant_id),
            IdempotencyRecordModel.actor_membership_id == uuid.UUID(scope.actor_membership_id),
            IdempotencyRecordModel.operation_code == scope.operation_code,
            IdempotencyRecordModel.key_hash == scope.key_hash,
        )

    def put_if_absent(self, record: Record) -> tuple[Record, bool]:
        row = IdempotencyRecordModel(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(record.scope.tenant_id),
            actor_membership_id=uuid.UUID(record.scope.actor_membership_id),
            operation_code=record.scope.operation_code,
            key_hash=record.scope.key_hash,
            request_hash=record.request_hash,
            state=record.state.value,
            operation_ref=uuid.UUID(record.operation_ref),
            response_status=record.response_status,
            response_ref=record.response_ref,
            external_unresolved=record.external_unresolved,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalar(
                select(IdempotencyRecordModel).where(*self._scope_filter(record.scope))
            )
            if existing is None:
                raise
            return _domain(existing), False
        return record, True

    def compare_and_set(self, old: Record, new: Record) -> bool:
        updated_id = self._session.scalar(
            update(IdempotencyRecordModel)
            .where(
                *self._scope_filter(old.scope),
                IdempotencyRecordModel.state == old.state.value,
                IdempotencyRecordModel.operation_ref == uuid.UUID(old.operation_ref),
                IdempotencyRecordModel.request_hash == old.request_hash,
            )
            .values(
                state=new.state.value,
                response_status=new.response_status,
                response_ref=new.response_ref,
                external_unresolved=new.external_unresolved,
            )
            .returning(IdempotencyRecordModel.id)
        )
        return updated_id is not None

    def delete_expired(self, now: datetime) -> int:
        deleted_ids = self._session.scalars(
            delete(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.expires_at <= now,
                IdempotencyRecordModel.external_unresolved.is_(False),
            )
            .returning(IdempotencyRecordModel.id)
        )
        return len(list(deleted_ids))


class PostgresIdempotencyRepository:
    """Runs bounded retention cleanup in independent, short transactions."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def delete_expired_batch(self, now: datetime, *, limit: int) -> int:
        if now.tzinfo is None or limit < 1:
            raise ValueError("cleanup requires an aware timestamp and positive batch limit")
        with session_scope(self._sessions) as session:
            expired_ids = list(
                session.scalars(
                    select(IdempotencyRecordModel.id)
                    .where(
                        IdempotencyRecordModel.expires_at <= now,
                        IdempotencyRecordModel.external_unresolved.is_(False),
                    )
                    .order_by(IdempotencyRecordModel.expires_at, IdempotencyRecordModel.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            if not expired_ids:
                return 0
            deleted_ids = session.scalars(
                delete(IdempotencyRecordModel)
                .where(IdempotencyRecordModel.id.in_(expired_ids))
                .returning(IdempotencyRecordModel.id)
            )
            return len(list(deleted_ids))
