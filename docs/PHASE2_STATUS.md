# P2 — Identity and tenancy status

**Status: NOT CLOSED.** Local implementation and HTTP checks pass, but P2 depends on open product,
security, architecture, and infrastructure decisions. The default authenticator remains
fail-closed; authorization defaults to `DenyAllPolicy`. No database, Redis, object-storage, or
queue integration is implemented.

**Assessment date:** 2026-11-16
**Baseline:** Engineering Documentation v2.4
**Exit gate:** owner-approved identity/session and authorization decisions, configured secret
management, persistent tenant isolation, and the required infrastructure evidence.

## Verification evidence

| Check | Result | Evidence |
|---|---|---|
| Python / locked environment | PASS | Python **3.12.16** (`backend/.python-version`); `uv sync --locked` with uv **0.13.8** resolved 61 packages and checked 60. |
| Ruff | PASS | Ruff **0.17.5**; `ruff format --check .` and `ruff check .` passed. |
| mypy | PASS | mypy **1.20.2**; 39 source files, no issues. |
| Backend tests | PASS | `uv run --locked pytest -ra`: **314 passed, 1 Starlette/httpx deprecation warning**. |
| Tenancy HTTP tests | PASS | `tests/test_tenancy_api.py`: **6 passed**, including AT-015, AT-031, and AT-037 over FastAPI HTTP requests. |
| Identity/config HTTP tests | PASS | `test_api.py`, `test_bearer_api.py`, `test_me_api.py`, `test_jwks.py`, `test_config.py`, and `test_checks.py` all passed in the full suite. |
| Package and dependency audit | PASS WITH QUALIFICATION | `uv build` built sdist and wheel. `pip-audit` found no known vulnerabilities but skipped the unpublished local `moallem 0.0.1` package. |
| GitHub Actions / production integrations | NOT RUN | A local test result is not a green CI run or evidence from live identity, persistence, or Moodle services. |

## Implemented scope

- **Membership context:** active membership is resolved server-side from
  `X-Active-Membership-ID`; malformed/missing/invalid contexts fail closed. Tenant identity is
  derived from the membership, not a client-supplied tenant header.
- **Authorization:** `require_tenant` hides cross-tenant resources as 404 (AT-015), then explicit
  permission evaluation applies. `DenyAllPolicy` remains the default while DEC-027 is open.
- **Authentication:** `NoAuthenticator` remains the production default unless issuer/audience
  configuration is explicitly provided. Bearer verification, issuer/audience/expiry checks, and
  subject mapping are implemented behind seams; this does not approve ADR-017 or select a provider.
- **JWKS and RS256:** HTTPS JWKS retrieval has size/cache limits and fails closed. The custom
  standard-library RS256 verifier is security-sensitive and should be replaced by a vetted
  implementation.
- **Secret boundary:** `SecretRef` and `SecretVault` interfaces exist; no operational secret
  manager or Moodle credential persistence is configured.
- **Tenant-scoped primitives:** scoped repository interfaces and tenant-derived cache/storage/
  message keys are unit-tested. They do not provide actual Redis, S3, broker, or database isolation.
- **P4 domain-only primitives:** task state, idempotency, events, outbox, and inbox logic remain
  in-memory/domain-level foundations only; no database DDL, dispatcher, or broker was added.
- **P2/P3 integration seam:** `MoodleReadService` performs tenant, permission, and connection-state
  checks before exposing a token to the adapter. See `PHASE3_STATUS.md`; live Moodle behavior is
  still unverified.

## Open decisions and blockers

| Decision / evidence | Owner or dependency | State |
|---|---|---|
| ADR-017 identity provider, issuer/audience, sessions and revocation | Product + Security | OPEN |
| ADR-015 state-management approval; ADR-016 type-checker approval | Product / Engineering owners | PROVISIONAL |
| DEC-026 site-sharing model; DEC-027 permission matrix; DEC-032 isolation strategy | Product, Security, Architecture | OPEN |
| DEC-030 broker and DEC-031 database schema/keys | Architecture / Data owners | OPEN; blocks persistence |
| Secret Manager selection and operational key custody | Security / Platform owners | OPEN |
| ADR-020 hosting, network egress, and private-campus connector | Infrastructure / Security owners | OPEN |
| P0-02/03/04 Moodle staging URL, current API evidence, and teacher account | Moodle administrator | BLOCKED |
| DEC-033 question-domain selection and AI provider | Product / Education and Engineering owners | OPEN; no AI code added |

Additional engineering proposals remain unapproved: decimal handling and NFC ordering for
canonical content, task-cancellation transition extensions, and the membership-context error
mapping. Do not treat these proposals as decisions.

## Security risk and proposed follow-up

`backend/src/moallem/domain/rs256.py` implements RSA signature verification by hand. Its current
tests pass, but test success does not provide the assurance of a vetted cryptographic library.
Replacing it with `PyJWT[crypto]` is recommended as a **separate, owner-approved dependency change**;
no dependency or lockfile change was made in this verification task.

**Do not mark P2 CLOSED** until the owners resolve the open decisions and the blocked persistence,
secret-management, and infrastructure evidence is available.
