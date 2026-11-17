# P1 execution notes — updated 2026-11-17

This change set hardens the repository foundation without moving P2/P3/P4 implementation scope
into P1.

## Changed

- Pinned Python 3.12.16 and Flutter 3.50.0 toolchains.
- Pinned GitHub Actions to immutable commit SHAs; moved Gitleaks from v2 to v3.
- Added Android and iOS build jobs to CI, plus explicit checks for committed native runners and
  `mobile/pubspec.lock`.
- Added `scripts/bootstrap_mobile.sh` to create native platform projects with Flutter, resolve and
  lock dependencies, format, analyze and test.
- Added mobile prerequisite checks and Makefile targets.
- Corrected stale P1 status using the green CI evidence; ADR-015/016 remain provisional because
  their governance approvals are separate from CI.
- Added PostgreSQL service, Alembic migration, and PostgreSQL-backed tests to the Backend CI job.

## Current verification

- GitHub Actions run [#44072361770](https://github.com/esamnajjar20/moallem-ai/actions/runs/44072361770)
  succeeded on committed SHA `a02b508a4a52c0a79486eefeea38446871b75194`: Backend, Android, unsigned
  iOS, and Secret Scan all passed. Backend ran Alembic and **323 tests** with PostgreSQL enabled.
- Latest local `make check` on the current worktree passed with PostgreSQL enabled: Ruff, formatting
  (100 files), mypy (54 source files), **362 tests with one Starlette/httpx deprecation warning**,
  package build, and `pip-audit` with no known vulnerabilities. The current uncommitted worktree
  changes are not covered by the cited CI run.
- The Flutter lockfile and native runners are committed and verified by CI.
- The `com.moallem` application ID prefix remains provisional pending publisher confirmation.
- ADR-015/016 remain governance decisions; P2–P4 and live Moodle integration are outside this P1
  evidence.

## Immutable action references

| Action | Pinned commit | Release line |
|---|---|---|
| `actions/checkout` | `d23441a48e516b6c34aea4fa41551a30e30af803` | v6 |
| `astral-sh/setup-uv` | `68559e99cc807c1eb7e9238fd43a15bba460eec2` | v10.3.3 |
| `subosito/flutter-action` | `1a449444c387b1966244ae4d4f8c696479add0b2` | v2.23.0 |
| `gitleaks/gitleaks-action` | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` | v3 |
