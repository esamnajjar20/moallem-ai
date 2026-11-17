from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from moallem.ai.quiz import (
    EducationalScope,
    QualityDecision,
    QualityRubric,
    QualityRubricRegistry,
    QuizDraftCommand,
    QuizDraftGenerationService,
    QuizQualityValidator,
    QuizSpec,
    RubricStatus,
)
from tests.ai.quiz.conftest import FakeGateway, make_output


def make_command(
    context_bundle, *, count: int = 1, maximum_grade: Decimal | None = None
) -> QuizDraftCommand:
    return QuizDraftCommand(
        spec=QuizSpec(
            name="اختبار القمر",
            question_count=count,
            question_types=("SINGLE_CHOICE",),
            maximum_grade=maximum_grade,
            language="ar",
            instructions="",
        ),
        tenant_id=context_bundle.tenant_id,
        task_id=UUID("00000000-0000-0000-0000-000000000302"),
        actor_membership_id=UUID("00000000-0000-0000-0000-000000000402"),
        course_id=context_bundle.course_id,
        invocation_id=UUID("00000000-0000-0000-0000-000000000502"),
        context=context_bundle,
        educational_scope=EducationalScope(
            grade_level="الصف السابع",
            subject="العلوم",
            learning_objectives=("تفسير حركة القمر حول الأرض",),
        ),
        max_output_tokens=1_000,
    )


async def generate_draft(
    context_bundle,
    question_registry,
    source_chunk,
    *,
    count=1,
    stems=None,
    quote=None,
    unsupported=False,
    reason=None,
    maximum_grade=None,
):
    output = make_output(
        source_chunk.chunk_id,
        stems=stems or ("What orbits Earth?",),
        quote=quote or "The Moon orbits Earth.",
        unsupported=unsupported,
        unsupported_reason=reason,
    )
    service = QuizDraftGenerationService(
        gateway=FakeGateway(output),
        question_types=question_registry,
        clock=lambda: datetime(2026, 11, 17, tzinfo=UTC),
    )
    return await service.generate(
        make_command(context_bundle, count=count, maximum_grade=maximum_grade)
    )


@pytest.mark.asyncio
async def test_clean_structure_is_only_pass_with_warnings_until_human_review(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(context_bundle, question_registry, source_chunk)
    validator = QuizQualityValidator(
        question_types=question_registry,
        clock=lambda: datetime(2026, 11, 17, tzinfo=UTC),
    )

    report = validator.validate(draft, context_bundle, rubric_version="education-rubric-unset")

    assert report.decision is QualityDecision.PASS_WITH_WARNINGS
    assert not report.hard_failures
    warning_codes = {issue.code for issue in report.warnings}
    assert "EDUCATIONAL_RUBRIC_NOT_CONFIGURED" in warning_codes
    assert "HUMAN_REVIEW_REQUIRED" in warning_codes
    assert "FACTUAL_ACCURACY_REQUIRES_HUMAN_REVIEW" in warning_codes
    assert report.can_preview is True
    assert report.human_review_required is True
    assert report.publish_allowed is False


@pytest.mark.asyncio
async def test_quality_blocks_unverifiable_quote(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(
        context_bundle, question_registry, source_chunk, quote="A quotation not in the course"
    )
    report = QuizQualityValidator(question_types=question_registry).validate(
        draft, context_bundle, rubric_version="structural-v1"
    )

    assert report.decision is QualityDecision.BLOCKED
    assert "QUESTION_SOURCE_QUOTE_NOT_FOUND" in {issue.code for issue in report.hard_failures}
    assert report.publish_allowed is False


@pytest.mark.asyncio
async def test_quality_blocks_exact_duplicate_stems(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(
        context_bundle,
        question_registry,
        source_chunk,
        count=2,
        stems=("What orbits Earth?", "WHAT  ORBITS EARTH?"),
    )
    report = QuizQualityValidator(question_types=question_registry).validate(
        draft, context_bundle, rubric_version="structural-v1"
    )

    assert report.decision is QualityDecision.BLOCKED
    assert "DUPLICATE_QUESTION_STEM" in {issue.code for issue in report.hard_failures}


@pytest.mark.asyncio
async def test_explicit_unsupported_item_is_warned_not_silently_asserted(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(
        context_bundle,
        question_registry,
        source_chunk,
        unsupported=True,
        reason="The supplied course sources do not support this question.",
    )
    report = QuizQualityValidator(question_types=question_registry).validate(
        draft, context_bundle, rubric_version="structural-v1"
    )

    assert report.decision is QualityDecision.PASS_WITH_WARNINGS
    assert "QUESTION_UNSUPPORTED_BY_SOURCE" in {issue.code for issue in report.warnings}
    assert draft.questions[0].preview.unsupported is True
    assert draft.questions[0].preview.unsupported_reason == (
        "The supplied course sources do not support this question."
    )


@pytest.mark.asyncio
async def test_quality_blocks_total_points_above_spec_limit(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(
        context_bundle,
        question_registry,
        source_chunk,
        maximum_grade=Decimal("0.5"),
    )
    report = QuizQualityValidator(question_types=question_registry).validate(
        draft, context_bundle, rubric_version="structural-v1"
    )

    assert report.decision is QualityDecision.BLOCKED
    assert "TOTAL_POINTS_EXCEED_MAXIMUM_GRADE" in {issue.code for issue in report.hard_failures}


@pytest.mark.asyncio
async def test_approved_rubric_does_not_replace_human_review(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(context_bundle, question_registry, source_chunk)
    validator = QuizQualityValidator(
        question_types=question_registry,
        rubrics=QualityRubricRegistry((QualityRubric("rubric-v1", RubricStatus.APPROVED),)),
    )
    report = validator.validate(draft, context_bundle, rubric_version="rubric-v1")

    assert report.decision is QualityDecision.PASS_WITH_WARNINGS
    assert report.human_review_required is True
    assert "EDUCATIONAL_RUBRIC_NOT_CONFIGURED" not in {issue.code for issue in report.warnings}


def test_context_scope_mismatch_is_not_validated(
    context_bundle, question_registry, source_chunk
) -> None:
    import asyncio

    draft = asyncio.run(
        generate_draft(context_bundle, question_registry, source_chunk)
    )
    from moallem.files.context import ContextBundle

    wrong_scope = ContextBundle(
        tenant_id=UUID("00000000-0000-0000-0000-000000000999"),
        course_id=context_bundle.course_id,
        chunks=context_bundle.chunks,
        total_characters=context_bundle.total_characters,
    )
    with pytest.raises(ValueError):
        QuizQualityValidator(question_types=question_registry).validate(
            draft, wrong_scope, rubric_version="rubric-v1"
        )



@pytest.mark.asyncio
async def test_quality_blocks_changed_source_content(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(context_bundle, question_registry, source_chunk)
    changed_content = source_chunk.content + " A changed sentence."
    changed_chunk = replace(
        source_chunk,
        content=changed_content,
        content_hash=hashlib.sha256(changed_content.encode("utf-8")).hexdigest(),
    )
    changed_context = type(context_bundle)(
        tenant_id=context_bundle.tenant_id,
        course_id=context_bundle.course_id,
        chunks=(changed_chunk,),
        total_characters=len(changed_content),
    )

    report = QuizQualityValidator(question_types=question_registry).validate(
        draft, changed_context, rubric_version="structural-v1"
    )

    assert report.decision is QualityDecision.BLOCKED
    assert "SOURCE_CONTEXT_CHANGED" in {issue.code for issue in report.hard_failures}



@pytest.mark.asyncio
async def test_quality_blocks_tampered_source_citation_metadata(
    context_bundle, question_registry, source_chunk
) -> None:
    draft = await generate_draft(context_bundle, question_registry, source_chunk)
    changed_citation = replace(draft.source_citations[0], page_number=99)
    tampered_draft = replace(draft, source_citations=(changed_citation,))

    report = QuizQualityValidator(question_types=question_registry).validate(
        tampered_draft, context_bundle, rubric_version="structural-v1"
    )

    assert report.decision is QualityDecision.BLOCKED
    assert "DRAFT_SOURCE_CITATION_METADATA_MISMATCH" in {
        issue.code for issue in report.hard_failures
    }
