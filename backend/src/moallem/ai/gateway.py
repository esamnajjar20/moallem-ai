"""Fail-closed provider-neutral AI gateway with durable, idempotent usage accounting."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from moallem.ai.contracts import AIExecutionPermit, AIProviderResponse, AIRequest
from moallem.ai.errors import (
    AIActualCostExceededReservation,
    AIInvocationAlreadyExists,
    AIInvocationConflict,
    AIProviderFailure,
    AIProviderOutcomeUnknown,
    AIReservationSettlementFailed,
    AIUsageLedgerConflict,
    AIUsageAccountingUnknown,
)
from moallem.ai.provider import AIExecutionAuthorizer, AIProvider
from moallem.ai.usage import (
    AIUsageLedger,
    UsageLedgerCompletion,
    UsageLedgerFailure,
    UsageLedgerBeginResult,
    UsageLedgerStart,
)


class AIGateway:
    """Dispatch one authorized provider invocation, never retrying ambiguous outcomes."""

    def __init__(
        self,
        *,
        provider: AIProvider,
        authorizer: AIExecutionAuthorizer,
        usage_ledger: AIUsageLedger,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._authorizer = authorizer
        self._usage_ledger = usage_ledger
        self._clock = clock or (lambda: datetime.now(UTC))

    async def generate(self, request: AIRequest) -> AIProviderResponse:
        provider_identity = self._provider.identity
        permit = cast(
            AIExecutionPermit,
            await self._authorizer.authorize(request, provider_identity),
        )
        try:
            permit.validate_for(request, provider_identity, now=self._clock())
        except ValueError as exc:
            from moallem.ai.errors import AIExecutionDenied

            await self._authorizer.release(permit)
            raise AIExecutionDenied(str(exc)) from None

        started = UsageLedgerStart(
            tenant_id=request.tenant_id,
            task_id=request.task_id,
            course_id=request.course_id,
            actor_membership_id=request.actor_membership_id,
            invocation_id=request.invocation_id,
            provider=provider_identity,
            prompt_version=request.prompt_version,
            request_hash=request.request_hash,
            permit_ref=permit.permit_ref,
            privacy_policy_ref=permit.privacy_policy_ref,
            budget_reservation_ref=permit.budget_reservation_ref,
            budget_reserved_amount=permit.budget_reserved_amount,
            budget_currency=permit.pricing.currency,
            pricing_version=permit.pricing.pricing_version,
            source_refs=request.source_refs,
        )
        begin_task = asyncio.create_task(asyncio.to_thread(self._usage_ledger.begin, started))
        try:
            begin_result = await asyncio.shield(begin_task)
        except asyncio.CancelledError:
            # The DB operation itself cannot be cancelled once running in its thread. Wait
            # for its definitive result before releasing the budget reservation.
            try:
                begin_result = await asyncio.shield(begin_task)
            except Exception:
                await self._authorizer.release(permit)
                raise
            if begin_result is UsageLedgerBeginResult.CREATED:
                await asyncio.to_thread(
                    self._mark_definite_failure,
                    request,
                    "AI_CANCELLED_BEFORE_PROVIDER_DISPATCH",
                )
                await self._authorizer.release(permit)
            raise
        except Exception:
            await self._authorizer.release(permit)
            raise AIUsageLedgerConflict("AI invocation could not be durably registered") from None
        if begin_result is UsageLedgerBeginResult.SAME_REQUEST:
            raise AIInvocationAlreadyExists("AI invocation identity already exists; no retry")
        if begin_result is UsageLedgerBeginResult.REQUEST_HASH_CONFLICT:
            raise AIInvocationConflict("AI invocation identity was reused with different content")
        if begin_result is not UsageLedgerBeginResult.CREATED:
            await self._authorizer.release(permit)
            raise AIUsageLedgerConflict("AI usage ledger returned an invalid begin result")

        try:
            response = await self._provider.generate(request)
        except asyncio.CancelledError:
            await asyncio.shield(
                asyncio.to_thread(
                    self._mark_unknown,
                    request,
                    "AI_CALL_CANCELLED_AFTER_DISPATCH",
                )
            )
            raise
        except AIProviderFailure as exc:
            await asyncio.to_thread(
                self._mark_definite_failure if exc.definitive else self._mark_unknown,
                request,
                exc.safe_code,
            )
            if exc.definitive:
                await self._authorizer.release(permit)
                raise
            raise AIProviderOutcomeUnknown("provider outcome is unknown; do not retry") from None
        except Exception:
            await asyncio.to_thread(
                self._mark_unknown, request, "AI_PROVIDER_OUTCOME_UNKNOWN"
            )
            raise AIProviderOutcomeUnknown(
                "provider outcome is unknown; do not retry automatically"
            ) from None

        if not isinstance(response, AIProviderResponse):
            await asyncio.to_thread(
                self._mark_unknown, request, "AI_PROVIDER_RESPONSE_INVALID"
            )
            raise AIProviderOutcomeUnknown("provider returned an invalid response object")
        if response.identity != provider_identity:
            await asyncio.to_thread(
                self._mark_unknown, request, "AI_PROVIDER_IDENTITY_MISMATCH"
            )
            raise AIProviderOutcomeUnknown("provider identity mismatch; result not accepted")
        if response.usage.output_tokens > request.max_output_tokens:
            await asyncio.to_thread(
                self._mark_unknown, request, "AI_PROVIDER_USAGE_LIMIT_MISMATCH"
            )
            raise AIProviderOutcomeUnknown("provider exceeded the declared output token limit")

        try:
            actual_cost = permit.pricing.calculate(response.usage)
        except (ValueError, ArithmeticError):
            # The provider has already answered. Preserve the invocation as UNKNOWN and
            # keep its reservation for operator reconciliation rather than losing accounting.
            await asyncio.to_thread(
                self._mark_unknown, request, "AI_USAGE_COST_CALCULATION_FAILED"
            )
            raise AIUsageAccountingUnknown(
                "provider usage was returned but its cost could not be safely recorded"
            ) from None
        completed = UsageLedgerCompletion(
            tenant_id=request.tenant_id,
            task_id=request.task_id,
            invocation_id=request.invocation_id,
            response_hash=hashlib.sha256(response.output_text.encode("utf-8")).hexdigest(),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_amount=actual_cost,
            currency=permit.pricing.currency,
        )
        completion_task = asyncio.create_task(
            asyncio.to_thread(self._usage_ledger.complete, completed)
        )
        cancelled_after_response = False
        try:
            committed = await asyncio.shield(completion_task)
        except asyncio.CancelledError:
            # The provider has already returned. Do not abandon a DB write running in a
            # thread: its commit outcome must be known before deciding what to do with the
            # reservation. The cancellation is re-raised only after finalization below.
            cancelled_after_response = True
            committed = await asyncio.shield(completion_task)
        if not committed:
            raise AIUsageLedgerConflict("usage ledger could not finalize this invocation")

        settlement_task = asyncio.create_task(self._authorizer.settle(permit, actual_cost))
        try:
            await asyncio.shield(settlement_task)
        except asyncio.CancelledError:
            # Settlement is an external accounting side effect too. Keep waiting for its
            # definitive result, rather than reporting cancellation with an unknown budget.
            cancelled_after_response = True
            try:
                await asyncio.shield(settlement_task)
            except Exception:
                raise AIReservationSettlementFailed(
                    "provider usage was recorded but the budget reservation could not be settled"
                ) from None
        except Exception:
            raise AIReservationSettlementFailed(
                "provider usage was recorded but the budget reservation could not be settled"
            ) from None

        if actual_cost > permit.budget_reserved_amount:
            # The provider call already happened. Preserve measured usage and surface the
            # overrun; never conceal it or make an automatic follow-up call.
            raise AIActualCostExceededReservation(
                "actual provider cost exceeded the pre-call reservation"
            )
        if cancelled_after_response:
            raise asyncio.CancelledError
        return response

    def _mark_unknown(self, request: AIRequest, safe_code: str) -> None:
        updated = self._usage_ledger.mark_unknown(
            UsageLedgerFailure(
                tenant_id=request.tenant_id,
                task_id=request.task_id,
                invocation_id=request.invocation_id,
                safe_error_code=safe_code,
            )
        )
        if not updated:
            raise AIUsageLedgerConflict("usage ledger could not mark invocation UNKNOWN")

    def _mark_definite_failure(self, request: AIRequest, safe_code: str) -> None:
        updated = self._usage_ledger.mark_failed(
            UsageLedgerFailure(
                tenant_id=request.tenant_id,
                task_id=request.task_id,
                invocation_id=request.invocation_id,
                safe_error_code=safe_code,
            )
        )
        if not updated:
            raise AIUsageLedgerConflict("usage ledger could not mark invocation FAILED")
