"""Map internal quiz drafts to Moodle write specs (Phase B).

Pure functions only — no network, no I/O.
Unsupported question types are rejected before any Moodle call.
"""

from __future__ import annotations

from decimal import Decimal

from moallem.ai.quiz.contracts import QuestionDraftPreview, QuizDraftPreview
from moallem.moodle.write import (
    QuestionCreateSpec,
    QuestionOptionSpec,
    assert_mvp_supported,
    map_internal_type,
)


class UnsupportedQuestionForPublish(ValueError):
    """Raised when a draft question cannot be published in the MVP write path."""


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

    name = f"Q-{str(draft.question_id)[:8]}"
    options: tuple[QuestionOptionSpec, ...] = ()
    correct_answer = draft.correct_answer_preview

    if moodle_type == "multichoice":
        if len(draft.options) < 2:
            raise UnsupportedQuestionForPublish(
                f"multichoice question {draft.question_id} needs at least 2 options"
            )
        # If correct_answer_preview matches an option text, mark it correct; otherwise
        # treat a single explicit correct via fraction when only one option is intended.
        correct_texts = set()
        if correct_answer:
            correct_texts.add(correct_answer.strip())
        mapped: list[QuestionOptionSpec] = []
        for opt in draft.options:
            is_correct = opt.text.strip() in correct_texts if correct_texts else False
            fraction = Decimal("1") if is_correct else Decimal("0")
            mapped.append(
                QuestionOptionSpec(text=opt.text, is_correct=is_correct, fraction=fraction)
            )
        # If nothing was marked correct but we have options, fail closed rather than publish
        # a quiz with no correct answer.
        if correct_texts and not any(o.is_correct for o in mapped):
            raise UnsupportedQuestionForPublish(
                f"multichoice question {draft.question_id}: correct_answer_preview does not match any option"
            )
        if not correct_texts:
            raise UnsupportedQuestionForPublish(
                f"multichoice question {draft.question_id}: correct_answer_preview is required"
            )
        options = tuple(mapped)

    elif moodle_type == "truefalse":
        if not correct_answer or correct_answer.strip().lower() not in {"true", "false", "صح", "خطأ"}:
            raise UnsupportedQuestionForPublish(
                f"truefalse question {draft.question_id}: correct_answer must be true/false"
            )
        # Normalise to English true/false for Moodle
        normalised = correct_answer.strip().lower()
        if normalised in {"صح", "true"}:
            correct_answer = "true"
        else:
            correct_answer = "false"

    elif moodle_type == "shortanswer":
        if not correct_answer or not correct_answer.strip():
            raise UnsupportedQuestionForPublish(
                f"shortanswer question {draft.question_id}: correct_answer is required"
            )

    return QuestionCreateSpec(
        question_type=moodle_type,
        name=name,
        text=draft.stem,
        default_mark=draft.points if draft.points > 0 else Decimal("1"),
        options=options,
        correct_answer=correct_answer,
        general_feedback=draft.rationale,
    )


def map_quiz_draft_to_specs(draft: QuizDraftPreview) -> tuple[str, str, list[QuestionCreateSpec]]:
    """Return (quiz_name, quiz_intro, question specs) ready for MoodleWriteService.

    Rejects the whole publish if any question is unsupported (fail-closed).
    """
    specs: list[QuestionCreateSpec] = []
    for q in draft.questions:
        specs.append(map_question_draft_to_spec(q))
    intro = draft.instructions or ""
    return draft.title, intro, specs
