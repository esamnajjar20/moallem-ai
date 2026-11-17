from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from moallem.ai.quiz.contracts import (
    GeneratedQuestion,
    QuestionDraftPreview,
    QuizDraftPreview,
    QuizSpec,
)
from moallem.ai.quiz.registry import QuestionTypeNotApproved, QuestionTypeRegistry


def _openapi_schemas() -> dict[str, object]:
    root = Path(__file__).resolve().parents[4]
    document = yaml.safe_load((root / "contracts" / "openapi.draft.yaml").read_text("utf-8"))
    return document["components"]["schemas"]


def test_quiz_spec_required_fields_match_openapi_draft() -> None:
    schemas = _openapi_schemas()
    runtime = QuizSpec.model_json_schema()
    contract = schemas["QuizSpec"]

    assert set(runtime["properties"]) == set(contract["properties"])
    assert set(runtime["required"]) == set(contract["required"])
    assert runtime["properties"]["question_types"]["items"]["pattern"] == contract[
        "properties"
    ]["question_types"]["items"]["pattern"]


def test_question_preview_contract_matches_openapi_draft() -> None:
    schemas = _openapi_schemas()
    runtime = QuestionDraftPreview.model_json_schema()
    contract = schemas["QuestionDraftPreview"]

    assert set(runtime["properties"]) == set(contract["properties"])
    assert set(runtime["required"]) == set(contract["required"])


def test_quiz_preview_required_fields_match_openapi_draft() -> None:
    schemas = _openapi_schemas()
    runtime = QuizDraftPreview.model_json_schema()
    contract = schemas["QuizDraftPreview"]

    assert set(runtime["properties"]) == set(contract["properties"])
    assert set(runtime["required"]) == set(contract["required"])


def test_registry_is_empty_by_default_unknown_type_fails_closed_and_is_immutable() -> None:
    registry = QuestionTypeRegistry()
    assert registry.codes() == ()
    with pytest.raises(QuestionTypeNotApproved):
        registry.get("SINGLE_CHOICE")
    with pytest.raises((AttributeError, TypeError)):
        registry._definitions = {}  # type: ignore[misc]


def test_generated_question_requires_explicit_evidence_decision() -> None:
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate(
            {
                "question_type_code": "SINGLE_CHOICE",
                "content": {"stem": "Question"},
            }
        )


def test_unsupported_question_requires_a_meaningful_reason() -> None:
    base = {
        "question_type_code": "SINGLE_CHOICE",
        "content": {"stem": "Question"},
        "unsupported": True,
    }
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate(base)
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate({**base, "unsupported_reason": "  "})

    parsed = GeneratedQuestion.model_validate(
        {**base, "unsupported_reason": "The provided source is insufficient."}
    )
    assert parsed.unsupported is True


def test_generated_question_rejects_reason_when_supported() -> None:
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate(
            {
                "question_type_code": "SINGLE_CHOICE",
                "content": {"stem": "Question"},
                "unsupported": False,
                "unsupported_reason": "No evidence.",
            }
        )
