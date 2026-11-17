"""Tests for SnapshotDraftLoader."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from moallem.ai.quiz.contracts import AnswerOptionPreview, QuestionDraftPreview, QuizDraftPreview
from moallem.domain.errors import TaskStateConflict
from moallem.worker.draft_loader import SnapshotDraftLoader


class _FakeSnapshot:
    def __init__(self, snapshot_id: str, content: dict) -> None:
        self.snapshot_id = snapshot_id
        self.content = content
        self.schema_version = "1.0"


class _FakeSource:
    def __init__(self, record: _FakeSnapshot) -> None:
        self._record = record

    def get_current_snapshot(self, ctx, task_id: str):  # noqa: ANN001
        del ctx, task_id
        return self._record


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


def test_load_from_top_level_preview() -> None:
    preview = _preview()
    source = _FakeSource(
        _FakeSnapshot("snap-1", {"preview": preview.model_dump(mode="json")})
    )
    loader = SnapshotDraftLoader(source)
    loaded = loader.load_draft(tenant_id=str(uuid4()), task_id=str(uuid4()), snapshot_id="snap-1")
    assert loaded.title == "اختبار"
    assert len(loaded.questions) == 1


def test_rejects_stale_snapshot_id() -> None:
    preview = _preview()
    source = _FakeSource(
        _FakeSnapshot("snap-head", {"preview": preview.model_dump(mode="json")})
    )
    loader = SnapshotDraftLoader(source)
    with pytest.raises(TaskStateConflict):
        loader.load_draft(
            tenant_id=str(uuid4()), task_id=str(uuid4()), snapshot_id="snap-old"
        )


def test_rebuild_from_question_previews() -> None:
    q = QuestionDraftPreview(
        question_id=uuid4(),
        question_type_code="SHORTANSWER",
        stem="عاصمة مصر؟",
        options=(),
        correct_answer_preview="القاهرة",
        rationale=None,
        points=Decimal("2"),
        source_refs=(),
        unsupported=False,
        unsupported_reason=None,
    )
    content = {
        "spec": {"name": "جغرافيا", "instructions": "أجب"},
        "questions": [
            {
                "preview": q.model_dump(mode="json"),
            }
        ],
        "schema_version": "1.0",
    }
    source = _FakeSource(_FakeSnapshot("snap-2", content))
    loader = SnapshotDraftLoader(source)
    loaded = loader.load_draft(tenant_id=str(uuid4()), task_id=str(uuid4()), snapshot_id="snap-2")
    assert loaded.title == "جغرافيا"
    assert loaded.questions[0].stem == "عاصمة مصر؟"
