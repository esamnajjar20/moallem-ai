"""Tests for draft → Moodle question mapping."""

from decimal import Decimal
from uuid import uuid4

import pytest

from moallem.ai.quiz.contracts import AnswerOptionPreview, QuestionDraftPreview, QuizDraftPreview
from moallem.moodle.question_mapping import (
    UnsupportedQuestionForPublish,
    map_question_draft_to_spec,
    map_quiz_draft_to_specs,
)


def _mcq(*, correct: str = "Paris") -> QuestionDraftPreview:
    return QuestionDraftPreview(
        question_id=uuid4(),
        question_type_code="MULTICHOICE",
        stem="عاصمة فرنسا؟",
        options=(
            AnswerOptionPreview(option_id="a", text="Paris"),
            AnswerOptionPreview(option_id="b", text="London"),
        ),
        correct_answer_preview=correct,
        rationale="عاصمة فرنسا هي باريس",
        points=Decimal("1"),
        source_refs=(uuid4(),),
        unsupported=False,
        unsupported_reason=None,
    )


def test_map_multichoice_success() -> None:
    spec = map_question_draft_to_spec(_mcq())
    assert spec.question_type == "multichoice"
    assert len(spec.options) == 2
    assert any(o.is_correct and o.text == "Paris" for o in spec.options)


def test_map_multichoice_rejects_missing_correct() -> None:
    q = _mcq(correct="Berlin")  # does not match options
    with pytest.raises(UnsupportedQuestionForPublish):
        map_question_draft_to_spec(q)


def test_map_truefalse() -> None:
    q = QuestionDraftPreview(
        question_id=uuid4(),
        question_type_code="TRUEFALSE",
        stem="الأرض كروية",
        options=(),
        correct_answer_preview="صح",
        rationale=None,
        points=Decimal("1"),
        source_refs=(),
        unsupported=False,
        unsupported_reason=None,
    )
    spec = map_question_draft_to_spec(q)
    assert spec.question_type == "truefalse"
    assert spec.correct_answer == "true"


def test_map_rejects_unsupported_flag() -> None:
    q = _mcq()
    q2 = q.model_copy(update={"unsupported": True, "unsupported_reason": "weak evidence"})
    with pytest.raises(UnsupportedQuestionForPublish):
        map_question_draft_to_spec(q2)


def test_map_quiz_draft() -> None:
    draft = QuizDraftPreview(
        title="اختبار تجريبي",
        instructions="اقرأ بعناية",
        questions=(_mcq(),),
        schema_version="1.0",
        total_points=Decimal("1"),
    )
    name, intro, specs = map_quiz_draft_to_specs(draft)
    assert name == "اختبار تجريبي"
    assert intro == "اقرأ بعناية"
    assert len(specs) == 1
