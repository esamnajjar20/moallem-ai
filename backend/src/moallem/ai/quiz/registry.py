"""Explicit allow-list of typed question payloads.

The registry starts empty. A question type becomes usable only when Product/Education approves
its schema and the application registers a strict payload model plus preview adapter.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from pydantic import BaseModel, ConfigDict, ValidationError

from moallem.ai.quiz.contracts import QuestionPreviewContent


_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class StrictQuestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class QuestionTypeNotApproved(ValueError):
    """Question type is not present in the server-owned allow-list."""


class QuestionPayloadInvalid(ValueError):
    """Model content does not satisfy the approved payload schema."""


PreviewAdapter = Callable[[BaseModel], QuestionPreviewContent]


@dataclass(frozen=True, slots=True)
class QuestionTypeDefinition:
    code: str
    schema_version: str
    payload_model: type[StrictQuestionPayload]
    preview_adapter: PreviewAdapter

    def __post_init__(self) -> None:
        if not _CODE.fullmatch(self.code):
            raise ValueError("question type code must be uppercase and stable")
        if not self.schema_version or self.schema_version != self.schema_version.strip():
            raise ValueError("question type schema version must be non-empty and trimmed")
        if len(self.schema_version) > 128:
            raise ValueError("question type schema version is too long")
        if not isinstance(self.payload_model, type) or not issubclass(
            self.payload_model, StrictQuestionPayload
        ):
            raise ValueError("payload model must extend StrictQuestionPayload")
        config = self.payload_model.model_config
        if config.get("extra") != "forbid" or config.get("strict") is not True:
            raise ValueError("question payload schemas must be strict and forbid extra fields")

    def json_schema(self) -> dict[str, object]:
        schema = self.payload_model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        return cast(dict[str, object], schema)

    def validate(self, payload: Mapping[str, object]) -> tuple[BaseModel, QuestionPreviewContent]:
        try:
            parsed = self.payload_model.model_validate(dict(payload), strict=True)
        except ValidationError:
            raise QuestionPayloadInvalid("question payload failed its registered schema") from None
        try:
            preview = self.preview_adapter(parsed)
        except Exception:
            raise QuestionPayloadInvalid("question preview adapter failed") from None
        if not isinstance(preview, QuestionPreviewContent):
            raise QuestionPayloadInvalid("question preview adapter returned an invalid DTO")
        return parsed, preview


@dataclass(frozen=True, slots=True, init=False)
class QuestionTypeRegistry:
    """Immutable registry; caller/model input cannot add or override question types."""

    _definitions: Mapping[str, QuestionTypeDefinition]

    def __init__(self, definitions: Iterable[QuestionTypeDefinition] = ()) -> None:
        entries: dict[str, QuestionTypeDefinition] = {}
        for definition in definitions:
            if definition.code in entries:
                raise ValueError("question type codes must be unique")
            entries[definition.code] = definition
        object.__setattr__(self, "_definitions", MappingProxyType(entries))

    def get(self, code: str) -> QuestionTypeDefinition:
        definition = self._definitions.get(code)
        if definition is None:
            raise QuestionTypeNotApproved("question type is not approved/configured")
        return definition

    def require(self, codes: Iterable[str]) -> tuple[QuestionTypeDefinition, ...]:
        definitions: list[QuestionTypeDefinition] = []
        for code in codes:
            definitions.append(self.get(code))
        return tuple(definitions)

    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


__all__ = [
    "QuestionPayloadInvalid",
    "QuestionTypeDefinition",
    "QuestionTypeNotApproved",
    "QuestionTypeRegistry",
    "StrictQuestionPayload",
]
