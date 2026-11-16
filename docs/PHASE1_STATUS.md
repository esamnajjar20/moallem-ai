# P1 — Repository Foundation: closure status

**Status: NOT CLOSED.** Locked backend and Flutter checks were executed locally, and the Android
debug APK build passed with Gradle caches and outputs on temporary storage. No GitHub Actions run
has demonstrated a green end-to-end gate; iOS still requires the macOS CI runner. The
`com.moallem` application ID remains provisional and unchanged.

**Assessment date:** 2026-11-16  
**Baseline:** `09_Implementation_Roadmap_v2.0` in Engineering Documentation v2.4  
**Exit gate:** reproducible Backend + Flutter builds, lint/type-check/test gates, and a green CI run.

## P1 checklist

| ID | Requirement | Current state | Evidence / remaining work |
|---|---|---|---|
| P1-01 | API, Worker and Flutter skeleton | IMPLEMENTED / LOCALLY VERIFIED | Python 3.12.16 locked checks pass; Flutter lockfile and Android/iOS runners exist. Flutter 3.50.0 format, analysis, tests, and debug APK build pass. The application ID stays provisional. |
| P1-02 | CI gates | CONFIGURED / NOT VERIFIED | CI pins actions to immutable commit SHAs and defines Backend, Android, iOS, and Secret Scan jobs. YAML parsed locally; `actionlint` is unavailable. A GitHub run is still required. |
| P1-03 | Config, health and readiness | IMPLEMENTED | `config.py` validates configuration fail-fast; `/healthz` and `/readyz` exist; structured JSON logging redacts sensitive values and carries request IDs. API/config/logging tests are included. |

## Verification evidence

| Check | Result | Qualification |
|---|---|---|
| Backend locked checks | **PASS** | `make check` with `uv run --locked`; Python 3.12.16, uv 0.13.8. |
| Ruff format/check | **PASS** | `make check` ran `ruff check .` and `ruff format --check .`; Ruff 0.17.5. |
| mypy | **PASS** | `make check`; mypy 1.20.2, 45 source files, no issues. |
| Backend tests | **PASS** | `make check`: **322 passed, 1 optional PostgreSQL test skipped**. With the temporary PostgreSQL 15.19 test database: **323 passed, 1 Starlette/httpx deprecation warning**. |
| Backend build/audit | **PASS WITH AUDIT QUALIFICATION** | `make check` built sdist and wheel. `pip-audit` found no known vulnerabilities after updating locked `cryptography` to 50.0.2; it skipped local `moallem 0.0.1` because it is not on PyPI. |
| Flutter pub/format/analyze/tests | **PASS** | Flutter 3.50.0 / Dart 3.14.0; enforced-lockfile pub get succeeded, 6 Dart files unchanged, analyze clean, **3 tests passed**. |
| Android debug APK | **PASS** | `flutter build apk --debug` succeeded with `GRADLE_USER_HOME=/tmp/moallem-gradle-user-home`; APK: `/tmp/moallem-gradle-project-build/app/outputs/flutter-apk/app-debug.apk` (129,067,034 bytes; ZIP integrity check passed). |
| GitHub Actions | **NOT RUN** | YAML parses and lists four jobs; `actionlint` is not installed. A PR and green GitHub run are still required. |

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

## Remaining P1 technical exit actions

1. Run the iOS build on macOS CI.
2. Open a PR and obtain a successful GitHub Actions run for Backend, Android, iOS, and Secret Scan.

**Do not mark the P1 technical gate CLOSED until all three actions have evidence.** ADR-015 and
ADR-016 owner approvals remain separate foundation-governance work and must be completed before
those decisions are treated as final. P2, Moodle integration, durable persistence/queue
infrastructure, and AI functionality remain outside this P1 closure gate.

## Toolchain and action source references

- Flutter 3.50 release (11 November 2026; Dart 3.14): https://docs.flutter.dev/release/whats-new
- Python 3.12.16 security release (25 October 2026): https://www.python.org/downloads/release/python-31216/
- GitHub Actions Node 20 removal (23 September 2026): https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-on-github-actions-runners/
- Flutter action release history: https://github.com/subosito/flutter-action/releases
- Gitleaks Action v3 migration: https://github.com/gitleaks/gitleaks-action/releases
