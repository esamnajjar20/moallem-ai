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
