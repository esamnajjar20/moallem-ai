"""Provisional typed quiz-draft contracts aligned with the v2.4 OpenAPI draft.

Question-type payloads are deliberately not hard-coded here. DEC-033 owns the approved
question-type set and each type's discriminated payload schema.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_QUESTION_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
Difficulty = Literal["EASY", "MEDIUM", "HARD"]


class StrictQuizModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class QuizSpec(StrictQuizModel):
    """Transport-facing request shape; still PROPOSED until DEC-033 is approved."""

    name: Annotated[str, Field(min_length=1, max_length=255)]
    question_count: Annotated[int, Field(ge=1, le=100)]
    question_types: Annotated[
        tuple[Annotated[str, Field(pattern=_QUESTION_TYPE_RE.pattern)], ...],
        Field(min_length=1, max_length=10),
    ]
    duration_seconds: Annotated[int, Field(ge=0, le=86_400)] | None = None
    maximum_grade: Annotated[Decimal, Field(gt=0)] | None = None
    language: str = "ar"
    instructions: Annotated[str, Field(max_length=4_000)] | None = None

    @field_validator("name", "language")
    @classmethod
    def _trimmed_required(cls, value: str) -> str:
        if not value or value != value.strip() or "\x00" in value:
            raise ValueError("value must be non-empty trimmed text without NUL bytes")
        return value

    @field_validator("question_types")
    @classmethod
    def _question_type_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("question_types must be unique")
        if any(not _QUESTION_TYPE_RE.fullmatch(code) for code in value):
            raise ValueError("question type codes must use the documented uppercase format")
        return value

    @field_validator("language")
    @classmethod
    def _language_format(cls, value: str) -> str:
        if not _LANGUAGE_RE.fullmatch(value):
            raise ValueError("language must use the supported locale format, e.g. ar or ar-PS")
        return value

    @field_validator("instructions")
    @classmethod
    def _instructions_text(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("instructions must not contain NUL bytes")
        return value


class EducationalScope(StrictQuizModel):
    """Teacher-supplied scope hints; no grade/subject taxonomy is assumed or approved."""

    grade_level: Annotated[str, Field(max_length=128)] | None = None
    subject: Annotated[str, Field(max_length=128)] | None = None
    curriculum: Annotated[str, Field(max_length=255)] | None = None
    learning_objectives: Annotated[tuple[str, ...], Field(max_length=40)] = ()

    @field_validator("grade_level", "subject", "curriculum")
    @classmethod
    def _optional_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip() or "\x00" in value):
            raise ValueError("scope values must be non-empty trimmed text")
        return value

    @field_validator("learning_objectives")
    @classmethod
    def _objectives(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item != item.strip() or len(item) > 1_000 for item in value):
            raise ValueError("learning objectives must be non-empty trimmed text")
        if len(set(value)) != len(value):
            raise ValueError("learning objectives must be unique")
        return value

    @property
    def has_core_scope(self) -> bool:
        return bool(self.grade_level and self.subject and self.learning_objectives)


class AnswerOptionPreview(StrictQuizModel):
    option_id: Annotated[str, Field(min_length=1, max_length=128)]
    text: Annotated[str, Field(min_length=1, max_length=4_000)]

    @field_validator("option_id", "text")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("answer option values must be trimmed printable text")
        return value


class QuestionPreviewContent(StrictQuizModel):
    """Type-specific adapter output projected into the common teacher preview DTO."""

    stem: Annotated[str, Field(min_length=1, max_length=10_000)]
    options: Annotated[tuple[AnswerOptionPreview, ...], Field(max_length=100)] = ()
    correct_answer_preview: Annotated[str, Field(max_length=4_000)] | None = None
    rationale: Annotated[str, Field(max_length=4_000)] | None = None
    points: Annotated[Decimal, Field(ge=0)]
    difficulty: Difficulty | None = None

    @field_validator("stem", "correct_answer_preview", "rationale")
    @classmethod
    def _optional_trimmed_text(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or "\x00" in value):
            raise ValueError("preview text must be trimmed and contain no NUL bytes")
        return value

    @model_validator(mode="after")
    def _unique_option_ids(self) -> QuestionPreviewContent:
        ids = [option.option_id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option IDs must be unique")
        return self


class QuestionDraftPreview(StrictQuizModel):
    question_id: UUID
    question_type_code: Annotated[str, Field(pattern=_QUESTION_TYPE_RE.pattern)]
    stem: Annotated[str, Field(min_length=1, max_length=10_000)]
    options: tuple[AnswerOptionPreview, ...] = ()
    correct_answer_preview: Annotated[str, Field(max_length=4_000)] | None = None
    rationale: Annotated[str, Field(max_length=4_000)] | None = None
    points: Annotated[Decimal, Field(ge=0)]
    source_refs: tuple[UUID, ...]
    unsupported: bool
    unsupported_reason: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    difficulty: Difficulty | None = None

    @field_validator("stem", "correct_answer_preview", "rationale", "unsupported_reason")
    @classmethod
    def _trimmed_text(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or "\x00" in value):
            raise ValueError("question preview text must be trimmed and contain no NUL bytes")
        return value

    @model_validator(mode="after")
    def _unsupported_reason_consistency(self) -> QuestionDraftPreview:
        if self.unsupported and not self.unsupported_reason:
            raise ValueError("unsupported questions must include unsupported_reason")
        if not self.unsupported and self.unsupported_reason is not None:
            raise ValueError("supported questions cannot include unsupported_reason")
        return self


class QuizDraftPreview(StrictQuizModel):
    title: Annotated[str, Field(min_length=1, max_length=255)]
    instructions: Annotated[str, Field(max_length=4_000)] | None = None
    questions: Annotated[tuple[QuestionDraftPreview, ...], Field(min_length=1, max_length=100)]
    schema_version: Annotated[str, Field(min_length=1, max_length=128)]
    total_points: Annotated[Decimal, Field(ge=0)]

    @field_validator("title", "schema_version")
    @classmethod
    def _required_trimmed(cls, value: str) -> str:
        if not value or value != value.strip() or "\x00" in value:
            raise ValueError("quiz preview values must be non-empty trimmed text")
        return value

    @field_validator("instructions")
    @classmethod
    def _instructions_text(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("quiz instructions must not contain NUL bytes")
        return value


class GeneratedSourceEvidence(StrictQuizModel):
    source_ref: UUID
    quote: Annotated[str, Field(min_length=1, max_length=2_000)]

    @field_validator("quote")
    @classmethod
    def _quote_text(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("source quote must be trimmed text without NUL bytes")
        return value


class GeneratedQuestion(StrictQuizModel):
    question_type_code: Annotated[str, Field(pattern=_QUESTION_TYPE_RE.pattern)]
    content: dict[str, object]
    source_evidence: Annotated[list[GeneratedSourceEvidence], Field(max_length=32)] = Field(
        default_factory=list
    )
    # Require the model to make an explicit evidence-support decision for every question.
    unsupported: bool
    unsupported_reason: Annotated[str, Field(max_length=1_000)] | None = None

    @field_validator("unsupported_reason")
    @classmethod
    def _unsupported_reason_text(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip() or "\x00" in value):
            raise ValueError("unsupported_reason must be non-empty trimmed text")
        return value

    @model_validator(mode="after")
    def _unsupported_reason_required(self) -> GeneratedQuestion:
        if self.unsupported and not self.unsupported_reason:
            raise ValueError("unsupported_reason is required when unsupported is true")
        if not self.unsupported and self.unsupported_reason is not None:
            raise ValueError("unsupported_reason is only valid when unsupported is true")
        return self


class GeneratedQuizOutput(StrictQuizModel):
    """The exact JSON envelope accepted from the model; additional keys are rejected."""

    questions: Annotated[list[GeneratedQuestion], Field(min_length=1, max_length=100)]


__all__ = [
    "AnswerOptionPreview",
    "EducationalScope",
    "GeneratedQuizOutput",
    "GeneratedSourceEvidence",
    "QuestionDraftPreview",
    "QuestionPreviewContent",
    "QuizDraftPreview",
    "QuizSpec",
    "StrictQuizModel",
]
