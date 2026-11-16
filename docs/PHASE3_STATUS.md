# P3 — Moodle Read Adapter: status

**Status: CODE WRITTEN, NOT CLOSED.** The exit gate ("Moodle read contract tests pass", with
compatibility evidence per read operation and teacher role) needs a real Moodle staging site.
P0-02/03/04 (staging URL, live API docs, teacher account) are still BLOCKED, so P3-01..03 cannot
be closed from a repository alone. What exists is the adapter, tested against **synthetic**
fixtures. Synthetic fixtures prove our parsing/safety logic, not that Moodle behaves this way.

## What was implemented (`backend/src/moallem/moodle/`)

| File | Covers | Notes |
|---|---|---|
| `url_policy.py` | SSRF baseline (`Validation/Moodle_Connection_SSRF_and_Network_Egress_v2.4.md`) | https only; no credentials/query/fragment/IP literals (incl. `0x7f.1`, decimal); blocks localhost/`.internal`/`.local`/metadata names; default-deny on non-global IPs incl. IPv4-mapped IPv6, CGNAT; **every** resolved address must pass; metadata ranges blocked even with a private-campus profile; redirect policy (cross-host denied, hop cap). |
| `client.py` | REST transport seam | Token only in POST body; `Token` redacted in repr/str/pickle; destination re-resolved and pinned per call; redirects not followed; remote error *messages discarded* (only a sanitised errorcode is kept); size/time limits passed to the transport. |
| `read.py` | P3-01..03 | `core_webservice_get_site_info` → `CapabilitySnapshot` (release/build, function list + SHA-256, missing required functions); `core_enrol_get_users_courses` → paged `CourseSummary`; `core_course_get_contents` → sections/modules/files shaped like the OpenAPI `CourseSection`/`CourseModuleSummary`; HTML reduced to plain text; caps on sections/modules/files with a `truncated` flag; file URLs accepted only on the connection's own host under `/webservice/pluginfile.php/`, never with a query/token. |
| `service.py` | P2 ↔ P3 glue | `MoodleReadService`: tenant check (foreign = 404, AT-015) → permission (`moodle.connection.read` / `moodle.course.read` / `moodle.course.content.read`, DenyAll until DEC-027) → connection ACTIVE → secret reveal → call. |
| `errors.py` | contract codes | `MOODLE_CREDENTIAL_INVALID/FUNCTION_NOT_AVAILABLE/PERMISSION_DENIED/UNAVAILABLE`, `CONNECTION_NOT_ACTIVE`. **HTTP statuses (422/422/403/503/409) are my proposal**; the OpenAPI draft names the codes but not their statuses. |

Tests: `tests/moodle/` (URL policy, client, read, service). 173 test cases across the new files
plus `tests/domain/test_tenant_keys.py` passed locally through a stand-in runner (see below).

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
5. **Real transport and DNS resolver** (pinned connect, TLS verification against the host, no
   redirects, byte cap) belong to the hosting decision ADR-020. Only the `MoodleTransport` /
   `Resolver` protocols exist. The outbound firewall/egress profile is still required on top.
6. **No HTTP routes.** `GET /courses` and `GET /courses/{id}/context` are not wired: it needs a
   persistent connection store (P2-02/P4) and I cannot run FastAPI here, so I did not add
   untested route code.
7. **Persistence of capability snapshots** (P3-01 "تخزين") needs the database layer (DEC-031).
8. Fill `Moodle Validation` rows MDL-001.. in `Implementation_Control` with real evidence
   (`Validation/Moodle_Staging_Validation_Checklist.md`) before calling any read SUPPORTED.

## Exit gate: NOT MET
Requires: staging evidence per operation + role, contract tests run against the recorded
(sanitised) responses, and a green CI run.
