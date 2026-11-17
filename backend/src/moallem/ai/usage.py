"""Durable AI usage ledger value objects and repository contract."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from moallem.ai.contracts import ProviderIdentity


class UsageLedgerBeginResult(StrEnum):
    CREATED = "CREATED"
    SAME_REQUEST = "SAME_REQUEST"
    REQUEST_HASH_CONFLICT = "REQUEST_HASH_CONFLICT"


@dataclass(frozen=True, slots=True)
class UsageLedgerStart:
    tenant_id: UUID
    task_id: UUID
    course_id: str
    actor_membership_id: UUID
    invocation_id: UUID
    provider: ProviderIdentity
    prompt_version: str
    request_hash: str
    permit_ref: str
    privacy_policy_ref: str
    budget_reservation_ref: str
    budget_reserved_amount: Decimal
    budget_currency: str
    pricing_version: str
    source_refs: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class UsageLedgerCompletion:
    tenant_id: UUID
    task_id: UUID
    invocation_id: UUID
    response_hash: str
    input_tokens: int
    output_tokens: int
    cost_amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class UsageLedgerFailure:
    tenant_id: UUID
    task_id: UUID
    invocation_id: UUID
    safe_error_code: str


class AIUsageLedger(Protocol):
    def begin(self, record: UsageLedgerStart) -> UsageLedgerBeginResult:
        """Atomically insert or classify an existing invocation by request hash."""

    def complete(self, record: UsageLedgerCompletion) -> bool:
        """Change STARTED to SUCCEEDED exactly once."""

    def mark_unknown(self, record: UsageLedgerFailure) -> bool:
        """Change STARTED to UNKNOWN; this state must not be automatically replayed."""

    def mark_failed(self, record: UsageLedgerFailure) -> bool:
        """Change STARTED to FAILED only for a provider-declared definite failure."""
