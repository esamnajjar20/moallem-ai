# P4 — PostgreSQL persistence, queue, Inbox, and recovery

**Status: PARTIAL, NOT CLOSED.** PostgreSQL `FOR UPDATE SKIP LOCKED` is the approved MVP queue.
Task persistence, the Outbox worker, Inbox processing, and protected dead-letter recovery are
implemented and locally verified against PostgreSQL. There are no production task handlers, no
configured administrative authorization, and no CI result for this worktree.

## Implemented

- SQLAlchemy models and migrations cover tenant-scoped tasks, events, idempotency, Outbox, Inbox,
  and task-recovery lineage. The current Alembic revision is `8c3f1a4d2b90`.
- `PostgresTaskRepository.create_idempotent` persists the idempotency record, task, initial event,
  and Outbox row in one transaction. Rollback, duplicate requests, and concurrent creation are
  tested. PostgreSQL composite foreign keys prevent cross-tenant Moodle connections and task
  recovery parents; a unique parent-recovery constraint prevents concurrent duplicate retries.
- The task API provides `POST /tasks`, `GET /tasks/{task_id}`, and
  `GET /tasks/{task_id}/events`. Access is membership/tenant scoped and permissions remain
  fail-closed under `DenyAllPolicy` unless an explicit policy is injected.
- `PostgresOutboxRepository` implements `FOR UPDATE SKIP LOCKED`, expiring leases, fencing
  generations, renewal, ACK, bounded retry, and Dead Letter transitions. Worker task-state changes
  and their event records are transactional. Claims are filtered to registered handler types;
  unsupported or malformed task types are reported and not claimed. With no registered handlers,
  the worker idles and logs its status rather than consuming work.
- `PostgresInboxConsumer` deduplicates on `(tenant_id, consumer, message_id)`, stores a canonical
  payload hash, and uses receipt leases/generations. A handler's database changes and the
  `PROCESSED` receipt commit together; the source adapter must ACK only when the returned result
  permits it. Retryable failures remain unacknowledged, while permanent/exhausted failures are
  recorded and acknowledged. External effects must be emitted through an Outbox.
- `TaskRecoveryService` lists and recovers Dead Letters but exposes no API endpoint. Its default
  policy is `DenyAllPolicy`; tests use an explicit allow-list. Recovery preserves the failed task,
  writes the requesting actor and reason to a new event, creates an idempotent linked task, and
  refuses recovery when dispatch/history indicates a possible external effect. The failed task's
  prior events and error remain intact.
- Worker retry behavior includes exponential backoff and jitter, max attempts, lease renewal,
  fencing, and graceful shutdown. Bounded idempotency cleanup excludes unresolved operations.

## Verification evidence

| Check | Result |
|---|---|
| Python | Python 3.12.16 (`backend/.python-version`) |
| `make check` | **PASS**: Ruff check/format, mypy (54 source files), **362 passed**, `uv build`, and `pip-audit` |
| PostgreSQL integration | **PASS**: all **33** tests in `tests/persistence/test_postgres_repositories.py`, including Inbox dedup/rollback/retry/lease expiry/concurrency/tenant scope, handler filtering, dead-letter recovery authorization and concurrency, downgrade guards, and a task lifecycle through success, retry, crash recovery, idempotent replay, and administrative recovery |
| Alembic | **PASS**: one head, `8c3f1a4d2b90`; `alembic check` reports “No new upgrade operations detected” |
| Migration compatibility | **PASS**: downgrade/re-upgrade exercised by PostgreSQL tests; legacy Inbox `COMPLETED` data survives a round trip as `PROCESSED`; orphan records and unsafe downgrade data are rejected without deleting data |
| Dependency audit | **PASS WITH QUALIFICATION**: no known vulnerabilities; the unpublished local `moallem 0.0.1` package cannot be audited on PyPI |
| Secret scan | Common hard-coded token/private-key patterns were scanned locally with no matches. Gitleaks was unavailable locally; the prior green CI Secret Scan does not cover this worktree |
| Warning | One Starlette deprecation warning: `starlette.testclient` currently uses `httpx`; test results are unaffected |
| GitHub Actions | **NOT RUN for this worktree**; earlier green CI applies only to its committed SHA |
| Moodle / external effects | **NOT RUN**; no Moodle write or AI handler was added |

The local PostgreSQL integration run used a disposable PostgreSQL 15 Alpine container, synthetic
identities and connection data, and no live Moodle credentials. It is not evidence of production
deployment, operational capacity, or Moodle compatibility.

## Remaining work, blockers, and risks

- No production task handler is registered. The worker's registry and lifecycle were exercised with
  synthetic test handlers only; no Moodle, AI, approval, or publishing operation is implemented.
- Inbox receipt processing is a persistence/consumer primitive; no external broker or source adapter
  is connected. The adapter must implement ACK/redelivery according to `InboxResult`.
- Administrative recovery has no API endpoint and remains inaccessible by default. Product/Security
  owners must approve the role/action matrix before any production policy is injected; do not bypass
  `DenyAllPolicy`.
- The no-external-effect check relies on persisted dispatch flags and task history. Any future
  handler must durably record dispatch before making an external write and use Outbox for external
  effects; this invariant has not been exercised against a real integration.
- Queue throughput, lock contention, failover, backup/restore, production key custody, and the
  1,000–10,000 teacher target are not benchmarked or proven. No production deployment is claimed.
- Secret Manager/KMS, hosting, operational monitoring, and database isolation/RLS decisions remain
  open. Moodle staging credentials, a teacher account, and real sanitized fixtures remain blocked
  on the Moodle administrator.
- The worktree remains local and uncommitted. Do not treat the older green CI run as verification of
  these changes.

**Do not mark P4 or the Moodle validation gate CLOSED.**
