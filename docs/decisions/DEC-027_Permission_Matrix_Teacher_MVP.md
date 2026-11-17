# DEC-027 — Permission Matrix (Teacher MVP)

**Status:** APPROVED  
**Date:** 2026-11-17  
**Owners:** Product + Security  
**Scope:** Vertical Slice للمعلم في MVP (P2–P7)

## Decision

Adopt the following explicit permission matrix for the Teacher role in the MVP.  
Any action not listed is denied. Role values are taken from `ActiveContext.roles`.

### Approved Matrix

| Permission Key                    | Description                                      | TEACHER | ADMIN (Tenant) |
|-----------------------------------|--------------------------------------------------|---------|----------------|
| `moodle.connection.read`          | قراءة حالة ربط Moodle                            | ✅      | ✅             |
| `moodle.connection.manage`        | إنشاء / فصل / تجديد ربط Moodle                   | ✅      | ✅             |
| `moodle.course.read`              | قراءة قائمة المقررات                             | ✅      | ✅             |
| `moodle.course.content.read`      | قراءة محتوى المقرر والملفات                      | ✅      | ✅             |
| `quiz.generate.request`           | طلب توليد اختبار بالذكاء الاصطناعي               | ✅      | ✅             |
| `quiz.draft.read`                 | قراءة مسودة الاختبار                             | ✅      | ✅             |
| `quiz.quality.view`               | عرض نتائج مدقق الجودة                            | ✅      | ✅             |
| `quiz.approve`                    | الموافقة على المسودة للنشر                       | ✅      | ✅             |
| `quiz.reject`                     | رفض المسودة                                      | ✅      | ✅             |
| `quiz.publish`                    | السماح ببدء عملية النشر إلى Moodle               | ✅      | ✅             |
| `task.create`                      | إنشاء مهمة توليد اختبار                      | ✅      | ✅             |
| `task.read`                       | قراءة حالة المهمة الخاصة بالمستخدم               | ✅      | ✅             |
| `task.events.read`                | قراءة أحداث المهمة                               | ✅      | ✅             |
| `ai.usage.read`                   | قراءة استخدام الذكاء الاصطناعي الخاص بالمستخدم   | ✅      | ✅             |

### Binding Rules

1. Evaluation order remains: **Tenant isolation first** (AT-015) → then permission check.
2. `X-Active-Membership-ID` must resolve to an ACTIVE membership.
3. Ownership / enrolment checks remain the responsibility of the service layer (MoodleReadService, task ownership, etc.).
4. Moodle role alone is never sufficient; the internal permission + enrolment check is required.
5. Unknown roles receive no grants.
6. Production default remains fail-closed until the policy is explicitly injected (or enabled via configuration).

## Implementation

- New class: `TeacherMVPPolicy` in `moallem.domain.authorization`
- Built on top of existing `StaticPolicy`
- Tests updated in `tests/domain/test_authorization.py`

## Reversibility

Can be replaced by a richer policy (resource-level, course-scoped, etc.) without changing the `PermissionPolicy` protocol.
