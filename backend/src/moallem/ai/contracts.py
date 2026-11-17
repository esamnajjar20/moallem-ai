"""Typed, provider-neutral request, response, pricing, and approval contracts.

Prompt and completion content are deliberately excluded from the durable usage ledger.
Only hashes, model metadata, token counts, and cost are persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from uuid import UUID

from moallem.domain.canonical import canonical_hash


class AIMessageRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"


_MAX_LEDGER_AMOUNT = Decimal("999999999999.999999999999")
_LEDGER_QUANTUM = Decimal("0.000000000001")
_MAX_BIGINT = 2**63 - 1
_MAX_SOURCE_REFS = 256


@dataclass(frozen=True, slots=True)
class AIMessage:
    role: AIMessageRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, AIMessageRole):
            raise ValueError("AI message role must be an explicit AIMessageRole")
        if not self.content.strip():
            raise ValueError("AI message content must not be empty")


@dataclass(frozen=True, slots=True)
class AIRequest:
    tenant_id: UUID
    task_id: UUID
    actor_membership_id: UUID
    course_id: str
    invocation_id: UUID
    prompt_version: str
    messages: tuple[AIMessage, ...]
    max_output_tokens: int
    data_classes: frozenset[str]
    source_refs: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not self.prompt_version.strip() or len(self.prompt_version) > 128:
            raise ValueError("prompt_version must be 1..128 characters")
        if not self.course_id or len(self.course_id) > 128:
            raise ValueError("course_id must be 1..128 characters")
        if not self.messages:
            raise ValueError("at least one AI message is required")
        if not 1 <= self.max_output_tokens <= _MAX_BIGINT:
            raise ValueError("max_output_tokens must be within PostgreSQL BIGINT range")
        if not self.data_classes or any(
            not value.strip() or len(value) > 64 or not value.isascii()
            for value in self.data_classes
        ):
            raise ValueError("data_classes must be explicit non-empty ASCII labels up to 64 chars")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("source_refs must not contain duplicates")
        if len(self.source_refs) > _MAX_SOURCE_REFS:
            raise ValueError(f"source_refs must not exceed {_MAX_SOURCE_REFS} entries")

    @property
    def request_hash(self) -> str:
        return canonical_hash(
            {
                "tenant_id": str(self.tenant_id),
                "task_id": str(self.task_id),
                "actor_membership_id": str(self.actor_membership_id),
                "course_id": self.course_id,
                "prompt_version": self.prompt_version,
                "max_output_tokens": self.max_output_tokens,
                "data_classes": sorted(self.data_classes),
                "source_refs": [str(source_ref) for source_ref in self.source_refs],
                "messages": [
                    {"role": message.role.value, "content": message.content}
                    for message in self.messages
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider_id: str
    model_id: str
    model_version: str
    region: str

    def __post_init__(self) -> None:
        limits = {
            "provider_id": 128,
            "model_id": 255,
            "model_version": 128,
            "region": 64,
        }
        for name, value in (
            ("provider_id", self.provider_id),
            ("model_id", self.model_id),
            ("model_version", self.model_version),
            ("region", self.region),
        ):
            if not value or not value.strip() or len(value) > limits[name]:
                raise ValueError(f"{name} must be 1..{limits[name]} characters")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if not (0 <= self.input_tokens <= _MAX_BIGINT) or not (
            0 <= self.output_tokens <= _MAX_BIGINT
        ):
            raise ValueError("token counts must be within PostgreSQL BIGINT range")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class AIProviderResponse:
    identity: ProviderIdentity
    output_text: str
    usage: TokenUsage
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.output_text.strip():
            raise ValueError("provider output must not be empty")


@dataclass(frozen=True, slots=True)
class ModelPricing:
    provider_id: str
    model_id: str
    model_version: str
    region: str
    pricing_version: str
    currency: str
    input_cost_per_million_tokens: Decimal
    output_cost_per_million_tokens: Decimal

    def __post_init__(self) -> None:
        limits = {
            "provider_id": 128,
            "model_id": 255,
            "model_version": 128,
            "region": 64,
            "pricing_version": 128,
        }
        for name, value in (
            ("provider_id", self.provider_id),
            ("model_id", self.model_id),
            ("model_version", self.model_version),
            ("region", self.region),
            ("pricing_version", self.pricing_version),
        ):
            if not value or not value.strip() or len(value) > limits[name]:
                raise ValueError(f"{name} must be 1..{limits[name]} characters")
        if (
            len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise ValueError("currency must be a 3-letter uppercase code")
        if (
            not self.input_cost_per_million_tokens.is_finite()
            or not self.output_cost_per_million_tokens.is_finite()
            or self.input_cost_per_million_tokens < 0
            or self.output_cost_per_million_tokens < 0
            or self.input_cost_per_million_tokens > _MAX_LEDGER_AMOUNT
            or self.output_cost_per_million_tokens > _MAX_LEDGER_AMOUNT
        ):
            raise ValueError("model prices must be finite, non-negative, and fit usage ledger")

    def calculate(self, usage: TokenUsage) -> Decimal:
        million = Decimal(1_000_000)
        amount = (
            Decimal(usage.input_tokens) * self.input_cost_per_million_tokens / million
            + Decimal(usage.output_tokens) * self.output_cost_per_million_tokens / million
        )
        if not amount.is_finite() or amount > _MAX_LEDGER_AMOUNT:
            raise ValueError("calculated AI cost does not fit usage ledger Numeric(24,12)")
        return amount.quantize(_LEDGER_QUANTUM, rounding=ROUND_HALF_UP)

    def matches(self, identity: ProviderIdentity) -> bool:
        return (
            self.provider_id == identity.provider_id
            and self.model_id == identity.model_id
            and self.model_version == identity.model_version
            and self.region == identity.region
        )


@dataclass(frozen=True, slots=True)
class AIExecutionPermit:
    """Server-issued proof that this exact call is approved and budget-reserved.

    This object is not accepted from model/tool input. A future authorization and budget
    service must issue it after resolving tenant, membership, provider, region and policy.
    """

    permit_ref: str
    tenant_id: UUID
    task_id: UUID
    course_id: str
    actor_membership_id: UUID
    provider: ProviderIdentity
    privacy_policy_ref: str
    budget_reservation_ref: str
    budget_reserved_amount: Decimal
    pricing: ModelPricing
    expires_at: datetime
    allowed_data_classes: frozenset[str]

    def validate_for(
        self,
        request: AIRequest,
        identity: ProviderIdentity,
        *,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("permit expiry must be timezone-aware")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("validation clock must be timezone-aware")
        if self.expires_at <= now:
            raise ValueError("AI execution permit expired")
        if (
            self.tenant_id != request.tenant_id
            or self.task_id != request.task_id
            or self.course_id != request.course_id
            or self.actor_membership_id != request.actor_membership_id
        ):
            raise ValueError("AI execution permit scope mismatch")
        if self.provider != identity or not self.pricing.matches(identity):
            raise ValueError("AI provider/model/region is not approved by this permit")
        if (
            not self.permit_ref.strip()
            or len(self.permit_ref) > 128
            or not self.privacy_policy_ref.strip()
            or len(self.privacy_policy_ref) > 128
        ):
            raise ValueError("AI privacy approval reference must be 1..128 characters")
        if (
            not self.budget_reservation_ref.strip()
            or len(self.budget_reservation_ref) > 128
            or not self.budget_reserved_amount.is_finite()
            or self.budget_reserved_amount <= 0
            or self.budget_reserved_amount > _MAX_LEDGER_AMOUNT
            or self.budget_reserved_amount.quantize(_LEDGER_QUANTUM)
            != self.budget_reserved_amount
        ):
            raise ValueError("a positive finite persisted budget reservation is required")
        if not request.data_classes.issubset(self.allowed_data_classes):
            raise ValueError("request contains data classes not approved for this provider")
