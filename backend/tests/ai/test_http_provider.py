from __future__ import annotations

import asyncio
import gzip
import json

import httpx
import pytest

from moallem.ai.contracts import AIMessage, AIMessageRole, AIRequest, ProviderIdentity
from moallem.ai.errors import AIProviderFailure
from moallem.ai.http_provider import OpenAICompatibleHTTPProvider


IDENTITY = ProviderIdentity("approved-id", "pinned-model", "2026-11-17", "eu-test-1")


def request() -> AIRequest:
    from uuid import uuid4

    return AIRequest(
        tenant_id=uuid4(),
        task_id=uuid4(),
        actor_membership_id=uuid4(),
        course_id="course-1",
        invocation_id=uuid4(),
        prompt_version="prompt-v1",
        messages=(AIMessage(AIMessageRole.USER, "Generate a short quiz item"),),
        max_output_tokens=100,
        data_classes=frozenset({"COURSE_CONTENT"}),
    )


def provider(
    handler,
    *,
    max_request_bytes: int = 2 * 1024 * 1024,
) -> OpenAICompatibleHTTPProvider:
    return OpenAICompatibleHTTPProvider(
        identity=IDENTITY,
        base_url="https://provider.example.test/v1",
        api_key="test-secret",
        allowed_hosts=("provider.example.test",),
        max_request_bytes=max_request_bytes,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_http_provider_maps_valid_response_and_never_logs_prompt() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-123"},
            json={
                "id": "resp-1",
                "model": "pinned-model",
                "choices": [{"message": {"content": "Question draft"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 12},
            },
        )

    client = provider(handler)
    result = asyncio.run(client.generate(request()))
    assert result.identity == IDENTITY
    assert result.output_text == "Question draft"
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 12
    assert result.provider_request_id == "req-123"
    assert captured["auth"] == "Bearer test-secret"
    assert captured["payload"]["model"] == "pinned-model"  # type: ignore[index]
    assert captured["payload"]["max_tokens"] == 100  # type: ignore[index]
    assert "Generate a short quiz item" in str(captured["payload"])  # sent only to provider
    asyncio.run(client.aclose())


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
def test_http_provider_classifies_explicit_rejections_as_definitive(status: int) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "do not surface provider body"})

    client = provider(handler)
    with pytest.raises(AIProviderFailure) as exc:
        asyncio.run(client.generate(request()))
    assert exc.value.definitive is True
    assert str(exc.value) == "AI_PROVIDER_REQUEST_REJECTED"
    asyncio.run(client.aclose())


@pytest.mark.parametrize("status", [302, 408, 409, 425, 429, 500, 502, 503])
def test_http_provider_never_follows_redirects_or_retries_ambiguous_statuses(status: int) -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"location": "https://elsewhere.example"})

    client = provider(handler)
    with pytest.raises(AIProviderFailure) as exc:
        asyncio.run(client.generate(request()))
    assert exc.value.definitive is False
    assert calls == 1
    asyncio.run(client.aclose())


def test_http_provider_rejects_model_mismatch_as_unknown() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "mutable-alias-now-points-elsewhere",
                "choices": [{"message": {"content": "output"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = provider(handler)
    with pytest.raises(AIProviderFailure) as exc:
        asyncio.run(client.generate(request()))
    assert exc.value.definitive is False
    assert str(exc.value) == "AI_PROVIDER_RESPONSE_INVALID"
    asyncio.run(client.aclose())


def test_http_provider_validates_endpoint_and_timeout() -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleHTTPProvider(
            identity=IDENTITY,
            base_url="http://provider.example.test/v1",
            api_key="secret",
            allowed_hosts=("provider.example.test",),
        )
    with pytest.raises(ValueError):
        OpenAICompatibleHTTPProvider(
            identity=IDENTITY,
            base_url="https://user:pass@provider.example.test/v1",
            api_key="secret",
            allowed_hosts=("provider.example.test",),
        )


def test_http_provider_timeout_is_an_ambiguous_non_retryable_outcome() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private transport details", request=request)

    client = provider(handler)
    with pytest.raises(AIProviderFailure) as exc:
        asyncio.run(client.generate(request()))
    assert exc.value.definitive is False
    assert str(exc.value) == "AI_PROVIDER_TRANSPORT_UNKNOWN"
    asyncio.run(client.aclose())


def test_http_provider_requires_exact_dns_hostname_allowlist() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid endpoint must not dispatch")

    with pytest.raises(ValueError, match="not allow-listed"):
        OpenAICompatibleHTTPProvider(
            identity=IDENTITY,
            base_url="https://other.example.test/v1",
            api_key="secret",
            allowed_hosts=("provider.example.test",),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
    with pytest.raises(ValueError, match="DNS hostname"):
        OpenAICompatibleHTTPProvider(
            identity=IDENTITY,
            base_url="https://127.0.0.1/v1",
            api_key="secret",
            allowed_hosts=("127.0.0.1",),
        )


def test_http_provider_rejects_oversized_request_before_dispatch() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = provider(handler, max_request_bytes=1024)
    with pytest.raises(AIProviderFailure) as exc:
        asyncio.run(client.generate(request_with_content("x" * 2048)))
    assert exc.value.safe_code == "AI_PROVIDER_REQUEST_TOO_LARGE"
    assert exc.value.definitive is True
    assert calls == 0
    asyncio.run(client.aclose())


def request_with_content(content: str) -> AIRequest:
    base = request()
    return AIRequest(
        tenant_id=base.tenant_id,
        task_id=base.task_id,
        actor_membership_id=base.actor_membership_id,
        course_id=base.course_id,
        invocation_id=base.invocation_id,
        prompt_version=base.prompt_version,
        messages=(AIMessage(AIMessageRole.USER, content),),
        max_output_tokens=base.max_output_tokens,
        data_classes=base.data_classes,
    )


def test_http_provider_rejects_compressed_responses() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(b"compressed response must be rejected"),
        )

    client = provider(handler)
    with pytest.raises(AIProviderFailure) as exc:
        asyncio.run(client.generate(request()))
    assert exc.value.safe_code == "AI_PROVIDER_COMPRESSED_RESPONSE_UNSUPPORTED"
    assert exc.value.definitive is False
    asyncio.run(client.aclose())
