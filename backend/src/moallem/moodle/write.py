"""Moodle write operations (Phase B) — DTOs, protocol, and pure mapping.

No network side effects live here by default. Concrete adapters that call Moodle
must be explicitly injected and are gated on Staging evidence (A1) + DEC-027.

See: docs/phase_b/MOODLE_WRITE_ADAPTER_DESIGN.md
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from moallem.moodle.client import MoodleClient
from moallem.moodle.errors import MoodleUnavailable

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuestionOptionSpec:
    text: str
    is_correct: bool
    fraction: Decimal  # 0..1 for multichoice; ignored for truefalse/shortanswer


@dataclass(frozen=True, slots=True)
class QuestionCreateSpec:
    """One question ready for Moodle. Produced only from trusted internal drafts."""

    question_type: str  # "multichoice" | "truefalse" | "shortanswer"
    name: str
    text: str
    default_mark: Decimal
    options: tuple[QuestionOptionSpec, ...] = ()
    correct_answer: str | None = None
    general_feedback: str | None = None

    def __post_init__(self) -> None:
        if self.question_type not in {"multichoice", "truefalse", "shortanswer"}:
            raise ValueError(f"unsupported question_type for MVP: {self.question_type}")
        if not self.name.strip() or not self.text.strip():
            raise ValueError("question name and text must be non-empty")
        if self.default_mark < 0:
            raise ValueError("default_mark must be >= 0")


@dataclass(frozen=True, slots=True)
class QuizCreateRequest:
    """Server-derived create request. Destination never comes from the client."""

    course_id: str
    name: str
    intro: str
    external_operation_key: str
    section_id: int | None = None
    time_open: datetime | None = None
    time_close: datetime | None = None

    def __post_init__(self) -> None:
        if not self.course_id.strip():
            raise ValueError("course_id is required")
        if not self.name.strip():
            raise ValueError("quiz name is required")
        if not self.external_operation_key.strip():
            raise ValueError("external_operation_key is required for idempotency")


@dataclass(frozen=True, slots=True)
class QuizCreateResult:
    """Immediate result from the create call. Treat as untrusted until verified."""

    moodle_quiz_id: int
    moodle_cmid: int | None
    raw_reference: str = ""


@dataclass(frozen=True, slots=True)
class QuizVerification:
    """Read-back proof. Publish is only COMPLETED when verification passes."""

    moodle_quiz_id: int
    name_matches: bool
    question_count: int
    course_id_matches: bool
    verified_at: datetime

    @property
    def is_verified(self) -> bool:
        return (
            self.name_matches
            and self.course_id_matches
            and self.question_count >= 0  # exact expected count checked by caller
        )


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class MoodleWriteAdapter(Protocol):
    """Side-effecting adapter. Only concrete implementations talk to Moodle."""

    def create_quiz(
        self,
        client: MoodleClient,
        request: QuizCreateRequest,
        questions: Sequence[QuestionCreateSpec],
    ) -> QuizCreateResult:
        """Create quiz + questions. Prefer idempotent behaviour on external_operation_key."""
        ...

    def verify_quiz(
        self,
        client: MoodleClient,
        *,
        course_id: str,
        moodle_quiz_id: int,
        expected_name: str,
        expected_question_count: int,
    ) -> QuizVerification:
        """Read-back. Must not trust the create response alone."""
        ...


class DenyAllWriteAdapter:
    """Production-safe default: no Moodle write is ever performed."""

    def create_quiz(
        self,
        client: MoodleClient,
        request: QuizCreateRequest,
        questions: Sequence[QuestionCreateSpec],
    ) -> QuizCreateResult:
        del client, request, questions
        raise MoodleUnavailable("Moodle write adapter is not enabled")

    def verify_quiz(
        self,
        client: MoodleClient,
        *,
        course_id: str,
        moodle_quiz_id: int,
        expected_name: str,
        expected_question_count: int,
    ) -> QuizVerification:
        del client, course_id, moodle_quiz_id, expected_name, expected_question_count
        raise MoodleUnavailable("Moodle write adapter is not enabled")


# ---------------------------------------------------------------------------
# MVP question mapping (pure)
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES = frozenset({"multichoice", "truefalse", "shortanswer"})


def map_internal_type(question_type_code: str) -> str | None:
    """Map internal/draft type code to Moodle qtype. Returns None if unsupported."""
    code = question_type_code.strip().lower()
    # Accept both short codes and common aliases
    aliases = {
        "multichoice": "multichoice",
        "multiple_choice": "multichoice",
        "mcq": "multichoice",
        "truefalse": "truefalse",
        "true_false": "truefalse",
        "tf": "truefalse",
        "shortanswer": "shortanswer",
        "short_answer": "shortanswer",
        "sa": "shortanswer",
    }
    return aliases.get(code)


def assert_mvp_supported(question_type: str) -> None:
    if question_type not in _SUPPORTED_TYPES:
        raise ValueError(f"question type not supported in MVP write path: {question_type}")
