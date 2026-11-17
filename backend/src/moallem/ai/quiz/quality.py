"""Deterministic structural and provenance checks for quiz drafts.

This module intentionally does not claim to prove factual correctness, educational alignment,
fairness, or age appropriateness. Those require an approved rubric and independent human review.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid5

from moallem.ai.quiz.generation import QuizDraft
from moallem.ai.quiz.registry import (
    QuestionPayloadInvalid,
    QuestionTypeNotApproved,
    QuestionTypeRegistry,
)
from moallem.files.context import ContextBundle


class QualityDecision(StrEnum):
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


class RubricStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"


@dataclass(frozen=True, slots=True)
class QualityRubric:
    version: str
    status: RubricStatus

    def __post_init__(self) -> None:
        if not self.version or self.version != self.version.strip() or len(self.version) > 128:
            raise ValueError("rubric version must be non-empty trimmed text")


@dataclass(frozen=True, slots=True, init=False)
class QualityRubricRegistry:
    """Server-owned rubric registry. No educational rubric is active by default."""

    _rubrics: Mapping[str, QualityRubric]

    def __init__(self, rubrics: Iterable[QualityRubric] = ()) -> None:
        entries: dict[str, QualityRubric] = {}
        for rubric in rubrics:
            if rubric.version in entries:
                raise ValueError("rubric versions must be unique")
            entries[rubric.version] = rubric
        object.__setattr__(self, "_rubrics", MappingProxyType(entries))

    def get(self, version: str) -> QualityRubric | None:
        return self._rubrics.get(version)


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    question_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class QuizQualityReport:
    validation_id: UUID
    draft_id: UUID
    draft_hash: str
    rubric_version: str
    validator_version: str
    decision: QualityDecision
    hard_failures: tuple[QualityIssue, ...]
    warnings: tuple[QualityIssue, ...]
    validated_at: datetime

    @property
    def human_review_required(self) -> bool:
        return True

    @property
    def publish_allowed(self) -> bool:
        return False

    @property
    def can_preview(self) -> bool:
        return self.decision is not QualityDecision.BLOCKED


class QuizQualityValidator:
    VERSION = "quiz-quality-validator/1.0"

    def __init__(
        self,
        *,
        question_types: QuestionTypeRegistry,
        rubrics: QualityRubricRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._question_types = question_types
        self._rubrics = rubrics or QualityRubricRegistry()
        self._clock = clock or (lambda: datetime.now(UTC))

    def validate(
        self, draft: QuizDraft, context: ContextBundle, *, rubric_version: str
    ) -> QuizQualityReport:
        if context.tenant_id != draft.tenant_id or context.course_id != draft.course_id:
            raise ValueError("quality context must match draft tenant/course scope")
        if not rubric_version or rubric_version != rubric_version.strip():
            raise ValueError("rubric_version must be non-empty trimmed text")

        hard: list[QualityIssue] = []
        warnings: list[QualityIssue] = []
        source_by_id = {chunk.chunk_id: chunk for chunk in context.chunks}
        current_source_hashes = {chunk.chunk_id: chunk.content_hash for chunk in context.chunks}
        if len(source_by_id) != len(context.chunks):
            hard.append(QualityIssue("SOURCE_CONTEXT_DUPLICATE_CHUNK_ID"))
        actual_characters = 0
        for chunk in context.chunks:
            actual_characters += len(chunk.content)
            if chunk.tenant_id != draft.tenant_id or chunk.course_id != draft.course_id:
                hard.append(QualityIssue("SOURCE_CONTEXT_SCOPE_INVALID"))
            actual_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            if actual_hash != chunk.content_hash:
                hard.append(QualityIssue("SOURCE_CONTEXT_CONTENT_HASH_INVALID"))
        if (
            isinstance(context.total_characters, bool)
            or not isinstance(context.total_characters, int)
            or actual_characters != context.total_characters
        ):
            hard.append(QualityIssue("SOURCE_CONTEXT_CHARACTER_COUNT_INVALID"))
        saved_source_hashes = dict(draft.context_source_hashes)
        if current_source_hashes != saved_source_hashes:
            hard.append(QualityIssue("SOURCE_CONTEXT_CHANGED"))
        expected_citations = tuple(
            sorted(
                (
                    (
                        chunk.chunk_id,
                        chunk.file_id,
                        chunk.file_version,
                        chunk.content_hash,
                        chunk.page_number,
                        chunk.section_path,
                    )
                    for chunk in context.chunks
                ),
                key=lambda citation: str(citation[0]),
            )
        )
        saved_citations = tuple(
            (
                citation.source_ref,
                citation.file_id,
                citation.file_version,
                citation.content_hash,
                citation.page_number,
                citation.section_path,
            )
            for citation in draft.source_citations
        )
        if saved_citations != expected_citations:
            hard.append(QualityIssue("DRAFT_SOURCE_CITATION_METADATA_MISMATCH"))
        observed_stems: dict[str, UUID] = {}
        total_points = Decimal(0)

        if len(draft.questions) != draft.spec.question_count:
            hard.append(QualityIssue("QUESTION_COUNT_MISMATCH"))

        if not draft.educational_scope.has_core_scope:
            warnings.append(QualityIssue("EDUCATIONAL_SCOPE_INCOMPLETE"))

        rubric = self._rubrics.get(rubric_version)
        if rubric is None:
            warnings.append(QualityIssue("EDUCATIONAL_RUBRIC_NOT_CONFIGURED"))
        elif rubric.status is not RubricStatus.APPROVED:
            warnings.append(QualityIssue("EDUCATIONAL_RUBRIC_NOT_APPROVED"))

        for question in draft.questions:
            if question.question_type_code not in draft.spec.question_types:
                hard.append(QualityIssue("QUESTION_TYPE_NOT_ALLOWED", question.question_id))
            try:
                definition = self._question_types.get(question.question_type_code)
                if definition.schema_version != question.question_type_schema_version:
                    hard.append(
                        QualityIssue("QUESTION_TYPE_SCHEMA_VERSION_MISMATCH", question.question_id)
                    )
                payload = json.loads(question.payload_json)
                _parsed, preview_content = definition.validate(payload)
            except (QuestionTypeNotApproved, QuestionPayloadInvalid, ValueError, TypeError):
                hard.append(QualityIssue("QUESTION_TYPE_SCHEMA_INVALID", question.question_id))
                continue

            if (
                preview_content.stem != question.preview.stem
                or preview_content.options != question.preview.options
                or preview_content.correct_answer_preview != question.preview.correct_answer_preview
                or preview_content.rationale != question.preview.rationale
                or preview_content.points != question.preview.points
                or preview_content.difficulty != question.preview.difficulty
                or question.preview.question_id != question.question_id
                or question.preview.question_type_code != question.question_type_code
                or question.preview.unsupported != question.unsupported
                or question.preview.unsupported_reason != question.unsupported_reason
            ):
                hard.append(QualityIssue("QUESTION_PREVIEW_PAYLOAD_MISMATCH", question.question_id))
            total_points += preview_content.points

            if question.unsupported:
                if not question.unsupported_reason:
                    hard.append(QualityIssue("UNSUPPORTED_REASON_REQUIRED", question.question_id))
                else:
                    warnings.append(
                        QualityIssue("QUESTION_UNSUPPORTED_BY_SOURCE", question.question_id)
                    )
            elif question.unsupported_reason is not None:
                hard.append(QualityIssue("UNSUPPORTED_FLAG_CONFLICT", question.question_id))

            if not question.source_evidence and not question.unsupported:
                hard.append(QualityIssue("QUESTION_SOURCE_EVIDENCE_REQUIRED", question.question_id))

            evidence_refs = [source_ref for source_ref, _quote in question.source_evidence]
            evidence_pairs = list(question.source_evidence)
            if len(evidence_pairs) != len(set(evidence_pairs)):
                hard.append(
                    QualityIssue("QUESTION_SOURCE_EVIDENCE_DUPLICATED", question.question_id)
                )
            if tuple(sorted(set(evidence_refs), key=str)) != question.preview.source_refs:
                hard.append(
                    QualityIssue("QUESTION_PREVIEW_SOURCE_REFS_MISMATCH", question.question_id)
                )

            for source_ref, quote in question.source_evidence:
                chunk = source_by_id.get(source_ref)
                if chunk is None:
                    hard.append(QualityIssue("QUESTION_SOURCE_OUT_OF_SCOPE", question.question_id))
                    continue
                if not _contains_exact_normalized_quote(chunk.content, quote):
                    hard.append(
                        QualityIssue("QUESTION_SOURCE_QUOTE_NOT_FOUND", question.question_id)
                    )

            normalized_stem = _normalize_stem(question.preview.stem)
            if normalized_stem in observed_stems:
                hard.append(QualityIssue("DUPLICATE_QUESTION_STEM", question.question_id))
            else:
                observed_stems[normalized_stem] = question.question_id

        if draft.spec.maximum_grade is not None and total_points > draft.spec.maximum_grade:
            hard.append(QualityIssue("TOTAL_POINTS_EXCEED_MAXIMUM_GRADE"))

        # These criteria cannot be certified by the same model that generated the draft.
        warnings.extend(
            (
                QualityIssue("HUMAN_REVIEW_REQUIRED"),
                QualityIssue("FACTUAL_ACCURACY_REQUIRES_HUMAN_REVIEW"),
                QualityIssue("ANSWER_CORRECTNESS_REQUIRES_HUMAN_REVIEW"),
                QualityIssue("EDUCATIONAL_ALIGNMENT_REQUIRES_HUMAN_REVIEW"),
                QualityIssue("FAIRNESS_AND_AGE_APPROPRIATENESS_REQUIRE_HUMAN_REVIEW"),
            )
        )

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("quality validator clock must be timezone-aware")
        decision = QualityDecision.BLOCKED if hard else QualityDecision.PASS_WITH_WARNINGS
        return QuizQualityReport(
            validation_id=_stable_validation_id(draft.draft_id, rubric_version),
            draft_id=draft.draft_id,
            draft_hash=draft.content_hash,
            rubric_version=rubric_version,
            validator_version=self.VERSION,
            decision=decision,
            hard_failures=tuple(_dedupe_issues(hard)),
            warnings=tuple(_dedupe_issues(warnings)),
            validated_at=now.astimezone(UTC),
        )


def _contains_exact_normalized_quote(source: str, quote: str) -> bool:
    return _normalize_quote(quote) in _normalize_quote(source)


def _normalize_quote(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_stem(value: str) -> str:
    return _normalize_quote(value).casefold()


def _stable_validation_id(draft_id: UUID, rubric_version: str) -> UUID:
    return uuid5(draft_id, f"{QuizQualityValidator.VERSION}:{rubric_version}")


def _dedupe_issues(issues: Iterable[QualityIssue]) -> list[QualityIssue]:
    seen: set[tuple[str, UUID | None]] = set()
    result: list[QualityIssue] = []
    for issue in issues:
        key = (issue.code, issue.question_id)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


__all__ = [
    "QualityDecision",
    "QualityIssue",
    "QualityRubric",
    "QualityRubricRegistry",
    "RubricStatus",
    "QuizQualityReport",
    "QuizQualityValidator",
]
