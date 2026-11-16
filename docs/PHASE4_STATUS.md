# P4 — PostgreSQL persistence and Moodle API routes

**Status: LOCALLY VERIFIED, NOT CLOSED.** The owner approved PostgreSQL and AES-256-GCM. Models,
an initial Alembic migration, repository adapters, and explicit `MoodleReadService` route injection
are implemented. Local integration tests pass against a temporary PostgreSQL 15.19 instance.
Production deployment, operational key custody, isolation review, and Moodle staging evidence
remain outstanding.

## Implemented

- SQLAlchemy models cover users, tenants, memberships, encrypted secret references, Moodle
  connections, and the task/idempotency/event/outbox/inbox tables in the P4 planning scope.
- Alembic migration creates and drops the schema. `alembic/env.py` requires
  `MOALLEM_DATABASE_URL`; credentials are not embedded in migration files.
- PostgreSQL adapters implement membership lookup, pre-provisioned Auth0 subject mapping, and
  tenant-filtered Moodle connection CRUD. A PostgreSQL development vault encrypts tokens with
  AES-256-GCM and uses tenant/reference associated data.
- `GET /courses` and `GET /courses/{course_id}/context` require
  `X-Active-Membership-ID` and invoke the injected `MoodleReadService`. A missing service returns
  503; no Moodle network transport, resolver, or service is enabled automatically.
- HTTP tests cover route contract parameters, fail-closed behavior, and a synthetic successful
  read through `MoodleReadService` and fake transport. `source_refs` is currently empty.

## Verification evidence

| Check | Result |
|---|---|
| Python | Python 3.12.16 (`backend/.python-version`) |
| Ruff check and format | PASS |
| mypy | PASS; 45 source files |
| Targeted routes/config/encryption tests | PASS; 18 passed |
| PostgreSQL repository integration | PASS; 1 passed against local PostgreSQL 15.19 using synthetic records |
| Alembic lifecycle | PASS; downgrade to base, upgrade to head, then `alembic check` reported no pending operations |
| Full `make check` | PASS; Ruff, formatting, mypy (45 files), pytest (**322 passed, 1 optional DB test skipped**), `uv build`, and `pip-audit` |
| Test suite with PostgreSQL enabled | PASS; **323 passed**, 1 Starlette/httpx deprecation warning |
| Dependency audit | PASS; no known vulnerabilities in audited dependencies; unpublished local package is not on PyPI |
| Moodle staging interoperability | **BLOCKED**; no Moodle staging URL/account or real sanitized fixtures |

Integration test instructions (after provisioning a disposable PostgreSQL test database and
applying the migration):

```bash
cd backend
export MOALLEM_DATABASE_URL='postgresql+psycopg://…'
export MOALLEM_TEST_DATABASE_URL="$MOALLEM_DATABASE_URL"
uv run --locked alembic upgrade head
uv run --locked pytest -q tests/persistence/test_postgres_repositories.py
```

The test inserts synthetic identities and a synthetic Moodle token, verifies that the database
stores ciphertext rather than the token, tests tenant-scoped connection lookups, and removes its
records. Never use production credentials or data for this test.

## Remaining blockers and risks

- Auth0 issuer/audience and session lifecycle, the final permission matrix (`DenyAllPolicy`
  remains the default), tenant isolation/RLS review, broker/Redis, and production KMS/Secret Manager
  remain unresolved or unimplemented.
- The app requires explicit safe construction/injection of `MoodleReadService`; the default
  `create_app()` deliberately leaves it unset. No live Moodle request has been made.
- The route paths remain at the root as currently implemented; compare deployment base-path
  routing with the OpenAPI draft before claiming full contract parity. The contract was not changed.
- Moodle teacher-only course semantics, real error behavior, and course/content field compatibility
  remain unverified until Moodle Admin provides staging access.

**Do not mark P4 or the Moodle validation gate CLOSED** based on these local PostgreSQL and synthetic
HTTP tests.
