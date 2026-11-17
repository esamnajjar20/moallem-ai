import uuid

from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.config import Environment, Settings
from moallem.domain.authorization import StaticPolicy
from moallem.domain.membership import (
    InMemoryMembershipRepository,
    Membership,
    MembershipStatus,
)

_USER_ID = str(uuid.uuid4())
_TENANT_ID = str(uuid.uuid4())
_MEMBERSHIP_ID = str(uuid.uuid4())
_CONNECTION_ID = str(uuid.uuid4())


def _client(*, allow_tasks: bool = False) -> TestClient:
    membership_repo = InMemoryMembershipRepository(
        {
            _MEMBERSHIP_ID: Membership(
                membership_id=_MEMBERSHIP_ID,
                user_id=_USER_ID,
                tenant_id=_TENANT_ID,
                roles=("TEACHER",),
                status=MembershipStatus.ACTIVE,
            )
        }
    )
    policy = (
        StaticPolicy({"TEACHER": frozenset({"task.create", "task.read"})}) if allow_tasks else None
    )
    app = create_app(
        Settings(env=Environment.TEST, _env_file=None),
        checks=[],
        membership_repo=membership_repo,
        permission_policy=policy,
    )
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {
        "X-Dev-User-ID": _USER_ID,
        "X-Active-Membership-ID": _MEMBERSHIP_ID,
        "Idempotency-Key": "x" * 22,
    }


def _payload() -> dict[str, str]:
    return {
        "task_type": "CREATE_QUIZ",
        "connection_id": _CONNECTION_ID,
        "course_id": "course-1",
        "prompt": "Create a draft quiz",
    }


def test_task_routes_remain_fail_closed_without_an_explicit_policy() -> None:
    response = _client().post("/tasks", headers=_headers(), json=_payload())

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_task_creation_reports_unconfigured_database_instead_of_faking_success() -> None:
    response = _client(allow_tasks=True).post("/tasks", headers=_headers(), json=_payload())

    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_task_request_rejects_unknown_fields_without_echoing_values() -> None:
    payload = {**_payload(), "unexpected_secret": "must-not-be-echoed"}
    response = _client().post("/tasks", headers=_headers(), json=payload)

    assert response.status_code == 400
    assert "must-not-be-echoed" not in response.text
    assert response.json()["code"] == "VALIDATION_FAILED"
