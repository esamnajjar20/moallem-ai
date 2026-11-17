# تقرير تنفيذ الجزء الثاني — طبقة نموذج الذكاء الاصطناعي (AI Model)

**التاريخ:** 2026-11-17  
**النطاق:** P5-01 / AI provider transport and model runtime foundation.  
**الحالة:** تحسينات طبقة النقل والتسجيل والإعدادات مكتملة محليًا؛ اختيار المزوّد والموديل والمنطقة
والتشغيل الحقيقي ما زال مفتوحًا. لا يُعد هذا إغلاقًا كاملًا لـP5 أو ADR-018.

## 1. خلاصة التدقيق قبل التعديل

وجدت في النسخة السابقة:

- عقودًا مستقلة عن المزوّد (`AIRequest`, `AIProviderResponse`, `ProviderIdentity`, `ModelPricing`,
  `AIExecutionPermit`).
- `AIGateway` لتسجيل الاستدعاء قبل الإرسال، منع تكرار invocation، احتساب التكلفة، وتسجيل نتيجة
  `FAILED` أو `UNKNOWN` دون إعادة محاولة عمياء.
- `OpenAICompatibleHTTPProvider` كموصل اختياري، لكنه غير مكوّن تلقائيًا في API أو Worker.
- مستودع PostgreSQL لسجل الاستخدام ومراجع المصادر.
- `DenyAllAIExecution` فقط كمنفذ آمن؛ لا يوجد Authorizer إنتاجي يحجز ميزانية المهمة والمؤسسة
  ويسوّي التكلفة ويعالج الحجوزات المعلقة.
- لم يكن هناك تنفيذ ملموس لـ`AIProviderRegistry`، ولا إعدادات `MOALLEM_AI_*`، ولا مصنع يربط الإعدادات
  بالموصل.

## 2. التعديلات المنفذة

### إعدادات المزوّد والموديل

- أُضيفت إعدادات اختيارية ومترابطة: Provider ID، Model ID، Model Version، Region، Base URL، API
  Key، وقائمة مضيفين مسموحين.
- لا يتطلب النظام إعداد مزوّد في التطوير أو staging؛ غياب المجموعة ينتج Registry فارغًا.
- جميع إعدادات المزوّد إلزامية عند بدء ضبطها؛ الإعداد الجزئي يرفضه التحقق مبكرًا.
- مفاتيح API من نوع `SecretStr`، ولا تظهر في `repr` أو ملخص الإعدادات.
- ترفض الإعدادات HTTP، بيانات اعتماد URL، IP literals، wildcard hosts، والمضيف الذي لا يطابق
  allow-list مطابقة تامة.
- ترفض قيمة إصدار الموديل العامة `latest/stable/default/current` كإشارة alias غير مثبت.

### Registry وFactory

- تنفيذ `StaticAIProviderRegistry` بمعرفات دقيقة، ومنع تكرار Provider ID، وعدم وجود fallback تلقائي.
- إضافة `build_ai_provider_registry(settings)` لبناء الموصل المطابق للإعدادات الصريحة أو Registry
  فارغ عند عدم الإعداد.
- إضافة إغلاق عملاء HTTP عبر `await registry.aclose()`.
- إنشاء Registry لا ينفذ استدعاءً، ولا ينشئ Permit أو Budget Reservation، ولا يغيّر سياسة المنع.

### تقوية موصل HTTP

- إضافة allow-list صريحة لمضيف DNS المطابق تمامًا، مع استمرار HTTPS وTLS والتحقق الافتراضي.
- وضع حد لحجم جسم الطلب قبل الإرسال وحجم الاستجابة أثناء القراءة الخام.
- طلب `Accept-Encoding: identity` ورفض الاستجابة المضغوطة حتى لا تتجاوز decompression حدود الحجم.
- منع redirects وإعادة المحاولة، والحفاظ على تصنيف نتيجة الاستدعاء الملتبسة كـUNKNOWN.
- المحافظة على عدم تسجيل محتوى الرسائل أو نص الاستجابة.

### تقوية العقود والبوابة

- فرض حد أقصى 64 رسالة و1 MiB لمحتوى طلب النموذج، ورفض NUL والنصوص غير الصالحة UTF-8.
- فرض حد 2 MiB لنص مخرجات المزوّد.
- التحقق من أن نتيجة Provider هي فعلًا `AIProviderResponse` قبل استعمالها.
- إصلاح حالة حساب تكلفة لا يمكن تمثيلها في سجل الاستخدام: يسجل invocation كـUNKNOWN وتبقى الحجزات دون تحرير تلقائي، بدل تركه STARTED بصمت.

## 3. الاختبارات

تم تشغيل الاختبارات المركزة في البيئة الحالية:

```text
PYTHONPATH=backend/src pytest -q backend/tests/ai backend/tests/test_config.py
63 passed

PYTHONPATH=backend/src pytest -q backend/tests
442 passed, 45 skipped, 1 failed
```

تغطي المجموعة المركزة الحالية:

- التشغيل الافتراضي دون مزوّد وتسجيل المزوّد الصريح.
- منع provider IDs المكررة وعدم الانتقال إلى مزوّد بديل.
- رفض إعدادات AI الجزئية والمضيف غير المصرح به وIP literal وwildcards وmodel aliases.
- حماية سر API key في مخرجات الإعدادات.
- حدود الطلب والاستجابة، رفض الضغط، رفض redirects، وعدم إعادة المحاولة للأخطاء الملتبسة.
- عدم تسجيل prompt/output، ربط model ID، حالة invocation المكررة، وتسجيل usage/budget.
- overflow في حساب التكلفة يتحول إلى UNKNOWN ولا يحرر الحجز.

**قيد البيئة:** شغلت الاختبارات باستخدام Python 3.13.5. المشروع يطلب Python `>=3.12,<3.13`؛ لذلك لا أعتبر هذه
النتيجة بديلًا عن تشغيل بوابة Python 3.12.x المعتمدة. الاختبار الوحيد الفاشل خارج طبقة AI هو
`test_docs_disabled_in_production`؛ تعثر قبل تنفيذ assertion عند إنشاء محرك PostgreSQL بسبب أن حزمة
`psycopg` المعلنة في dependencies غير مثبّتة في بيئة التشغيل الحالية. تخطّت 45 حالة PostgreSQL لعدم
توفير `MOALLEM_TEST_DATABASE_URL` وخدمة PostgreSQL. لم تتوفر أدوات Ruff أو mypy ولم أتمكن من تشغيلهما.
لا توجد مفاتيح مزوّد حقيقية أو اتصالات خارجية في الاختبارات.

## 4. ما أُغلق برمجيًا وما لم يُغلق

| البند | الحالة | الملاحظة |
|---|---|---|
| Provider-neutral contracts | موجود سابقًا | لم يتم تغيير واجهة المجال الأساسية |
| Optional model/provider settings | منفذ | مع تحقق all-or-none وحماية الأسرار |
| Exact-ID provider registry | منفذ | بلا fallback |
| Provider factory | منفذ | لا يفعّل التنفيذ |
| HTTPS/host allow-list/request-response caps | منفذ | egress firewall يبقى مطلوبًا |
| Ambiguous outcome handling | منفذ ومحسن | لا retry تلقائي |
| Usage ledger PostgreSQL | موجود سابقًا | يتطلب تشغيل اختبارات PostgreSQL الفعلية |
| Production budget Authorizer | غير منفذ | لا يجوز تجاوزه أو استخدام Fake authorizer في الإنتاج |
| Provider/model/region decision ADR-018 | OPEN | لا يوجد اعتماد للمالك |
| Data-class/privacy/retention approval | OPEN | DEC-028 وADR-018 |
| Model benchmark against two providers | غير منفذ | يحتاج اختيار المرشحين ومفاتيح/خدمات مصرح بها ومراجعين |
| Production end-to-end from Worker | غير منفذ | لا يوجد AI task handler موصول |
| Quiz generation schema/educational validator | خارج هذا الجزء | يتبع P6 وDEC-033/034 |

## 5. بوابات قبل تفعيل النموذج

1. اعتماد ADR-018 من Product وPrivacy وEducation وFinOps: المزوّد، الموديل الدقيق والإصدار،
   المنطقة، البيانات المسموح بإرسالها، الشروط، الاحتفاظ، والأسعار.
2. تجربة نموذجين مُدارين على benchmark عربي اصطناعي موحد؛ مع مراجعة بشرية ومعايير قبول يقرّها
   Education Lead وفق ADR-024 وDEC-033/034.
3. إغلاق DEC-043: أسعار موثقة، سقف لكل Task وسقف زمني لكل Tenant، وحجز ذري قبل الاستدعاء.
4. تنفيذ Authorizer إنتاجي دائم مع settlement وorphan-reservation reconciliation وسجل عمليات
   `UNKNOWN` قابل للمراجعة.
5. اعتماد egress host allow-list ومكان تخزين السر ودوران المفتاح ومراقبة الاستخدام.
6. اختبار PostgreSQL integration/Concurrency على Python 3.12.x، ثم اختبار staging حقيقي دون بيانات
   أشخاص قبل فتح بيانات المقررات الحقيقية.
7. توصيل AI handler بالـWorker بعد إغلاق جميع البوابات السابقة، وليس قبلها.

## 6. القرار النهائي

**تم إغلاق فجوات كود الإعداد والتسجيل والنقل التي يمكن تنفيذها دون اختيار مزوّد.** لا أعتبر اختيار
الموديل أو جودة المخرجات أو التشغيل الإنتاجي مغلقًا؛ فهذه تحتاج قرارًا وقياسًا وبيانات اعتماد لم
تُقدّم بعد. يبقى `DenyAllAIExecution` هو السلوك الآمن، ويظل P5 = PARTIAL / NOT READY.
