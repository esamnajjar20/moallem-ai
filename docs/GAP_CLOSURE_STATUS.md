# إغلاق الفجوات — حالة الربط الشامل

**التاريخ:** 2026-11-17

## ما أُغلق بالكود في هذه الجولة

| الفجوة | الإجراء |
|--------|--------|
| مصفوفة الصلاحيات لا تطابق `task.create` في API | أُضيف `PERM_TASK_CREATE` إلى `TeacherMVPPolicy` |
| مسارات Flutter لا تطابق Backend | محاذاة `ApiQuizRepository` مع `/tasks`, `/tasks/{id}/snapshot`, `/tasks/{id}/approvals`, `/tasks/{id}/result` + `Idempotency-Key` |
| عدم وجود Write Adapter جاهز للـ Staging | `StagingMoodleWriteAdapter` (fail-closed حتى تُمرَّر `StagingWriteConfig` من أدلة A1) |
| مسار النشر غير قابل للاختبار بدون شبكة | اختبارات Fake + mapping + policy |
| توثيق ما تبقى خارجيًا | هذا الملف |

## سلسلة Vertical Slice (بعد الإغلاق)

```
Flutter (Mock أو API)
  → POST /api/v1/tasks (CREATE_QUIZ)
  → Worker: توليد مسودة + جودة (P5/P6 — ما زال DenyAllAI بدون مزود)
  → GET snapshot → معاينة في التطبيق
  → POST /tasks/{id}/approvals
  → Worker PublishQuizHandler
       → SnapshotDraftLoader
       → question_mapping
       → MoodleWriteService + TeacherMVPPolicy
       → Fake / Staging / DenyAll adapter
  → GET /tasks/{id}/result
```

## فجوات ما زالت خارجية (لا تُغلق بالكود وحده)

| ID | الفجوة | المالك |
|----|--------|--------|
| A1 | Moodle Staging URL + token + دوال WS لإنشاء الاختبار | Moodle Admin |
| A3 | مزود AI + مفاتيح + ميزانية | Product / FinOps |
| AUTH | Auth0 PKCE حقيقي على الموبايل | Mobile + Auth |
| CONN-API | لا يوجد بعد endpoint HTTP رسمي لإنشاء Moodle connection في الـ API (الربط عبر عمليات داخلية / لاحقًا) | Backend |
| STAGING-FN | أسماء دوال create/verify على الموقع الحقيقي | A1 evidence |

## تفعيل مسار النشر على Staging (عند توفر A1)

```python
from moallem.moodle.staging_write_adapter import StagingMoodleWriteAdapter, StagingWriteConfig
from moallem.worker.composition import build_handler_registry

adapter = StagingMoodleWriteAdapter(
    StagingWriteConfig(
        create_quiz_function="...",  # من دليل Staging
        verify_quiz_function="...",
    )
)
handlers = build_handler_registry(
    publications=publications,
    connections=connections,
    vault=vault,
    transport=transport,
    resolver=resolver,
    write_adapter=adapter,
    enable_teacher_policy=True,
)
```

## الحكم النهائي

- **الفجوات البرمجية القابلة للإغلاق في المستودع:** أُغلقت أو رُبطت.
- **الفجوات التشغيلية/الخارجية:** تبقى بوابة Pilot (Staging + AI provider + Auth0).
- المنتج ما زال **غير جاهز لـ Pilot حقيقي** حتى تُغلق A1 وA3، لكنه **جاهز هندسيًا** لربطها دون إعادة تصميم.
