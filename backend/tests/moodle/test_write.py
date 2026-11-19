"""Unit tests for Moodle write DTOs, mapping, and DenyAll adapter."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from moallem.moodle.errors import MoodleUnavailable
from moallem.moodle.write import (
    DenyAllWriteAdapter,
    QuestionCreateSpec,
    QuestionOptionSpec,
    QuizCreateRequest,
    assert_mvp_supported,
    map_internal_type,
)


def test_map_internal_type_aliases() -> None:
    assert map_internal_type("multichoice") == "multichoice"
    assert map_internal_type("MCQ") == "multichoice"
    assert map_internal_type("true_false") == "truefalse"
    assert map_internal_type("shortanswer") == "shortanswer"
    assert map_internal_type("essay") is None


def test_assert_mvp_supported() -> None:
    assert_mvp_supported("multichoice")
    with pytest.raises(ValueError):
        assert_mvp_supported("essay")


def test_question_create_spec_rejects_unsupported_type() -> None:
    with pytest.raises(ValueError, match="unsupported question_type"):
        QuestionCreateSpec(
            question_type="essay",
            name="Q1",
            text="Explain...",
            default_mark=Decimal("1"),
        )


def test_question_create_spec_accepts_multichoice() -> None:
    q = QuestionCreateSpec(
        question_type="multichoice",
        name="Q1",
        text="Capital of France?",
        default_mark=Decimal("1"),
        options=(
            QuestionOptionSpec(text="Paris", is_correct=True, fraction=Decimal("1")),
            QuestionOptionSpec(text="London", is_correct=False, fraction=Decimal("0")),
        ),
    )
    assert q.question_type == "multichoice"
    assert len(q.options) == 2


def test_quiz_create_request_requires_operation_key() -> None:
    with pytest.raises(ValueError, match="external_operation_key"):
        QuizCreateRequest(
            course_id="12",
            name="Quiz 1",
            intro="",
            external_operation_key="  ",
        )


def test_deny_all_write_adapter_raises() -> None:
    adapter = DenyAllWriteAdapter()
    req = QuizCreateRequest(
        course_id="12",
        name="Quiz 1",
        intro="",
        external_operation_key="op-1",
    )
    with pytest.raises(MoodleUnavailable):
        adapter.create_quiz(None, req, [])  # type: ignore[arg-type]

    with pytest.raises(MoodleUnavailable):
        adapter.verify_quiz(
            None,  # type: ignore[arg-type]
            course_id="12",
            moodle_quiz_id=1,
            expected_name="Quiz 1",
            expected_question_count=0,
        )


def test_quiz_verification_is_verified_property() -> None:
    from moallem.moodle.write import QuizVerification

    ok = QuizVerification(
        moodle_quiz_id=99,
        name_matches=True,
        question_count=3,
        course_id_matches=True,
        verified_at=datetime.now(UTC),
    )
    assert ok.is_verified is True

    bad = QuizVerification(
        moodle_quiz_id=99,
        name_matches=False,
        question_count=3,
        course_id_matches=True,
        verified_at=datetime.now(UTC),
    )
    assert bad.is_verified is False


def _verification(**overrides: object):  # type: ignore[no-untyped-def]
    from moallem.moodle.write import QuizVerification

    base: dict[str, object] = {
        "moodle_quiz_id": 1,
        "name_matches": True,
        "question_count": 3,
        "course_id_matches": True,
        "verified_at": datetime.now(UTC),
    }
    base.update(overrides)
    return QuizVerification(**base)  # type: ignore[arg-type]


def test_verification_requires_exact_question_count() -> None:
    assert _verification().matches(3)
    assert not _verification().matches(4)


def test_unknown_question_count_never_verifies() -> None:
    from moallem.moodle.write import UNKNOWN_QUESTION_COUNT

    v = _verification(question_count=UNKNOWN_QUESTION_COUNT)
    assert not v.is_verified
    assert not v.matches(UNKNOWN_QUESTION_COUNT)


def test_verification_fails_on_name_or_course_mismatch() -> None:
    assert not _verification(name_matches=False).matches(3)
    assert not _verification(course_id_matches=False).matches(3)
