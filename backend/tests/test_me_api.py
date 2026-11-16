"""UNRUN in the authoring sandbox (needs fastapi/httpx)."""

import uuid

from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.config import Settings
from moallem.domain.membership import InMemoryMembershipRepository, Membership, MembershipStatus

MID = str(uuid.uuid4())


def _client() -> TestClient:
    repo = InMemoryMembershipRepository(
        {MID: Membership(MID, "u1", str(uuid.uuid4()), ("TEACHER",), MembershipStatus.ACTIVE)}
    )
    app = create_app(Settings(env="test", _env_file=None), checks=[], membership_repo=repo)
    return TestClient(app)


def test_me_requires_authentication() -> None:
    r = _client().get("/api/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_me_lists_memberships_without_membership_header() -> None:
    r = _client().get("/api/v1/me", headers={"X-Dev-User-ID": "u1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1" and body["memberships"][0]["membership_id"] == MID
