# P5 — AI Gateway, usage ledger, secure files, and source provenance

**Status: PARTIAL / NOT READY.** The application-side provider and file-service clients, scope contracts, fail-closed pipeline, and unit tests are implemented. P5 is not production-enabled and is not closed: required privacy/provider/storage approvals and the external services themselves are not present. PostgreSQL integration and static analysis gates could not be executed in this environment.

## Scope and owner decisions

The scope is taken from `Implementation_Control_v2.5_P5.xlsx`, sheet `Execution Backlog`:

- **P5-01 — AI provider gateway and usage ledger.** The provider-neutral gateway/ledger and HTTP adapter pre-existed. This pass adds optional all-or-none `MOALLEM_AI_*` settings, a strict exact-host allow-list, a non-fallback `StaticAIProviderRegistry`, a provider factory, request/response bounds, and stronger runtime contract validation. The registry/factory are not composed into API/Worker, and no live execution is enabled. P0-09 / ADR-018 provider, model revision, data classes, region, privacy terms and production authorization/budget policy remain unapproved.
- **P5-02 — secure file intake/extraction and provenance.** The application clients for private quarantine storage, malware scanning and sandboxed extraction are implemented. The corresponding service deployments, storage/KMS/region/lifecycle decisions, scanner engine and parser sandbox are not. DEC-028 and DEC-029 remain open.

These owner decisions cannot be made by code changes. No provider, region, retention schedule, KMS key policy, or external service has been selected on the user's behalf.

## Implemented in the application

### P5-01 — AI Gateway

- `backend/src/moallem/ai/http_provider.py` adds `OpenAICompatibleHTTPProvider`, an opt-in HTTPS Chat Completions client with bounded responses, pinned model ID matching, no redirects, no automatic retry, and explicit unknown-outcome treatment. It does not log prompt/completion bodies.
- Optional provider transport registration is now implemented by `StaticAIProviderRegistry` and `build_ai_provider_registry(settings)`. The factory returns an empty registry when unconfigured, or registers only the single exact provider/model/version/region from the complete settings group. It performs no fallback selection and is deliberately not wired into API/Worker startup. `DenyAllAIExecution` remains the default and rejects AI dispatch until an approved authorizer is injected. The adapter's provider/model-version/region identity values are deployment assertions, not independently verified facts from the remote endpoint.
- Provider settings are optional and all-or-none. API keys use `SecretStr`; provider endpoints must use HTTPS and an exact DNS hostname allow-list. Wildcard hosts and IP literals are rejected. The adapter applies request/response byte limits, identity-only encoding, no redirects, no automatic retries, pinned response model ID, and safe `UNKNOWN` treatment for ambiguous outcomes. `AIRequest`, `AIProviderResponse`, `TokenUsage`, and `ProviderIdentity` now enforce stronger boundary validation.
- `AIGateway` records invocation identity and request hash before external dispatch; it rejects duplicate/conflicting invocation IDs, does not retry ambiguous provider outcomes, records usage/cost metadata, and settles the reservation after successful ledger completion. Cancellation after provider response waits for ledger completion and settlement before propagating cancellation.
- `PostgresAIUsageLedgerRepository` persists the usage record and source-reference links atomically, validates identity/hash/currency/cost, and checks source tenant/course/file/chunk state and content hash.
- A production budget authorizer/reservation/reconciliation service is still not implemented. The `AIExecutionAuthorizer` is a contract; `DenyAllAIExecution` is the only safe default. No persisted orphan-reservation recovery worker or automated `UNKNOWN`-outcome reconciliation is present.

### P5-02 — private file-service adapters

- `backend/src/moallem/files/http_adapters.py` adds `HTTPQuarantineStorage`, `HTTPMalwareScanner`, and `HTTPSandboxedExtractor` clients. They require HTTPS and can use `build_mtls_client` with CA and client certificate/key. Environment proxy inheritance and redirects are disabled for internal clients.
- Storage requires an explicit private-bucket allow-list, streams file bytes, and deletes only using the canonical tenant/file identity after a failed registration or invalid returned reference. Cleanup failure is surfaced.
- Scanner requests include **tenant_id, file_id, and storage_ref**. The scanner service must validate the exact object-to-tenant/file mapping before reading data. A scanner ID mismatch or invalid response is never treated as CLEAN.
- Parser requests also include tenant_id/file_id plus profile and limits. The parser service must verify object ownership itself, enforce the selected `sandbox_policy_id`, network/shell isolation and resource limits, and complete PDF/OOXML validation. OCR remains disabled unless explicitly enabled.
- Both scanner and parser clients restrict storage references to explicitly configured buckets. Unit tests verify the tenant/file identity is passed intact. These clients do not prove that remote storage, AV, or parser services have actually been deployed or securely configured.
- `httpx` is a runtime dependency because the new service adapters import it in application code.

### Current P5-01 model-foundation update

The model transport foundation is now configurable and composable without making it executable:

- `backend/src/moallem/ai/factory.py` builds an empty registry by default, or one explicitly pinned provider when the full configuration group is present.
- `StaticAIProviderRegistry` uses exact IDs, rejects duplicates, exposes no fallback behavior, and attempts to close all managed adapters.
- `docs/adr/ADR-018-ai-provider-model-region.md` records that provider/model/region selection remains OPEN; `docs/AI_MODEL_CONFIGURATION.md` documents the safe opt-in transport settings.
- `DenyAllAIExecution` is unchanged and remains the only default execution policy. No production authorizer, durable budget reservation, settlement/reconciliation worker, live provider credentials, or AI Worker handler was added.

### Database and migrations

- P5 migration `b51a7c2d9e30` creates usage-ledger and source-provenance tables and composite tenant/course/task relationships.
- P5 migration `d61f8a2c9e34` aligns the course ID width and constrains SHA-256 and private storage references.
- Alembic reports exactly one head: `d61f8a2c9e34`.
- Historical migration guards that previously queried with Python `scalar_one()` during offline generation were moved to PostgreSQL `DO` blocks, preserving the data guards while allowing full offline SQL review.

## Verification results

| Check | Result | Evidence / qualification |
|---|---:|---|
| Focused AI + config tests (current model pass) | **63 passed** | Covers provider registry/factory, transport bounds, contracts, gateway accounting, and optional settings. Uses HTTP mock transports, not production services. |
| Full backend pytest (current checkout) | **442 passed, 45 skipped, 1 failed** | The 45 PostgreSQL tests skip because `MOALLEM_TEST_DATABASE_URL` and a PostgreSQL service are absent. The sole failure occurs when `test_docs_disabled_in_production` constructs a PostgreSQL engine and the environment lacks the declared `psycopg` runtime package. No test was removed or weakened. |
| `python -m compileall -q backend/src backend/tests backend/scripts backend/alembic/versions` | **PASS** | Python 3.13.5 only; project constraint is `>=3.12,<3.13`. This does not replace validation on Python 3.12. |
| `alembic heads` | **PASS** | Exactly one head: `d61f8a2c9e34`. |
| Full `alembic upgrade head --sql` | **PASS** | Generated PostgreSQL SQL for the entire chain from `base` to head (438 lines). Offline SQL generation only; no database writes occurred. |
| Full `alembic downgrade head:base --sql` | **PASS** | Generated complete downgrade SQL (222 lines). This does not prove the downgrades execute successfully against populated PostgreSQL data. |
| `alembic check` | **NOT RUN** | Requires a live database connection/schema reflection. |
| Live PostgreSQL migrations and integration tests | **NOT RUN** | No PostgreSQL service/URL available. |
| Ruff / Mypy | **NOT RUN** | Executables/modules are not installed in this environment. |
| Provider/storage/scanner/parser live E2E | **NOT RUN** | External provider and internal file services are not selected/deployed/approved. |

## Remaining production gates (not safely closable from this checkout)

1. **P0-09 / ADR-018 approval:** provider, exact model revision, processing region, allowed data classes, contractual privacy terms, Arabic-quality acceptance, cost/latency limits and fallback policy.
2. **DEC-028:** retention, deletion and anonymization schedule for prompts, usage metadata, files, extracted chunks and provider data.
3. **DEC-029:** private object-store provider/bucket, region, KMS key ownership, encryption policy, lifecycle and deletion evidence.
4. Production `AIExecutionAuthorizer`: persistent budget reservation/settlement/reconciliation, actor/tenant policy, audit ownership and orphan-reservation recovery. The current contract and deny-all default are not a production budget system.
5. Deploy and independently verify the storage gateway, malware-scanning engine and isolated PDF/OOXML sandbox. Their clients now require tenant/file binding, but the server-side services must enforce it.
6. Define operator handling for provider outcome `UNKNOWN`; it must not be blindly retried because doing so can duplicate costs or actions.
7. Deploy/reconcile orphaned quarantine objects and failed metadata cleanup. The client reports cleanup failures; no production orphan sweeper is proven here.
8. Connect the approved components to production API/Worker execution and prove the end-to-end permissions and data flow. These modules are not enabled by default.
9. Run the full test/migration/check suite on Python 3.12 and a disposable PostgreSQL instance, including `alembic check`, upgrade, downgrade/re-upgrade, concurrency, and tenant-isolation integration tests.
10. Embeddings/vector index/retrieval ranking are not implemented in this P5 code; `ContextBuilder` supplies validated provenance-aware context but is not a complete RAG retrieval platform.

## Final decision

**P5 = PARTIAL / NOT READY.** Application-side adapter code and local contract verification are complete for the current source scope, but owner approvals, external service deployments, persistent budget authorization/reconciliation, live PostgreSQL verification, and Python 3.12/static-analysis checks remain open. Keep `DenyAllAIExecution`, do not register a provider, and do not enable uploads or send real teacher/learner data until all relevant approvals and operational evidence are recorded.
