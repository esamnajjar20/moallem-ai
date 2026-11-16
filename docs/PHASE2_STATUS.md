# حالة ما بعد P0/P1 — ما تبقّى وما نُفّذ

**الخلاصة:** لا يمكن إغلاق بوابة P1 ولا أي بند P0 من هذه البيئة (لا شبكة، لا CI، لا أصحاب قرار، لا Moodle staging). نُفّذ ما يمكن تنفيذه دون انتظار أحد: نواة نطاق (domain core) خالية من الاعتماديات لأربعة قرارات بحالة `READY_FOR_APPROVAL`/`PROPOSED`، مع 41 اختباراً.

## 1) خريطة المتبقي

| المرحلة | الحالة | ما يمنعها | هل أنجزت جزءاً منها هنا؟ |
|---|---|---|---|
| P0 | لم تُغلق | أشخاص وجهات: مالكون، مسؤول Moodle، توقيعات | لا (حزمة P0 جاهزة سابقاً) |
| P1 | الشيفرة موجودة، **البوابة غير محققة** | `uv.lock`، `pubspec.lock`، أول تشغيل CI | لا (يحتاج شبكة) |
| P2 هوية/عضوية | جزئي | ADR-017 (issuer/session)، DEC-026/027/032 | نعم: سياق العضوية فقط (DEC-039) |
| P3 قراءة Moodle | محجوب | EXT-MDL-001..003 | لا |
| P4 مهام/اعتمادية | جزئي | DEC-030 (broker)، DEC-031 (DDL/PK)، قاعدة بيانات | نعم: آلة الحالات، الأحداث، سجل الخطوات، التجزئة |
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

مرفق أيضاً `contracts/agent_runtime_limits.v2.4.json` وتطابقه مع الثابت في الشيفرة مُختبَر.

## 3) ما شُغِّل فعلاً وما لم يُشغَّل

- **شُغِّل ونجح:** 41/41 اختباراً، لكن عبر بديل محلي صغير يحاكي `pytest.raises` فقط، لا pytest الحقيقي.
- **لم يُشغَّل:** pytest الحقيقي، ruff، mypy strict، اختبارات P1 المعتمدة على fastapi/pydantic، Flutter.
- **مخاطر معروفة عند أول تشغيل:** mypy strict قد يشكو من تعليقات `# type: ignore` في الاختبارات إن كان `warn_unused_ignores` فعّالاً؛ و`ruff format` سيعيد تنسيق بعض الأسطر الطويلة. إصلاحات صغيرة متوقعة.
- لم يُربط شيء من هذه النواة بـ FastAPI بعد (لا dependency ولا router)، عمداً، حتى يمر P1 CI أولاً.

## 4) قرارات اتخذتها وتحتاج موافقة (لا تُعد مغلقة)

1. **رفض الأعداد العشرية في المحتوى المجزَّأ.** RFC 8785 يتطلب تنسيق أرقام ECMAScript الذي لا تعيد بايثون إنتاجه دائماً. البديل: أعداد صحيحة (≤ 2^53−1) أو نصوص عشرية. يؤثر في تصميم QuizSpec (الدرجات مثلاً).
2. **NFC قبل ترتيب JCS.** نتيجته أن حروفاً مثل U+FB33 تتفكك وتتغير مواضعها مقارنة بمتجهات RFC الحرفية؛ المتجهات هنا مبنية على خط المعالجة المقترح لا على RFC وحده. متجهات التبادل مع أنظمة أخرى تحتاج اتفاقاً.
3. **GAP-TASK-001:** جدول الانتقالات في v2.0 لا يتيح CANCELLED من PLANNING/DRAFTING/VALIDATING/NEEDS_REVISION/APPROVED/EXECUTING/NEEDS_RECONCILIATION، بينما DEC-042 يقتضيه قبل الإرسال أو بعد إثبات غياب الأثر. أضفتها في `CANCEL_EXTENSIONS` منفصلة عن الجدول الحرفي. تحتاج تأكيد المالك.
4. **كل سياق عضوية غير صالح = 400 `MEMBERSHIP_CONTEXT_INVALID` بنفس الرسالة** (مجهول/غريب/معلّق/مُلغى) لمنع تعداد العضويات. العقد الحالي يستخدم BadRequest لهذا؛ إن فضّلتم 403 فهو تغيير عقد.

## 5) الخطوات التالية بالترتيب

1. على جهاز بشبكة: الخطوات الأربع في `PHASE1_STATUS.md` (lock، ruff، mypy، pytest الحقيقي، flutter)، ثم أول CI. هذه هي بوابة P1.
2. أرسل `P0_moallem-p0/02_moodle_admin_request.md` وعيّن المالكين (01). كل ما يخص Moodle ينتظر الرد.
3. وقّع/عدّل البنود الأربعة في القسم 4.
4. بعد نجاح CI: ربط `membership.py` كـ dependency في FastAPI، ثم `/me` (أول عملية من الـ17)، مع محقق جلسة وهمي صريح التسمية حتى يُحسم ADR-017.
5. DEC-031/030 قبل أي DDL أو outbox فعلي.

## 6) إضافة لاحقة: ربط العضوية و`/me` (غير مُشغَّل)

- `api/deps.py` و`api/me.py` و`tests/test_me_api.py` وتعديل `api/app.py` كُتبت وتُترجم (`compileall`) لكنها **لم تُشغَّل** لغياب fastapi/httpx هنا.
- المصادقة: `NoAuthenticator` افتراضيًا (يرفض كل شيء)، و`DevAuthenticator` يرفض الإنشاء خارج development/test. ADR-017 ما زال مفتوحًا.
- مستودع العضويات في الذاكرة وفارغ افتراضيًا حتى P4 (يفشل مغلقًا).
- أُضيف `INVITED` إلى `MembershipStatus` لتطابق enum العقد، وأُضيف اختباران لتطابق `TaskStatus` و`MembershipStatus` مع OpenAPI (شُغِّلا ونجحا).

## 7) إضافة لاحقة: idempotency وoutbox/inbox (P4-02/P4-03، منطق نطاق فقط)

- `domain/idempotency.py` + `tests/domain/test_idempotency.py` (9 اختبارات): HMAC للمفتاح، نطاق (tenant، عضوية، عملية، مفتاح)، `NEW / IN_PROGRESS / REPLAY`، تعارض الـhash = 409 في كل الحالات، ولا انتهاء لسجل خارجي غير مُسوّى. التفرد الفعلي يتطلب UNIQUE في PostgreSQL (DEC-031 مفتوح)؛ المخزن هنا بديل ذاكرة.
- `domain/outbox.py` + `tests/domain/test_outbox.py` (6 اختبارات): PENDING→LEASED→PUBLISHED/DEAD_LETTER، إعادة الاستحواذ بعد انتهاء المهلة فقط، fencing بـ`lease_generation`، وinbox dedup بالمفتاح (consumer، message).
- **بلا قيم افتراضية عمداً:** `ttl` (الاحتفاظ)، `max_attempts`، `retry_after`، ومفتاح HMAC الخادمي. المواصفة لا تحدد قيماً (DEC-030 وسياسة الاحتفاظ مفتوحان).
- **التحقق:** 56 اختباراً نطاقياً نجحت عبر بديل pytest (41 سابقة + 15 جديدة). لم يُشغَّل pytest الحقيقي ولا ruff ولا mypy. خطر معروف: أسطر طويلة ستحتاج `ruff format`، و`# type: ignore[arg-type]` في test_outbox قد يشكو منه mypy.
- **غير منجز:** جداول PostgreSQL، المعاملة الواحدة (سجل + Task + outbox + event)، المُرسِل (dispatcher)، P4-04 (إعادة تشغيل worker). كلها بعد DEC-030/031.
