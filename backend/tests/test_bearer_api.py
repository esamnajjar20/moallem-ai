"""BearerAuthenticator over HTTP (needs fastapi + httpx; UNRUN in the authoring sandbox)."""

import uuid

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


def test_dev_header_is_not_accepted_when_bearer_is_configured() -> None:
    r = _client().get("/api/v1/me", headers={"X-Dev-User-ID": "u1"})
    assert r.status_code == 401


def test_expired_bearer_is_401() -> None:
    r = _client().get("/api/v1/me", headers={"Authorization": f"Bearer {_token(exp=NOW - 1)}"})
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"
