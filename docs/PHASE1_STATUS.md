# P1 — Repository Foundation: closure status

**Status: NOT CLOSED.** Backend foundations exist and the source test suite passes, but the
mobile lockfile/native projects are not yet present and no GitHub Actions run has demonstrated a
green end-to-end repository gate.

**Assessment date:** 2026-11-16  
**Baseline:** `09_Implementation_Roadmap_v2.0` in Engineering Documentation v2.4  
**Exit gate:** reproducible Backend + Flutter builds, lint/type-check/test gates, and a green CI run.

## P1 checklist

| ID | Requirement | Current state | Evidence / remaining work |
|---|---|---|---|
| P1-01 | API, Worker and Flutter skeleton | PARTIAL | FastAPI and Worker skeletons plus Flutter RTL shell exist. `backend/uv.lock` is committed. Flutter is now pinned to 3.50.0, but `mobile/pubspec.lock`, `mobile/android/`, and `mobile/ios/` are still missing. Run `scripts/bootstrap_mobile.sh` on a machine with Flutter 3.50.0 and commit its generated outputs. |
| P1-02 | CI gates | CONFIGURED / NOT VERIFIED | CI now pins GitHub Actions to immutable commit SHAs and defines Backend, Android, iOS, and secret-scan jobs. It has not been run by GitHub for this uploaded snapshot. CI intentionally fails mobile prerequisites until the Flutter lockfile and native runners are committed. |
| P1-03 | Config, health and readiness | IMPLEMENTED | `config.py` validates configuration fail-fast; `/healthz` and `/readyz` exist; structured JSON logging redacts sensitive values and carries request IDs. API/config/logging tests are included. |

## Verification evidence

| Check | Result | Qualification |
|---|---|---|
| Backend tests | **82 passed** | Re-run in this environment with `python3 -m pytest -q`; runtime Python was 3.13.5, while the project contract is Python 3.12.x. This is a useful source-level smoke test, not the pinned-toolchain gate. |
| Ruff format/check | Historical status says passed | The previous `PHASE1_STATUS` recorded 39 files unchanged and Ruff clean. Ruff is not installed in the current execution environment, so that result was not independently repeated here. |
| mypy strict | Historical status says 24 source files passed | The previous status file recorded success; ADR-016 text was inconsistent and has been corrected. mypy is not installed in the current execution environment, so the check was not independently repeated here. |
| Backend locked sync/build/audit | NOT VERIFIED HERE | Python 3.12.16 and dependency tools could not be downloaded because this execution environment has no DNS/network access. CI now runs these checks with a pinned interpreter and uv. |
| Flutter format/analyze/tests/builds | NOT RUN | Flutter and Dart are not installed in this environment. A repeatable bootstrap script and pinned CI jobs are provided. |
| GitHub Actions | NOT RUN | A workflow file is not evidence of a passing workflow run. A push/PR to the actual GitHub repository is required. |

## Toolchain pins added

- Backend Python: `backend/.python-version` = `3.12.16`.
- Backend uv in CI: `0.13.6` (via the pinned `astral-sh/setup-uv` action).
- Mobile Flutter: `mobile/.flutter-version` and `mobile/.fvmrc` = `3.50.0`.
- Mobile Dart: supplied by Flutter 3.50.0 (Dart 3.14.0).
- Flutter package versions remain locked only after `flutter pub get` creates and commits `mobile/pubspec.lock`.

## CI hardening applied

- All third-party GitHub Actions are pinned to immutable commit SHAs.
- The secret scanner was upgraded from Gitleaks Action v2 (Node 20) to v3 (Node 24).
- Android runs format, analysis, tests and a debug APK build on Ubuntu.
- iOS runs format, analysis, tests and an unsigned release build on macOS.
- Both mobile jobs fail clearly when the lockfile or committed platform runners are missing.

## One-time mobile bootstrap

From the repository root, on a machine with Flutter 3.50.0 installed:

```bash
./scripts/bootstrap_mobile.sh
```

Then review and commit:

```text
mobile/pubspec.lock
mobile/android/
mobile/ios/
```

The default native application ID prefix (`com.moallem`) is provisional. Set
`MOALLEM_MOBILE_ORG` to the product-owner-approved reverse-DNS prefix before bootstrap if the
publisher identity has been decided. Do not ship until the identifier is confirmed.

## Remaining P1 technical exit actions

1. Run the one-time Flutter bootstrap and commit the generated lockfile and Android/iOS runners.
2. Run `uv sync --locked`, `make check`, and the mobile checks using the pinned toolchains.
3. Push the updated repository and obtain a successful GitHub Actions run for all four jobs.

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
