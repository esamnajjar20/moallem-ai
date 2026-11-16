import os
import uuid

import pytest
from sqlalchemy import select

from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import (
    ActiveContext,
    MembershipStatus,
)
from moallem.domain.secret_encryption import Aes256Gcm
from moallem.moodle.service import ConnectionStatus, MoodleConnection
from moallem.persistence.database import create_database, session_scope
from moallem.persistence.models import (
    MembershipModel,
    SecretVaultEntryModel,
    TenantModel,
    UserModel,
)
from moallem.persistence.repositories import (
    PostgresMembershipRepository,
    PostgresSubjectMapper,
    new_postgres_connection_repository,
)
from moallem.persistence.vault import PostgresEncryptedVault

_DATABASE_URL = os.environ.get("MOALLEM_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="set MOALLEM_TEST_DATABASE_URL and run Alembic migrations for PostgreSQL integration",
)


def test_postgres_membership_scoped_repository_and_encrypted_vault() -> None:
    assert _DATABASE_URL is not None
    engine, sessions = create_database(_DATABASE_URL)
    tenant_id, user_id, membership_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    connection_id = uuid.uuid4()
    context = ActiveContext(str(user_id), str(membership_id), str(tenant_id), ("TEACHER",))
    memberships = PostgresMembershipRepository(sessions)
    subjects = PostgresSubjectMapper(sessions)
    connections = new_postgres_connection_repository(sessions)
    vault = PostgresEncryptedVault(sessions, Aes256Gcm(bytes(range(32))))
    secret_ref = None
    connection_added = False

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

        other_context = ActiveContext(
            str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), ("TEACHER",)
        )
        with pytest.raises(ResourceNotFound):
            connections.get(other_context, str(connection_id))
    finally:
        try:
            if secret_ref is not None:
                if connection_added:
                    connections.delete(context, str(connection_id))
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
