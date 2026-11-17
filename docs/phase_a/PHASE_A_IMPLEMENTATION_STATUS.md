# Phase A — Implementation Status

**Date:** 2026-11-17  
**Status:** A2 implemented in code; A1/A3/A4 approved as decisions and waiting external evidence/credentials.

## Completed in this change set

### A2 — DEC-027 Permission Matrix (code)

| Item | Location | Notes |
|------|----------|-------|
| Decision record | `docs/decisions/DEC-027_Permission_Matrix_Teacher_MVP.md` | APPROVED |
| Permission constants | `moallem.domain.authorization` | Stable keys |
| `TeacherMVPPolicy` | `moallem.domain.authorization` | Grants TEACHER + ADMIN the approved matrix |
| Tests | `tests/domain/test_authorization.py` | Covers grants, deny, tenant isolation, unknown roles |
| Production default | Still `DenyAllPolicy()` in `create_app` | Fail-closed until explicitly injected |

**How to activate the approved policy (temporary / tests / staging):**

```python
from moallem.domain.authorization import TeacherMVPPolicy

app = create_app(permission_policy=TeacherMVPPolicy())
```

Or in tests / local scripts inject the policy into `MoodleReadService`, task routes, etc.

### A1 — Moodle Staging

- Template ready: `docs/phase_a/MOODLE_STAGING_EVIDENCE_TEMPLATE.md`
- **Blocked on external input** (URL + teacher account + course).

### A3 — AI Provider + Budget

- Decision recorded in `docs/decisions/PHASE_A_APPROVED_DECISIONS.md`
- `DenyAllAIExecution` remains default until concrete credentials + reservation authorizer exist.

### A4 — Storage / Scanner

- Simplified MVP decisions recorded.
- No code change required yet (fail-closed / disabled path already exists).

## Recommended next actions

1. Fill `MOODLE_STAGING_EVIDENCE.md` from the template (A1).
2. In the real repository, apply the same `authorization.py` + test changes.
3. When ready, inject `TeacherMVPPolicy()` in the application factory for Staging only.
4. Proceed to Phase B (Moodle Write Adapter + end-to-end worker).

## Safety note

The default remains deny-all. No production behaviour changes until the policy is deliberately composed.
