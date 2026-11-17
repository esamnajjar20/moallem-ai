"""Explicit AI provider composition from validated deployment settings.

Constructing this registry only configures a transport. It does not authorize execution,
create a budget reservation, or enable an AI task. The default registry is empty.
"""

from moallem.ai.contracts import ProviderIdentity
from moallem.ai.http_provider import OpenAICompatibleHTTPProvider
from moallem.ai.provider import StaticAIProviderRegistry
from moallem.config import Settings


def build_ai_provider_registry(settings: Settings) -> StaticAIProviderRegistry:
    """Build the explicitly configured provider registry, or an empty registry by default."""
    if settings.ai_provider_id is None:
        return StaticAIProviderRegistry()

    # Settings validation guarantees that this complete group exists together.
    assert settings.ai_model_id is not None  # noqa: S101
    assert settings.ai_model_version is not None  # noqa: S101
    assert settings.ai_region is not None  # noqa: S101
    assert settings.ai_base_url is not None  # noqa: S101
    assert settings.ai_api_key is not None  # noqa: S101
    assert settings.ai_allowed_hosts is not None  # noqa: S101

    provider = OpenAICompatibleHTTPProvider(
        identity=ProviderIdentity(
            provider_id=settings.ai_provider_id,
            model_id=settings.ai_model_id,
            model_version=settings.ai_model_version,
            region=settings.ai_region,
        ),
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key.get_secret_value(),
        allowed_hosts=settings.ai_allowed_hosts,
        timeout_seconds=settings.ai_timeout_seconds,
        max_request_bytes=settings.ai_max_request_bytes,
        max_response_bytes=settings.ai_max_response_bytes,
    )
    return StaticAIProviderRegistry((provider,))
