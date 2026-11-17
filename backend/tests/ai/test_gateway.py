from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest

from moallem.ai.contracts import (
    AIExecutionPermit,
    AIMessage,
    AIMessageRole,
    AIProviderResponse,
    AIRequest,
    ModelPricing,
    ProviderIdentity,
    TokenUsage,
)
from moallem.ai.errors import (
    AIActualCostExceededReservation,
    AIExecutionDenied,
    AIInvocationAlreadyExists,
    AIInvocationConflict,
    AIProviderFailure,
    AIProviderOutcomeUnknown,
    AIUsageAccountingUnknown,
)
from moallem.ai.gateway import AIGateway
from moallem.ai.provider import DenyAllAIExecution
from moallem.ai.usage import (
    UsageLedgerBeginResult,
    UsageLedgerCompletion,
    UsageLedgerFailure,
    UsageLedgerStart,
)


IDENTITY = ProviderIdentity("provider-test", "model-test", "2026-01", "test-region")


def make_request(*, content: str = "Create a question") -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(),
        task_id=uuid4(),
        actor_membership_id=uuid4(),
        course_id="course-42",
        invocation_id=uuid4(),
        prompt_version="quiz-prompt-v1",
        messages=(AIMessage(AIMessageRole.USER, content),),
        max_output_tokens=200,
        data_classes=frozenset({"COURSE_CONTENT"}),
    )


def make_permit(request: AIRequest, *, reserved: Decimal = Decimal("1.00")) -> AIExecutionPermit:
    pricing = ModelPricing(
        provider_id=IDENTITY.provider_id,
        model_id=IDENTITY.model_id,
        model_version=IDENTITY.model_version,
        region=IDENTITY.region,
        pricing_version="price-v1",
        currency="USD",
        input_cost_per_million_tokens=Decimal("1.00"),
        output_cost_per_million_tokens=Decimal("2.00"),
    )
    return AIExecutionPermit(
        permit_ref="permit-1",
        tenant_id=request.tenant_id,
        task_id=request.task_id,
        actor_membership_id=request.actor_membership_id,
        course_id=request.course_id,
        provider=IDENTITY,
        privacy_policy_ref="privacy-approval-1",
        budget_reservation_ref="budget-reservation-1",
        budget_reserved_amount=reserved,
        pricing=pricing,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        allowed_data_classes=frozenset({"COURSE_CONTENT"}),
    )


class FakeProvider:
    identity = IDENTITY

    def __init__(self, response: AIProviderResponse | None = None, error: Exception | None = None):
        self.calls = 0
        self.response = response or AIProviderResponse(
            identity=IDENTITY,
            output_text="A draft question",
            usage=TokenUsage(input_tokens=1000, output_tokens=100),
        )
        self.error = error

    async def generate(self, request: AIRequest) -> AIProviderResponse:
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class FakeAuthorizer:
    def __init__(self, permit: AIExecutionPermit):
        self.permit = permit
        self.calls = 0
        self.settled: list[tuple[str, Decimal]] = []
        self.released: list[str] = []

    async def authorize(self, request: AIRequest, provider: ProviderIdentity) -> AIExecutionPermit:
        self.calls += 1
        return self.permit

    async def settle(self, permit: AIExecutionPermit, actual_cost: Decimal) -> None:
        self.settled.append((permit.budget_reservation_ref, actual_cost))

    async def release(self, permit: AIExecutionPermit) -> None:
        self.released.append(permit.budget_reservation_ref)


class FakeLedger:
    def __init__(self, begin_result: UsageLedgerBeginResult = UsageLedgerBeginResult.CREATED):
        self.begin_result = begin_result
        self.starts: list[UsageLedgerStart] = []
        self.completions: list[UsageLedgerCompletion] = []
        self.unknown: list[UsageLedgerFailure] = []
        self.failed: list[UsageLedgerFailure] = []
        self.block_completion = False
        self.completion_started = Event()
        self.allow_completion = Event()

    def begin(self, record: UsageLedgerStart) -> UsageLedgerBeginResult:
        self.starts.append(record)
        return self.begin_result

    def complete(self, record: UsageLedgerCompletion) -> bool:
        if self.block_completion:
            self.completion_started.set()
            if not self.allow_completion.wait(timeout=5):
                raise TimeoutError("test did not release blocked ledger completion")
        self.completions.append(record)
        return True

    def mark_unknown(self, record: UsageLedgerFailure) -> bool:
        self.unknown.append(record)
        return True

    def mark_failed(self, record: UsageLedgerFailure) -> bool:
        self.failed.append(record)
        return True


def test_gateway_default_deny_does_not_call_provider_or_ledger() -> None:
    request = make_request()
    provider = FakeProvider()
    ledger = FakeLedger()
    gateway = AIGateway(
        provider=provider,
        authorizer=DenyAllAIExecution(),
        usage_ledger=ledger,
    )

    with pytest.raises(AIExecutionDenied):
        asyncio.run(gateway.generate(request))

    assert provider.calls == 0
    assert ledger.starts == []


def test_gateway_records_usage_and_hashes_not_prompt_or_completion() -> None:
    request = make_request()
    provider = FakeProvider()
    ledger = FakeLedger()
    authorizer = FakeAuthorizer(make_permit(request))
    gateway = AIGateway(
        provider=provider,
        authorizer=authorizer,
        usage_ledger=ledger,
    )

    result = asyncio.run(gateway.generate(request))

    assert result.output_text == "A draft question"
    assert provider.calls == 1
    assert len(ledger.starts) == 1
    assert len(ledger.completions) == 1
    assert ledger.starts[0].request_hash == request.request_hash
    assert not hasattr(ledger.starts[0], "messages")
    assert not hasattr(ledger.completions[0], "output_text")
    assert ledger.completions[0].input_tokens == 1000
    assert ledger.completions[0].output_tokens == 100
    assert ledger.completions[0].cost_amount == Decimal("0.0012")
    assert authorizer.settled == [("budget-reservation-1", Decimal("0.0012"))]
    assert authorizer.released == []


def test_same_invocation_and_same_hash_is_not_dispatched_twice() -> None:
    request = make_request()
    provider = FakeProvider()
    ledger = FakeLedger(UsageLedgerBeginResult.SAME_REQUEST)
    gateway = AIGateway(
        provider=provider,
        authorizer=FakeAuthorizer(make_permit(request)),
        usage_ledger=ledger,
    )

    with pytest.raises(AIInvocationAlreadyExists):
        asyncio.run(gateway.generate(request))

    assert provider.calls == 0


def test_reused_invocation_with_different_request_hash_is_conflict() -> None:
    request = make_request()
    provider = FakeProvider()
    ledger = FakeLedger(UsageLedgerBeginResult.REQUEST_HASH_CONFLICT)
    gateway = AIGateway(
        provider=provider,
        authorizer=FakeAuthorizer(make_permit(request)),
        usage_ledger=ledger,
    )

    with pytest.raises(AIInvocationConflict):
        asyncio.run(gateway.generate(request))

    assert provider.calls == 0


def test_ambiguous_provider_failure_is_unknown_and_never_retried() -> None:
    request = make_request()
    provider = FakeProvider(error=TimeoutError("network timeout"))
    ledger = FakeLedger()
    gateway = AIGateway(
        provider=provider,
        authorizer=FakeAuthorizer(make_permit(request)),
        usage_ledger=ledger,
    )

    with pytest.raises(AIProviderOutcomeUnknown):
        asyncio.run(gateway.generate(request))

    assert provider.calls == 1
    assert len(ledger.unknown) == 1
    assert ledger.failed == []


def test_actual_cost_overrun_is_still_recorded_and_then_raised() -> None:
    request = make_request()
    provider = FakeProvider()
    ledger = FakeLedger()
    gateway = AIGateway(
        provider=provider,
        authorizer=FakeAuthorizer(make_permit(request, reserved=Decimal("0.0001"))),
        usage_ledger=ledger,
    )

    with pytest.raises(AIActualCostExceededReservation):
        asyncio.run(gateway.generate(request))

    assert len(ledger.completions) == 1
    assert ledger.completions[0].cost_amount > Decimal("0.0001")


def test_expired_or_wrong_scope_permit_denies_before_ledger() -> None:
    request = make_request()
    expired = make_permit(request)
    expired = replace(expired, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    provider = FakeProvider()
    ledger = FakeLedger()
    gateway = AIGateway(
        provider=provider,
        authorizer=FakeAuthorizer(expired),
        usage_ledger=ledger,
    )

    with pytest.raises(AIExecutionDenied):
        asyncio.run(gateway.generate(request))

    assert provider.calls == 0
    assert ledger.starts == []


def test_definitive_provider_failure_releases_reservation_after_failed_ledger_state() -> None:
    request = make_request()
    provider = FakeProvider(error=AIProviderFailure("PROVIDER_REJECTED", definitive=True))
    ledger = FakeLedger()
    authorizer = FakeAuthorizer(make_permit(request))
    gateway = AIGateway(provider=provider, authorizer=authorizer, usage_ledger=ledger)

    with pytest.raises(AIProviderFailure):
        asyncio.run(gateway.generate(request))

    assert provider.calls == 1
    assert len(ledger.failed) == 1
    assert authorizer.released == ["budget-reservation-1"]
    assert authorizer.settled == []


def test_unknown_provider_outcome_keeps_reservation_for_reconciliation() -> None:
    request = make_request()
    provider = FakeProvider(error=TimeoutError("ambiguous timeout"))
    ledger = FakeLedger()
    authorizer = FakeAuthorizer(make_permit(request))
    gateway = AIGateway(provider=provider, authorizer=authorizer, usage_ledger=ledger)

    with pytest.raises(AIProviderOutcomeUnknown):
        asyncio.run(gateway.generate(request))

    assert ledger.unknown
    assert authorizer.released == []
    assert authorizer.settled == []


def test_ai_request_hash_binds_course_and_provenance_refs() -> None:
    request = make_request()
    source_ref = uuid4()
    with_source = replace(request, source_refs=(source_ref,))
    assert with_source.request_hash != request.request_hash
    assert replace(with_source, course_id="another-course").request_hash != with_source.request_hash


def test_cancellation_after_provider_response_waits_for_usage_and_budget_settlement() -> None:
    request = make_request()
    provider = FakeProvider()
    ledger = FakeLedger()
    ledger.block_completion = True
    authorizer = FakeAuthorizer(make_permit(request))
    gateway = AIGateway(provider=provider, authorizer=authorizer, usage_ledger=ledger)

    async def scenario() -> None:
        task = asyncio.create_task(gateway.generate(request))
        assert await asyncio.to_thread(ledger.completion_started.wait, 2)
        task.cancel()
        ledger.allow_completion.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert provider.calls == 1
    assert len(ledger.completions) == 1
    assert authorizer.settled == [("budget-reservation-1", ledger.completions[0].cost_amount)]


def test_ai_request_rejects_unbounded_messages_and_content() -> None:
    request = make_request()
    with pytest.raises(ValueError, match="messages"):
        replace(request, messages=tuple(request.messages * 65))
    with pytest.raises(ValueError, match="1MiB"):
        replace(request, messages=(AIMessage(AIMessageRole.USER, "x" * (1024 * 1024 + 1)),))
    with pytest.raises(ValueError, match="NUL"):
        AIMessage(AIMessageRole.USER, "bad\x00content")


def test_cost_calculation_overflow_is_marked_unknown_and_keeps_reservation() -> None:
    request = make_request()
    expensive_pricing = ModelPricing(
        provider_id=IDENTITY.provider_id,
        model_id=IDENTITY.model_id,
        model_version=IDENTITY.model_version,
        region=IDENTITY.region,
        pricing_version="price-overflow",
        currency="USD",
        input_cost_per_million_tokens=Decimal("999999999999.000000000000"),
        output_cost_per_million_tokens=Decimal("0"),
    )
    permit = replace(make_permit(request), pricing=expensive_pricing)
    provider = FakeProvider(
        response=AIProviderResponse(
            identity=IDENTITY,
            output_text="known result",
            usage=TokenUsage(input_tokens=2**63 - 1, output_tokens=0),
        )
    )
    ledger = FakeLedger()
    authorizer = FakeAuthorizer(permit)
    gateway = AIGateway(provider=provider, authorizer=authorizer, usage_ledger=ledger)

    with pytest.raises(AIUsageAccountingUnknown):
        asyncio.run(gateway.generate(request))

    assert ledger.unknown[0].safe_error_code == "AI_USAGE_COST_CALCULATION_FAILED"
    assert ledger.completions == []
    assert authorizer.released == []
    assert authorizer.settled == []
