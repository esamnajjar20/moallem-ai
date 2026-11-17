"""Guards drift between code and the draft OpenAPI contract."""

from pathlib import Path
from typing import Any

import yaml

from moallem.errors import ErrorCode

OPENAPI = Path(__file__).resolve().parents[2] / "contracts" / "openapi.draft.yaml"


def test_error_codes_match_openapi_enum() -> None:
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    enum = spec["components"]["schemas"]["ErrorEnvelope"]["properties"]["code"]["enum"]
    assert {c.value for c in ErrorCode} == set(enum)


def _schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))[
        "components"
    ]["schemas"]
    return schemas


def test_task_status_matches_openapi_enum() -> None:
    from moallem.domain.tasks import TaskStatus

    enum = _schemas()["TaskStatus"]["properties"]["task_status"]["enum"]
    assert {s.value for s in TaskStatus} == set(enum)


def test_membership_status_matches_openapi_enum() -> None:
    from moallem.domain.membership import MembershipStatus

    enum = _schemas()["MembershipSummary"]["properties"]["status"]["enum"]
    assert {s.value for s in MembershipStatus} == set(enum)


def test_task_routes_and_event_types_match_openapi() -> None:
    from moallem.api.app import create_app
    from moallem.api.task_schemas import TaskEventType
    from moallem.config import Environment, Settings

    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    contract_paths = spec["paths"]
    app_paths = create_app(Settings(env=Environment.TEST, _env_file=None), checks=[]).openapi()[
        "paths"
    ]
    expected = {
        "/tasks": {"post"},
        "/tasks/{task_id}": {"get"},
        "/tasks/{task_id}/events": {"get"},
    }
    for path, methods in expected.items():
        assert path in contract_paths
        versioned_path = f"/api/v1{path}"
        assert versioned_path in app_paths
        assert methods <= set(contract_paths[path])
        assert methods <= set(app_paths[versioned_path])

    task_contract = _schemas()
    assert {event.value for event in TaskEventType} == set(
        task_contract["TaskEvent"]["properties"]["event_type"]["enum"]
    )
    post_parameters = {
        parameter["name"]: parameter
        for parameter in app_paths["/api/v1/tasks"]["post"]["parameters"]
    }
    assert post_parameters["Idempotency-Key"]["required"] is True
    assert post_parameters["X-Active-Membership-ID"]["required"] is True
    assert "202" in app_paths["/api/v1/tasks"]["post"]["responses"]
