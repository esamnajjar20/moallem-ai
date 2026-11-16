import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.config import Settings
from moallem.domain.membership import (
    InMemoryMembershipRepository,
    Membership,
    MembershipStatus,
)

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.draft.yaml"
_USER_ID = str(uuid.uuid4())
_TENANT_ID = str(uuid.uuid4())
_MEMBERSHIP_ID = str(uuid.uuid4())


def _client() -> tuple[TestClient, dict[str, str]]:
    repo = InMemoryMembershipRepository(
        {
            _MEMBERSHIP_ID: Membership(
                _MEMBERSHIP_ID,
                _USER_ID,
                _TENANT_ID,
                ("TEACHER",),
                MembershipStatus.ACTIVE,
            )
        }
    )
    app = create_app(Settings(env="test", _env_file=None), checks=[], membership_repo=repo)
    return TestClient(app), {
        "X-Dev-User-ID": _USER_ID,
        "X-Active-Membership-ID": _MEMBERSHIP_ID,
    }


def _contract_parameters(operation: dict[str, Any]) -> dict[str, Any]:
    components = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))["components"]
    result: dict[str, Any] = {}
    for parameter in operation["parameters"]:
        if "$ref" in parameter:
            name = parameter["$ref"].rsplit("/", 1)[-1]
            parameter = components["parameters"][name]
        result[parameter["name"]] = parameter
    return result


def test_course_read_route_parameters_match_openapi_contract() -> None:
    client, _headers = _client()
    spec = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))
    generated = client.app.openapi()
    for path, operation_id in (
        ("/courses", "listTeacherCourses"),
        ("/courses/{course_id}/context", "getCourseContext"),
    ):
        contract_operation = spec["paths"][path]["get"]
        generated_operation = generated["paths"][path]["get"]
        assert contract_operation["operationId"] == operation_id
        assert generated_operation["operationId"] == operation_id
        expected = _contract_parameters(contract_operation)
        actual = {parameter["name"]: parameter for parameter in generated_operation["parameters"]}
        assert set(actual) == set(expected)
        membership = actual["X-Active-Membership-ID"]
        assert membership["in"] == "header" and membership["required"] is True
        assert membership["schema"]["type"] == "string"


def test_course_read_routes_fail_closed_until_connection_repository_exists() -> None:
    client, headers = _client()
    responses = (
        client.get("/courses?connection_id=00000000-0000-4000-8000-000000000001", headers=headers),
        client.get(
            "/courses/42/context?connection_id=00000000-0000-4000-8000-000000000001",
            headers=headers,
        ),
    )
    for response in responses:
        assert response.status_code == 503
        assert response.json()["code"] == "MOODLE_UNAVAILABLE"
        assert "not configured" in response.json()["message"]


def test_course_read_routes_require_membership_context_header() -> None:
    client, headers = _client()
    del headers["X-Active-Membership-ID"]
    response = client.get(
        "/courses?connection_id=00000000-0000-4000-8000-000000000001",
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] in {"MEMBERSHIP_CONTEXT_REQUIRED", "VALIDATION_FAILED"}
