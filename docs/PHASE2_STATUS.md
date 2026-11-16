# حالة ما بعد P0/P1 — ما تبقّى وما نُفّذ

**الخلاصة:** تحقق تقدم Backend P1 محلياً (uv.lock + نتائج lint/type-check مسجلة سابقاً + 82 اختباراً)، لكن **بوابة P1 الكلية غير مغلقة** حتى إنشاء `mobile/pubspec.lock` ومشروعي Android/iOS وتشغيل CI الأخضر. لا يمكن إغلاق أي بند P0 من هذه البيئة (لا أصحاب قرار، لا Moodle staging). نواة النطاق (domain core) مكتملة منطقياً مع 56 اختباراً نطاقياً ضمن الـ82.

**آخر تحديث تحقق:** 2026-11-16

## 1) خريطة المتبقي

| المرحلة | الحالة | ما يمنعها | هل أنجزت جزءاً منها هنا؟ |
|---|---|---|---|
| P0 | لم تُغلق | أشخاص وجهات: مالكون، مسؤول Moodle، توقيعات | لا (حزمة P0 جاهزة سابقاً) |
| P1 Backend | تحقق محلي مسجل؛ CI غير مثبت | تشغيل CI المقفل على GitHub وتأكيد Python 3.12.16 | نعم: lock + نتائج lint/types سابقة + 82 tests |
| P1 Mobile | مفتوح | Flutter 3.50.0 + pubspec.lock + Android/iOS runners | تم تثبيت toolchain وإضافة bootstrap؛ لم تُولد المخرجات لغياب Flutter |
| P2 هوية/عضوية | جزئي | ADR-017 (issuer/session)، DEC-026/027/032 | نعم: سياق العضوية + `/me` |
| P3 قراءة Moodle | محجوب | EXT-MDL-001..003 | لا |
| P4 مهام/اعتمادية | منطق نطاق مكتمل | DEC-030 (broker)، DEC-031 (DDL/PK)، قاعدة بيانات | نعم: آلة الحالات، الأحداث، idempotency، outbox |
| P5–P8 | محجوبة | ADR-018/020، DEC-033/034، إثبات Moodle write | لا |
| P9–P11 | بعيدة | — | لا |

## 2) ما نُفّذ (backend/src/moallem/domain/)

| الملف | القرار/الفجوة | الاختبارات |
|---|---|---|
| `canonical.py` | GAP-DATA-001، HASH-VECTORS-01، بصمة idempotency | `test_canonical.py` |
| `tasks.py` | آلة الحالات + DEC-042 (الإلغاء نية لا وعد)، AT-044 | `test_tasks.py` |
| `events.py` | DEC-044: cursor موقّع حصري، 410 عند انتهاء الاحتفاظ، AT-045 | `test_events.py` |
| `membership.py` | DEC-039، AT-037، AT-031 | `test_membership.py` |
| `external.py` | DEC-041: مفاتيح ثابتة، UNKNOWN لا يُعاد، سقف 256 خطوة | `test_external.py` |
| `idempotency.py` | P4-02، GAP-API-003 | `test_idempotency.py` |
| `outbox.py` | P4-03 | `test_outbox.py` |

مرفق أيضاً `contracts/agent_runtime_limits.v2.4.json` وتطابقه مع الثابت في الشيفرة مُختبَر.

## 3) ما شُغِّل فعلاً (2026-11-16)

- **شُغِّل ونجح:**
  - `uv lock` → `backend/uv.lock`
  - `ruff format` + `ruff check` → نظيف
  - `mypy --strict` → 24 ملفاً بلا ملاحظات
  - `pytest` → **82 passed** (domain + api + config + me + contract parity)
- **لم يُشغَّل في ذلك التحقق:** CI على GitHub، Flutter، `uv build` / `pip-audit` داخل venv مقفل (قيود بيئة)، `uvicorn` حي. في مراجعة P1 التالية أُعيد تشغيل اختبارات المصدر على Python 3.13.5 فقط؛ هذا لا يثبت اجتياز Python 3.12.16 المقفل.

## 4) قرارات اتخذتها وتحتاج موافقة (لا تُعد مغلقة)

1. **رفض الأعداد العشرية في المحتوى المجزَّأ.** RFC 8785 يتطلب تنسيق أرقام ECMAScript الذي لا تعيد بايثون إنتاجه دائماً. البديل: أعداد صحيحة (≤ 2^53−1) أو نصوص عشرية. يؤثر في تصميم QuizSpec (الدرجات مثلاً).
2. **NFC قبل ترتيب JCS.** نتيجته أن حروفاً مثل U+FB33 تتفكك وتتغير مواضعها مقارنة بمتجهات RFC الحرفية؛ المتجهات هنا مبنية على خط المعالجة المقترح لا على RFC وحده. متجهات التبادل مع أنظمة أخرى تحتاج اتفاقاً.
3. **GAP-TASK-001:** جدول الانتقالات في v2.0 لا يتيح CANCELLED من PLANNING/DRAFTING/VALIDATING/NEEDS_REVISION/APPROVED/EXECUTING/NEEDS_RECONCILIATION، بينما DEC-042 يقتضيه قبل الإرسال أو بعد إثبات غياب الأثر. أضفتها في `CANCEL_EXTENSIONS` منفصلة عن الجدول الحرفي. تحتاج تأكيد المالك.
4. **كل سياق عضوية غير صالح = 400 `MEMBERSHIP_CONTEXT_INVALID` بنفس الرسالة** (مجهول/غريب/معلّق/مُلغى) لمنع تعداد العضويات. العقد الحالي يستخدم BadRequest لهذا؛ إن فضّلتم 403 فهو تغيير عقد.

## 5) الخطوات التالية بالترتيب

1. تشغيل `scripts/bootstrap_mobile.sh` على Flutter 3.50.0 ثم إدخال `mobile/pubspec.lock` وAndroid/iOS runners في المستودع.
2. تشغيل CI على PR والتحقق من Backend وAndroid وiOS وSecret Scan جميعها خضراء.
3. أرسل طلب Moodle Admin وعيّن المالكين. كل ما يخص Moodle ينتظر الرد.
4. وقّع/عدّل البنود الأربعة في القسم 4 + ADR-015/016.
5. بعد نجاح CI: الإبقاء على ربط `membership` و`/me`؛ استبدال `NoAuthenticator` عند حسم ADR-017.
6. DEC-031/030 قبل أي DDL أو outbox فعلي.

## 6) ربط العضوية و`/me`

- `api/deps.py` و`api/me.py` و`tests/test_me_api.py` وتعديل `api/app.py` **شُغِّلت ضمن الـ82 اختباراً**.
- المصادقة: `NoAuthenticator` افتراضيًا (يرفض كل شيء)، و`DevAuthenticator` يرفض الإنشاء خارج development/test. ADR-017 ما زال مفتوحًا.
- مستودع العضويات في الذاكرة وفارغ افتراضيًا حتى P4 (يفشل مغلقًا).
- `INVITED` موجود في `MembershipStatus`؛ تطابق enum مع OpenAPI مُختبَر.

## 7) idempotency وoutbox/inbox (P4-02/P4-03، منطق نطاق فقط)

- `domain/idempotency.py` + اختبارات: HMAC، نطاق، NEW/IN_PROGRESS/REPLAY، تعارض hash = 409، لا انتهاء لسجل خارجي غير مُسوّى.
- `domain/outbox.py` + اختبارات: PENDING→LEASED→PUBLISHED/DEAD_LETTER، fencing بـ`lease_generation`، inbox dedup.
- **بلا قيم افتراضية عمداً:** `ttl`، `max_attempts`، `retry_after`، ومفتاح HMAC الخادمي.
- **غير منجز:** جداول PostgreSQL، المعاملة الواحدة، المُرسِل (dispatcher)، P4-04. كلها بعد DEC-030/031.
