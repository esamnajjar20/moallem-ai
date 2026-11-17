# P4 remediation after independent audit

**Date:** 2026-11-17  
**Scope:** P4 task/event/Outbox, Inbox, worker, legacy receipt handling, and migration contract.  
**Base:** source snapshot `moallem-ai-main.zip`; the archive did not contain `.git` metadata.

## Remediated defects

### 1. Recovery event API contract

- Added `TASK_RECOVERED` to `TaskEventType` in `backend/src/moallem/api/task_schemas.py`.
- Added the same value to `TaskEvent.event_type` in `contracts/openapi.draft.yaml`.
- Added `test_task_event_endpoint_serializes_recovery_events` in `backend/tests/test_tasks_api.py`, which exercises the real HTTP route and checks that the recovery event is serialized successfully.

### 2. Lease validity after database lock waits

- Outbox `renew`, `acknowledge`, and `fail` now lock the row first and evaluate lease ownership, generation, and expiration using a timestamp taken after the lock is acquired.
- Outbox failure also rechecks the related Task/claim after acquiring the Task lock, so a wait on either row cannot extend an expired worker's authority.
- `transition_for_worker` now obtains the Outbox and Task locks before validating the lease, and checks again after flushing Task + TaskEvent changes. An expired claim raises `LeaseLost`, rolling back both records.
- Inbox claim and failure recording now check lease state after obtaining the receipt lock. Inbox processing validates the claim after the handler returns and again after flushing `PROCESSED`; a handler that overruns its lease raises `InboxLeaseLost`, rolling back its database effects and receipt transition.
- Expanded the PostgreSQL integration module from 33 to 42 collected cases. New cases use an observed `SELECT ... FOR UPDATE` and lock-holder coordination to force actual lock waits across lease expiry; tests assert stale ACK/renew/fail/transition/claim are rejected and a later generation can recover. This is synchronization-based fault injection, not an arbitrary timing delay intended to hide a race.

### 3. Legacy Inbox receipts and unsafe `PROCESSING` history

- A pre-tenant receipt with `tenant_id IS NULL` is retained as a deduplication tombstone. The consumer refuses to create a new tenant-scoped receipt with the same `(consumer, message_id)` and raises `InboxLegacyReceiptConflict`; it never guesses which tenant owns the historical message.
- Added a unique partial index over legacy unscoped `(consumer, message_id)` receipts to retain the uniqueness property for the tombstone set.
- Pre-tenant `PROCESSING` receipts do not contain enough tenant/lease evidence to prove whether their handler committed. The 8c migration now preserves them as non-retryable `FAILED` with `LEGACY_PROCESSING_OUTCOME_UNKNOWN`. The follow-up 9d migration repeats this quarantine for deployments that may already have applied an earlier 8c revision. It clears stale lease fields to satisfy the invariant and preserves the receipt row.
- Added tests for tombstone conflicts and migration quarantine/downgrade guards.

**Operational rule:** a quarantined legacy receipt is not automatically replayed. Reconciliation must be performed against the original source system by an authorized operator; this change intentionally avoids inventing tenant attribution or replaying a possibly committed side effect.

### 4. Handler registration

- `TaskHandlerRegistry.register` now requires a callable coroutine `execute` method at registration time. Invalid objects and synchronous handlers are rejected before they can be claimed and retried as poison tasks.
- Added unit coverage for missing and synchronous `execute` methods.

### 5. Graceful shutdown coverage

- Added a worker unit test proving an in-flight handler is cancelled after the configured zero-grace shutdown path and the worker does not ACK or record a retry for a cancelled handler. The durable lease remains to expire and be reclaimed through the normal fencing flow.

### 6. Migration metadata

- Corrected the future-dated `Create Date` comment on revision `6a1e9dce4f21` to the project date. No schema operation in that revision was changed.
- Added revision `9d4e7a2c1b60` after `8c3f1a4d2b90` for legacy Inbox tombstone uniqueness and compatibility quarantine.

## Deliberately not implemented in P4

These are not treated as defects of the current P4 persistence boundary because the repository does not include the required integration components or security approvals:

- **P5 integration:** production Moodle/AI task handlers, external dispatch adapters, broker/source Inbox ACK adapters, and end-to-end reconciliation of uncertain remote writes. The worker remains fail-safe with an empty production registry; it must not be populated with placeholder handlers.
- **P9 security/operations:** PostgreSQL RLS/role separation, KMS/Secret Manager, production secrets custody, load/lock/failover/backup testing, and measured 1,000–10,000 teacher capacity.
- **P11 administration:** administrative recovery API/UI and its role/action matrix. `DenyAllPolicy` remains the default; no bypass or permissive fallback was introduced.

## Verification status in this remediation session

- `python3 -m compileall -q src tests`: **PASS** on the available Python 3.13.5 interpreter. The project requires Python 3.12.16; compilation is a syntax check, not a replacement for the supported runtime.
- Full non-PostgreSQL pytest run with `PYTHONPATH=src` and excluding only the unrelated production-startup test that cannot import the absent PostgreSQL driver: **331 passed, 42 skipped, 1 deselected**. The 42 PostgreSQL integration cases were skipped because `MOALLEM_TEST_DATABASE_URL` is absent.
- `python3 -m alembic heads`: **PASS**, exactly one head: `9d4e7a2c1b60`. `alembic history` also resolves the linear chain from the base revision.
- `alembic check`, actual upgrade/downgrade/re-upgrade, and all 42 PostgreSQL cases: **NOT RUN** because no PostgreSQL server/client or database URL was available.
- The separate unrelated test `tests/test_api.py::test_docs_disabled_in_production` fails in this Python environment with `ModuleNotFoundError: psycopg` when it creates its explicit PostgreSQL engine. It was deselected in the 331-pass run; the test and its production assertions were not modified. The project's declared dependency includes `psycopg[binary,pool]`, but installing it and Python 3.12 was blocked by unavailable package-index DNS.
- Ruff and mypy were not available in the environment and could not be installed because package-index DNS was unavailable. No Ruff/mypy success is claimed.
- No test was removed, weakened, or skipped in source to hide a failure.

## Release decision

**P4 remains PARTIAL / NOT READY for closure** until the exact final tree is exercised on Python 3.12.16 against a disposable PostgreSQL 15+ database, including the full PostgreSQL test module, `alembic heads`, `alembic check`, and downgrade/re-upgrade. P5/P9/P11 scope above remains separately gated.
