# Moallem AI

Planning baseline: Moallem AI Engineering Documentation v2.4.

## Current implementation status

- Backend: locked Python 3.12.16 checks pass; `make check` reports 322 passed and one optional
  PostgreSQL test skipped. With the temporary PostgreSQL 15.19 test database, all 323 tests pass.
- Mobile foundation: Flutter shell exists; toolchain is now pinned to Flutter 3.50.0 / Dart 3.14.0.
- **P1 is not yet closed:** Flutter 3.50.0 format, analysis, tests, and Android debug APK build pass locally; a green GitHub Actions run is still required for closure.
- **P3 read adapter:** code and synthetic-fixture tests exist (`backend/src/moallem/moodle/`); it is unverified against a real Moodle. See `docs/PHASE3_STATUS.md`.
- **P4 persistence:** PostgreSQL models, Alembic migration, tenant-scoped repositories, and Moodle route injection are locally verified; production key custody and Moodle staging remain blocked. See `docs/PHASE4_STATUS.md`.
- ADR-015 (Riverpod) and ADR-016 (mypy) remain provisional pending owner sign-off.
- P2/P4 domain primitives are not a substitute for the later persistence, identity, Moodle, or queue integrations.

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
