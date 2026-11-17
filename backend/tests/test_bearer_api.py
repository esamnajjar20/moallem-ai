"""HTTP-level tests for Auth0 bearer authentication and its error contract."""

import uuid

import pytest
from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.api.deps import BearerAuthenticator
from moallem.config import Settings
from moallem.domain.identity import InMemorySubjectMapper
from moallem.domain.membership import InMemoryMembershipRepository, Membership, MembershipStatus
from tests.helpers_jwt import HS256Verifier, mint

ISS, AUD, NOW = "https://idp.example", "moallem-api", 1_000_000
MID = str(uuid.uuid4())


def _client() -> TestClient:
    auth = BearerAuthenticator(
        HS256Verifier(),
        InMemorySubjectMapper({(ISS, "sub-1"): "u1"}),
        issuer=ISS,
        audience=AUD,
        leeway_seconds=0,
        max_lifetime_seconds=900,
        clock=lambda: NOW,
    )
    repo = InMemoryMembershipRepository(
        {MID: Membership(MID, "u1", str(uuid.uuid4()), ("TEACHER",), MembershipStatus.ACTIVE)}
    )
    app = create_app(
        Settings(env="test", _env_file=None), checks=[], authenticator=auth, membership_repo=repo
    )
    return TestClient(app)


def _token(**over: object) -> str:
    p: dict[str, object] = {
        "iss": ISS,
        "sub": "sub-1",
        "aud": AUD,
        "iat": NOW - 10,
        "exp": NOW + 600,
    }
    p.update(over)
    return mint(p)


def test_valid_bearer_reaches_me() -> None:
    r = _client().get("/api/v1/me", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200 and r.json()["user_id"] == "u1"
    assert r.headers["cache-control"] == "no-store"


def test_dev_header_is_not_accepted_when_bearer_is_configured() -> None:
    r = _client().get("/api/v1/me", headers={"X-Dev-User-ID": "u1"})
    assert r.status_code == 401


def test_expired_bearer_is_401() -> None:
    r = _client().get("/api/v1/me", headers={"Authorization": f"Bearer {_token(exp=NOW - 1)}"})
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert r.headers["www-authenticate"].startswith("Bearer ")
    assert r.headers["cache-control"] == "no-store"


def test_missing_token_has_bearer_challenge_and_no_store() -> None:
    response = _client().get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer realm="moallem-api"'
    assert response.headers["cache-control"] == "no-store"


def test_auth0_mode_without_postgres_mapping_fails_closed_outside_tests() -> None:
    from moallem.config import Environment

    settings = Settings(
        env=Environment.DEVELOPMENT,
        auth_issuer="https://tenant.auth0.com/",
        auth_audience="https://api.moallem",
        auth_max_token_lifetime_seconds=900,
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="PostgreSQL identity mapping"):
        create_app(settings, checks=[])


def test_custom_authentication_adapter_cannot_override_runtime_auth() -> None:
    from moallem.api.deps import NoAuthenticator

    with pytest.raises(RuntimeError, match="may only be injected in tests"):
        create_app(Settings(env="development", _env_file=None), checks=[], authenticator=NoAuthenticator())


def test_custom_readiness_checks_cannot_replace_auth0_and_database_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    def fake_database(*_args: object, **_kwargs: object):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        return engine, sessionmaker(engine)

    monkeypatch.setattr("moallem.api.app.create_database", fake_database)
    settings = Settings(
        env="development",
        database_url="postgresql://unused:unused@localhost/moallem",
        auth_issuer="https://tenant.auth0.com/",
        auth_audience="https://api.moallem",
        auth_max_token_lifetime_seconds=900,
        _env_file=None,
    )
    app = create_app(settings, checks=[])
    names = {check.__name__ for check in app.state.readiness_checks}
    assert names == {"_postgres_check", "_auth0_jwks_check"}
    app.state.db_engine.dispose()
