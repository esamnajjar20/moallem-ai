# إغلاق الفجوات — الحالة بعد المراجعة والإصلاح

**التاريخ:** 2026-11-18
**المرجع:** تقرير مراجعة Moallem AI (حزمة إغلاق الفجوات).

> **ملاحظة صدق:** الإصلاحات أدناه كُتبت ورُوجعت بقراءة الكود فقط. لم تُشغَّل
> الاختبارات ولا `ruff` ولا `mypy` ولا `flutter analyze` في بيئة الإصلاح (بلا شبكة).
> شغّل `make check` و`make mobile-check` قبل الاعتماد.

## ما أُصلح

| # | المشكلة | الإصلاح |
|---|---------|---------|
| 1 | `registered_types()` تُستدعى كدالة وهي property | `worker/main.py` |
| 2 | `MoodleClient(site_url=…)` و`vault.reveal(ref)` بتوقيع خاطئ | `moodle/write_service.py` |
| 3 | قراءة `connection_id/course_id` من حقول غير موجودة + سقوط على قيم اختبار | الوجهة من `snapshot.destination` والفشل مغلق (`SNAPSHOT_DESTINATION_INVALID`) |
| 4 | المعالج لا يستخدم سجل النشر ويكرر انتقالات الحالة | `worker/handlers/publish_quiz.py` يتبع: intent ← plan ← dispatch ← outcome ← verifying ← complete |
| 5 | الأسئلة لا تُرسل والتحقق شكلي | `staging_write_adapter.py`: إرسال فعلي، `MoodlePartialWrite`، idnumber كامل، بحث idempotent، عدد غير معروف لا يُتحقَّق |
| 6 | اختبار النشر لا يختبر النشر | `tests/worker/test_publish_handler.py` + `tests/moodle/test_write_service.py` |
| 7 | سجل الـ Worker فارغ/غير مختبر | `worker/composition.py` + `test_composition.py` (يبقى fail-closed بدون الاعتماديات) |
| 8 | فحص المستأجر شكلي | `snapshot.tenant_id` مقابل `ctx` + ربط `connection_id` |
| 9 | أدوار `TEACHER` ثابتة في الـ Worker | `worker/actor.py` يعيد قراءة العضوية (نشطة/مستأجر/أدوار) |
| 10 | مصفوفة الصلاحيات لا تُفعَّل في الـ API | `MOALLEM_PERMISSION_POLICY=teacher_mvp` (الافتراضي `deny_all`) |
| 11 | مطابقة الإجابة بالنص الحرفي | `option_id` أولًا ثم تطبيع Unicode/تشكيل؛ الغموض يُرفض |
| 12 | استدعاءات شبكة متزامنة داخل async | `asyncio.to_thread` |
| 13 | `CourseSummary` لا يُترجم (حقل `fullname`) | `course.dart` |
| 14 | تسجيل الدخول بلا توكن؛ `connection_id = membership_id`؛ موافقة ببيانات وهمية؛ لا انتظار للمسودة/النشر؛ `COMPLETED` ثابتة | تعديلات Flutter (راجع الملفات) |
| 15 | أسطر طويلة/ترتيب imports في الملفات المعدّلة | عُدّلت؛ `ruff format` و`dart format` لم يُشغَّلا |

## ما لا يزال مفتوحًا (خارج الكود)

| ID | الفجوة |
|----|--------|
| A1 | أسماء دوال WS وبارامتراتها وصيغة ردودها على Moodle Staging؛ الـ adapter مغلق حتى تُمرَّر `StagingWriteConfig` |
| AUTH | Auth0 PKCE على الموبايل؛ الحالي تسجيل بتوكن يُتحقق منه عبر `/me` ويُخزَّن في secure storage |
| CONN-API | لا endpoint لإدارة اتصال Moodle؛ التطبيق يقرأ `MOALLEM_CONNECTION_ID` |
| KEY-CUSTODY | مفتاح تشفير الخزنة للـ Worker؛ لذلك لا يُسجَّل معالج النشر في `worker/main.py` افتراضيًا |
| PREFLIGHT | `PublishAuthorizer` الحقيقي غير موجود؛ الافتراضي `DenyAll` يمنع الإرسال (`PUBLISH_BLOCKED`) |
| LOCK | `mobile/pubspec.lock` يحتاج `flutter pub get` لتحديثه |
