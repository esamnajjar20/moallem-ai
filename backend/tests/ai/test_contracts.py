from __future__ import annotations

import pytest

from moallem.ai.contracts import AIProviderResponse, ProviderIdentity, TokenUsage


def test_token_usage_rejects_boolean_and_non_integer_counts() -> None:
    with pytest.raises(ValueError, match="integers"):
        TokenUsage(input_tokens=True, output_tokens=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="integers"):
        TokenUsage(input_tokens=1, output_tokens=1.5)  # type: ignore[arg-type]


def test_provider_identity_requires_trimmed_pinned_identity() -> None:
    with pytest.raises(ValueError, match="trimmed"):
        ProviderIdentity("provider", "model", " revision ", "region")
    with pytest.raises(ValueError, match="pinned revision"):
        ProviderIdentity("provider", "model", "latest", "region")


def test_provider_response_rejects_unvalidated_usage_and_unsafe_request_id() -> None:
    identity = ProviderIdentity("provider", "model", "revision", "region")
    usage = TokenUsage(input_tokens=1, output_tokens=1)
    with pytest.raises(ValueError, match="validated TokenUsage"):
        AIProviderResponse(
            identity=identity,
            output_text="model output",
            usage=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="printable"):
        AIProviderResponse(
            identity=identity,
            output_text="model output",
            usage=usage,
            provider_request_id="request\nforged",
        )
