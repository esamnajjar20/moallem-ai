# Phase A — Approved Decisions (2026-11-17)

All items below are **APPROVED** for implementation of the MVP Vertical Slice.

---

## A1 — Moodle Staging Evidence (External Gate)

**Status:** APPROVED as a required gate  
**Action:** Evidence pack must be completed before enabling live Moodle read/write.

Template location: `docs/phase_a/MOODLE_STAGING_EVIDENCE_TEMPLATE.md`

Until the evidence pack is filled with a real Staging URL + teacher account + course:

- Moodle transport remains opt-in
- No live write adapter is enabled
- Integration tests against real Moodle stay skipped

---

## A2 — DEC-027 Permission Matrix

**Status:** APPROVED  
**Document:** `docs/decisions/DEC-027_Permission_Matrix_Teacher_MVP.md`

`TeacherMVPPolicy` is the approved implementation for the Teacher role in MVP.

---

## A3 — ADR-018 + DEC-043 (AI Provider + Budget)

**Status:** APPROVED (MVP constraints)

### Provider (temporary MVP choice)
- Prefer an OpenAI-compatible Chat Completions endpoint.
- Exact provider / model / region must still be recorded in the final ADR-018 when credentials are available.
- No automatic cross-provider fallback.
- No learner data is sent.
- Course material may be sent only after privacy review of the chosen provider.

### Budget (DEC-043)
- Per-task budget reservation is **mandatory** before any AI call.
- Per-tenant period budget is required.
- Missing or exhausted budget → fail-closed (`AIExecutionDenied`).
- Numeric limits will be set after first pilot measurements; until then use conservative development defaults.

`DenyAllAIExecution` remains the production default until a concrete authorizer with reservation/settlement is injected.

---

## A4 — DEC-028 / DEC-029 (Storage, Scanner, Lifecycle)

**Status:** APPROVED (simplified for MVP)

| Topic              | MVP Decision                                      |
|--------------------|---------------------------------------------------|
| Object Storage     | S3-compatible (MinIO or cloud). Can be disabled. |
| Encryption         | AES-256-GCM (already selected)                    |
| Malware Scanner    | Disabled for MVP + reject executable types only   |
| Extraction Sandbox | Disabled for MVP; PDF/DOCX via safe libraries only|
| Retention          | Drafts: 90 days (configurable later)              |

Full lifecycle and KMS decisions remain open for post-MVP.

---

## Next Implementation Steps

1. Implement `TeacherMVPPolicy` (done in this change set).
2. Complete Moodle Staging Evidence Pack (A1).
3. Wire concrete AI provider + budget authorizer once credentials exist.
4. Implement Moodle Write Adapter + end-to-end worker handler (Phase B).
