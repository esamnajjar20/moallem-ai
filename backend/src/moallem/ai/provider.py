"""Provider adapter contract. Concrete network adapters require ADR-018 approval."""

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Protocol

from moallem.ai.contracts import (
    AIExecutionPermit,
    AIProviderResponse,
    AIRequest,
    ProviderIdentity,
)


class AIProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    async def generate(self, request: AIRequest) -> AIProviderResponse: ...


class AIExecutionAuthorizer(Protocol):
    async def authorize(
        self, request: AIRequest, provider: ProviderIdentity
    ) -> AIExecutionPermit:
        """Atomically reserve the invocation budget and issue a server-side permit.

        Implementations must be idempotent for (tenant, task, invocation) and must not
        issue a permit until provider, model, version, region, privacy, data classes, and
        tenant/task budgets have all been approved. There is deliberately no default
        implementation that calls a provider.
        """
        ...

    async def settle(self, permit: AIExecutionPermit, actual_cost: Decimal) -> None:
        """Atomically settle the reservation against measured usage; idempotent by ref."""
        ...

    async def release(self, permit: AIExecutionPermit) -> None:
        """Release a reservation only when the provider outcome is known not to have run."""
        ...


class AIProviderRegistry(Protocol):
    def get(self, provider_id: str) -> AIProvider: ...

    def provider_ids(self) -> Sequence[str]: ...


class StaticAIProviderRegistry:
    """Immutable exact-ID registry; it never chooses a fallback provider."""

    def __init__(self, providers: Iterable[AIProvider] = ()) -> None:
        entries: dict[str, AIProvider] = {}
        for provider in providers:
            provider_id = provider.identity.provider_id
            if provider_id in entries:
                raise ValueError("AI provider IDs must be unique")
            entries[provider_id] = provider
        self._providers = entries

    def get(self, provider_id: str) -> AIProvider:
        from moallem.ai.errors import AIProviderNotConfigured

        provider = self._providers.get(provider_id)
        if provider is None:
            raise AIProviderNotConfigured("requested AI provider is not registered")
        return provider

    def provider_ids(self) -> Sequence[str]:
        return tuple(sorted(self._providers))

    async def aclose(self) -> None:
        """Close every owned adapter, including when one close operation fails."""
        import asyncio

        close_operations = []
        for provider in self._providers.values():
            close = getattr(provider, "aclose", None)
            if callable(close):
                close_operations.append(close())
        results = await asyncio.gather(*close_operations, return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("one or more AI provider clients failed to close") from failures[0]


class DenyAllAIExecution:
    """Safe default policy: AI calls are disabled until a reviewed policy is injected."""

    async def authorize(
        self, request: AIRequest, provider: ProviderIdentity
    ) -> AIExecutionPermit:
        from moallem.ai.errors import AIExecutionDenied

        raise AIExecutionDenied("AI_PROVIDER_PRIVACY_APPROVAL_REQUIRED")

    async def settle(self, permit: AIExecutionPermit, actual_cost: Decimal) -> None:
        raise RuntimeError("DenyAllAIExecution never issues permits")

    async def release(self, permit: AIExecutionPermit) -> None:
        raise RuntimeError("DenyAllAIExecution never issues permits")
