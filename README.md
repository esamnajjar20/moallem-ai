# Moallem AI

Planning baseline: Moallem AI Engineering Documentation v2.4.

## Current implementation status

- Backend: locked Python 3.12.16 `make check` passes on the current worktree: Ruff, mypy (54 source
  files), **362 tests with PostgreSQL enabled**, package build, and dependency audit (one
  Starlette/httpx deprecation warning; the unpublished local package cannot be audited on PyPI).
- Mobile foundation: Flutter shell exists; toolchain is now pinned to Flutter 3.50.0 / Dart 3.14.0.
- **P1 technical gate passed on the committed baseline:** GitHub Actions run
  [#44072361770](https://github.com/esamnajjar20/moallem-ai/actions/runs/44072361770) succeeded on
  main for Backend, Android, unsigned iOS, and Secret Scan. See `docs/PHASE1_STATUS.md`; ADR-015
  and ADR-016 remain provisional.
- **P3 read adapter:** code and synthetic-fixture tests exist (`backend/src/moallem/moodle/`); it is unverified against a real Moodle. See `docs/PHASE3_STATUS.md`.
- **P4 persistence and queue:** PostgreSQL task/idempotency/event/outbox writes, tenant-scoped Inbox consumer, fail-closed dead-letter recovery service, worker leases/retries, and migrations are locally verified. No production task handler or admin recovery API is configured; `DenyAllPolicy` remains the default. These worktree changes are not in the green CI commit; production key custody and operations remain incomplete. See `docs/PHASE4_STATUS.md`.
- ADR-015 (Riverpod) and ADR-016 (mypy) remain provisional pending owner sign-off.
- P2 remains partial; the Moodle adapter has no live staging verification. The worker starts without handlers only in an idle, fail-closed mode and logs unsupported task types without claiming them.

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
