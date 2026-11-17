"""Auth0 subject mapping and account lifecycle tests using an isolated SQLite user table."""

import uuid
from argparse import Namespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from moallem.api.app import _check_auth_schema
from moallem.persistence.models import UserModel
from moallem.persistence.repositories import PostgresSubjectMapper
from scripts.manage_auth_identity import set_status


def test_subject_mapping_requires_active_preprovisioned_user() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    UserModel.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    issuer = "https://tenant.auth0.com/"
    subject = "auth0|synthetic-user"
    with sessions.begin() as session:
        session.add(
            UserModel(
                id=user_id,
                auth_issuer=issuer,
                auth_subject=subject,
                auth_status="ACTIVE",
            )
        )
    mapper = PostgresSubjectMapper(sessions)
    assert mapper.user_id_for(issuer, subject) == str(user_id)
    assert mapper.user_id_for(issuer, "auth0|unknown") is None

    with sessions.begin() as session:
        user = session.get(UserModel, user_id)
        assert user is not None
        user.auth_status = "SUSPENDED"
    assert mapper.user_id_for(issuer, subject) is None

    with sessions.begin() as session:
        user = session.get(UserModel, user_id)
        assert user is not None
        user.auth_status = "REVOKED"
    assert mapper.user_id_for(issuer, subject) is None
    engine.dispose()


def test_auth_schema_readiness_rejects_pre_lifecycle_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        try:
            _check_auth_schema(engine)
        except Exception as exc:
            assert "no such table" in str(exc).lower()
        else:
            raise AssertionError("readiness must reject missing identity schema")
        UserModel.__table__.create(engine)
        _check_auth_schema(engine)
    finally:
        engine.dispose()


def test_revoked_identity_cannot_be_reactivated_by_operator_script() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    UserModel.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    with sessions.begin() as session:
        session.add(
            UserModel(
                id=user_id,
                auth_issuer="https://tenant.auth0.com/",
                auth_subject="auth0|terminal",
                auth_status="REVOKED",
            )
        )
    try:
        try:
            set_status(Namespace(user_id=str(user_id), status="ACTIVE"), sessions)
        except ValueError as exc:
            assert "terminal" in str(exc)
        else:
            raise AssertionError("a revoked identity must not be reactivated")
    finally:
        engine.dispose()
