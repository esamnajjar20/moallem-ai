"""Opt-in OpenAI Chat Completions-compatible HTTP provider adapter.

The adapter is deliberately not registered by the application factory. Deployments must
supply an approved HTTPS endpoint, model identity, version, region, API credential, and
network egress policy. AIGateway + an approved authorizer remain mandatory.
"""

from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

import httpx

from moallem.ai.contracts import (
    AIProviderResponse,
    AIRequest,
    ProviderIdentity,
    TokenUsage,
)
from moallem.ai.errors import AIProviderFailure

_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_DEFINITE_REJECTION_STATUSES = frozenset({400, 401, 403, 404, 413, 422})


def _validate_https_endpoint(value: str, allowed_hosts: frozenset[str]) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("provider base URL must be 1..2048 characters")
    if not allowed_hosts:
        raise ValueError("an exact provider hostname allow-list is required")
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("provider base URL must be an absolute HTTPS URL without credentials")
    hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("provider base URL must use an allow-listed DNS hostname")
    normalized_hosts = {
        host.encode("idna").decode("ascii").lower().rstrip(".") for host in allowed_hosts
    }
    if hostname not in normalized_hosts:
        raise ValueError("provider base URL hostname is not allow-listed")
    return value.rstrip("/")


async def _read_limited(response: httpx.Response, limit: int) -> bytes:
    """Read raw identity-encoded bytes so decompression cannot bypass the body limit."""
    body = bytearray()
    async for block in response.aiter_raw():
        if len(body) + len(block) > limit:
            raise AIProviderFailure("AI_PROVIDER_RESPONSE_TOO_LARGE", definitive=False)
        body.extend(block)
    return bytes(body)


class OpenAICompatibleHTTPProvider:
    """No-retry, bounded-response adapter for ``POST /chat/completions``.

    ``provider_id`` and ``region`` are deployment assertions, not values inferred from an
    untrusted response. The returned model must exactly match the configured model ID.
    ``model_version`` must therefore identify a pinned model revision, not a mutable alias,
    before any production permit can be issued.
    """

    def __init__(
        self,
        *,
        identity: ProviderIdentity,
        base_url: str,
        api_key: str,
        allowed_hosts: frozenset[str] | tuple[str, ...],
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_request_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or not api_key.strip() or len(api_key) > 8192:
            raise ValueError("provider API key must be non-empty and bounded")
        if not 0 < timeout_seconds <= 300:
            raise ValueError("provider timeout must be > 0 and <= 300 seconds")
        if not 1024 <= max_request_bytes <= 16 * 1024 * 1024:
            raise ValueError("provider request limit must be 1KiB..16MiB")
        if not 1024 <= max_response_bytes <= 16 * 1024 * 1024:
            raise ValueError("provider response limit must be 1KiB..16MiB")
        self._identity = identity
        self._base_url = _validate_https_endpoint(base_url, frozenset(allowed_hosts))
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: AIRequest) -> AIProviderResponse:
        payload = {
            "model": self._identity.model_id,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.max_output_tokens,
        }
        try:
            request_body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if len(request_body) > self._max_request_bytes:
                raise AIProviderFailure("AI_PROVIDER_REQUEST_TOO_LARGE", definitive=True)
            async with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                content=request_body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    definitive = response.status_code in _DEFINITE_REJECTION_STATUSES
                    code = (
                        "AI_PROVIDER_REQUEST_REJECTED"
                        if definitive
                        else "AI_PROVIDER_HTTP_OUTCOME_UNKNOWN"
                    )
                    raise AIProviderFailure(code, definitive=definitive)
                content_encoding = response.headers.get("content-encoding", "identity").lower()
                if content_encoding not in ("", "identity"):
                    raise AIProviderFailure(
                        "AI_PROVIDER_COMPRESSED_RESPONSE_UNSUPPORTED", definitive=False
                    )
                if response.is_stream_consumed:
                    # Mock/custom transports may return a fully buffered response. Production
                    # clients use the raw streaming path below, bounded before JSON parsing.
                    raw = response.content
                    if len(raw) > self._max_response_bytes:
                        raise AIProviderFailure("AI_PROVIDER_RESPONSE_TOO_LARGE", definitive=False)
                else:
                    raw = await _read_limited(response, self._max_response_bytes)
                request_id = response.headers.get("x-request-id", "")[:256] or None
        except AIProviderFailure:
            raise
        except httpx.HTTPError:
            # A timeout, disconnect, TLS error, or protocol error may occur after dispatch.
            # Never retry here: the gateway will preserve UNKNOWN for reconciliation.
            raise AIProviderFailure("AI_PROVIDER_TRANSPORT_UNKNOWN", definitive=False) from None

        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("response root must be an object")
            returned_model = data.get("model")
            choices = data.get("choices")
            usage = data.get("usage")
            if returned_model != self._identity.model_id:
                raise ValueError("response model mismatch")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("response choices are invalid")
            message = choices[0].get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("response content is invalid")
            if not isinstance(usage, dict):
                raise ValueError("response usage is missing")
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            if (
                isinstance(prompt_tokens, bool)
                or not isinstance(prompt_tokens, int)
                or isinstance(completion_tokens, bool)
                or not isinstance(completion_tokens, int)
                or prompt_tokens < 0
                or completion_tokens < 0
            ):
                raise ValueError("response token usage is invalid")
            return AIProviderResponse(
                identity=self._identity,
                output_text=message["content"],
                usage=TokenUsage(
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                ),
                provider_request_id=request_id,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            # A 2xx response can mean the provider already executed/billed the request.
            raise AIProviderFailure("AI_PROVIDER_RESPONSE_INVALID", definitive=False) from None
