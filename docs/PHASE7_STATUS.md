# P7 — Approval & Publish status

**Status: PARTIAL / NOT READY FOR LIVE PUBLISH.** The approval, immutable snapshot, durable publish-intent, external-step ledger, and reconciliation foundations are implemented. The production default remains deny-all; no Moodle write is enabled by this phase patch.

## Implemented

- Immutable, versioned quiz snapshots bind the full quiz content, quality report, schema version, and server-resolved Moodle destination into a canonical SHA-256 digest.
- Snapshot and approval records are append-only at the PostgreSQL level.
- Approval is tenant-, task-, membership-, snapshot-, and hash-scoped; stale snapshots are rejected. Approval decisions are idempotent and expire.
- API exposes task snapshot read and approval decision routes, protected by the permission policy. `DenyAllPolicy` remains the production default while DEC-027 is open.
- Publish intent creation is worker-only and requires an approved, current snapshot and unexpired approval.
- External operations have deterministic keys and a durable step ledger. Unknown outcomes are reconciled rather than blindly retried; verified completion is persisted with the exact snapshot hash and external object reference.
- P7 database readiness checks require the migration's tables and task result column.
- Migration `c8f2a7d91e40` follows `f4a2d9c61b80` and creates the snapshot, approval, publish-intent, and tool-invocation tables.

## Verification

- Focused P7 domain/readiness tests: **8 passed**.
- Full backend suite: **479 passed, 46 skipped, 1 failed**.
- The 46 skipped tests require a real PostgreSQL test database and applied migrations. This includes the P7 end-to-end integration test for approval, UNKNOWN outcome, reconciliation, and verified completion.
- The one failure is environmental: `tests/test_api.py::test_docs_disabled_in_production` cannot create the PostgreSQL engine because `psycopg` is not installed in this Python 3.13.5 environment.
- `python -m compileall -q src scripts`: passed.
- OpenAPI YAML parse: passed (14 paths).
- Alembic offline SQL generation: passed through head `c8f2a7d91e40` using a placeholder PostgreSQL URL. This does **not** apply the migration to a live database.

## Not closed / external gates

1. DEC-027 permission matrix and an approved teacher/administrator authorization policy. Until approved and composed, the default `DenyAllPolicy` blocks API actions.
2. DEC-043 durable budget reservation/settlement and the approved AI execution path remain prerequisites to any end-to-end AI-to-publish workflow.
3. A real Moodle write adapter, site-specific capability/profile verification, secure credential validation, and staging evidence are not included/enabled here.
4. A worker handler that composes the approved preflight, Moodle create operation, read-back verification, and P7 ledger needs to be implemented and tested against a real Moodle staging site before live publishing.
5. Run the PostgreSQL integration suite with `MOALLE​​M_TEST_DATABASE_URL` (without the zero-width formatting; use `MOALLEM_TEST_DATABASE_URL`) after applying all Alembic migrations, then verify backup/restore and deployment migration procedure.
6. Run with the project's pinned Python 3.12 and install the locked development dependencies, including `psycopg`; run Ruff and Mypy.

## Safety boundary

This implementation intentionally does not claim that a Moodle quiz was published. The repository has no live Moodle write side effect in this phase. The default `DenyAllPublishAuthorizer` blocks dispatch unless a trusted server-side authorizer is explicitly injected; API composition uses the deny-all default. Do not change this default based on client-supplied fields or test fixtures.
