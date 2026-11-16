# P3 — Moodle Read Adapter: status

**Status: LOCALLY VERIFIED CODE, NOT CLOSED.** The adapter, local TLS transport tests, route
guards, and sanitized-fixture replay harness pass repository tests. The exit gate still requires
real Moodle staging evidence for each read operation and teacher role. P0-02/03/04 (staging URL,
live API docs, teacher account) are BLOCKED; synthetic tests do not establish Moodle compatibility.

## What was implemented (`backend/src/moallem/moodle/`)

| File | Covers | Notes |
|---|---|---|
| `url_policy.py` | SSRF baseline (`Validation/Moodle_Connection_SSRF_and_Network_Egress_v2.4.md`) | https only; no credentials/query/fragment/IP literals (incl. `0x7f.1`, decimal); blocks localhost/`.internal`/`.local`/metadata names; default-deny on non-global IPs incl. IPv4-mapped IPv6, CGNAT; **every** resolved address must pass; metadata ranges blocked even with a private-campus profile; redirect policy (cross-host denied, hop cap). |
| `client.py` | REST transport seam | Token only in POST body; `Token` redacted in repr/str/pickle; destination re-resolved and pinned per call; redirects not followed; remote error *messages discarded* (only a sanitised errorcode is kept); size/time limits passed to the transport. |
| `transport.py` | Opt-in stdlib HTTPS transport | `SystemResolver` and `PinnedHttpsTransport` connect to the validated pinned IP while using the original hostname for SNI, Host, and TLS verification; do not follow redirects; enforce socket timeout and stream response bytes up to the configured cap. Not wired into the app. |
| `read.py` | P3-01..03 | `core_webservice_get_site_info` → `CapabilitySnapshot` (release/build, function list + SHA-256, missing required functions); `core_enrol_get_users_courses` → paged `CourseSummary`; `core_course_get_contents` → sections/modules/files shaped like the OpenAPI `CourseSection`/`CourseModuleSummary`; HTML reduced to plain text; caps on sections/modules/files with a `truncated` flag; file URLs accepted only on the connection's own host under `/webservice/pluginfile.php/`, never with a query/token. |
| `service.py` | P2 ↔ P3 glue | `MoodleReadService`: tenant check (foreign = 404, AT-015) → permission (`moodle.connection.read` / `moodle.course.read` / `moodle.course.content.read`, DenyAll until DEC-027) → connection ACTIVE → secret reveal → call. |
| `routes.py` | Fail-closed course routes | `GET /courses` and `GET /courses/{course_id}/context` require active membership and return 503 `MOODLE_UNAVAILABLE` until the connection repository/read service is configured. No route activates Moodle access. |
| `errors.py` | contract codes | `MOODLE_CREDENTIAL_INVALID/FUNCTION_NOT_AVAILABLE/PERMISSION_DENIED/UNAVAILABLE`, `CONNECTION_NOT_ACTIVE`. **HTTP statuses (422/422/403/503/409) are my proposal**; the OpenAPI draft names the codes but not their statuses. |

Verification: full locked backend suite **314 passed, 1 warning** on Python 3.12.16; includes
local TLS tests (SNI/Host/pinned IP/TLS verification, redirect not followed, size cap and timeout),
malformed URL and redirect-hop-limit tests, contract-parameter parity tests, and route 503 tests.
The fixture-replay unit test uses in-memory synthetic data only. No real staging fixture was added.

## What is still open (needs staging or a decision)

1. **Teacher-only course list.** `core_enrol_get_users_courses` returns every enrolment and no
   role. How to restrict to teacher courses (per-course role lookup? a plugin?) must be decided
   from staging evidence. `list_teacher_courses` is therefore *enrolled* courses today; do not
   use it as an authorisation signal for writes.
2. **Moodle errorcode mapping** (`invalidtoken`, `accessexception`, `nopermissions`, …) comes
   from Moodle conventions, not evidence. Unknown codes degrade to `MOODLE_UNAVAILABLE`, never to
   a permission/credential claim.
3. **Token in a POST body for `pluginfile.php`** is assumed to work; verify on staging (P3-03).
4. **Capabilities** (`CapabilitySnapshot.capabilities`) is intentionally empty: per-role capability
   evidence cannot be produced without a teacher account.
5. **Transport remains opt-in.** The stdlib transport/resolver now exist and were tested against
   a local TLS server; they are not selected by the application. ADR-020, deployment egress
   controls, and an approved network profile remain required before any live connection.
6. **Routes remain unavailable.** Both course endpoints fail closed with 503 until a connection
   repository/read service is configured. The current draft contract has no explicit 503 response
   on these two operations; the contract file was not changed. Route parameter/header parity is
   tested, but the successful 200 path cannot be exercised without the blocked repository.
7. **Persistence of capability snapshots** (P3-01 "تخزين") needs the database layer (DEC-031).
8. The replay harness is `backend/scripts/replay_moodle_fixtures.py`; format and sanitization rules
   are in `docs/MOODLE_RECORDED_FIXTURES.md`. Fill Moodle Validation rows MDL-001.. with real
   evidence from `Validation/Moodle_Staging_Validation_Checklist.md` before calling any read SUPPORTED.

## Exit gate: NOT MET
Requires: staging evidence per operation + role, contract tests run against the recorded
(sanitised) responses, and a green CI run.
