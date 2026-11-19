"""Map internal quiz drafts to Moodle write specs (Phase B).

Pure functions only: no network, no I/O.
Unsupported or ambiguous questions are rejected before any Moodle call (fail-closed).
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from moallem.ai.quiz.contracts import QuestionDraftPreview, QuizDraftPreview
from moallem.moodle.write import (
    QuestionCreateSpec,
    QuestionOptionSpec,
    assert_mvp_supported,
    map_internal_type,
)

_ARABIC_MARKS = re.compile("[\u0640\u064b-\u065f\u0670]")  # tatweel + harakat
_SPACES = re.compile(r"\s+")
_TRUE = frozenset({"true", "صح", "صحيح"})
_FALSE = frozenset({"false", "خطأ", "خطا", "خاطئ"})


class UnsupportedQuestionForPublish(ValueError):
    """Raised when a draft question cannot be published in the MVP write path."""


def normalize_answer_text(value: str) -> str:
    """Normalize for comparison only (never for what is sent to Moodle)."""
    text = unicodedata.normalize("NFKC", value)
    text = _ARABIC_MARKS.sub("", text)
    return _SPACES.sub(" ", text).strip().casefold()


def _map_multichoice(draft: QuestionDraftPreview) -> tuple[tuple[QuestionOptionSpec, ...], str]:
    qid = draft.question_id
    if len(draft.options) < 2:
        raise UnsupportedQuestionForPublish(f"multichoice {qid} needs at least 2 options")
    answer = (draft.correct_answer_preview or "").strip()
    if not answer:
        raise UnsupportedQuestionForPublish(f"multichoice {qid}: correct answer is required")

    # 1) exact option_id match wins; 2) otherwise a normalized text match.
    matches = [i for i, o in enumerate(draft.options) if o.option_id == answer]
    if not matches:
        wanted = normalize_answer_text(answer)
        matches = [
            i for i, o in enumerate(draft.options) if normalize_answer_text(o.text) == wanted
        ]
    if len(matches) != 1:
        reason = "matches no option" if not matches else "matches several options"
        raise UnsupportedQuestionForPublish(f"multichoice {qid}: correct answer {reason}")

    options = tuple(
        QuestionOptionSpec(
            text=o.text,
            is_correct=i == matches[0],
            fraction=Decimal(1) if i == matches[0] else Decimal(0),
        )
        for i, o in enumerate(draft.options)
    )
    return options, draft.options[matches[0]].text


def map_question_draft_to_spec(draft: QuestionDraftPreview) -> QuestionCreateSpec:
    """Convert one QuestionDraftPreview into a Moodle-oriented QuestionCreateSpec."""
    if draft.unsupported:
        reason = draft.unsupported_reason or "marked unsupported"
        raise UnsupportedQuestionForPublish(
            f"question {draft.question_id} is unsupported: {reason}"
        )

    moodle_type = map_internal_type(draft.question_type_code)
    if moodle_type is None:
        raise UnsupportedQuestionForPublish(
            f"question type not supported for publish: {draft.question_type_code}"
        )
    assert_mvp_supported(moodle_type)

    options: tuple[QuestionOptionSpec, ...] = ()
    correct_answer = draft.correct_answer_preview

    if moodle_type == "multichoice":
        options, correct_answer = _map_multichoice(draft)
    elif moodle_type == "truefalse":
        normalized = normalize_answer_text(correct_answer or "")
        if normalized in _TRUE:
            correct_answer = "true"
        elif normalized in _FALSE:
            correct_answer = "false"
        else:
            raise UnsupportedQuestionForPublish(
                f"truefalse question {draft.question_id}: correct answer must be true/false"
            )
    elif not correct_answer or not correct_answer.strip():
        raise UnsupportedQuestionForPublish(
            f"shortanswer question {draft.question_id}: correct answer is required"
        )

    return QuestionCreateSpec(
        question_type=moodle_type,
        name=f"Q-{str(draft.question_id)[:8]}",
        text=draft.stem,
        default_mark=draft.points if draft.points > 0 else Decimal(1),
        options=options,
        correct_answer=correct_answer,
        general_feedback=draft.rationale,
    )


def map_quiz_draft_to_specs(draft: QuizDraftPreview) -> tuple[str, str, list[QuestionCreateSpec]]:
    """Return (quiz_name, quiz_intro, question specs) ready for MoodleWriteService.

    Rejects the whole publish if any question is unsupported (fail-closed).
    """
    specs = [map_question_draft_to_spec(q) for q in draft.questions]
    return draft.title, draft.instructions or "", specs
