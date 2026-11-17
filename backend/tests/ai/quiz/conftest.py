from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import Field

from moallem.ai.contracts import AIProviderResponse, ProviderIdentity, TokenUsage
from moallem.ai.quiz import (
    AnswerOptionPreview,
    QuestionPreviewContent,
    QuestionTypeDefinition,
    QuestionTypeRegistry,
    StrictQuestionPayload,
)
from moallem.files.context import ContextBuilder, ContextBundle
from moallem.files.contracts import SourceChunk


IDENTITY = ProviderIdentity("provider-test", "model-test", "2026-01", "test-region")


class ChoiceOption(StrictQuestionPayload):
    option_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ChoicePayload(StrictQuestionPayload):
    stem: str = Field(min_length=1)
    options: list[ChoiceOption] = Field(min_length=2, max_length=5)
    correct_option_id: str
    rationale: str
    points: str


def choice_preview(payload: object) -> QuestionPreviewContent:
    choice = cast(ChoicePayload, payload)
    return QuestionPreviewContent(
        stem=choice.stem,
        options=tuple(
            AnswerOptionPreview(option_id=option.option_id, text=option.text)
            for option in choice.options
        ),
        correct_answer_preview=choice.correct_option_id,
        rationale=choice.rationale,
        points=Decimal(choice.points),
        difficulty="MEDIUM",
    )


@pytest.fixture
def source_chunk() -> SourceChunk:
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    file_id = UUID("00000000-0000-0000-0000-000000000101")
    content = "The Moon orbits Earth. The Moon is Earth's natural satellite."
    return SourceChunk(
        chunk_id=UUID("00000000-0000-0000-0000-000000000201"),
        tenant_id=tenant_id,
        course_id="course-1",
        file_id=file_id,
        file_version=1,
        chunk_index=0,
        page_number=2,
        section_path="Space / Moon",
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


@pytest.fixture
def context_bundle(source_chunk: SourceChunk) -> ContextBundle:
    return ContextBuilder().build(
        tenant_id=source_chunk.tenant_id,
        course_id=source_chunk.course_id,
        retrieved=(source_chunk,),
        max_chunks=10,
        max_characters=10_000,
    )


@pytest.fixture
def question_registry() -> QuestionTypeRegistry:
    return QuestionTypeRegistry(
        (
            QuestionTypeDefinition(
                code="SINGLE_CHOICE",
                schema_version="test-choice/1.0",
                payload_model=ChoicePayload,
                preview_adapter=choice_preview,
            ),
        )
    )


def make_output(
    source_ref: UUID,
    *,
    stems: tuple[str, ...] = ("What orbits Earth?",),
    quote: str = "The Moon orbits Earth.",
    unsupported: bool = False,
    unsupported_reason: str | None = None,
) -> str:
    questions = []
    for stem in stems:
        questions.append(
            {
                "question_type_code": "SINGLE_CHOICE",
                "content": {
                    "stem": stem,
                    "options": [
                        {"option_id": "A", "text": "The Moon"},
                        {"option_id": "B", "text": "Mars"},
                    ],
                    "correct_option_id": "A",
                    "rationale": "The source identifies the Moon as orbiting Earth.",
                    "points": "1",
                },
                "source_evidence": (
                    [] if unsupported else [{"source_ref": str(source_ref), "quote": quote}]
                ),
                "unsupported": unsupported,
                "unsupported_reason": unsupported_reason,
            }
        )
    return json.dumps({"questions": questions}, ensure_ascii=False)


class FakeGateway:
    def __init__(self, output: str | None = None) -> None:
        self.output = output or "{}"
        self.calls = 0
        self.requests = []

    async def generate(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append(request)
        return AIProviderResponse(
            identity=IDENTITY,
            output_text=self.output,
            usage=TokenUsage(input_tokens=120, output_tokens=60),
            provider_request_id="provider-request-1",
        )

