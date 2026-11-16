# P2 — Identity and tenancy status

**Status: NOT CLOSED.** The owner approved Auth0, PostgreSQL, AES-256-GCM, and Engineering
Documentation v2.4 on 2026-11-16. Local PostgreSQL persistence now covers membership, Auth0
subject mapping, tenant-scoped Moodle connections, and an AES-GCM development vault. Remaining
identity/session, authorization, tenant-isolation, key-custody, and deployment decisions still
block closure. The default authenticator remains fail-closed and authorization defaults to
`DenyAllPolicy`.

**Assessment date:** 2026-11-16
**Baseline:** Engineering Documentation v2.4
**Exit gate:** owner-approved identity/session and authorization decisions, configured secret
management, persistent tenant isolation, and the required infrastructure evidence.

## Verification evidence

| Check | Result | Evidence |
|---|---|---|
| Python / locked environment | PASS | Python **3.12.16** (`backend/.python-version`); `uv sync --locked` with uv **0.13.8** resolved 61 packages and checked 60. |
| Ruff | PASS | Ruff **0.17.5**; `ruff format --check .` and `ruff check .` passed. |
| mypy | PASS | mypy **1.20.2**; 45 source files, no issues. |
| Backend tests | PASS | Full suite: **322 passed, 1 skipped** when the optional PostgreSQL test URL is unset. With the temporary PostgreSQL 15.19 test database configured: **323 passed, 1 Starlette/httpx deprecation warning**. |
| Tenancy HTTP tests | PASS | `tests/test_tenancy_api.py`: **6 passed**, including AT-015, AT-031, and AT-037 over FastAPI HTTP requests. |
| Identity/config HTTP tests | PASS | `test_api.py`, `test_bearer_api.py`, `test_me_api.py`, `test_jwks.py`, `test_config.py`, and `test_checks.py` all passed in the full suite. |
| Package and dependency audit | PASS WITH QUALIFICATION | `uv build` built sdist and wheel. `pip-audit` found no known vulnerabilities after updating locked `cryptography` to 50.0.2; it skipped the unpublished local `moallem 0.0.1` package. |
| GitHub Actions / production integrations | NOT RUN | A local test result is not a green CI run or evidence from live identity, persistence, or Moodle services. |

## Implemented scope

- **Membership context:** active membership is resolved server-side from
  `X-Active-Membership-ID`; malformed/missing/invalid contexts fail closed. Tenant identity is
  derived from the membership, not a client-supplied tenant header.
- **Authorization:** `require_tenant` hides cross-tenant resources as 404 (AT-015), then explicit
  permission evaluation applies. `DenyAllPolicy` remains the default while DEC-027 is open.
- **Authentication:** Auth0 is the owner-approved provider. Bearer verification, issuer/audience/
  expiry checks, and pre-provisioned subject mapping are implemented; production still fails
  closed without configured issuer/audience and persistent membership records.
- **JWKS and RS256:** HTTPS JWKS retrieval has size/cache limits and fails closed. RS256 verification
  uses PyJWT/cryptography; this does not replace operational Auth0 configuration or evidence.
- **Secret boundary:** Moodle credential references are tenant-scoped in PostgreSQL and encrypted
  at rest by the AES-256-GCM development vault. The environment-provided key is development-only;
  no production KMS/Secret Manager is configured.
- **PostgreSQL:** SQLAlchemy models and an Alembic migration cover users, memberships, Moodle
  connections, secret references, and P4 task/idempotency/event/outbox/inbox tables. PostgreSQL
  membership lookup, subject mapping, tenant-scoped connection access, and encrypted-vault
  round-trips passed a local PostgreSQL integration test. This is not production deployment,
  row-level security, or proof of operational isolation.
- **Other infrastructure:** Redis, object storage, and a queue/broker are not integrated.
- **P4 domain-only primitives:** task state, idempotency, events, outbox, and inbox logic remain
  in-memory/domain-level foundations only; no database DDL, dispatcher, or broker was added.
- **P2/P3 integration seam:** `MoodleReadService` performs tenant, permission, and connection-state
  checks before exposing a token to the adapter. See `PHASE3_STATUS.md`; live Moodle behavior is
  still unverified.

## Open decisions and blockers

| Decision / evidence | Owner or dependency | State |
|---|---|---|
| ADR-017 identity provider | Owner | APPROVED: Auth0; issuer/audience, sessions and revocation remain OPEN |
| ADR-015 state-management approval; ADR-016 type-checker approval | Product / Engineering owners | PROVISIONAL |
| DEC-026 site-sharing model; DEC-027 permission matrix; DEC-032 isolation strategy | Product, Security, Architecture | OPEN |
| DEC-030 broker | Architecture / Data owners | OPEN; blocks queue integration |
| PostgreSQL schema/isolation and production key strategy | Architecture / Security owners | PARTLY OPEN; PostgreSQL and AES-256-GCM approved; RLS/schema review and key operations remain |
| Secret Manager selection and operational key custody | Security / Platform owners | OPEN; production AES key is not configured |
| ADR-020 hosting, network egress, and private-campus connector | Infrastructure / Security owners | OPEN |
| P0-02/03/04 Moodle staging URL, current API evidence, and teacher account | Moodle administrator | BLOCKED |
| DEC-033 question-domain selection and AI provider | Product / Education and Engineering owners | OPEN; no AI code added |

Additional engineering proposals remain unapproved: decimal handling and NFC ordering for
canonical content, task-cancellation transition extensions, and the membership-context error
mapping. Do not treat these proposals as decisions.

## Security risk and proposed follow-up

The development vault stores authenticated AES-GCM ciphertext in PostgreSQL and binds it to tenant
and secret-reference identifiers. The encryption key is supplied through environment configuration
only in development/test; do not use that mode in production. Production key custody, rotation,
backup/recovery, and KMS/Secret Manager integration remain unresolved and must be fail-closed.

**Do not mark P2 CLOSED** until the owners resolve the open decisions and the blocked persistence,
secret-management, and infrastructure evidence is available.
