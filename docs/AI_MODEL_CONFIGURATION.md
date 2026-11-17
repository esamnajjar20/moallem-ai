# AI Model Transport Configuration

**Default state: no provider is configured and no AI invocation is enabled.** This document covers
transport construction only. Read `docs/adr/ADR-018-ai-provider-model-region.md` before configuring
any endpoint or sending any data.

## Optional deployment settings

The provider group is all-or-none. No provider, model, version, region, URL, or secret is supplied by
default.

```dotenv
MOALLEM_AI_PROVIDER_ID=approved-provider-id
MOALLEM_AI_MODEL_ID=approved-exact-model-id
MOALLEM_AI_MODEL_VERSION=approved-immutable-revision
MOALLEM_AI_REGION=approved-processing-region
MOALLEM_AI_BASE_URL=https://approved-provider.example/v1
MOALLEM_AI_API_KEY=<injected-secret>
MOALLEM_AI_ALLOWED_HOSTS=["approved-provider.example"]
MOALLEM_AI_TIMEOUT_SECONDS=60
MOALLEM_AI_MAX_REQUEST_BYTES=2097152
MOALLEM_AI_MAX_RESPONSE_BYTES=2097152
```

The values above are placeholders, not a provider recommendation or a deployment configuration.
`MOALLEM_AI_ALLOWED_HOSTS` is a JSON array of exact DNS hostnames; wildcard names and IP literals
are rejected. The hostname in `MOALLEM_AI_BASE_URL` must exactly match an allow-list entry.

`MOALLEM_AI_API_KEY` is a `SecretStr` and is omitted from repr and safe configuration summaries.
Inject production credentials from the approved Secret Manager at runtime; do not commit them or
store them in a production `.env` file. The repository currently does not implement production
Secret Manager/KMS integration.

## Composition contract

`build_ai_provider_registry(settings)` returns an empty exact-ID registry when the provider group
is absent. When fully configured, it creates one `OpenAICompatibleHTTPProvider`. The registry does
not pick a fallback provider, and its caller owns `await registry.aclose()` at process shutdown.

Constructing this registry does not:

- authorize a model request;
- create or reserve a task/tenant budget;
- mark a provider/model/region as approved;
- register a task handler or expose an API endpoint;
- enable automatic retries, failover, or cross-region routing.

`DenyAllAIExecution` remains the default. The registry must only be composed with an approved
`AIExecutionAuthorizer` after ADR-018 and DEC-043 are closed with evidence. The production budget
authorizer, persistent reservation/settlement, and orphan/UNKNOWN reconciliation are not yet
implemented.

## Transport behavior

- HTTPS only, exact DNS hostname allow-list, TLS verification on, `trust_env=False`.
- Redirects are not followed; no automatic retry is performed.
- Request and response bytes are bounded; compressed responses are rejected to keep the response
  size bound meaningful.
- Provider model ID in the response must equal the configured model ID.
- A timeout, redirect, 429, 5xx, malformed success, unsupported compression, or model mismatch is
  treated as an ambiguous outcome after dispatch. Do not retry automatically.
- The adapter sends one Chat Completions-compatible request. It does not prove the provider's
  model revision or processing region; those remain deployment/contract approval assertions.

The adapter is not a general-purpose model client. A provider that does not implement the same
Chat Completions request/response shape requires its own adapter and tests.
