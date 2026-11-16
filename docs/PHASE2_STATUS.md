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

## 8) P2 — الهوية والعضوية (جلسة 2026-11-16، تنفيذ جزئي ضمن المتاح)

**P2 لا يُغلق من هنا:** ADR-017 وDEC-026/027/032 مفتوحة، وP2-02 محجوب (Secret Manager)، وP2-03 يحتاج قاعدة بيانات/worker/cache/storage غير موجودة بعد.

| البند | الحالة | ما تغيّر |
|---|---|---|
| P2-01 | PARTIAL-CODE | `MembershipContextInvalid` صار **403** (DEC-039 في Planning_Closure_Decisions_v2.4)؛ الرأس المشوّه صار **400 VALIDATION_FAILED** (`MembershipContextMalformed`)؛ الغائب يبقى 400 `MEMBERSHIP_CONTEXT_REQUIRED`. |
| P2-01/03 | جديد | `domain/authorization.py`: `require_tenant` (مورد مؤسسة أخرى = 404 بلا كشف وجود، AT-015) ثم `authorize` (سياسة صريحة؛ الافتراضي `DenyAllPolicy` لأن DEC-027 مفتوح). |
| P2-03 | جزئي | اختبارات نطاقية للعزل بين المؤسسات + `tests/test_tenancy_api.py` (AT-037/AT-031/AT-015 عبر HTTP على مسار probe). **طبقات DB/worker/cache/storage غير مغطاة.** |

**التحقق:** 65 اختباراً نطاقياً نجحت عبر shim محلي (بلا pytest). `tests/test_tenancy_api.py` **لم يُشغَّل** (لا fastapi/httpx في البيئة)، ولم يُشغَّل ruff/mypy.

**تعارض وثائقي يحتاج قرار المالك:** `openapi.draft.yaml` يصف `BadRequest` بأنه يشمل «missing/invalid required request context» بينما Closure Decisions v2.4 يحدد 403 للعضوية غير الصالحة. نُفّذ ما في Closure Decisions؛ وصف `BadRequest` في OpenAPI لم يُعدَّل.

### إضافة لاحقة (نفس الجلسة)

- `domain/scoped.py`: مستودع مقيّد بالمؤسسة (كل عملية تتطلب `ActiveContext`) + `tests/domain/test_scoped.py`.
- `domain/secrets.py`: `SecretRef` محجوب في repr/str/log + واجهة `SecretVault` + `tests/domain/test_secrets.py`. **اختيار Secret Manager ما زال مفتوحاً.**
- `docs/P2_DECISION_PROPOSALS.md`: مقترحات ADR-017 وDEC-026/027/032 **بحالة PROPOSED، بانتظار توقيع المالكين**.
- التحقق: 74 اختباراً نطاقياً عبر shim. ruff/mypy وملفات HTTP لم تُشغَّل.

### مصادقة Bearer (ADR-017 — PROPOSED، تنفيذ عام بلا مزوّد)

- `domain/identity.py`: تحليل `Authorization: Bearer` ← `TokenVerifier` (التوقيع، قابل للاستبدال) ← فحص iss/aud/exp/nbf/سقف العمر ← ربط `(issuer, sub)` بمستخدم عالمي. كل الإخفاقات 401 بنفس الرسالة. لا إنشاء تلقائي لمستخدم مجهول.
- `api/deps.py`: `BearerAuthenticator` (غير موصول في `create_app` حتى تُعتمد إعدادات issuer/audience).
- `tests/helpers_jwt.py`: موقّع/متحقق HS256 **للاختبار فقط** (داخل tests/ فلا يُشحن).
- **لا مكتبة تشفير أُضيفت** (تحديث `uv.lock` غير ممكن دون شبكة). التحقق الحقيقي من RS256/JWKS يحتاج مكتبة وقرار المزوّد.
- التحقق: 79 اختباراً نطاقياً عبر shim؛ `test_bearer_api.py` لم يُشغَّل.

### Auth0 (RS256 + JWKS) — موصول

- `domain/rs256.py`: تحقق RS256 بمكتبة stdlib فقط (عمليات المفتاح العام فقط؛ alg=RS256 صارم، kid إلزامي، مفتاح ≥ 2048 بت، e ≥ 65537، مقارنة الحشو بالكتلة كاملة). **تحقق تشفيري مكتوب يدوياً: يُنصح باستبداله بـ PyJWT عند تحديث `uv.lock` ومراجعته أمنياً.**
- `api/jwks.py`: جلب JWKS من `{issuer}.well-known/jwks.json` (https فقط، حد 256KB، cache ساعة، تحديث عند kid مجهول مرة/دقيقة، يفشل مغلقاً).
- `config.py`: `MOALLEM_AUTH_ISSUER` / `AUDIENCE` / `MAX_TOKEN_LIFETIME_SECONDS` (الثلاثة معاً أو لا شيء). `create_app` يستعمل `BearerAuthenticator` عند ضبطها.
- `DerivedSubjectMapper`: user_id = UUIDv5(issuer|sub) (مطابق لصيغة uuid في العقد، بلا جدول). لا يمنح صلاحية؛ العضوية ما زالت مطلوبة. **قرار قابل للتراجع:** تغيير issuer يغيّر المعرّفات.
- **تنبيه Auth0:** عمر access token الافتراضي للـ API هو 86400 ثانية؛ اخفضه في Auth0 ليطابق السقف (مثلاً 900) وإلا سيُرفض كل توكن.
- التحقق: 90 اختباراً (نطاق + JWKS) عبر shim. لم تُشغَّل: اختبارات config/HTTP وruff/mypy.

## P2-03 — عزل cache / storage / worker (إضافة)

- `domain/tenant_keys.py`: مفاتيح cache ومسارات storage وغلاف رسائل الطابور تُبنى **من `ActiveContext` فقط**؛ المؤسسة جزء من المفتاح بالبناء، والمقاطع تُرفض إن احتوت `/` أو `:` أو `..` أو فراغاً. مفتاح/مسار/رسالة تخص مؤسسة أخرى = `ResourceNotFound` (AT-015).
- `tests/domain/test_tenant_keys.py`.
- **ما لا يغطيه:** لا Redis ولا S3 ولا broker فعلي بعد (ADR-020, DEC-030)؛ هذه هي الواجهة التي يجب أن تلتزم بها تلك الطبقات. اختبارات DB (`DB-TEN-01`) تنتظر DEC-031.
- ربط Moodle بالعضوية والصلاحية: `moodle/service.py` (انظر `PHASE3_STATUS.md`).
