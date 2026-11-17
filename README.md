# Moallem AI

Planning baseline: Moallem AI Engineering Documentation v2.4.

## Current implementation status

- Backend baseline verification recorded before the P5 closure changes: Python 3.12.16 `make check`,
  Ruff, mypy (54 source files), **362 tests with PostgreSQL enabled**, package build, and dependency
  audit (one Starlette/httpx deprecation warning; unpublished local package cannot be audited on PyPI).
  This historical result was not rerun on the current P5 worktree; see the P5 closure report for
  the exact current environment results.
- Mobile foundation: Flutter shell exists; toolchain is now pinned to Flutter 3.50.0 / Dart 3.14.0.
- **P1 technical gate passed on the committed baseline:** GitHub Actions run
  [#44072361770](https://github.com/esamnajjar20/moallem-ai/actions/runs/44072361770) succeeded on
  main for Backend, Android, unsigned iOS, and Secret Scan. See `docs/PHASE1_STATUS.md`; ADR-015
  and ADR-016 remain provisional.
- **P3 read adapter:** code and synthetic-fixture tests exist (`backend/src/moallem/moodle/`); versioned routes are exposed under `/api/v1`, course context reads verify enrolment of the connected Moodle principal, and safe file provenance metadata is returned. This is not proof of a teacher role, and the adapter remains unverified against a real Moodle. See `docs/PHASE3_STATUS.md`.
- **P4 persistence and queue:** PostgreSQL task/idempotency/event/outbox writes, tenant-scoped Inbox consumer, fail-closed dead-letter recovery service, worker leases/retries, and migrations are locally verified. No production task handler or admin recovery API is configured; `DenyAllPolicy` remains the default. These worktree changes are not in the green CI commit; production key custody and operations remain incomplete. See `docs/PHASE4_STATUS.md`.
- **P5 AI Gateway + secure file provenance:** application-side provider/storage/scanner/sandbox HTTP clients and fail-closed pipelines are implemented as opt-in adapters. `DenyAllAIExecution` remains the default; no provider or file service is enabled. P5 remains **PARTIAL / NOT READY** pending ADR-018/P0-09, DEC-028/029 approvals, production budget/reconciliation, actual storage/scanner/parser deployments, and PostgreSQL/Python 3.12 validation. See `docs/PHASE5_STATUS.md` and `docs/P5_CLOSURE_REPORT_AR.md`. Current local verification: 406 backend tests passed, 45 PostgreSQL tests skipped, one environment failure due missing `psycopg`; do not treat this as a production gate pass.
- ADR-015 (Riverpod) and ADR-016 (mypy) remain provisional pending owner sign-off.
- P2 remains partial; connection enrollment/rotation/disconnect HTTP operations and the approved permission matrix are not complete. The Moodle adapter has no live staging verification. The worker starts without handlers only in an idle, fail-closed mode and logs unsupported task types without claiming them.

## Repository layout

```text
backend/    FastAPI API + Worker skeleton (Python 3.12.16)
mobile/     Flutter shell (Flutter 3.50.0 / Dart 3.14.0, Arabic RTL)
contracts/  OpenAPI draft and agent runtime limits (not frozen)
docs/       ADRs and phase status
scripts/    Repeatable local bootstrap and CI prerequisite checks
```

## Backend quick start

```bash
cd backend
cp .env.example .env
uv sync --locked
make -C .. check
make -C .. api
```

## Mobile one-time setup

Install Flutter 3.50.0, then run from the repository root:

```bash
./scripts/bootstrap_mobile.sh
```

Review and commit the generated `mobile/pubspec.lock`, `mobile/android/`, and `mobile/ios/`.

See [`docs/PHASE1_STATUS.md`](docs/PHASE1_STATUS.md) for the exact exit gate and evidence.
