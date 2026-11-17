import asyncio
import base64
import hashlib
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event, Lock, get_ident

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event as sqlalchemy_event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from moallem.ai.contracts import ProviderIdentity
from moallem.ai.usage import (
    UsageLedgerBeginResult,
    UsageLedgerCompletion,
    UsageLedgerStart,
)
from moallem.api.app import create_app
from moallem.config import Environment, Settings
from moallem.domain.authorization import StaticPolicy
from moallem.domain.errors import PermissionDenied, ResourceNotFound, TaskStateConflict
from moallem.domain.idempotency import IdempotencyKeyReused, Outcome, RecordState
from moallem.domain.membership import (
    ActiveContext,
    MembershipStatus,
)
from moallem.domain.secret_encryption import Aes256Gcm
from moallem.domain.secrets import SecretRef
from moallem.domain.tasks import TaskStatus
from moallem.files.contracts import (
    ExtractionProfile,
    FileUpload,
    PersistedChunkInput,
    ScanResult,
    ScanVerdict,
    SourceFileRegistration,
)
from moallem.moodle.service import ConnectionStatus, MoodleConnection
from moallem.persistence.ai_usage_repository import (
    AIUsageSourceReferenceError,
    PostgresAIUsageLedgerRepository,
)
from moallem.persistence.database import SessionFactory, create_database, session_scope
from moallem.persistence.idempotency_repository import PostgresIdempotencyRepository
from moallem.persistence.inbox_repository import (
    InboxLegacyReceiptConflict,
    InboxLeaseLost,
    InboxMessage,
    InboxMessageConflict,
    InboxResult,
    InboxRetryPolicy,
    PostgresInboxConsumer,
    RetryableInboxError,
)
from moallem.persistence.models import (
    AIUsageLedgerModel,
    AIUsageSourceRefModel,
    IdempotencyRecordModel,
    InboxReceiptModel,
    MembershipModel,
    OutboxEventModel,
    SecretVaultEntryModel,
    SourceChunkModel,
    SourceFileModel,
    TaskEventModel,
    TaskModel,
    TenantModel,
    UserModel,
)
from moallem.persistence.outbox_repository import LeaseLost, PostgresOutboxRepository
from moallem.persistence.source_file_repository import PostgresSourceFileRepository
from moallem.persistence.repositories import (
    PostgresMembershipRepository,
    PostgresSubjectMapper,
    new_postgres_connection_repository,
)
from moallem.persistence.task_repository import (
    IdempotentTaskResult,
    PersistedTask,
    PostgresTaskRepository,
)
from moallem.persistence.vault import PostgresEncryptedVault
from moallem.services.task_recovery import TaskRecoveryService
from moallem.worker.queue import (
    PostgresTaskWorker,
    RetryPolicy,
    TaskExecutionContext,
    TaskHandlerRegistry,
    WorkerSettings,
)

_DATABASE_URL = os.environ.get("MOALLEM_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="set MOALLEM_TEST_DATABASE_URL and run Alembic migrations for PostgreSQL integration",
)


@dataclass(slots=True)
class PostgresTaskEnvironment:
    engine: Engine
    sessions: SessionFactory
    context: ActiveContext
    connection_id: str
    tasks: PostgresTaskRepository


def _run_after_a_row_lock_expires(
    engine: Engine,
    *,
    model: type,
    row_filter: object,
    table_name: str,
    lease_expires_at: datetime,
    operation,
):
    """Hold a row lock until its lease expires, then release the waiting worker.

    The SQLAlchemy event proves the worker reached the SELECT ... FOR UPDATE after its
    repository method had started. The deliberate wait is tied to the real lease deadline,
    rather than an arbitrary sleep used to mask a scheduling race.
    """
    query_started = Event()
    worker_thread_id: int | None = None

    def observe_query(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        if (
            worker_thread_id == get_ident()
            and table_name in statement.lower()
            and "for update" in statement.lower()
        ):
            query_started.set()

    sqlalchemy_event.listen(engine, "before_cursor_execute", observe_query)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with Session(engine) as lock_session:
                with lock_session.begin():
                    lock_session.scalar(
                        select(model).where(row_filter).with_for_update()
                    )

                    def invoke():
                        nonlocal worker_thread_id
                        worker_thread_id = get_ident()
                        return operation()

                    future = pool.submit(invoke)
                    assert query_started.wait(timeout=5), "worker did not reach its row-lock query"
                    while datetime.now(UTC) < lease_expires_at:
                        remaining = (lease_expires_at - datetime.now(UTC)).total_seconds()
                        Event().wait(min(max(remaining, 0), 0.05))
            return future.result(timeout=5)
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", observe_query)


@pytest.fixture
def postgres_task_environment() -> Iterator[PostgresTaskEnvironment]:
    assert _DATABASE_URL is not None
    engine, sessions = create_database(_DATABASE_URL)
    tenant_id, user_id, membership_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    connection_id = uuid.uuid4()
    context = ActiveContext(str(user_id), str(membership_id), str(tenant_id), ("TEACHER",))
    connections = new_postgres_connection_repository(sessions)
    tasks = PostgresTaskRepository(sessions)
    vault = PostgresEncryptedVault(sessions, Aes256Gcm(bytes(range(32))))
    secret_ref: SecretRef | None = None
    connection_added = False

    try:
        with session_scope(sessions) as session:
            session.add(TenantModel(id=tenant_id, name="Synthetic task tenant"))
            session.add(
                UserModel(
                    id=user_id,
                    auth_issuer="https://integration.example/",
                    auth_subject=str(user_id),
                )
            )
            session.flush()
            session.add(
                MembershipModel(
                    id=membership_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    roles=["TEACHER"],
                    status=MembershipStatus.ACTIVE.value,
                )
            )

        secret_ref = vault.put(context, "synthetic-task-token")
        connections.add(
            context,
            MoodleConnection(
                connection_id=str(connection_id),
                tenant_id=str(tenant_id),
                site_url="https://task-moodle.example.edu",
                secret_ref=secret_ref,
                status=ConnectionStatus.ACTIVE,
                moodle_user_id=101,
            ),
        )
        connection_added = True
        yield PostgresTaskEnvironment(engine, sessions, context, str(connection_id), tasks)
    finally:
        try:
            with session_scope(sessions) as session:
                session.execute(
                    delete(AIUsageSourceRefModel).where(
                        AIUsageSourceRefModel.tenant_id == tenant_id
                    )
                )
                session.execute(
                    delete(SourceChunkModel).where(SourceChunkModel.tenant_id == tenant_id)
                )
                session.execute(
                    delete(SourceFileModel).where(SourceFileModel.tenant_id == tenant_id)
                )
                session.execute(
                    delete(AIUsageLedgerModel).where(AIUsageLedgerModel.tenant_id == tenant_id)
                )
                session.execute(
                    delete(InboxReceiptModel).where(InboxReceiptModel.tenant_id == tenant_id)
                )
                session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.tenant_id == tenant_id
                    )
                )
                session.execute(
                    delete(OutboxEventModel).where(OutboxEventModel.tenant_id == tenant_id)
                )
                session.execute(delete(TaskEventModel).where(TaskEventModel.tenant_id == tenant_id))
                session.execute(
                    delete(TaskModel).where(
                        TaskModel.tenant_id == tenant_id,
                        TaskModel.retry_of_task_id.is_not(None),
                    )
                )
                session.execute(delete(TaskModel).where(TaskModel.tenant_id == tenant_id))
            if connection_added:
                connections.delete(context, str(connection_id))
            if secret_ref is not None:
                vault.delete(context, secret_ref)
            with session_scope(sessions) as session:
                membership = session.get(MembershipModel, membership_id)
                user = session.get(UserModel, user_id)
                tenant = session.get(TenantModel, tenant_id)
                if membership is not None:
                    session.delete(membership)
                if user is not None:
                    session.delete(user)
                if tenant is not None:
                    session.delete(tenant)
        finally:
            engine.dispose()


def _create_task(
    environment: PostgresTaskEnvironment,
    task_id: str,
    *,
    task_type: str = "CREATE_QUIZ",
    connection_id: str | None = None,
) -> PersistedTask:
    return environment.tasks.create(
        environment.context,
        task_id=task_id,
        task_type=task_type,
        connection_id=connection_id or environment.connection_id,
        course_id="synthetic-course",
        prompt="Create a synthetic draft",
        request_payload={"locale": "ar"},
    )


def _create_idempotent_task(
    environment: PostgresTaskEnvironment,
    task_id: str,
    *,
    task_type: str = "CREATE_QUIZ",
    idempotency_key: str = "k" * 22,
    prompt: str = "Create a synthetic draft",
) -> IdempotentTaskResult:
    return environment.tasks.create_idempotent(
        environment.context,
        task_id=task_id,
        task_type=task_type,
        connection_id=environment.connection_id,
        course_id="synthetic-course",
        prompt=prompt,
        request_payload={"locale": "ar"},
        idempotency_key=idempotency_key,
        idempotency_hmac_key=b"h" * 32,
        idempotency_retention_seconds=3600,
    )


def _insert_legacy_task(
    environment: PostgresTaskEnvironment, task_id: str, *, connection_id: str | None = None
) -> None:
    with session_scope(environment.sessions) as session:
        session.execute(
            text(
                "INSERT INTO tasks "
                "(id, tenant_id, actor_membership_id, task_type, connection_id, course_id, "
                "prompt, request_payload, status, latest_event_sequence) "
                "VALUES (:id, :tenant_id, :membership_id, 'CREATE_QUIZ', :connection_id, "
                "'synthetic-course', 'legacy task', '{}'::jsonb, 'RECEIVED', 1)"
            ),
            {
                "id": uuid.UUID(task_id),
                "tenant_id": uuid.UUID(environment.context.tenant_id),
                "membership_id": uuid.UUID(environment.context.membership_id),
                "connection_id": uuid.UUID(connection_id or environment.connection_id),
            },
        )


def _alembic_config() -> Config:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    return config


def test_postgres_membership_scoped_repository_and_encrypted_vault() -> None:
    assert _DATABASE_URL is not None
    engine, sessions = create_database(_DATABASE_URL)
    tenant_id, user_id, membership_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    connection_id = uuid.uuid4()
    other_tenant_id, other_user_id, other_membership_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    other_connection_id = uuid.uuid4()
    context = ActiveContext(str(user_id), str(membership_id), str(tenant_id), ("TEACHER",))
    other_context = ActiveContext(
        str(other_user_id), str(other_membership_id), str(other_tenant_id), ("TEACHER",)
    )
    memberships = PostgresMembershipRepository(sessions)
    subjects = PostgresSubjectMapper(sessions)
    connections = new_postgres_connection_repository(sessions)
    tasks = PostgresTaskRepository(sessions)
    vault = PostgresEncryptedVault(sessions, Aes256Gcm(bytes(range(32))))
    secret_ref = None
    other_secret_ref = None
    connection_added = False
    other_connection_added = False
    task_added = False

    try:
        with session_scope(sessions) as session:
            session.add(TenantModel(id=tenant_id, name="Synthetic test tenant"))
            session.add(
                UserModel(
                    id=user_id,
                    auth_issuer="https://integration.example/",
                    auth_subject="synthetic-subject",
                )
            )
            session.flush()
            session.add(
                MembershipModel(
                    id=membership_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    roles=["TEACHER"],
                    status=MembershipStatus.ACTIVE.value,
                )
            )

        member = memberships.get(str(membership_id))
        assert member is not None
        assert member.user_id == str(user_id)
        assert member.tenant_id == str(tenant_id)
        assert member.roles == ("TEACHER",)
        assert memberships.list_for_user(str(user_id)) == [member]
        assert subjects.user_id_for("https://integration.example/", "synthetic-subject") == str(
            user_id
        )
        assert subjects.user_id_for("https://integration.example/", "unknown") is None

        secret_ref = vault.put(context, "synthetic-moodle-token")
        connection = MoodleConnection(
            connection_id=str(connection_id),
            tenant_id=str(tenant_id),
            site_url="https://moodle.example.edu",
            secret_ref=secret_ref,
            status=ConnectionStatus.ACTIVE,
            moodle_user_id=42,
        )
        connections.add(context, connection)
        connection_added = True
        assert connections.get(context, str(connection_id)) == connection
        assert connections.list(context) == [connection]
        assert vault.reveal(context, secret_ref) == "synthetic-moodle-token"
        with session_scope(sessions) as session:
            ciphertext = session.scalar(
                select(SecretVaultEntryModel.ciphertext).where(
                    SecretVaultEntryModel.tenant_id == tenant_id,
                    SecretVaultEntryModel.reference_id == uuid.UUID(secret_ref.ref_id),
                )
            )
            assert ciphertext is not None
            assert "synthetic-moodle-token" not in ciphertext

        unrelated_context = ActiveContext(
            str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), ("TEACHER",)
        )
        with pytest.raises(ResourceNotFound):
            connections.get(unrelated_context, str(connection_id))

        task_id = str(uuid.uuid4())
        created_task = tasks.create(
            context,
            task_id=task_id,
            task_type="CREATE_QUIZ",
            connection_id=str(connection_id),
            course_id="synthetic-course",
            prompt="Create a synthetic draft",
            request_payload={"locale": "ar"},
        )
        task_added = True
        assert created_task.status is TaskStatus.RECEIVED
        assert created_task.latest_event_sequence == 1
        assert tasks.get(context, task_id) == created_task
        assert [event.sequence for event in tasks.list_events(context, task_id)] == [1]
        with session_scope(sessions) as session:
            outbox = session.scalar(
                select(OutboxEventModel).where(OutboxEventModel.task_id == uuid.UUID(task_id))
            )
            assert outbox is not None
            assert outbox.status == "PENDING"

        updated_task = tasks.transition(
            context,
            task_id,
            TaskStatus.PLANNING,
            event_type="STATUS_CHANGED",
            message_code="PLANNING_STARTED",
        )
        assert updated_task.status is TaskStatus.PLANNING
        assert updated_task.latest_event_sequence == 2
        assert [event.sequence for event in tasks.list_events(context, task_id)] == [1, 2]
        with pytest.raises(TaskStateConflict):
            tasks.transition(
                context,
                task_id,
                TaskStatus.COMPLETED,
                event_type="STATUS_CHANGED",
            )
        assert tasks.get(context, task_id).status is TaskStatus.PLANNING

        wrong_owner = ActiveContext(
            str(uuid.uuid4()), str(uuid.uuid4()), str(tenant_id), ("TEACHER",)
        )
        with pytest.raises(ResourceNotFound):
            tasks.get(wrong_owner, task_id)

        with session_scope(sessions) as session:
            session.add(TenantModel(id=other_tenant_id, name="Other synthetic tenant"))
            session.add(
                UserModel(
                    id=other_user_id,
                    auth_issuer="https://integration.example/",
                    auth_subject="other-synthetic-subject",
                )
            )
            session.flush()
            session.add(
                MembershipModel(
                    id=other_membership_id,
                    user_id=other_user_id,
                    tenant_id=other_tenant_id,
                    roles=["TEACHER"],
                    status=MembershipStatus.ACTIVE.value,
                )
            )
        other_secret_ref = vault.put(other_context, "other-synthetic-token")
        connections.add(
            other_context,
            MoodleConnection(
                connection_id=str(other_connection_id),
                tenant_id=str(other_tenant_id),
                site_url="https://other-moodle.example.edu",
                secret_ref=other_secret_ref,
                status=ConnectionStatus.ACTIVE,
                moodle_user_id=84,
            ),
        )
        other_connection_added = True
        cross_tenant_task_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            tasks.create(
                context,
                task_id=cross_tenant_task_id,
                task_type="CREATE_QUIZ",
                connection_id=str(other_connection_id),
                course_id="other-tenant-course",
                prompt="Must fail closed",
                request_payload={},
            )
        with session_scope(sessions) as session:
            assert session.get(TaskModel, uuid.UUID(cross_tenant_task_id)) is None
    finally:
        try:
            if task_added:
                with session_scope(sessions) as session:
                    session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.task_id == uuid.UUID(task_id)
                        )
                    )
                    session.execute(
                        delete(TaskEventModel).where(TaskEventModel.task_id == uuid.UUID(task_id))
                    )
                    task = session.get(TaskModel, uuid.UUID(task_id))
                    if task is not None:
                        session.delete(task)
            if other_secret_ref is not None:
                if other_connection_added:
                    connections.delete(other_context, str(other_connection_id))
                vault.delete(other_context, other_secret_ref)
            if secret_ref is not None:
                if connection_added:
                    connections.delete(context, str(connection_id))
                vault.delete(context, secret_ref)
            with session_scope(sessions) as session:
                membership = session.get(MembershipModel, membership_id)
                user = session.get(UserModel, user_id)
                tenant = session.get(TenantModel, tenant_id)
                other_membership = session.get(MembershipModel, other_membership_id)
                other_user = session.get(UserModel, other_user_id)
                other_tenant = session.get(TenantModel, other_tenant_id)
                if membership is not None:
                    session.delete(membership)
                if user is not None:
                    session.delete(user)
                if tenant is not None:
                    session.delete(tenant)
                if other_membership is not None:
                    session.delete(other_membership)
                if other_user is not None:
                    session.delete(other_user)
                if other_tenant is not None:
                    session.delete(other_tenant)
        finally:
            engine.dispose()


def test_task_create_rolls_back_task_event_and_outbox_on_outbox_failure(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task_id = uuid.uuid4()
    with environment.engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS ck_test_reject_task_outbox")
        )
        connection.execute(
            text(
                "ALTER TABLE outbox_events ADD CONSTRAINT ck_test_reject_task_outbox "
                "CHECK (payload ->> 'task_type' IS DISTINCT FROM 'FORCE_ROLLBACK')"
            )
        )

    try:
        with pytest.raises(IntegrityError):
            _create_task(environment, str(task_id), task_type="FORCE_ROLLBACK")
        with session_scope(environment.sessions) as session:
            assert session.get(TaskModel, task_id) is None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(TaskEventModel)
                    .where(TaskEventModel.task_id == task_id)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(OutboxEventModel.task_id == task_id)
                )
                == 0
            )
    finally:
        with environment.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS ck_test_reject_task_outbox"
                )
            )


def test_duplicate_task_creation_preserves_single_task_event_and_outbox(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task_id = uuid.uuid4()
    _create_task(environment, str(task_id))

    with pytest.raises(IntegrityError):
        _create_task(environment, str(task_id))

    with session_scope(environment.sessions) as session:
        assert session.scalar(select(TaskModel).where(TaskModel.id == task_id)) is not None
        events = session.scalars(
            select(TaskEventModel).where(TaskEventModel.task_id == task_id)
        ).all()
        outbox = session.scalars(
            select(OutboxEventModel).where(OutboxEventModel.task_id == task_id)
        ).all()
        assert [(event.sequence, event.event_type) for event in events] == [(1, "TASK_CREATED")]
        assert len(outbox) == 1
        assert outbox[0].status == "PENDING"
        assert outbox[0].payload == {"task_id": str(task_id), "task_type": "CREATE_QUIZ"}


def test_concurrent_duplicate_task_creation_has_one_atomic_winner(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task_id = str(uuid.uuid4())
    barrier = Barrier(2)

    def create_once() -> bool:
        barrier.wait(timeout=10)
        try:
            _create_task(environment, task_id)
        except IntegrityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_once) for _ in range(2)]
        outcomes = [future.result(timeout=20) for future in futures]

    assert sorted(outcomes) == [False, True]
    with session_scope(environment.sessions) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskModel)
                .where(TaskModel.id == uuid.UUID(task_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskEventModel)
                .where(TaskEventModel.task_id == uuid.UUID(task_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.task_id == uuid.UUID(task_id))
            )
            == 1
        )


def test_concurrent_task_transitions_serialize_event_sequences(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task_id = str(uuid.uuid4())
    _create_task(environment, task_id)
    barrier = Barrier(2)

    def transition_once() -> bool:
        barrier.wait(timeout=10)
        try:
            environment.tasks.transition(
                environment.context,
                task_id,
                TaskStatus.PLANNING,
                event_type="STATUS_CHANGED",
            )
        except TaskStateConflict:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(transition_once) for _ in range(2)]
        outcomes = [future.result(timeout=20) for future in futures]

    assert sorted(outcomes) == [False, True]
    assert environment.tasks.get(environment.context, task_id).status is TaskStatus.PLANNING
    assert [
        event.sequence for event in environment.tasks.list_events(environment.context, task_id)
    ] == [1, 2]


def test_task_create_rejects_missing_moodle_connection(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        _create_task(environment, str(task_id), connection_id=str(uuid.uuid4()))
    with session_scope(environment.sessions) as session:
        assert session.get(TaskModel, task_id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskEventModel)
                .where(TaskEventModel.task_id == task_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.task_id == task_id)
            )
            == 0
        )


def test_task_connection_fk_migration_preserves_valid_legacy_task(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    task_id = str(uuid.uuid4())
    environment.engine.dispose()

    try:
        command.downgrade(alembic_config, "34b685ae0554")
        _insert_legacy_task(environment, task_id)
        command.upgrade(alembic_config, "head")
        assert environment.tasks.get(environment.context, task_id).task_id == task_id
    finally:
        command.upgrade(alembic_config, "head")


def test_task_connection_fk_migration_rejects_orphan_legacy_task_without_deleting_it(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    task_id = str(uuid.uuid4())
    environment.engine.dispose()

    try:
        command.downgrade(alembic_config, "34b685ae0554")
        _insert_legacy_task(environment, task_id, connection_id=str(uuid.uuid4()))
        with pytest.raises(IntegrityError):
            command.upgrade(alembic_config, "head")
        with environment.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "34b685ae0554"
            )
        with session_scope(environment.sessions) as session:
            assert session.scalar(
                text("SELECT EXISTS (SELECT 1 FROM tasks WHERE id = :task_id)"),
                {"task_id": uuid.UUID(task_id)},
            )
            session.execute(
                delete(OutboxEventModel).where(OutboxEventModel.task_id == uuid.UUID(task_id))
            )
            session.execute(
                delete(TaskEventModel).where(TaskEventModel.task_id == uuid.UUID(task_id))
            )
            session.execute(delete(TaskModel).where(TaskModel.id == uuid.UUID(task_id)))
        command.upgrade(alembic_config, "head")
    finally:
        command.upgrade(alembic_config, "head")


def test_postgres_idempotency_replay_and_request_conflict_are_atomic(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    first = _create_idempotent_task(environment, str(uuid.uuid4()))
    replay = _create_idempotent_task(environment, str(uuid.uuid4()))

    assert first.outcome is Outcome.NEW
    assert replay.outcome is Outcome.IN_PROGRESS
    assert replay.task.task_id == first.task.task_id
    with pytest.raises(IdempotencyKeyReused):
        _create_idempotent_task(
            environment, str(uuid.uuid4()), prompt="A different canonical request"
        )

    with session_scope(environment.sessions) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskModel)
                .where(TaskModel.tenant_id == uuid.UUID(environment.context.tenant_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRecordModel)
                .where(IdempotencyRecordModel.operation_ref == uuid.UUID(first.task.task_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.task_id == uuid.UUID(first.task.task_id))
            )
            == 1
        )


def test_concurrent_idempotency_requests_create_one_task(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    barrier = Barrier(2)

    def create_once() -> IdempotentTaskResult:
        barrier.wait(timeout=10)
        return _create_idempotent_task(environment, str(uuid.uuid4()))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_once) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]

    assert {result.outcome for result in results} == {Outcome.NEW, Outcome.IN_PROGRESS}
    assert len({result.task.task_id for result in results}) == 1
    with session_scope(environment.sessions) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskModel)
                .where(TaskModel.tenant_id == uuid.UUID(environment.context.tenant_id))
            )
            == 1
        )


def test_idempotency_task_event_and_outbox_rollback_together(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task_id = uuid.uuid4()
    with environment.engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE outbox_events ADD CONSTRAINT ck_test_reject_idempotent_outbox "
                "CHECK (payload ->> 'task_type' IS DISTINCT FROM 'FORCE_ROLLBACK')"
            )
        )
    try:
        with pytest.raises(IntegrityError):
            _create_idempotent_task(environment, str(task_id), task_type="FORCE_ROLLBACK")
        with session_scope(environment.sessions) as session:
            assert session.get(TaskModel, task_id) is None
            for model in (TaskEventModel, OutboxEventModel):
                assert (
                    session.scalar(
                        select(func.count()).select_from(model).where(model.task_id == task_id)
                    )
                    == 0
                )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecordModel)
                    .where(IdempotencyRecordModel.operation_ref == task_id)
                )
                == 0
            )
    finally:
        with environment.engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE outbox_events DROP CONSTRAINT ck_test_reject_idempotent_outbox")
            )


def test_outbox_claim_recovery_and_fencing(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    now = datetime.now(UTC)
    first_claim = queue.claim_batch(
        owner="worker-a", limit=1, lease=timedelta(seconds=30), now=now
    )[0]
    assert first_claim.attempts == 1
    assert (
        queue.claim_batch(
            owner="worker-b",
            limit=1,
            lease=timedelta(seconds=30),
            now=now + timedelta(seconds=10),
        )
        == []
    )

    recovered = queue.claim_batch(
        owner="worker-b",
        limit=1,
        lease=timedelta(seconds=30),
        now=now + timedelta(seconds=31),
    )[0]
    assert recovered.attempts == 2
    assert recovered.generation == first_claim.generation + 1
    assert not queue.acknowledge(first_claim, now=now + timedelta(seconds=31))
    assert queue.acknowledge(recovered, now=now + timedelta(seconds=31))

    with session_scope(environment.sessions) as session:
        outbox = session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.task_id == uuid.UUID(task.task_id))
        )
        assert outbox is not None
        assert outbox.status == "PUBLISHED"
        assert outbox.lease_owner is None
        assert outbox.lease_expires_at is None


def test_outbox_lease_renewal_expiry_and_nonretryable_failure(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    claimed_at = datetime.now(UTC)
    claim = queue.claim_batch(
        owner="renewal-worker",
        limit=1,
        lease=timedelta(seconds=10),
        now=claimed_at,
    )[0]
    assert queue.renew(claim, lease=timedelta(seconds=10), now=claimed_at + timedelta(seconds=5))
    assert not queue.renew(
        claim, lease=timedelta(seconds=10), now=claimed_at + timedelta(seconds=16)
    )
    recovered = queue.claim_batch(
        owner="after-expiry",
        limit=1,
        lease=timedelta(seconds=10),
        now=claimed_at + timedelta(seconds=16),
    )[0]
    assert recovered.generation == claim.generation + 1
    assert (
        queue.fail(
            recovered,
            error_code="NON_RETRYABLE",
            retryable=False,
            max_attempts=3,
            retry_at=claimed_at + timedelta(seconds=30),
            now=claimed_at + timedelta(seconds=16),
        )
        == "DEAD_LETTER"
    )
    assert environment.tasks.get(environment.context, task.task_id).status is TaskStatus.FAILED


@pytest.mark.parametrize("operation", ["acknowledge", "renew", "fail"])
def test_outbox_operations_reject_a_lease_expired_during_row_lock_wait(
    postgres_task_environment: PostgresTaskEnvironment,
    operation: str,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    claim = queue.claim_batch(
        owner=f"lock-wait-{operation}", limit=1, lease=timedelta(seconds=1)
    )[0]

    def perform_operation():
        if operation == "acknowledge":
            return queue.acknowledge(claim)
        if operation == "renew":
            return queue.renew(claim, lease=timedelta(seconds=30))
        return queue.fail(
            claim,
            error_code="LOCK_WAIT_EXPIRED",
            retryable=True,
            max_attempts=5,
            retry_at=datetime.now(UTC) + timedelta(minutes=1),
        )

    result = _run_after_a_row_lock_expires(
        environment.engine,
        model=OutboxEventModel,
        row_filter=OutboxEventModel.event_id == uuid.UUID(claim.event_id),
        table_name="outbox_events",
        lease_expires_at=claim.lease_expires_at,
        operation=perform_operation,
    )
    assert result == {"acknowledge": False, "renew": False, "fail": None}[operation]

    # A stale worker must leave the event available for the next generation.
    recovered = queue.claim_batch(
        owner=f"recovered-{operation}", limit=1, lease=timedelta(seconds=30)
    )
    assert len(recovered) == 1
    assert recovered[0].task_id == task.task_id
    assert recovered[0].generation == claim.generation + 1


def test_task_transition_rejects_a_lease_expired_while_waiting_for_outbox_lock(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    claim = queue.claim_batch(
        owner="transition-lock-wait", limit=1, lease=timedelta(seconds=1)
    )[0]

    def perform_transition():
        try:
            return environment.tasks.transition_for_worker(claim, TaskStatus.PLANNING)
        except LeaseLost as exc:
            return exc

    result = _run_after_a_row_lock_expires(
        environment.engine,
        model=OutboxEventModel,
        row_filter=OutboxEventModel.event_id == uuid.UUID(claim.event_id),
        table_name="outbox_events",
        lease_expires_at=claim.lease_expires_at,
        operation=perform_transition,
    )
    assert isinstance(result, LeaseLost)
    assert environment.tasks.get(environment.context, task.task_id).status is TaskStatus.RECEIVED
    assert len(environment.tasks.list_events(environment.context, task.task_id)) == 1


def test_retry_exhaustion_dead_letters_and_fails_task_atomically(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_idempotent_task(environment, str(uuid.uuid4())).task
    queue = PostgresOutboxRepository(environment.sessions)
    now = datetime.now(UTC)
    first_claim = queue.claim_batch(
        owner="worker-a", limit=1, lease=timedelta(seconds=60), now=now
    )[0]
    retry_at = now + timedelta(seconds=5)
    assert (
        queue.fail(
            first_claim,
            error_code="TRANSIENT_UPSTREAM",
            retryable=True,
            max_attempts=2,
            retry_at=retry_at,
            now=now,
        )
        == "PENDING"
    )
    second_claim = queue.claim_batch(
        owner="worker-b",
        limit=1,
        lease=timedelta(seconds=60),
        now=retry_at,
    )[0]
    assert second_claim.attempts == 2
    assert (
        queue.fail(
            second_claim,
            error_code="TRANSIENT_UPSTREAM",
            retryable=True,
            max_attempts=2,
            retry_at=retry_at + timedelta(seconds=1),
            now=retry_at,
        )
        == "DEAD_LETTER"
    )

    assert environment.tasks.get(environment.context, task.task_id).status is TaskStatus.FAILED
    assert [
        event.event_type
        for event in environment.tasks.list_events(environment.context, task.task_id)
    ] == ["TASK_CREATED", "TASK_FAILED"]
    with session_scope(environment.sessions) as session:
        outbox = session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.task_id == uuid.UUID(task.task_id))
        )
        idem = session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.operation_ref == uuid.UUID(task.task_id)
            )
        )
        assert outbox is not None and outbox.status == "DEAD_LETTER"
        assert outbox.last_error_code == "TRANSIENT_UPSTREAM"
        assert idem is not None and idem.state == RecordState.FAILED_FINAL.value


def test_task_http_api_replays_idempotency_and_paginates_membership_bound_events(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    settings = Settings(
        env=Environment.TEST,
        _env_file=None,
        database_url=_DATABASE_URL,
        idempotency_hmac_key=base64.b64encode(b"i" * 32).decode(),
        idempotency_retention_seconds=3600,
        event_cursor_hmac_key=base64.b64encode(b"e" * 32).decode(),
    )
    app = create_app(
        settings,
        checks=[],
        permission_policy=StaticPolicy({"TEACHER": frozenset({"task.create", "task.read"})}),
    )
    headers = {
        "X-Dev-User-ID": environment.context.user_id,
        "X-Active-Membership-ID": environment.context.membership_id,
        "Idempotency-Key": "a" * 22,
    }
    body = {
        "task_type": "CREATE_QUIZ",
        "connection_id": environment.connection_id,
        "course_id": "synthetic-course",
        "prompt": "Synthetic integration request",
    }

    with TestClient(app) as client:
        created = client.post("/tasks", headers=headers, json=body)
        replay = client.post("/tasks", headers=headers, json=body)
        assert created.status_code == 202
        assert replay.status_code == 202
        task_id = created.json()["task_id"]
        assert replay.json()["task_id"] == task_id
        assert created.json()["task_status"] == "RECEIVED"

        conflict = client.post(
            "/tasks", headers=headers, json={**body, "prompt": "Different request"}
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

        environment.tasks.transition(
            environment.context,
            task_id,
            TaskStatus.PLANNING,
            event_type="STATUS_CHANGED",
            message_code="PLANNING_STARTED",
        )
        status = client.get(f"/tasks/{task_id}", headers=headers)
        assert status.status_code == 200
        assert status.json()["task_status"] == "PLANNING"

        first_page = client.get(f"/tasks/{task_id}/events?limit=1", headers=headers)
        assert first_page.status_code == 200
        assert first_page.json()["has_more"] is True
        next_cursor = first_page.json()["next_cursor"]
        next_page = client.get(
            f"/tasks/{task_id}/events?limit=1&cursor={next_cursor}", headers=headers
        )
        assert next_page.status_code == 200
        assert next_page.json()["has_more"] is False
        assert [event["sequence"] for event in next_page.json()["items"]] == [2]


def test_idempotency_cleanup_is_bounded_and_preserves_unresolved_external_operations(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    now = datetime.now(UTC)
    expired_at = now - timedelta(seconds=1)
    resolved_task = _create_idempotent_task(
        environment, str(uuid.uuid4()), idempotency_key="a" * 22
    )
    second_resolved_task = _create_idempotent_task(
        environment, str(uuid.uuid4()), idempotency_key="c" * 22
    )
    unresolved_task = _create_idempotent_task(
        environment, str(uuid.uuid4()), idempotency_key="b" * 22
    )
    with session_scope(environment.sessions) as session:
        for task in (resolved_task.task, second_resolved_task.task, unresolved_task.task):
            record = session.scalar(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.operation_ref == uuid.UUID(task.task_id)
                )
            )
            assert record is not None
            record.expires_at = expired_at
        unresolved = session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.operation_ref == uuid.UUID(unresolved_task.task.task_id)
            )
        )
        assert unresolved is not None
        unresolved.external_unresolved = True

    cleanup = PostgresIdempotencyRepository(environment.sessions)
    assert cleanup.delete_expired_batch(now, limit=1) == 1
    assert cleanup.delete_expired_batch(now, limit=1) == 1
    assert cleanup.delete_expired_batch(now, limit=1) == 0
    with session_scope(environment.sessions) as session:
        unresolved = session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.operation_ref == uuid.UUID(unresolved_task.task.task_id)
            )
        )
        assert unresolved is not None and unresolved.external_unresolved
        unresolved.external_unresolved = False
    assert cleanup.delete_expired_batch(now, limit=1) == 1


def test_worker_runs_registered_handler_and_acks_yielded_task(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    claim = queue.claim_batch(owner="worker-test", limit=1, lease=timedelta(seconds=30))[0]

    class CreateQuizHandler:
        async def execute(self, task: PersistedTask, context: TaskExecutionContext) -> None:
            assert task.status is TaskStatus.PLANNING
            for status in (
                TaskStatus.CONTEXT_GATHERING,
                TaskStatus.DRAFTING,
                TaskStatus.VALIDATING,
                TaskStatus.AWAITING_APPROVAL,
            ):
                await context.transition(status)

    worker = PostgresTaskWorker(
        queue=queue,
        idempotency=PostgresIdempotencyRepository(environment.sessions),
        tasks=environment.tasks,
        handlers=TaskHandlerRegistry({"CREATE_QUIZ": CreateQuizHandler()}),
        worker_id="worker-test",
        settings=WorkerSettings(
            poll_seconds=0.1,
            batch_size=1,
            lease_seconds=30,
            lease_renew_seconds=10,
            shutdown_grace_seconds=1,
            idempotency_cleanup_interval_seconds=300,
            idempotency_cleanup_batch_size=10,
            retry_policy=RetryPolicy(3, 1, 60),
        ),
    )
    asyncio.run(worker._process_claim(claim))

    assert (
        environment.tasks.get(environment.context, task.task_id).status
        is TaskStatus.AWAITING_APPROVAL
    )
    with session_scope(environment.sessions) as session:
        outbox = session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.task_id == uuid.UUID(task.task_id))
        )
        assert outbox is not None and outbox.status == "PUBLISHED"


def test_worker_with_empty_registry_reports_but_does_not_claim_work(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    worker = PostgresTaskWorker(
        queue=queue,
        idempotency=PostgresIdempotencyRepository(environment.sessions),
        tasks=environment.tasks,
        handlers=TaskHandlerRegistry(),
        worker_id="idle-worker",
        settings=WorkerSettings(
            poll_seconds=0.1,
            batch_size=1,
            lease_seconds=30,
            lease_renew_seconds=10,
            shutdown_grace_seconds=1,
            idempotency_cleanup_interval_seconds=300,
            idempotency_cleanup_batch_size=10,
            retry_policy=RetryPolicy(3, 1, 60),
        ),
    )
    stop = asyncio.Event()

    async def stop_worker() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    async def run_worker() -> None:
        await asyncio.gather(worker.run(stop), stop_worker())

    asyncio.run(run_worker())
    with session_scope(environment.sessions) as session:
        outbox = session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.task_id == uuid.UUID(task.task_id))
        )
        assert outbox is not None
        assert outbox.status == "PENDING" and outbox.attempts == 0
    assert queue.unhandled_task_types(set()) == ["CREATE_QUIZ"]


def test_outbox_does_not_claim_unregistered_task_types(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    supported = _create_task(environment, str(uuid.uuid4()), task_type="CREATE_QUIZ")
    unsupported = _create_task(environment, str(uuid.uuid4()), task_type="FUTURE_TASK")
    queue = PostgresOutboxRepository(environment.sessions)

    assert queue.unhandled_task_types({"CREATE_QUIZ"}) == ["FUTURE_TASK"]
    assert (
        queue.claim_batch(
            owner="registered-worker",
            limit=10,
            lease=timedelta(seconds=30),
            supported_task_types={"CREATE_QUIZ"},
        )[0].task_id
        == supported.task_id
    )
    assert (
        queue.claim_batch(
            owner="empty-registry",
            limit=10,
            lease=timedelta(seconds=30),
            supported_task_types=set(),
        )
        == []
    )
    assert queue.unhandled_task_types({"CREATE_QUIZ"}) == ["FUTURE_TASK"]
    assert (
        queue.claim_batch(
            owner="future-worker",
            limit=1,
            lease=timedelta(seconds=30),
            supported_task_types={"FUTURE_TASK"},
        )[0].task_id
        == unsupported.task_id
    )


def test_idempotency_constraint_migration_round_trips_valid_records(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    environment.engine.dispose()
    task_id = str(uuid.uuid4())

    try:
        command.downgrade(alembic_config, "37cc62a430a9")
        _insert_legacy_task(environment, task_id)
        with session_scope(environment.sessions) as session:
            session.execute(
                text(
                    "INSERT INTO idempotency_records "
                    "(id, tenant_id, actor_membership_id, operation_code, key_hash, request_hash, "
                    "state, operation_ref, created_at, expires_at) "
                    "VALUES (:id, :tenant_id, :membership_id, 'TASK_CREATE', :key_hash, "
                    ":request_hash, 'IN_PROGRESS', :task_id, :created_at, :expires_at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": uuid.UUID(environment.context.tenant_id),
                    "membership_id": uuid.UUID(environment.context.membership_id),
                    "key_hash": "a" * 64,
                    "request_hash": "b" * 64,
                    "task_id": uuid.UUID(task_id),
                    "created_at": datetime.now(UTC),
                    "expires_at": datetime.now(UTC) + timedelta(hours=1),
                },
            )
        command.upgrade(alembic_config, "head")
        assert environment.tasks.get(environment.context, task_id).task_id == task_id
        command.downgrade(alembic_config, "37cc62a430a9")
        with session_scope(environment.sessions) as session:
            record = session.scalar(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.operation_ref == uuid.UUID(task_id)
                )
            )
            assert record is not None
        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecordModel)
                    .where(IdempotencyRecordModel.operation_ref == uuid.UUID(task_id))
                )
                == 1
            )
    finally:
        command.upgrade(alembic_config, "head")


def test_idempotency_constraint_migration_rejects_orphan_records_without_deleting_them(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    orphan_operation_id = uuid.uuid4()
    environment.engine.dispose()

    try:
        command.downgrade(alembic_config, "37cc62a430a9")
        with session_scope(environment.sessions) as session:
            session.add(
                IdempotencyRecordModel(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID(environment.context.tenant_id),
                    actor_membership_id=uuid.UUID(environment.context.membership_id),
                    operation_code="TASK_CREATE",
                    key_hash="a" * 64,
                    request_hash="b" * 64,
                    state="IN_PROGRESS",
                    operation_ref=orphan_operation_id,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        with pytest.raises(RuntimeError, match="orphan record"):
            command.upgrade(alembic_config, "head")
        with environment.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "37cc62a430a9"
            )
        with session_scope(environment.sessions) as session:
            orphan = session.scalar(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.operation_ref == orphan_operation_id
                )
            )
            assert orphan is not None
            session.execute(
                delete(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.operation_ref == orphan_operation_id
                )
            )
        command.upgrade(alembic_config, "head")
    finally:
        command.upgrade(alembic_config, "head")


def test_inbox_consumes_once_and_rejects_payload_reuse(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=30,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=30),
    )
    message = InboxMessage(
        environment.context.tenant_id,
        "course-indexer",
        "message-001",
        {"course_id": "synthetic-course"},
    )
    calls = 0

    class Handler:
        def process(self, session: Session, received: InboxMessage) -> str:
            nonlocal calls
            calls += 1
            session.execute(
                update(TenantModel)
                .where(TenantModel.id == uuid.UUID(received.tenant_id))
                .values(name="Inbox processed")
            )
            return "result-1"

    first = consumer.consume(message, Handler(), owner="inbox-worker")
    duplicate = consumer.consume(message, Handler(), owner="inbox-worker-2")

    assert first.state == "PROCESSED" and first.acknowledge
    assert duplicate.state == "PROCESSED" and duplicate.acknowledge and duplicate.duplicate
    assert duplicate.result_ref == "result-1"
    assert calls == 1
    with session_scope(environment.sessions) as session:
        tenant = session.get(TenantModel, uuid.UUID(environment.context.tenant_id))
        assert tenant is not None and tenant.name == "Inbox processed"

    with pytest.raises(InboxMessageConflict):
        consumer.consume(
            InboxMessage(
                environment.context.tenant_id,
                "course-indexer",
                "message-001",
                {"course_id": "different-course"},
            ),
            Handler(),
            owner="inbox-worker-3",
        )


def test_inbox_rolls_back_handler_effect_and_retries_after_backoff(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=30,
        retry_policy=InboxRetryPolicy(max_attempts=2, base_delay_seconds=2, max_delay_seconds=10),
    )
    message = InboxMessage(
        environment.context.tenant_id,
        "course-indexer",
        "message-retry",
        {"course_id": "synthetic-course"},
    )

    class FailingHandler:
        def process(self, session: Session, received: InboxMessage) -> str:
            session.execute(
                update(TenantModel)
                .where(TenantModel.id == uuid.UUID(received.tenant_id))
                .values(name="must rollback")
            )
            raise RetryableInboxError("TEMPORARY_FAILURE")

    failed = consumer.consume(message, FailingHandler(), owner="inbox-worker")
    assert failed.state == "FAILED" and not failed.acknowledge
    with session_scope(environment.sessions) as session:
        tenant = session.get(TenantModel, uuid.UUID(environment.context.tenant_id))
        receipt = session.scalar(
            select(InboxReceiptModel).where(
                InboxReceiptModel.tenant_id == uuid.UUID(environment.context.tenant_id),
                InboxReceiptModel.message_id == message.message_id,
            )
        )
        assert tenant is not None
        assert tenant.name == "Synthetic task tenant"
        assert receipt is not None and receipt.attempts == 1
        retry_at = receipt.next_attempt_at

    class SuccessfulHandler:
        def process(self, session: Session, received: InboxMessage) -> str:
            session.execute(
                update(TenantModel)
                .where(TenantModel.id == uuid.UUID(received.tenant_id))
                .values(name="retry committed")
            )
            return "retry-result"

    result = consumer.consume(message, SuccessfulHandler(), owner="inbox-worker-2", now=retry_at)
    assert result.state == "PROCESSED" and result.acknowledge
    with session_scope(environment.sessions) as session:
        tenant = session.get(TenantModel, uuid.UUID(environment.context.tenant_id))
        receipt = session.scalar(
            select(InboxReceiptModel).where(
                InboxReceiptModel.tenant_id == uuid.UUID(environment.context.tenant_id),
                InboxReceiptModel.message_id == message.message_id,
            )
        )
        assert tenant is not None and tenant.name == "retry committed"
        assert receipt is not None and receipt.attempts == 2


def test_inbox_expired_lease_is_fenced_and_recovered(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=10,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=10),
    )
    message = InboxMessage(
        environment.context.tenant_id, "audit-consumer", "crash-message", {"event": "safe"}
    )
    claimed_at = datetime.now(UTC)
    stale = consumer.claim(message, owner="worker-old", now=claimed_at)
    assert not isinstance(stale, InboxResult)
    busy = consumer.claim(message, owner="worker-busy", now=claimed_at + timedelta(seconds=5))
    assert isinstance(busy, InboxResult) and not busy.acknowledge
    recovered = consumer.claim(message, owner="worker-new", now=claimed_at + timedelta(seconds=11))
    assert not isinstance(recovered, InboxResult)
    assert recovered.generation == stale.generation + 1

    class Handler:
        def process(self, session: Session, received: InboxMessage) -> str:
            return "recovered"

    with pytest.raises(InboxLeaseLost):
        consumer.process(stale, message, Handler(), now=claimed_at + timedelta(seconds=11))
    result = consumer.process(recovered, message, Handler(), now=claimed_at + timedelta(seconds=11))
    assert result.state == "PROCESSED" and result.acknowledge


def test_inbox_claim_rechecks_expiry_after_waiting_for_receipt_lock(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=1,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=10),
    )
    message = InboxMessage(
        environment.context.tenant_id, "inbox-lock-wait", "receipt-lock-wait", {"v": 1}
    )
    original = consumer.claim(message, owner="inbox-lock-owner")
    assert not isinstance(original, InboxResult)

    result = _run_after_a_row_lock_expires(
        environment.engine,
        model=InboxReceiptModel,
        row_filter=InboxReceiptModel.id == uuid.UUID(original.receipt_id),
        table_name="inbox_receipts",
        lease_expires_at=original.lease_expires_at,
        operation=lambda: consumer.claim(message, owner="inbox-lock-recovery"),
    )
    assert not isinstance(result, InboxResult)
    assert result.generation == original.generation + 1
    assert result.owner == "inbox-lock-recovery"


def test_inbox_handler_cannot_commit_after_its_lease_expires(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=1,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=10),
    )
    message = InboxMessage(
        environment.context.tenant_id, "inbox-handler-lease", "slow-handler", {"v": 2}
    )
    claim = consumer.claim(message, owner="slow-inbox-handler")
    assert not isinstance(claim, InboxResult)
    handler_started = Event()

    class SlowHandler:
        def process(self, session: Session, received: InboxMessage) -> str:
            session.execute(
                update(TenantModel)
                .where(TenantModel.id == uuid.UUID(received.tenant_id))
                .values(name="must rollback after lease expiry")
            )
            handler_started.set()
            while datetime.now(UTC) < claim.lease_expires_at:
                remaining = (claim.lease_expires_at - datetime.now(UTC)).total_seconds()
                Event().wait(min(max(remaining, 0), 0.05))
            return "stale-result"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(consumer.process, claim, message, SlowHandler())
        assert handler_started.wait(timeout=5)
        while datetime.now(UTC) < claim.lease_expires_at:
            remaining = (claim.lease_expires_at - datetime.now(UTC)).total_seconds()
            Event().wait(min(max(remaining, 0), 0.05))
        with pytest.raises(InboxLeaseLost):
            future.result(timeout=5)

    with session_scope(environment.sessions) as session:
        tenant = session.get(TenantModel, uuid.UUID(environment.context.tenant_id))
        receipt = session.get(InboxReceiptModel, uuid.UUID(claim.receipt_id))
        assert tenant is not None and tenant.name == "Synthetic task tenant"
        assert receipt is not None and receipt.state == "PROCESSING"

    recovered = consumer.claim(message, owner="after-slow-handler")
    assert not isinstance(recovered, InboxResult)
    assert recovered.generation == claim.generation + 1


def test_inbox_concurrent_delivery_has_one_transactional_handler_call(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=30,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=30),
    )
    message = InboxMessage(
        environment.context.tenant_id, "concurrent-consumer", "same-message", {"value": 1}
    )
    committed_tenant_name = "Inbox handler committed with receipt"
    barrier = Barrier(2)
    lock = Lock()
    calls = 0

    class Handler:
        def process(self, session: Session, received: InboxMessage) -> str:
            nonlocal calls
            with lock:
                calls += 1
            session.execute(
                update(TenantModel)
                .where(TenantModel.id == uuid.UUID(received.tenant_id))
                .values(name=committed_tenant_name)
            )
            return "one-result"

    def consume(owner: str) -> InboxResult:
        barrier.wait()
        return consumer.consume(message, Handler(), owner=owner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, ("inbox-a", "inbox-b")))
    assert calls == 1
    assert all(result.state in {"PROCESSED", "PROCESSING"} for result in results)
    assert all(
        result.acknowledge if result.state == "PROCESSED" else not result.acknowledge
        for result in results
    )
    duplicate = consumer.consume(message, Handler(), owner="inbox-redelivery")
    assert duplicate.state == "PROCESSED" and duplicate.acknowledge and duplicate.duplicate
    assert calls == 1
    with session_scope(environment.sessions) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(InboxReceiptModel)
                .where(
                    InboxReceiptModel.tenant_id == uuid.UUID(environment.context.tenant_id),
                    InboxReceiptModel.consumer == message.consumer,
                    InboxReceiptModel.message_id == message.message_id,
                )
            )
            == 1
        )
        receipt = session.scalar(
            select(InboxReceiptModel).where(
                InboxReceiptModel.tenant_id == uuid.UUID(environment.context.tenant_id),
                InboxReceiptModel.consumer == message.consumer,
                InboxReceiptModel.message_id == message.message_id,
            )
        )
        assert receipt is not None
        assert receipt.state == "PROCESSED" and receipt.completed_at is not None
        assert receipt.lease_owner is None and receipt.lease_expires_at is None
        tenant = session.get(TenantModel, uuid.UUID(environment.context.tenant_id))
        assert tenant is not None and tenant.name == committed_tenant_name


def test_inbox_legacy_unscoped_receipt_is_never_reprocessed(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    message = InboxMessage(
        environment.context.tenant_id,
        "legacy-consumer",
        "legacy-global-message-id",
        {"value": "new delivery"},
    )
    legacy_id = uuid.uuid4()
    with session_scope(environment.sessions) as session:
        session.add(
            InboxReceiptModel(
                id=legacy_id,
                tenant_id=None,
                consumer=message.consumer,
                message_id=message.message_id,
                state="PROCESSED",
                payload_hash=None,
            )
        )
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=30,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=30),
    )

    with pytest.raises(InboxLegacyReceiptConflict, match="manual tenant reconciliation"):
        consumer.claim(message, owner="legacy-redelivery")

    with session_scope(environment.sessions) as session:
        legacy = session.get(InboxReceiptModel, legacy_id)
        tenant_scoped = session.scalar(
            select(InboxReceiptModel).where(
                InboxReceiptModel.tenant_id == uuid.UUID(environment.context.tenant_id),
                InboxReceiptModel.consumer == message.consumer,
                InboxReceiptModel.message_id == message.message_id,
            )
        )
        assert legacy is not None and legacy.tenant_id is None and legacy.state == "PROCESSED"
        assert tenant_scoped is None
        session.delete(legacy)


def test_inbox_deduplication_is_scoped_to_tenant(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    second_tenant_id = uuid.uuid4()
    with session_scope(environment.sessions) as session:
        session.add(TenantModel(id=second_tenant_id, name="Second synthetic tenant"))
    consumer = PostgresInboxConsumer(
        environment.sessions,
        lease_seconds=30,
        retry_policy=InboxRetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=30),
    )

    class Handler:
        def process(self, session: Session, message: InboxMessage) -> str:
            return message.tenant_id

    try:
        first = consumer.consume(
            InboxMessage(environment.context.tenant_id, "tenant-test", "shared-id", {"v": 1}),
            Handler(),
            owner="tenant-worker-a",
        )
        second = consumer.consume(
            InboxMessage(str(second_tenant_id), "tenant-test", "shared-id", {"v": 1}),
            Handler(),
            owner="tenant-worker-b",
        )
        assert first.result_ref == environment.context.tenant_id
        assert second.result_ref == str(second_tenant_id)
        assert not second.duplicate
    finally:
        with session_scope(environment.sessions) as session:
            session.execute(
                delete(InboxReceiptModel).where(InboxReceiptModel.tenant_id == second_tenant_id)
            )
            session.execute(delete(TenantModel).where(TenantModel.id == second_tenant_id))


def test_task_recovery_is_fail_closed_idempotent_and_tenant_scoped(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    original = _create_idempotent_task(environment, str(uuid.uuid4())).task
    queue = PostgresOutboxRepository(environment.sessions)
    claim = queue.claim_batch(owner="recovery-setup", limit=1, lease=timedelta(seconds=30))[0]
    assert (
        queue.fail(
            claim,
            error_code="HANDLER_NOT_REGISTERED",
            retryable=False,
            max_attempts=3,
            retry_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        == "DEAD_LETTER"
    )
    denied = TaskRecoveryService(
        environment.tasks,
        idempotency_hmac_key=b"r" * 32,
        idempotency_retention_seconds=3600,
    )
    with pytest.raises(PermissionDenied):
        denied.recover(
            environment.context,
            original.task_id,
            idempotency_key="r" * 22,
            reason="retry after configuration fix",
        )

    policy = StaticPolicy(
        {"TEACHER": frozenset({"task.dead_letter.list", "task.dead_letter.recover"})}
    )
    recovery = TaskRecoveryService(
        environment.tasks,
        idempotency_hmac_key=b"r" * 32,
        idempotency_retention_seconds=3600,
        policy=policy,
    )
    listed = recovery.list_dead_letters(environment.context)
    assert [(item.task.task_id, item.last_error_code) for item in listed] == [
        (original.task_id, "HANDLER_NOT_REGISTERED")
    ]
    first = recovery.recover(
        environment.context,
        original.task_id,
        idempotency_key="s" * 22,
        reason="retry after configuration fix",
    )
    replay = recovery.recover(
        environment.context,
        original.task_id,
        idempotency_key="s" * 22,
        reason="retry after configuration fix",
    )
    assert replay.task.task_id == first.task.task_id
    assert replay.outcome is Outcome.IN_PROGRESS
    assert environment.tasks.get(environment.context, original.task_id).status is TaskStatus.FAILED
    with pytest.raises(TaskStateConflict, match="already has a recovery"):
        recovery.recover(
            environment.context,
            original.task_id,
            idempotency_key="t" * 22,
            reason="second independent retry",
        )
    with session_scope(environment.sessions) as session:
        recovery_event = session.scalar(
            select(TaskEventModel).where(TaskEventModel.task_id == uuid.UUID(first.task.task_id))
        )
        assert recovery_event is not None and recovery_event.event_type == "TASK_RECOVERED"
        assert recovery_event.payload["requested_by_user_id"] == environment.context.user_id
        assert recovery_event.payload["reason"] == "retry after configuration fix"
        child = session.get(TaskModel, uuid.UUID(first.task.task_id))
        assert child is not None and child.retry_of_task_id == uuid.UUID(original.task_id)

    other_context = ActiveContext(
        str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), ("TEACHER",)
    )
    with pytest.raises(ResourceNotFound):
        recovery.recover(
            other_context,
            original.task_id,
            idempotency_key="u" * 22,
            reason="must not reveal cross tenant task",
        )


def test_task_recovery_refuses_possible_external_effects(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    original = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    claim = queue.claim_batch(owner="recovery-risk-setup", limit=1, lease=timedelta(seconds=30))[0]
    assert (
        queue.fail(
            claim,
            error_code="UNKNOWN_OUTCOME",
            retryable=False,
            max_attempts=1,
            retry_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        == "DEAD_LETTER"
    )
    with session_scope(environment.sessions) as session:
        session.execute(
            update(TaskModel)
            .where(TaskModel.id == uuid.UUID(original.task_id))
            .values(external_dispatched=True)
        )
    recovery = TaskRecoveryService(
        environment.tasks,
        idempotency_hmac_key=b"v" * 32,
        idempotency_retention_seconds=3600,
        policy=StaticPolicy({"TEACHER": frozenset({"task.dead_letter.recover"})}),
    )
    with pytest.raises(TaskStateConflict, match="not safe"):
        recovery.recover(
            environment.context,
            original.task_id,
            idempotency_key="v" * 22,
            reason="external outcome is uncertain",
        )


def test_task_recovery_serializes_concurrent_requests(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    original = _create_task(environment, str(uuid.uuid4()))
    queue = PostgresOutboxRepository(environment.sessions)
    claim = queue.claim_batch(
        owner="concurrent-recovery-setup", limit=1, lease=timedelta(seconds=30)
    )[0]
    assert (
        queue.fail(
            claim,
            error_code="SAFE_FAILURE",
            retryable=False,
            max_attempts=1,
            retry_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        == "DEAD_LETTER"
    )
    recovery = TaskRecoveryService(
        environment.tasks,
        idempotency_hmac_key=b"w" * 32,
        idempotency_retention_seconds=3600,
        policy=StaticPolicy({"TEACHER": frozenset({"task.dead_letter.recover"})}),
    )
    barrier = Barrier(2)

    def recover(key: str) -> str | None:
        barrier.wait()
        try:
            return recovery.recover(
                environment.context,
                original.task_id,
                idempotency_key=key,
                reason="one concurrent recovery",
            ).task.task_id
        except TaskStateConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        children = list(pool.map(recover, ("x" * 22, "y" * 22)))
    assert sum(child is not None for child in children) == 1
    with session_scope(environment.sessions) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskModel)
                .where(
                    TaskModel.tenant_id == uuid.UUID(environment.context.tenant_id),
                    TaskModel.retry_of_task_id == uuid.UUID(original.task_id),
                )
            )
            == 1
        )


def test_postgres_task_lifecycle_success_retry_crash_and_recovery(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    queue = PostgresOutboxRepository(environment.sessions)

    class CompleteSyntheticTask:
        async def execute(self, task: PersistedTask, context: TaskExecutionContext) -> None:
            for status in (
                TaskStatus.CONTEXT_GATHERING,
                TaskStatus.DRAFTING,
                TaskStatus.VALIDATING,
                TaskStatus.EXECUTING,
                TaskStatus.VERIFYING,
                TaskStatus.COMPLETED,
            ):
                await context.transition(status)

    worker = PostgresTaskWorker(
        queue=queue,
        idempotency=PostgresIdempotencyRepository(environment.sessions),
        tasks=environment.tasks,
        handlers=TaskHandlerRegistry({"CREATE_QUIZ": CompleteSyntheticTask()}),
        worker_id="lifecycle-worker",
        settings=WorkerSettings(
            poll_seconds=0.1,
            batch_size=4,
            lease_seconds=30,
            lease_renew_seconds=10,
            shutdown_grace_seconds=1,
            idempotency_cleanup_interval_seconds=300,
            idempotency_cleanup_batch_size=10,
            retry_policy=RetryPolicy(2, 1, 10),
        ),
    )

    success_task_id = str(uuid.uuid4())
    _create_idempotent_task(
        environment,
        success_task_id,
        idempotency_key="e" * 22,
    )
    success_claim = queue.claim_batch(
        owner="lifecycle-success",
        limit=1,
        lease=timedelta(seconds=30),
        supported_task_types={"CREATE_QUIZ"},
    )[0]
    asyncio.run(worker._process_claim(success_claim))
    assert (
        environment.tasks.get(environment.context, success_task_id).status is TaskStatus.COMPLETED
    )
    replay = _create_idempotent_task(
        environment,
        success_task_id,
        idempotency_key="e" * 22,
    )
    assert replay.outcome is Outcome.REPLAY
    assert replay.task.status is TaskStatus.COMPLETED

    retry_task = _create_idempotent_task(
        environment,
        str(uuid.uuid4()),
        idempotency_key="f" * 22,
    ).task
    first_attempt_at = datetime.now(UTC)
    first_retry_claim = queue.claim_batch(
        owner="lifecycle-retry-a",
        limit=1,
        lease=timedelta(seconds=30),
        supported_task_types={"CREATE_QUIZ"},
        now=first_attempt_at,
    )[0]
    retry_at = first_attempt_at + timedelta(seconds=5)
    assert (
        queue.fail(
            first_retry_claim,
            error_code="TRANSIENT_FAILURE",
            retryable=True,
            max_attempts=2,
            retry_at=retry_at,
            now=first_attempt_at,
        )
        == "PENDING"
    )
    assert (
        queue.claim_batch(
            owner="lifecycle-too-early",
            limit=1,
            lease=timedelta(seconds=30),
            supported_task_types={"CREATE_QUIZ"},
            now=retry_at - timedelta(seconds=1),
        )
        == []
    )
    second_retry_claim = queue.claim_batch(
        owner="lifecycle-retry-b",
        limit=1,
        lease=timedelta(seconds=30),
        supported_task_types={"CREATE_QUIZ"},
        now=retry_at,
    )[0]
    assert second_retry_claim.attempts == 2
    assert (
        queue.fail(
            second_retry_claim,
            error_code="TRANSIENT_FAILURE",
            retryable=True,
            max_attempts=2,
            retry_at=retry_at + timedelta(seconds=5),
            now=retry_at,
        )
        == "DEAD_LETTER"
    )
    assert (
        environment.tasks.get(environment.context, retry_task.task_id).status is TaskStatus.FAILED
    )

    crash_task = _create_idempotent_task(
        environment,
        str(uuid.uuid4()),
        idempotency_key="g" * 22,
    ).task
    crash_at = datetime.now(UTC)
    stale_claim = queue.claim_batch(
        owner="crashed-worker",
        limit=1,
        lease=timedelta(seconds=30),
        supported_task_types={"CREATE_QUIZ"},
        now=crash_at,
    )[0]
    recovered_claim = queue.claim_batch(
        owner="lifecycle-recovered-worker",
        limit=1,
        lease=timedelta(seconds=30),
        supported_task_types={"CREATE_QUIZ"},
        now=crash_at + timedelta(seconds=31),
    )[0]
    assert recovered_claim.generation == stale_claim.generation + 1
    assert not queue.acknowledge(stale_claim)
    asyncio.run(worker._process_claim(recovered_claim))
    assert (
        environment.tasks.get(environment.context, crash_task.task_id).status
        is TaskStatus.COMPLETED
    )

    recovery = TaskRecoveryService(
        environment.tasks,
        idempotency_hmac_key=b"z" * 32,
        idempotency_retention_seconds=3600,
        policy=StaticPolicy({"TEACHER": frozenset({"task.dead_letter.recover"})}),
    )
    recovered_task = recovery.recover(
        environment.context,
        retry_task.task_id,
        idempotency_key="h" * 22,
        reason="retry after transient failure was isolated",
    ).task
    recovery_claim = queue.claim_batch(
        owner="lifecycle-recovery-worker",
        limit=1,
        lease=timedelta(seconds=30),
        supported_task_types={"CREATE_QUIZ"},
    )[0]
    assert recovery_claim.task_id == recovered_task.task_id
    asyncio.run(worker._process_claim(recovery_claim))
    assert (
        environment.tasks.get(environment.context, recovered_task.task_id).status
        is TaskStatus.COMPLETED
    )
    assert (
        environment.tasks.get(environment.context, retry_task.task_id).status is TaskStatus.FAILED
    )
    with pytest.raises(ResourceNotFound):
        environment.tasks.get(
            ActiveContext(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), ("TEACHER",)),
            recovered_task.task_id,
        )


def test_inbox_migration_round_trips_legacy_receipts(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    receipt_id = uuid.uuid4()
    environment.engine.dispose()

    try:
        command.downgrade(alembic_config, "6a1e9dce4f21")
        with session_scope(environment.sessions) as session:
            session.execute(
                text(
                    "INSERT INTO inbox_receipts "
                    "(id, consumer, message_id, state, processed_result_ref, completed_at) "
                    "VALUES (:id, 'legacy-consumer', 'legacy-message', 'COMPLETED', "
                    "'legacy-result', :completed_at)"
                ),
                {"id": receipt_id, "completed_at": datetime.now(UTC)},
            )
        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            receipt = session.get(InboxReceiptModel, receipt_id)
            assert receipt is not None
            assert receipt.state == "PROCESSED"
            assert receipt.tenant_id is None
            assert receipt.processed_result_ref == "legacy-result"

        command.downgrade(alembic_config, "6a1e9dce4f21")
        with session_scope(environment.sessions) as session:
            legacy = session.execute(
                text("SELECT state, processed_result_ref FROM inbox_receipts WHERE id = :id"),
                {"id": receipt_id},
            ).one()
            assert legacy == ("COMPLETED", "legacy-result")
        command.upgrade(alembic_config, "head")
    finally:
        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            session.execute(delete(InboxReceiptModel).where(InboxReceiptModel.id == receipt_id))


def test_inbox_migration_quarantines_legacy_processing_receipts(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    receipt_id = uuid.uuid4()
    environment.engine.dispose()

    try:
        command.downgrade(alembic_config, "6a1e9dce4f21")
        with session_scope(environment.sessions) as session:
            session.execute(
                text(
                    "INSERT INTO inbox_receipts "
                    "(id, consumer, message_id, state) "
                    "VALUES (:id, 'legacy-processing', 'ambiguous-effect', 'PROCESSING')"
                ),
                {"id": receipt_id},
            )

        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            receipt = session.get(InboxReceiptModel, receipt_id)
            assert receipt is not None
            assert receipt.tenant_id is None
            assert receipt.state == "FAILED"
            assert receipt.retryable is False
            assert receipt.last_error_code == "LEGACY_PROCESSING_OUTCOME_UNKNOWN"
            assert receipt.completed_at is not None

        with pytest.raises(RuntimeError, match="cannot downgrade inbox processing data"):
            command.downgrade(alembic_config, "6a1e9dce4f21")

        with session_scope(environment.sessions) as session:
            session.execute(delete(InboxReceiptModel).where(InboxReceiptModel.id == receipt_id))
        command.downgrade(alembic_config, "6a1e9dce4f21")
        command.upgrade(alembic_config, "head")
    finally:
        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            session.execute(delete(InboxReceiptModel).where(InboxReceiptModel.id == receipt_id))


def test_followup_migration_quarantines_legacy_processing_after_8c_was_applied(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    receipt_id = uuid.uuid4()
    environment.engine.dispose()

    try:
        # Simulate a database that had already applied 8c before its compatibility
        # correction. This PROCESSING receipt satisfies 8c's lease CHECK but still has
        # no tenant attribution, so only revision 9d can quarantine it.
        command.downgrade(alembic_config, "8c3f1a4d2b90")
        with session_scope(environment.sessions) as session:
            session.execute(
                text(
                    "INSERT INTO inbox_receipts "
                    "(id, tenant_id, consumer, message_id, state, payload_hash, attempts, "
                    "retryable, next_attempt_at, lease_owner, lease_expires_at, lease_generation) "
                    "VALUES (:id, NULL, 'legacy-after-8c', 'in-flight-unknown', 'PROCESSING', "
                    ":payload_hash, 1, false, now(), 'old-worker', "
                    "now() + interval '30 seconds', 1)"
                ),
                {"id": receipt_id, "payload_hash": "b" * 64},
            )

        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            receipt = session.get(InboxReceiptModel, receipt_id)
            assert receipt is not None
            assert receipt.tenant_id is None
            assert receipt.state == "FAILED"
            assert receipt.retryable is False
            assert receipt.last_error_code == "LEGACY_PROCESSING_OUTCOME_UNKNOWN"
            assert receipt.lease_owner is None and receipt.lease_expires_at is None
    finally:
        command.upgrade(alembic_config, "head")
        with session_scope(environment.sessions) as session:
            session.execute(delete(InboxReceiptModel).where(InboxReceiptModel.id == receipt_id))


def test_inbox_migration_refuses_downgrade_with_live_processing_receipt(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    alembic_config = _alembic_config()
    receipt_id = uuid.uuid4()

    try:
        with session_scope(environment.sessions) as session:
            session.add(
                InboxReceiptModel(
                    id=receipt_id,
                    tenant_id=uuid.UUID(environment.context.tenant_id),
                    consumer="migration-guard",
                    message_id="processing-receipt",
                    state="PROCESSING",
                    payload_hash="a" * 64,
                    attempts=1,
                    lease_owner="migration-test",
                    lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
                    lease_generation=1,
                )
            )
        with pytest.raises(RuntimeError, match="cannot downgrade inbox processing data"):
            command.downgrade(alembic_config, "6a1e9dce4f21")
        with environment.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "8c3f1a4d2b90"
            )
        with session_scope(environment.sessions) as session:
            receipt = session.get(InboxReceiptModel, receipt_id)
            assert receipt is not None and receipt.state == "PROCESSING"
    finally:
        with session_scope(environment.sessions) as session:
            session.execute(delete(InboxReceiptModel).where(InboxReceiptModel.id == receipt_id))


def test_task_recovery_migration_refuses_downgrade_with_retry_lineage(
    postgres_task_environment: PostgresTaskEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _DATABASE_URL is not None
    environment = postgres_task_environment
    monkeypatch.setenv("MOALLEM_DATABASE_URL", _DATABASE_URL)
    parent = _create_task(environment, str(uuid.uuid4()))
    child_id = uuid.uuid4()
    with session_scope(environment.sessions) as session:
        session.add(
            TaskModel(
                id=child_id,
                tenant_id=uuid.UUID(environment.context.tenant_id),
                actor_membership_id=uuid.UUID(environment.context.membership_id),
                task_type=parent.task_type,
                connection_id=uuid.UUID(environment.connection_id),
                retry_of_task_id=uuid.UUID(parent.task_id),
                course_id=parent.course_id,
                prompt=parent.prompt,
                request_payload=parent.request_payload,
                status=TaskStatus.RECEIVED.value,
                latest_event_sequence=1,
            )
        )

    with pytest.raises(RuntimeError, match="cannot downgrade task recovery lineage"):
        command.downgrade(_alembic_config(), "6a1e9dce4f21")
    with session_scope(environment.sessions) as session:
        child = session.get(TaskModel, child_id)
        assert child is not None and child.retry_of_task_id == uuid.UUID(parent.task_id)


def test_postgres_p5_ai_usage_idempotency_and_one_way_finalization(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    tenant_id = uuid.UUID(environment.context.tenant_id)
    task_id = uuid.UUID(task.task_id)
    membership_id = uuid.UUID(environment.context.membership_id)
    invocation_id = uuid.uuid4()
    repository = PostgresAIUsageLedgerRepository(environment.sessions)
    identity = ProviderIdentity("synthetic-provider", "synthetic-model", "v1", "test-region")

    def start(request_hash: str) -> UsageLedgerStart:
        return UsageLedgerStart(
            tenant_id=tenant_id,
            task_id=task_id,
            course_id="synthetic-course",
            actor_membership_id=membership_id,
            invocation_id=invocation_id,
            provider=identity,
            prompt_version="synthetic-prompt-v1",
            request_hash=request_hash,
            permit_ref="synthetic-permit",
            privacy_policy_ref="synthetic-privacy-approval",
            budget_reservation_ref="synthetic-budget-reservation",
            budget_reserved_amount=Decimal("1.000000000000"),
            budget_currency="USD",
            pricing_version="synthetic-pricing-v1",
            source_refs=(),
        )

    request_hash = hashlib.sha256(b"same request").hexdigest()
    assert repository.begin(start(request_hash)) is UsageLedgerBeginResult.CREATED
    assert repository.begin(start(request_hash)) is UsageLedgerBeginResult.SAME_REQUEST
    assert (
        repository.begin(start(hashlib.sha256(b"different request").hexdigest()))
        is UsageLedgerBeginResult.REQUEST_HASH_CONFLICT
    )

    completion = UsageLedgerCompletion(
        tenant_id=tenant_id,
        task_id=task_id,
        invocation_id=invocation_id,
        response_hash=hashlib.sha256(b"synthetic response").hexdigest(),
        input_tokens=17,
        output_tokens=9,
        cost_amount=Decimal("0.000017000000"),
        currency="USD",
    )
    assert repository.complete(completion) is True
    assert repository.complete(completion) is False

    with session_scope(environment.sessions) as session:
        row = session.scalar(
            select(AIUsageLedgerModel).where(
                AIUsageLedgerModel.tenant_id == tenant_id,
                AIUsageLedgerModel.task_id == task_id,
                AIUsageLedgerModel.invocation_id == invocation_id,
            )
        )
        assert row is not None
        assert row.state == "SUCCEEDED"
        assert row.request_hash == request_hash
        assert row.input_tokens == 17
        assert row.output_tokens == 9
        assert row.response_hash == completion.response_hash
        assert row.cost_amount == completion.cost_amount


def test_postgres_p5_source_file_extraction_is_scoped_and_hash_bound(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    tenant_id = uuid.UUID(environment.context.tenant_id)
    membership_id = uuid.UUID(environment.context.membership_id)
    file_id = uuid.uuid4()
    content = b"synthetic lesson source"
    content_hash = hashlib.sha256(content).hexdigest()
    upload = FileUpload(
        file_id=file_id,
        tenant_id=tenant_id,
        course_id="synthetic-course",
        uploaded_by_membership_id=membership_id,
        task_id=None,
        version=1,
        original_filename="lesson.pdf",
        declared_mime_type="application/pdf",
        extraction_profile=ExtractionProfile.PDF_TEXT,
    )
    repository = PostgresSourceFileRepository(environment.sessions)
    repository.create_quarantined(
        SourceFileRegistration(
            upload=upload,
            detected_mime_type="application/pdf",
            sha256=content_hash,
            byte_size=len(content),
            storage_ref=f"synthetic-private/{tenant_id}/{file_id}",
        )
    )
    repository.record_scan_result(
        upload, ScanResult(ScanVerdict.CLEAN, "synthetic-av", "1.0")
    )
    chunk_id = uuid.uuid4()
    chunk_text = "verified course text"
    chunk = PersistedChunkInput(
        chunk_id=chunk_id,
        chunk_index=0,
        page_number=1,
        section_path="Chapter 1",
        content=chunk_text,
        content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
    )
    repository.persist_extracted(
        upload,
        expected_sha256=content_hash,
        extractor_version="synthetic-sandbox-v1",
        page_count=1,
        chunks=[chunk],
    )

    visible = repository.get_chunks(
        tenant_id=tenant_id, course_id="synthetic-course", chunk_ids=[chunk_id]
    )
    assert len(visible) == 1
    assert visible[0].content == chunk_text
    assert visible[0].content_hash == chunk.content_hash
    assert repository.get_chunks(
        tenant_id=tenant_id, course_id="another-course", chunk_ids=[chunk_id]
    ) == ()
    assert repository.get_chunks(
        tenant_id=uuid.uuid4(), course_id="synthetic-course", chunk_ids=[chunk_id]
    ) == ()


def test_postgres_p5_ai_source_ref_cross_course_failure_rolls_back_usage_row(
    postgres_task_environment: PostgresTaskEnvironment,
) -> None:
    environment = postgres_task_environment
    task = _create_task(environment, str(uuid.uuid4()))
    tenant_id = uuid.UUID(environment.context.tenant_id)
    membership_id = uuid.UUID(environment.context.membership_id)
    file_id = uuid.uuid4()
    file_content = b"another course source"
    upload = FileUpload(
        file_id=file_id,
        tenant_id=tenant_id,
        course_id="different-course",
        uploaded_by_membership_id=membership_id,
        task_id=None,
        version=1,
        original_filename="other.pdf",
        declared_mime_type="application/pdf",
        extraction_profile=ExtractionProfile.PDF_TEXT,
    )
    files = PostgresSourceFileRepository(environment.sessions)
    files.create_quarantined(
        SourceFileRegistration(
            upload=upload,
            detected_mime_type="application/pdf",
            sha256=hashlib.sha256(file_content).hexdigest(),
            byte_size=len(file_content),
            storage_ref=f"synthetic-private/{tenant_id}/{file_id}",
        )
    )
    files.record_scan_result(upload, ScanResult(ScanVerdict.CLEAN, "synthetic-av", "1.0"))
    chunk_text = "confidential other course text"
    chunk_id = uuid.uuid4()
    files.persist_extracted(
        upload,
        expected_sha256=hashlib.sha256(file_content).hexdigest(),
        extractor_version="synthetic-sandbox-v1",
        page_count=1,
        chunks=[
            PersistedChunkInput(
                chunk_id=chunk_id,
                chunk_index=0,
                page_number=1,
                section_path=None,
                content=chunk_text,
                content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
            )
        ],
    )

    invocation_id = uuid.uuid4()
    usage = PostgresAIUsageLedgerRepository(environment.sessions)
    record = UsageLedgerStart(
        tenant_id=tenant_id,
        task_id=uuid.UUID(task.task_id),
        course_id="synthetic-course",
        actor_membership_id=membership_id,
        invocation_id=invocation_id,
        provider=ProviderIdentity("synthetic-provider", "synthetic-model", "v1", "test-region"),
        prompt_version="synthetic-prompt-v1",
        request_hash=hashlib.sha256(b"cross-course attempt").hexdigest(),
        permit_ref="synthetic-permit",
        privacy_policy_ref="synthetic-privacy-approval",
        budget_reservation_ref="synthetic-budget-reservation",
        budget_reserved_amount=Decimal("1.000000000000"),
        budget_currency="USD",
        pricing_version="synthetic-pricing-v1",
        source_refs=(chunk_id,),
    )

    with pytest.raises(AIUsageSourceReferenceError):
        usage.begin(record)

    with session_scope(environment.sessions) as session:
        assert (
            session.scalar(
                select(AIUsageLedgerModel.id).where(
                    AIUsageLedgerModel.tenant_id == tenant_id,
                    AIUsageLedgerModel.task_id == uuid.UUID(task.task_id),
                    AIUsageLedgerModel.invocation_id == invocation_id,
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(SourceChunkModel.id).where(
                    SourceChunkModel.tenant_id == tenant_id,
                    SourceChunkModel.id == chunk_id,
                )
            )
            == chunk_id
        )

    # Bypass the repository-level precheck and prove the composite PostgreSQL FK still
    # rejects a source chunk whose course differs from the usage/task course.
    fk_invocation_id = uuid.uuid4()
    assert (
        usage.begin(replace(record, invocation_id=fk_invocation_id, source_refs=()))
        is UsageLedgerBeginResult.CREATED
    )
    with pytest.raises(IntegrityError):
        with session_scope(environment.sessions) as session:
            session.add(
                AIUsageSourceRefModel(
                    tenant_id=tenant_id,
                    task_id=uuid.UUID(task.task_id),
                    invocation_id=fk_invocation_id,
                    course_id="synthetic-course",
                    source_chunk_id=chunk_id,
                )
            )
