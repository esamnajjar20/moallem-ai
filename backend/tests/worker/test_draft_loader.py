"""Tests for draft_from_snapshot_content."""

from decimal import Decimal
from uuid import uuid4

import pytest

from moallem.ai.quiz.contracts import QuestionDraftPreview, QuizDraftPreview
from moallem.domain.errors import ResourceNotFound, TaskStateConflict
from moallem.worker.draft_loader import draft_from_snapshot_content


def _preview() -> QuizDraftPreview:
    return QuizDraftPreview(
        title="اختبار",
        instructions=None,
        questions=(
            QuestionDraftPreview(
                question_id=uuid4(),
                question_type_code="TRUEFALSE",
                stem="سؤال",
                options=(),
                correct_answer_preview="true",
                rationale=None,
                points=Decimal("1"),
                source_refs=(),
                unsupported=False,
                unsupported_reason=None,
            ),
        ),
        schema_version="1.0",
        total_points=Decimal("1"),
    )


def test_loads_validated_preview() -> None:
    preview = _preview()
    loaded = draft_from_snapshot_content({"preview": preview.model_dump(mode="json")})
    assert loaded.title == "اختبار"
    assert len(loaded.questions) == 1


def test_missing_preview_is_not_publishable() -> None:
    with pytest.raises(TaskStateConflict):
        draft_from_snapshot_content({"questions": []})


def test_non_mapping_content_is_not_found() -> None:
    with pytest.raises(ResourceNotFound):
        draft_from_snapshot_content(None)


def test_invalid_preview_is_rejected() -> None:
    with pytest.raises(ValueError):
        draft_from_snapshot_content({"preview": {"title": ""}})
