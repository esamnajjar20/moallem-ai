"""SQLAlchemy-backed identity and tenant-scoped Moodle repositories."""

import uuid
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm.attributes import InstrumentedAttribute

from moallem.domain.authorization import require_tenant
from moallem.domain.errors import ResourceNotFound
from moallem.domain.identity import SubjectMapper
from moallem.domain.membership import (
    ActiveContext,
    Membership,
    MembershipRepository,
    MembershipStatus,
)
from moallem.domain.secrets import SecretRef
from moallem.moodle.service import (
    ConnectionStatus,
    MoodleConnection,
)
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import (
    Base,
    MembershipModel,
    MoodleConnectionModel,
    UserModel,
)

T = TypeVar("T")
M = TypeVar("M", bound=Base)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


class PostgresMembershipRepository(MembershipRepository):
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    @staticmethod
    def _domain(row: MembershipModel) -> Membership:
        return Membership(
            membership_id=str(row.id),
            user_id=str(row.user_id),
            tenant_id=str(row.tenant_id),
            roles=tuple(row.roles),
            status=MembershipStatus(row.status),
        )

    def get(self, membership_id: str) -> Membership | None:
        member_id = _uuid(membership_id)
        if member_id is None:
            return None
        with session_scope(self._sessions) as session:
            row = session.get(MembershipModel, member_id)
            return self._domain(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[Membership]:
        parsed_user_id = _uuid(user_id)
        if parsed_user_id is None:
            return []
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(MembershipModel)
                .where(MembershipModel.user_id == parsed_user_id)
                .order_by(MembershipModel.created_at, MembershipModel.id)
            )
            return [self._domain(row) for row in rows]


class PostgresSubjectMapper(SubjectMapper):
    """Resolve pre-provisioned issuer/subject identities; never auto-provision users."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def user_id_for(self, issuer: str, subject: str) -> str | None:
        with session_scope(self._sessions) as session:
            user_id = session.scalar(
                select(UserModel.id).where(
                    UserModel.auth_issuer == issuer,
                    UserModel.auth_subject == subject,
                    UserModel.auth_status == "ACTIVE",
                )
            )
            return str(user_id) if user_id is not None else None


class PostgresScopedRepository[T, M: Base]:
    """CRUD adapter that applies tenant and id predicates on every SQL operation."""

    def __init__(
        self,
        sessions: SessionFactory,
        model: type[M],
        *,
        id_column: InstrumentedAttribute[uuid.UUID],
        tenant_column: InstrumentedAttribute[uuid.UUID],
        id_of: Callable[[T], str],
        tenant_of: Callable[[T], str],
        to_model: Callable[[T], M],
        to_domain: Callable[[M], T],
    ) -> None:
        self._sessions = sessions
        self._model = model
        self._id_column = id_column
        self._tenant_column = tenant_column
        self._id_of = id_of
        self._tenant_of = tenant_of
        self._to_model = to_model
        self._to_domain = to_domain

    def add(self, ctx: ActiveContext, item: T) -> None:
        require_tenant(ctx, self._tenant_of(item))
        with session_scope(self._sessions) as session:
            session.add(self._to_model(item))

    def get(self, ctx: ActiveContext, item_id: str) -> T:
        tenant_id, parsed_id = _uuid(ctx.tenant_id), _uuid(item_id)
        if tenant_id is None or parsed_id is None:
            raise ResourceNotFound("resource not found")
        with session_scope(self._sessions) as session:
            statement = select(self._model).where(
                self._tenant_column == tenant_id,
                self._id_column == parsed_id,
            )
            row = session.scalar(statement)
            if row is None:
                raise ResourceNotFound("resource not found")
            return self._to_domain(row)

    def list(self, ctx: ActiveContext) -> list[T]:
        tenant_id = _uuid(ctx.tenant_id)
        if tenant_id is None:
            return []
        with session_scope(self._sessions) as session:
            rows = session.scalars(select(self._model).where(self._tenant_column == tenant_id))
            return [self._to_domain(row) for row in rows]

    def delete(self, ctx: ActiveContext, item_id: str) -> None:
        item = self.get(ctx, item_id)
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(self._model).where(
                    self._tenant_column == uuid.UUID(ctx.tenant_id),
                    self._id_column == uuid.UUID(self._id_of(item)),
                )
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            session.delete(row)


def new_postgres_connection_repository(
    sessions: SessionFactory,
) -> PostgresScopedRepository[MoodleConnection, MoodleConnectionModel]:
    def to_model(connection: MoodleConnection) -> MoodleConnectionModel:
        return MoodleConnectionModel(
            id=uuid.UUID(connection.connection_id),
            tenant_id=uuid.UUID(connection.tenant_id),
            site_url=connection.site_url,
            secret_reference_id=uuid.UUID(connection.secret_ref.ref_id),
            status=connection.status.value,
            moodle_user_id=connection.moodle_user_id,
        )

    def to_domain(row: MoodleConnectionModel) -> MoodleConnection:
        return MoodleConnection(
            connection_id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_url=row.site_url,
            secret_ref=SecretRef(str(row.tenant_id), str(row.secret_reference_id)),
            status=ConnectionStatus(row.status),
            moodle_user_id=row.moodle_user_id,
        )

    return PostgresScopedRepository(
        sessions,
        MoodleConnectionModel,
        id_column=MoodleConnectionModel.id,
        tenant_column=MoodleConnectionModel.tenant_id,
        id_of=lambda item: item.connection_id,
        tenant_of=lambda item: item.tenant_id,
        to_model=to_model,
        to_domain=to_domain,
    )
