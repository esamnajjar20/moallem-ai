from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from moallem.ai.errors import AIProviderNotConfigured
from moallem.ai.factory import build_ai_provider_registry
from moallem.ai.provider import StaticAIProviderRegistry
from moallem.config import Settings


def test_registry_is_empty_when_provider_is_not_configured() -> None:
    registry = build_ai_provider_registry(Settings(_env_file=None))
    assert registry.provider_ids() == ()
    with pytest.raises(AIProviderNotConfigured):
        registry.get("any-provider")
    asyncio.run(registry.aclose())


def test_factory_builds_only_the_explicitly_pinned_provider() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider_id="provider-test",
        ai_model_id="pinned-model",
        ai_model_version="rev-2026-11-17-1",
        ai_region="eu-test-1",
        ai_base_url="https://api.provider.example/v1",
        ai_api_key=SecretStr("never-log-this"),
        ai_allowed_hosts=("api.provider.example",),
    )
    registry = build_ai_provider_registry(settings)
    provider = registry.get("provider-test")
    assert provider.identity.provider_id == "provider-test"
    assert provider.identity.model_id == "pinned-model"
    assert provider.identity.model_version == "rev-2026-11-17-1"
    assert registry.provider_ids() == ("provider-test",)
    asyncio.run(registry.aclose())


class _StubProvider:
    def __init__(self, provider_id: str) -> None:
        from moallem.ai.contracts import ProviderIdentity

        self.identity = ProviderIdentity(provider_id, "model", "revision", "region")

    async def generate(self, request: object) -> object:
        raise NotImplementedError


def test_static_registry_rejects_duplicate_ids_and_never_falls_back() -> None:
    with pytest.raises(ValueError, match="unique"):
        StaticAIProviderRegistry((_StubProvider("same"), _StubProvider("same")))
    registry = StaticAIProviderRegistry((_StubProvider("one"), _StubProvider("two")))
    assert registry.provider_ids() == ("one", "two")
    with pytest.raises(AIProviderNotConfigured):
        registry.get("missing")


def test_registry_closes_all_owned_adapters_even_when_one_close_fails() -> None:
    closed: list[str] = []

    class ClosingProvider(_StubProvider):
        def __init__(self, provider_id: str, *, fails: bool = False) -> None:
            super().__init__(provider_id)
            self.fails = fails

        async def aclose(self) -> None:
            closed.append(self.identity.provider_id)
            if self.fails:
                raise RuntimeError("private close detail")

    registry = StaticAIProviderRegistry(
        (ClosingProvider("first", fails=True), ClosingProvider("second"))
    )
    with pytest.raises(RuntimeError, match="failed to close"):
        asyncio.run(registry.aclose())
    assert sorted(closed) == ["first", "second"]
