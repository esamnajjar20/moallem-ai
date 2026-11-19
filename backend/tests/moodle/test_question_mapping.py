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


def test_map_multichoice_matches_by_option_id() -> None:
    spec = map_question_draft_to_spec(_mcq(correct="a"))
    assert [o.is_correct for o in spec.options] == [True, False]


def test_map_multichoice_matches_arabic_text_with_diacritics_and_spaces() -> None:
    q = QuestionDraftPreview(
        question_id=uuid4(),
        question_type_code="MULTICHOICE",
        stem="ما عاصمة فلسطين؟",
        options=(
            AnswerOptionPreview(option_id="a", text="القُدس  الشريف"),
            AnswerOptionPreview(option_id="b", text="حيفا"),
        ),
        correct_answer_preview="القدس الشريف",
        rationale=None,
        points=Decimal("1"),
        source_refs=(),
        unsupported=False,
        unsupported_reason=None,
    )
    spec = map_question_draft_to_spec(q)
    assert [o.is_correct for o in spec.options] == [True, False]
    # What is sent to Moodle keeps the original text, not the normalized one.
    assert spec.options[0].text == "القُدس  الشريف"


def test_map_multichoice_rejects_ambiguous_correct_answer() -> None:
    q = QuestionDraftPreview(
        question_id=uuid4(),
        question_type_code="MULTICHOICE",
        stem="سؤال",
        options=(
            AnswerOptionPreview(option_id="a", text="نعم"),
            AnswerOptionPreview(option_id="b", text="نَعَم"),
        ),
        correct_answer_preview="نعم",
        rationale=None,
        points=Decimal("1"),
        source_refs=(),
        unsupported=False,
        unsupported_reason=None,
    )
    with pytest.raises(UnsupportedQuestionForPublish, match="several"):
        map_question_draft_to_spec(q)


def test_map_shortanswer_requires_answer() -> None:
    q = QuestionDraftPreview(
        question_id=uuid4(),
        question_type_code="SHORTANSWER",
        stem="اذكر العاصمة",
        options=(),
        correct_answer_preview=None,
        rationale=None,
        points=Decimal("1"),
        source_refs=(),
        unsupported=False,
        unsupported_reason=None,
    )
    with pytest.raises(UnsupportedQuestionForPublish):
        map_question_draft_to_spec(q)
