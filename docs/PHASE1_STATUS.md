# P1 — Repository Foundation: closure status

**Status: TECHNICAL GATE CLOSED WITH EVIDENCE (2026-11-17).** GitHub Actions run
[#44072361770](https://github.com/esamnajjar20/moallem-ai/actions/runs/44072361770) tested
`a02b508a4a52c0a79486eefeea38446871b75194`; Backend, Android, unsigned iOS, and Secret Scan all
passed. The `com.moallem` application ID remains provisional and unchanged. ADR-015/016 governance
approvals remain separate from this technical gate. The uncommitted worktree changes under review
are not included in that CI run.

**Assessment date:** 2026-11-17
**Baseline:** `09_Implementation_Roadmap_v2.0` in Engineering Documentation v2.4  
**Exit gate:** reproducible Backend + Flutter builds, lint/type-check/test gates, and a green CI run.

## P1 checklist

| ID | Requirement | Current state | Evidence / remaining work |
|---|---|---|---|
| P1-01 | API, Worker and Flutter skeleton | IMPLEMENTED / LOCALLY VERIFIED | Python 3.12.16 locked checks pass; Flutter lockfile and Android/iOS runners exist. Flutter 3.50.0 format, analysis, tests, and debug APK build pass. The application ID stays provisional. |
| P1-02 | CI gates | VERIFIED | CI pins actions to immutable commit SHAs. Run #44072361770 passed Backend, Android, iOS, and Secret Scan on the committed SHA cited above; current uncommitted changes are not covered. |
| P1-03 | Config, health and readiness | IMPLEMENTED | `config.py` validates configuration fail-fast; `/healthz` and `/readyz` exist; structured JSON logging redacts sensitive values and carries request IDs. API/config/logging tests are included. |

## Verification evidence

| Check | Result | Qualification |
|---|---|---|
| Backend locked checks | **PASS** | Local `make check` on 2026-11-17 used `uv run --locked`, Python 3.12.16, uv 0.13.8, and PostgreSQL. |
| Ruff format/check | **PASS** | Current worktree `make check`: `ruff check .` and `ruff format --check .`; 100 files formatted. |
| mypy | **PASS** | Current worktree `make check`: **54 source files**, no issues. |
| Backend tests | **PASS** | Current worktree: **362 passed, 1 warning**, with PostgreSQL migration and integration enabled. CI run #44072361770 passed 323 tests on the earlier committed SHA; it does not cover the current worktree changes. |
| Backend build/audit | **PASS WITH AUDIT QUALIFICATION** | Local `make check` built sdist and wheel. `pip-audit` found no known vulnerabilities; it skipped local `moallem 0.0.1` because it is not on PyPI. |
| Flutter pub/format/analyze/tests | **PASS** | Flutter 3.50.0 / Dart 3.14.0; enforced-lockfile pub get succeeded, 6 Dart files unchanged, analyze clean, **3 tests passed**. |
| Android debug APK | **PASS** | `flutter build apk --debug` succeeded with `GRADLE_USER_HOME=/tmp/moallem-gradle-user-home`; APK: `/tmp/moallem-gradle-project-build/app/outputs/flutter-apk/app-debug.apk` (129,067,034 bytes; ZIP integrity check passed). |
| GitHub Actions | **PASS** | Run #44072361770, SHA `a02b508a4a52c0a79486eefeea38446871b75194`: Backend, Android, unsigned iOS, and Secret Scan all succeeded. Backend applied Alembic migrations and ran PostgreSQL-backed tests. |

## Toolchain pins added

- Backend Python: `backend/.python-version` = `3.12.16`.
- Backend uv in CI: `0.13.6` (via the pinned `astral-sh/setup-uv` action).
- Mobile Flutter: `mobile/.flutter-version` and `mobile/.fvmrc` = `3.50.0`.
- Mobile Dart: supplied by Flutter 3.50.0 (Dart 3.14.0).
- `mobile/pubspec.lock` exists; `flutter pub get --enforce-lockfile` succeeds without changing dependency versions.

## CI hardening applied

- All third-party GitHub Actions are pinned to immutable commit SHAs.
- The secret scanner was upgraded from Gitleaks Action v2 (Node 20) to v3 (Node 24).
- Android runs format, analysis, tests and a debug APK build on Ubuntu.
- iOS runs format, analysis, tests and an unsigned release build on macOS.
- Both mobile jobs fail clearly when the lockfile or committed platform runners are missing.

## Mobile bootstrap evidence

`mobile/pubspec.lock`, `mobile/android/`, and `mobile/ios/` are present, and
`./scripts/check_mobile_prerequisites.sh` passes with Flutter 3.50.0. The bootstrap command remains
available for regenerating these files on a compatible setup:

```bash
./scripts/bootstrap_mobile.sh
```

Review and commit generated files only when deliberately regenerating them:

```text
mobile/pubspec.lock
mobile/android/
mobile/ios/
```

The default native application ID prefix (`com.moallem`) is provisional. Set
`MOALLEM_MOBILE_ORG` to the product-owner-approved reverse-DNS prefix before bootstrap if the
publisher identity has been decided. Do not ship until the identifier is confirmed.

## Remaining P1 governance notes

The technical exit gate is closed based on the successful run above. ADR-015 (Flutter state
management) and ADR-016 (Python type checker) remain provisional governance decisions; do not
represent them as owner-approved. P2, Moodle integration, durable task execution, and AI
functionality remain outside this P1 gate.

## Toolchain and action source references

- Flutter 3.50 release (11 November 2026; Dart 3.14): https://docs.flutter.dev/release/whats-new
- Python 3.12.16 security release (25 October 2026): https://www.python.org/downloads/release/python-31216/
- GitHub Actions Node 20 removal (23 September 2026): https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-on-github-actions-runners/
- Flutter action release history: https://github.com/subosito/flutter-action/releases
- Gitleaks Action v3 migration: https://github.com/gitleaks/gitleaks-action/releases
