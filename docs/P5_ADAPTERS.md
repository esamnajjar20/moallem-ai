# P5 external adapter contracts

**Status: opt-in clients only. No external provider, object store, scanner, or parser service is selected or enabled by default.**

The implementation adds deployment-facing HTTP clients while preserving the deny-by-default execution policy. The HTTP clients do not constitute evidence that a remote service exists, that its operator is approved, or that its infrastructure satisfies the required security controls.

## AI provider adapter

`backend/src/moallem/ai/http_provider.py` provides `OpenAICompatibleHTTPProvider` for providers implementing the Chat Completions request/response shape.

- Configure an absolute HTTPS base URL ending in the provider API prefix (for example `/v1`), an API key from a secret manager, and a `ProviderIdentity` whose model ID is pinned.
- The adapter sends one `POST {base_url}/chat/completions`, with `model`, messages, and `max_tokens`.
- It does not follow redirects, perform retries, log prompt/response bodies, or include provider response bodies in exceptions.
- A small allow-list of explicit HTTP rejection statuses is classified as definite failure. Timeouts, redirects, 429, 5xx, malformed successful responses, model mismatch, and transport errors are classified as unknown and must not be retried automatically.
- The returned model must exactly match the configured model ID. `provider_id`, `model_version`, and `region` are deployment assertions; a successful HTTP response does not independently prove them. The permit authorizer must only issue permits for a reviewed endpoint/model/region tuple.
- `DenyAllAIExecution` remains the default. This adapter alone cannot dispatch AI calls through the application.

## Private quarantine storage gateway

`backend/src/moallem/files/http_adapters.py` provides `HTTPQuarantineStorage`. The internal storage gateway must implement:

- `PUT /v1/quarantine/{tenant_id}/{file_id}` with a streamed `application/octet-stream` request body.
- `201` (or `200`/`202`) with JSON `{"storage_ref":"s3://<approved-bucket>/<opaque-key>"}`.
- `DELETE /v1/quarantine/{tenant_id}/{file_id}` as an idempotent operation that resolves the canonical object mapping from the authenticated tenant/file identity. Optional `X-Expected-Storage-Ref` is a compare guard only; it must not be used as an arbitrary path.
- The client requires an explicit bucket allow-list and supported private URI schemes. A reference outside the allow-list is rejected and cleanup is attempted by the canonical tenant/file key.
- The service must enforce private ACLs, tenant/file binding, encryption at rest with the approved KMS/key policy, TLS/mTLS authentication, multipart abort on disconnect, and auditable deletion. The client does not prove those controls by examining the URI.

Use `build_mtls_client(ca_file, client_certificate, client_key, timeout_seconds)` for the internal storage, scanner, and parser service clients. It verifies the server certificate and hostname, presents the client certificate, disables environment proxy inheritance, and does not follow redirects.

## Malware scanner service

`HTTPMalwareScanner` calls `POST /v1/scan` with `tenant_id`, `file_id`, and the private storage reference. The service must authenticate the mTLS caller, verify that the requested object is the exact object registered to that tenant/file pair, reject cross-tenant or mismatched references before reading bytes, and audit the decision. A storage reference alone is not an authorization token. The service response must contain `verdict` (`CLEAN`, `MALICIOUS`, `ERROR`, or `UNKNOWN`), `scanner_id`, and `scanner_version`. The adapter compares the returned scanner ID against a configured expected ID. A mismatch or invalid response is `UNKNOWN`, never `CLEAN`.

The scanner service must run a maintained malware engine (for example ClamAV), have read-only access to the approved quarantine bucket, and fail closed on unsupported, encrypted, malformed, or unscannable objects. A unit-test mock is not a malware scan.

## Sandboxed parser service

`HTTPSandboxedExtractor` calls `POST /v1/extract` with `tenant_id`, `file_id`, a private storage reference, MIME/profile, page/character bounds, and an expected `sandbox_policy_id`. The parser service must independently verify the tenant/file/object binding before reading the object; it must not authorize access from the storage reference alone. The response must repeat that policy ID and include `extractor_version`, `page_count`, and `blocks` containing text/page/section provenance.

The service must enforce, not merely echo, the requested policy and tenant/file binding: no network, no shell, CPU/memory/wall-clock limits, strict PDF structure checks, OOXML package validation (`[Content_Types].xml` and expected relationships), path traversal/symlink rejection, archive-entry/decompression-ratio limits, and no arbitrary external links. OCR stays disabled unless a separate policy explicitly enables it. The application bounds the response and validates page/text limits again before persistence.

The `sandbox_policy_id` handshake is a deployment/configuration guard, not a cryptographic attestation. Production approval still requires deployment evidence, isolation tests, and operator review.

## Required deployment evidence before enabling

1. Signed approval of ADR-018/P0-09 (provider, model revision, region, categories sent, terms, Arabic quality, latency/cost, fallback policy).
2. Approved DEC-028 retention/deletion/anonymization schedule and DEC-029 storage/KMS/region/lifecycle choice.
3. Allow-listed provider and storage buckets; external egress allow-list; secret-manager ownership and rotation.
4. mTLS certificates, scanner engine/version, parser sandbox build/policy ID, resource-limit and network-isolation evidence.
5. Orphan cleanup reconciliation, budget reservation settlement/reconciliation, provider UNKNOWN-outcome operations, and audit/alert ownership.
6. PostgreSQL migration, `alembic check`, upgrade/downgrade/re-upgrade, tenant isolation, and full integration-test evidence against a disposable PostgreSQL instance on Python 3.12.

Until those artifacts exist, keep the adapter clients unregistered, keep `DenyAllAIExecution`, keep uploads disabled, and do not send teacher/course/learner data to external services.
