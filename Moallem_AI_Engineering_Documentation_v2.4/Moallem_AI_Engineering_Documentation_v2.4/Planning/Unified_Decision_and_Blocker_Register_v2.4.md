# Moallem AI — سجل القرارات والعوائق الموحد v2.4

**الحالة:** سجل التخطيط المرجعي الوحيد اعتباراً من 15 نوفمبر 2026؛ ويضم خطوط الأساس المقترحة لإغلاق P0-H إلى P0-L في v2.4. يحل هذا السجل محل ترقيم `BLK-*` المتعارض بين سجل Markdown وورقة Excel في v2.1. احتُفظ بمعرفات ADR-015 إلى ADR-025 كما هي لتجنب كسر الإحالات التاريخية.

## قواعد المعرفات والحالات

- `ADR-*` قرار معماري/منتجي مسجل؛ يبقى مفتوحاً حتى يملك قراراً ومالكاً وأساساً وأثرًا وتاريخ مراجعة.
- `DEC-*` قرار إضافي لم يكن له ADR مستقل؛ يجب نقله لاحقاً إلى ADR رسمي عند اعتماده.
- `EXT-*` مدخل خارجي مطلوب من مسؤول أو جهة أخرى.
- `VER-*` تحقق تجريبي لا يثبت بمجرد قراءة وثيقة عامة.
- `GAP-*` فجوة في الوثائق أو العقد يجب تصحيحها قبل تجميد مواصفات التنفيذ.

الحالات: `BASELINED` مبدأ موثق لا يعني التنفيذ؛ `PROPOSED` خط أساس تصميمي محدد لم يعتمد بعد؛ `READY_FOR_APPROVAL` حزمة قرار مكتملة تنتظر توقيع المالك؛ `OPEN` قرار غير محسوم؛ `BLOCKED` ينتظر مدخلاً/قراراً؛ `VERIFY` يحتاج دليلاً تجريبياً؛ `CLOSED` لا يستخدم إلا بعد إرفاق دليل أو قرار معتمد.

## A. قرارات ADR قائمة

| ID | القرار | الحالة | المالك | بوابة الإغلاق / معيار القرار |
|---|---|---|---|---|
| ADR-015 | Flutter state management (Riverpod vs Bloc) | OPEN | Mobile Lead | Prototype صغير + قابلية الاختبار والصيانة وتوافق الفريق؛ لا يُعد مانعاً لقرارات Moodle. |
| ADR-016 | Python type checker (Pyright vs mypy) | OPEN | Backend Lead | تجربة CI صارمة على مشروع نموذجي وتوثيق سياسة strictness. |
| ADR-017 | Identity/authentication/session flow | IMPLEMENTED / VERIFY EXTERNAL | Product + Security | Backend MVP decision and implementation recorded in `docs/adr/ADR-017-authentication-and-session.md`: Auth0 OIDC PKCE client, RS256 API access tokens <=900s, rotating refresh tokens on native SDK, pre-provisioned subject mapping, immediate API deny for SUSPENDED/REVOKED users, MFA required in Auth0 MVP policy. Live tenant and Android/iOS device evidence remain a release gate. |
| ADR-018 | AI provider/model/data region | OPEN | Product + Privacy | العربية، جودة التعليم، شروط البيانات، الاحتفاظ، region، التكلفة، latency وfallback. |
| ADR-019 | SSE vs polling | OPEN | Backend + Mobile | مقارنة على شبكة ضعيفة/بطارية/عدد الاتصالات؛ GET task status يبقى مصدر الحالة. |
| ADR-020 | Hosting provider/region/network | OPEN | Product + Infra | PostgreSQL and AES-256-GCM selected for P4 on 2026-11-16; hosting, residency, egress, availability, budget, backup, Moodle/AI connectivity remain open. See owner approval record. |
| ADR-021 | Admin console scope/technology | DEFERRED | Product + Ops | بعد ثبوت احتياج الدعم/Pilot؛ لا يوسع MVP. |
| ADR-022 | RPO/RTO | OPEN | Product + Ops | أثر الانقطاع، كلفة الحماية، ونتيجة restore drill موثقة. |
| ADR-023 | SLO/capacity/concurrency | OPEN | SRE/FinOps | baseline ثم pilot load؛ الأهداف الحالية فرضيات لا SLA. |
| ADR-024 | Educational AI quality governance | BASELINED-PRINCIPLE | Education Lead | اعتماد rubric version، المجال/الصفوف، golden set، المراجعين وحد القبول. |
| ADR-025 | Release governance | CONDITIONAL | Ops/Release | CI/CD وstaging، rollback/forward-fix، evidence pack ومصفوفة توافق. |

## B. قرارات إضافية يجب حسمها

| ID | القرار | الحالة | المالك | البدائل/أسئلة الحسم | بوابة الإغلاق |
|---|---|---|---|---|---|
| DEC-026 | هل يمكن مشاركة Moodle Site بين أكثر من Tenant؟ | OPEN | Product + Architecture | سجل Site مركزي مع grants منفصلة؛ أو Site مستقل لكل Tenant. لا تفترض مشاركة credential أو صلاحيات بين tenants. | تحديد ownership، isolation boundaries، uniqueness، billing، revocation واختبارات cross-tenant. |
| DEC-027 | Permission Matrix teacher × action × resource | OPEN | Product + Security | صلاحية على مستوى المقرر/النشاط/نوع العملية؛ دور Moodle وحده لا يكفي. | مصفوفة قابلة للاختبار لكل فعل قراءة/كتابة/موافقة ودور. |
| DEC-028 | Retention/deletion/anonymization | OPEN | Product + Privacy | مدد منفصلة للمحتوى والملفات والمقاطع/embeddings والتدقيق والنسخ الاحتياطية. | Data lifecycle map + مدد + deletion propagation + legal/contract review. |
| DEC-029 | Object Storage/KMS/region/lifecycle | OPEN | Infra + Security | AES-256-GCM selected as the application-level encryption algorithm on 2026-11-16; KMS/Secret Manager, key rotation, region, lifecycle, backups, deletion and signed-URL policy remain open. | اختيار موثق واختبار وصول وعزل وحذف واستعادة. |
| DEC-030 | Queue delivery/persistence/retry/DLQ/visibility | OPEN | Backend + Ops | Celery/Redis أو وسيط آخر؛ ack timing؛ lease؛ retry/backoff؛ dead-letter؛ ordering. | ADR واختبارات crash/duplicate/poison message وقيود عدم ضياع outbox. |
| DEC-031 | PK strategy وDDL النهائي | OPEN | Tech Lead | PostgreSQL selected for P4 on 2026-11-16; internal/external IDs, PK/FK strategy, membership history and final production DDL remain open. | DDL review + migration/upgrade tests. |
| DEC-032 | RLS أم عزل التطبيق والمفاتيح المركبة أم الجمع بينهما؟ | OPEN | Backend + Security | RLS defense-in-depth مقابل كلفة إدارة session context وpooling. | threat analysis واختبارات عزل worker/API/cache/storage، لا قرار شكلي فقط. |
| DEC-033 | أنواع الأسئلة التي تدخل MVP وQuestion DTO | OPEN | Product + Education | اختيار نوع/أنواع بداية محدودة، بنية الإجابة والتصحيح والمشتتات والوسائط. | Scope واضح + discriminated schema + golden examples + Moodle mapping. |
| DEC-034 | النطاق التعليمي وعتبات الجودة | OPEN | Education Lead | صف/مرحلة/مادة/منهاج/لغة؛ دقة المصدر؛ طريقة التحكيم واتفاق المراجعين. | Golden Dataset ومقياس قبول/رفض محدد ومبرر. |
| DEC-035 | External operation identity/idempotency | PROPOSED | Integration + Backend | في MVP تحفظ هوية العملية والخطوة بشكل ثابت؛ لا يسمح بالـautomatic retry بعد dispatch إلا إذا أثبت Moodle-side lookup موثوق الغياب؛ وإلا manual reconciliation. | اعتماد DEC-041 وإثبات timeout-after-success على staging؛ طريقة lookup الفعلية تبقى EXT/VER-MDL evidence. |
| DEC-036 | التعامل مع partial Moodle writes | PROPOSED | Integration + Backend | تنفيذ مركب durable بخطوات مستقلة مسجلة؛ forward recovery هو الافتراضي؛ لا تعويض/حذف تلقائي دون عملية معتمدة ومثبتة. | اعتماد DEC-041 وإثبات إنشاء/استعادة/تحقق كل خطوة على Moodle staging؛ broker وlookup الفعليان يبقيان مدخلين منفصلين. |
| DEC-037 | دورة حياة ربط Moodle والاعتمادات | PROPOSED | Product + Security | أساس MVP: enroll/validate/rotate/local disconnect مع Web Service token لمستخدم مخوّل وحفظ vault-only؛ لا يثبت token وحده domain ownership ولا يحقق remote revoke تلقائيًا. | اعتماد DEC-040، تحديد UX/المالك، فحص staging وصلاحيات الخدمة، وموافقة Security؛ remote revoke يبقى Moodle Admin/Plugin action. |
| DEC-038 | Offline drafts/cache وبيانات الهاتف | OPEN | Product + Security + Mobile | ما الذي يحفظ محلياً؟ TTL؟ تشفير؟ حذف عند logout/revoke؟ هل المسودة المحلية مستقلة عن Snapshot server-side؟ | سياسة لكل نوع بيانات وحالات device loss/account switch. |

ملاحظة تحديث v2.4: قرارات DEC-035..037 أصبحت خطوط أساس مقترحة ضمن DEC-041/DEC-040 وبوابات P0-I/P0-L؛ لا يعني تغييرها إلى PROPOSED أن Local Plugin أو lookup الحي أو صلاحيات موقع Moodle قد ثبتت.

## C. مدخلات خارجية

| ID | المدخل | الحالة | المالك الخارجي | المطلوب |
|---|---|---|---|---|
| EXT-MDL-001 | Moodle staging profile | BLOCKED | Moodle Admin | URL عبر HTTPS، version/build، إعدادات البروتوكول، سياسة الشبكة والمهلات. |
| EXT-MDL-002 | Live Web Services documentation | BLOCKED | Moodle Admin | API docs الحية/قائمة الدوال المضافة للخدمة وschema المعاملات/الاستجابات. |
| EXT-MDL-003 | Teacher test identity and course | BLOCKED | Moodle Admin | حساب معلم تجريبي، مقرر تجريبي، membership/role/capabilities موثقة. |
| EXT-MDL-004 | Local Plugin deployment authority | OPEN/CONDITIONAL | Moodle Admin + Product | من يثبت/يحدّث/يوقع/يصون الإضافة؟ وما سياسة مراجعة الكود؟ |

## D. تحقق Moodle المطلوب

| ID | العملية | الحالة | دليل القبول |
|---|---|---|---|
| VER-MDL-001 | Discovery: version/build/services/functions/capabilities | VERIFY | نتيجة من site staging مرتبطة بتاريخ وإعدادات الخدمة. |
| VER-MDL-002 | List teacher courses + course contents | VERIFY | طلب/استجابة منقحان واختبار صلاحيات إيجابي/سلبي. |
| VER-MDL-003 | Quiz shell/settings | BLOCKED | إنشاء وقراءة إعدادات الاختبار بحساب teacher. |
| VER-MDL-004 | Question category and question creation | BLOCKED | إنشاء/إيجاد category وإنشاء كل نوع سؤال معتمد في MVP. |
| VER-MDL-005 | Add/order/mark question slots | BLOCKED | ربط الأسئلة بالاختبار والتحقق من الترتيب والدرجات. |
| VER-MDL-006 | Read-back verification | BLOCKED | مقارنة مستقلة للمقرر والإعدادات وعدد/مراجع الأسئلة. |
| VER-MDL-007 | Timeout after successful or partial write | BLOCKED | قطع الرد بعد أثر فعلي؛ reconciliation يكتشف الأثر ولا يكرر. |
| VER-MDL-008 | Token expired/revoked, permissions, throttling | VERIFY | تصنيف خطأ موثق وعدم retry أعمى وعدم تسريب أسرار. |

## E. فجوات وثائقية/تعاقدية

| ID | الفجوة | الحالة بعد v2.2 | الملف المتأثر | الإجراء |
|---|---|---|---|---|
| GAP-API-001 | اختلاف العمليات والمسارات بين Word وOpenAPI | PARTIALLY-CORRECTED | `Specifications/02_API_Contract_v2.4_Addendum.docx`, `Contracts/openapi.draft.yaml` | OpenAPI draft يحتوي 17 عملية ومعاملات path/header موحدة؛ يتبقى اعتماد مصدر العقد النهائي وتشغيل validator/route parity في CI. |
| GAP-API-002 | QuizSpec وQuestion DTO ليسا نهائيين | PARTIALLY-CORRECTED | `Contracts/openapi.draft.yaml`, `Specifications/02_API_Contract_v2.4_Addendum.docx` | `QuizSpec` وtransport DTOs محددة مبدئيًا؛ QuestionDraft union وأنواع الأسئلة والحدود التعليمية تبقى DEC-033/034. |
| GAP-API-003 | Idempotency مذكور عاماً وغير متصل بكل الكتابات | PARTIALLY-CORRECTED | OpenAPI + API Spec | أضيفت الرؤوس إلى revisions/approvals/cancel/validation؛ يلزم تحديد retention/expiry وatomic storage. |
| GAP-API-004 | العميل يرسل destination ضمن ApprovalRequest | CORRECTED-IN-DRAFT | OpenAPI + API Spec | أزيل destination من الطلب؛ يؤخذ من snapshot المحفوظ على الخادم. |
| GAP-DATA-001 | canonical hash بلا خوارزمية تطبيع دقيقة | OPEN | DB + Agent | تحديد canonical JSON، Unicode normalization، number/time encoding، schema version وtest vectors. |
| GAP-DATA-002 | سباق concurrent edit/approval غير معرف | OPEN | DB + API + Agent | optimistic concurrency عبر base snapshot version/hash، رفض stale revision/approval ذرياً. |
| GAP-AGENT-001 | نتيجة timeout لا يمكن البحث عنها إذا لم يصل external_quiz_ref | PARTIALLY-CORRECTED | `Specifications/03_04_Reliability_and_Tool_Registry_v2.4_Addendum.docx`, `Contracts/tool_registry.draft.json` | v2.4 يثبت external_operation_key ويحدد lookup موثوقًا إن توفر؛ بدونه manual reconciliation بلا retry آلي. Local Plugin/lookup proof ما زال EXT/VER-MDL. |
| GAP-AGENT-002 | partial write (shell created, questions incomplete) غير مفصل | PARTIALLY-CORRECTED | `Specifications/03_04_Reliability_and_Tool_Registry_v2.4_Addendum.docx`, `Planning/Planning_Closure_Decisions_v2.4.docx` | كل خطوة لها external_step_key/state؛ forward recovery أو manual review افتراضي؛ لا compensation آلي. يحتاج staging fault test وتحديد plugin/lookup. |
| GAP-PRIV-001 | data flow/retention/deletion غير مكتمل | OPEN | Security + DB + Ops | Data inventory and lifecycle incl. embeddings, logs, backups, provider copies. |
| GAP-TEST-001 | traceability لا تغطي كل قرارات ومكونات الرحلة | PARTIALLY-CORRECTED | `Planning/Requirements_Traceability.csv`; `Planning/Test_ID_Catalog_v2.4.csv` | v2.4 يضم 31 requirement و80 Test IDs ويربط IDs بالدليل والمالك؛ تبقى أدلة التنفيذ ونتائج الاختبار واستكمال الربط مع كل قرار/مكون أثناء التنفيذ. |
| GAP-OPS-001 | semantics queue/lease/retry/DLQ لم تحسم | PARTIALLY-CORRECTED | `Specifications/03_04_Reliability_and_Tool_Registry_v2.4_Addendum.docx`, `Planning/Planning_Closure_Decisions_v2.4.docx` | v2.4 يحدد PostgreSQL ledger/outbox/inbox، lease fencing، dedup and UNKNOWN semantics؛ اختيار broker وvisibility/DLQ/retry tuning يبقى DEC-030 واختبارات الفشل. |
| GAP-UX-001 | دورة ربط Moodle غير معرفة من البداية للنهاية | OPEN | PRD + Flutter + API | ربط/تجديد/إبطال/فصل connection sequence. |

## F. مرجع mapping للمعرفات القديمة

- سجلات `BLK-001..BLK-022` في Markdown v2.1 و`BLK-001..BLK-008` في Excel v2.0 ليست namespace موحدة. لا تنقل المعرفات القديمة إلى ملاحظات جديدة.
- `BLK-001` في السجلين كان حول Moodle site، ويمكن ربطه بـ`EXT-MDL-001`.
- `BLK-002` في Markdown كان تفعيل Web Services، بينما `BLK-002` في Excel كان Quiz create/question/slot mappings؛ أصبحا `EXT-MDL-002` و`VER-MDL-003..005` على التوالي.
- بقية mapping يتبع الموضوع لا الرقم؛ هذا السجل هو المرجع المعتمد لأي إحالة جديدة.

## G. قاعدة الإغلاق

لا يغلق أي `DEC/ADR` بمجرد كتابة اختيار؛ يجب تسجيل المبررات والبدائل المرفوضة والآثار والمالك والتاريخ. ولا يغلق `EXT/VER` دون evidence من المصدر/البيئة المعنية. لا يعني `CLOSED` أن التنفيذ اكتمل إلا إذا كان دليل التنفيذ/الاختبار جزءاً من الإغلاق.


## H. قرارات وفجوات أضيفت في تدقيق الاتساق v2.4

### H.1 قرارات مفتوحة جديدة

| ID | النوع | القرار | الحالة | المالك | بوابة الإغلاق / معيار القرار |
|---|---|---|---|---|---|
| DEC-039 | DEC / Identity & Tenancy | طريقة تمرير سياق العضوية النشطة في الطلبات متعددة المؤسسات | PROPOSED | Backend + Security + Product | اعتماد X-Active-Membership-ID إلزاميًا لكل طلب tenant-scoped عدا GET /me؛ الخادم يشتق user/tenant/roles من بيانات موثوقة ويتحقق من owner + ACTIVE + permission في كل طلب. READY_FOR_APPROVAL؛ Auth0 token/session implementation is recorded under ADR-017. |
| DEC-040 | DEC / Moodle Connection | دورة إنشاء/ربط اتصال Moodle وإدارة بيانات الاعتماد | PROPOSED | Product + Security + Integration | MVP يستخدم legacy External Web Services token لمستخدم Moodle مخوّل وخدمة مخصصة؛ enroll/validate/rotate/local disconnect؛ vault-only storage؛ remote revoke في Moodle Admin ما لم يثبت Plugin/API. لا ادعاء domain ownership بمجرد token. READY_FOR_APPROVAL؛ site mapping BLOCKED. |
| DEC-041 | DEC / Reliability | هرم معرفات نية النشر والعملية الخارجية والخطوة الخارجية | PROPOSED | Backend + Integration | اعتماد هرم ثابت: publish_intent_id + external_operation_key + external_step_key؛ attempt_no عداد نقل فقط؛ قيد UNIQUE على tenant/publish_intent/step؛ UNKNOWN لا يعاد إلا بعد إثبات الغياب. READY_FOR_APPROVAL. |
| DEC-042 | DEC / Task Lifecycle | سلوك الإلغاء بعد إرسال كتابة خارجية | PROPOSED | Backend + Product + Integration | Cancel هو intent. قبل dispatch يجوز CANCELLED؛ بعد dispatch يبقى cancel_requested مع EXECUTING أو NEEDS_RECONCILIATION حتى يثبت الغياب أو تتم تسوية الأثر. UNKNOWN لا يساوي CANCELLED. READY_FOR_APPROVAL. |
| DEC-043 | DEC / Agent Runtime | حدود تشغيل الوكيل والمهام والأدوات والميزانيات | PROPOSED | Agent + Ops + Security | حدود MVP المقترحة في agent_runtime_limits.v2.4.json: 900s/24 steps/30 outer tool calls/2 parallel/24k tokens/256 external steps per composite publish/2 read retries/0 write retries after dispatch; per-task and tenant-period cost reservations are atomic. Cost + tenant budgets إلزامية بلا default؛ عند غيابها يوقف AI task. READY_FOR_APPROVAL + FinOps calibration. |
| DEC-044 | DEC / Events & API | ترتيب أحداث المهمة وسلوك cursor عند إعادة الاتصال | PROPOSED | Backend + Mobile | task_events.sequence BIGINT رتيب لكل task؛ UNIQUE(tenant_id,task_id,sequence)؛ cursor opaque/versioned/exclusive (sequence > last_sequence)؛ 410 عند انتهاء الاحتفاظ؛ GET status authoritative. READY_FOR_APPROVAL. |

### H.2 فجوات جديدة

| ID | المجال | الفجوة | الحالة | الإجراء المطلوب |
|---|---|---|---|---|
| GAP-API-005 | API/Identity | سياق العضوية النشطة يحتاج اعتماد selector وتطبيق تحقق موحد. | CORRECTED-IN-DRAFT | X-Active-Membership-ID إلزامي في عقد v2.4 المقترح؛ الخادم يتحقق من owner/ACTIVE/tenant/permissions، ولا يقبل tenant/role من العميل. اختبار AT-037 مطلوب. |
| GAP-API-006 | API/Moodle Connection | دورة الاتصال كانت ناقصة في عقد v2.3. | CORRECTED-IN-DRAFT | أضيفت POST enroll وGET detail وPOST validate-by-id وPUT credential rotate وDELETE local disconnect. الإبطال البعيد موثق كإجراء Moodle Admin/Plugin ولا يدعي API غير مثبت. Site-specific validation ما زالت BLOCKED. |
| GAP-API-007 | API Contract | DTOs والأخطاء والـcursor كانت عامة أو ناقصة. | PARTIALLY-CORRECTED | v2.4 يحدد transport DTOs وerror enum وsequence cursor وretry classification؛ يظل Question payload union وأنواع الأسئلة OPEN تحت DEC-033. |
| GAP-AGENT-003 | Agent/Tool Registry | Registry v2.3 لم يكن يحقق عقد كل أداة. | CORRECTED-IN-DRAFT | v2.4 يضيف JSON Schema draft 2020-12 input/output لكل أداة وبقية حقول policy؛ لا تزال كل الأدوات executable=false حتى اختبار schemas وتطبيق permission engine، كما تظل Moodle tools BLOCKED/VERIFY. |
| GAP-DATA-003 | Data/Queue | تفاصيل idempotency/outbox/inbox/tool invocation كانت غير مكتملة. | CORRECTED-IN-DRAFT | v2.4 يحدد scope/hash/state/lease/reclaim/transaction boundary/step identity. مدد الاحتفاظ الدقيقة وسياسة DLQ النهائية تحتاج توافق retention وقرار DEC-030. |
| GAP-TASK-001 | Task Lifecycle | إلغاء المهمة بعد dispatch لم يكن له معنى نهائي. | CORRECTED-IN-DRAFT | cancel_requested منفصل عن CANCELLED؛ قبل dispatch يمكن إلغاء آمن، بعد dispatch reconciliation/settlement مطلوب؛ unresolved لا يصبح absent. |
| GAP-OPS-002 | Agent/Operations | حدود الوكيل وميزانياته لم تكن معرفة. | CORRECTED-IN-DRAFT | حدود عددية مقترحة في agent_runtime_limits.v2.4.json؛ ميزانية التكلفة لكل Task/Tenant إلزامية وتظل غير محددة ماليًا حتى ADR-018/FinOps. |
| GAP-TEST-002 | QA/Governance | كان هناك Test IDs في Traceability دون فهرس موحد يعرّف النطاق والدليل والمالك. | CORRECTED-IN-DRAFT | أضيف `Planning/Test_ID_Catalog_v2.4.csv` بفهرس موحد من 80 معرفًا؛ يجب تسجيل أي معرف جديد فيه وربط كل Requirement بدليل قبول ومالك قبل اعتماد التخطيط. |
| GAP-MATRIX-001 | Moodle Inventory | اختلاف عنوان إصدار XLSX عن JSON/اسم الملف، وثلاثة سجلات جديدة كانت تفتقد حالة مرجع الإصدار، وعدد السجلات التاريخية كان يوصف بإجمال غير دقيق. | CORRECTED-IN-DRAFT | توحيد title على v2.0 وإكمال MCAPI-246..248 وتوضيح 237 سجلًا موسومًا صراحةً بـ3.11 + سجل MCAPI-245 التاريخي ذي تحديث response في 5.3. |

## I. بوابات قبول التخطيط v2.3

| البوابة | المطلوب قبل إغلاقها | الحالة |
|---|---|---|
| P0-H Membership Context | X-Active-Membership-ID إلزامي والتحقق من owner/ACTIVE/tenant/resource لكل طلب؛ AT-037 | READY_FOR_APPROVAL |
| P0-I Connection Lifecycle | legacy External Service token + enroll/validate/rotate/local disconnect + vault + pending-task disposition؛ remote revoke is Moodle Admin action | READY_FOR_APPROVAL |
| P0-J Contract Completeness | transport DTOs + Error Catalogue + sequence cursor + retry semantics + connection API؛ Question union باقٍ تحت DEC-033 | READY_FOR_APPROVAL_WITH_DOMAIN_RESIDUAL |
| P0-K Tool Contract | versioned schemas وpolicy metadata لكل أداة؛ runtime guardrails مقترحة؛ executable=false حتى CI/policy engine/site mapping | READY_FOR_APPROVAL |
| P0-L Reliability & Cancel | publish/operation/step identities؛ transactional ledger/outbox/inbox؛ ordered events؛ cancellation and manual reconciliation semantics | READY_FOR_APPROVAL |
| P1-M Test Governance | فهرس شامل للـTest IDs وربط كل requirement باختبار معرف ودليل | PROPOSED |
| P1-N Matrix Hygiene | اتساق JSON/XLSX/README ومرجع الإصدار والسجلات الحديثة | CORRECTED-IN-DRAFT |

## J. ملاحظات مرجعية على مصفوفة Moodle

- العدد الفعلي: 248 سجلًا، 239 اسم دالة فريدًا، 12 فجوة وظيفية.
- 237 سجلًا تحمل صراحةً عبارة مرجع كتالوج MoodleDocs التاريخي 3.11.
- MCAPI-245 سجل تاريخي منفصل وموثق كتحديث response في Moodle 5.3، وليس من السجلات الموسومة حرفيًا بعبارة 3.11.
- MCAPI-246 إلى MCAPI-248 إضافات Moodle 5.3 مرتبطة بـMDL-86513؛ أُكملت قيمة مرجع الإصدار لها في بيانات v2.3.
- إصدار Moodle 5.3.1 هو آخر patch منشور في سلسلة 5.3 بتاريخ فحص 15 نوفمبر 2026؛ لا تعني هذه المعلومة أن موقع الجامعة يعمل بهذا الإصدار أو يتيح الوظائف.


## L. خطوط الأساس المقترحة لإغلاق P0-H إلى P0-L في v2.4

| البوابة | القرار المقترح | ملفات التفاصيل | بقايا الاعتماد/الإثبات |
|---|---|---|---|
| P0-H | X-Active-Membership-ID لكل طلب مؤسسي عدا GET /me؛ لا tenant_id/role من العميل. | `Planning/Planning_Closure_Decisions_v2.4.docx`; `Contracts/openapi.draft.yaml` | اعتماد Product/Security + AT-037. |
| P0-I | Moodle legacy External Web Service token لمستخدم مخوّل وخدمة مخصصة؛ Secret Manager؛ rotate بعد تحقق؛ DELETE يفصل محليًا ولا يدعي remote revoke. | `Specifications/02_API_Contract_v2.4_Addendum.docx` | Moodle staging + live functions + AT-038..040؛ إبطال Moodle البعيد مسؤولية الموقع. |
| P0-J | Typed transport schemas، 17 operation، Error Code enum، cursor sequence. QuestionDraft union يظل DEC-033. | `Contracts/openapi.draft.yaml` | OpenAPI validator/contract tests + قرار question types. |
| P0-K | JSON Schema لكل أداة وpolicy contract كامل؛ runtime caps مقترحة؛ التكلفة mandatory config. | `Contracts/tool_registry.draft.json`; `Contracts/agent_runtime_limits.v2.4.json` | approval + registry completeness CI + provider/FinOps budgets. |
| P0-L | Postgres idempotency/outbox/inbox/tool ledger، per-step identity، cancel intent/reconciliation، sequence events. | `Specifications/03_04_Reliability_and_Tool_Registry_v2.4_Addendum.docx` | اختيار broker DEC-030 + اختبار Moodle/Plugin للـlookup؛ بدونه manual reconciliation. |

### L.1 ما لا يغلق تلقائيًا
- تنفيذ Backend لـ`ADR-017` أصبح IMPLEMENTED؛ لا تُعتبر بوابة Auth0/PKCE مغلقة قبل اختبار tenant حقيقي وأجهزة Android/iOS. Header العضوية ليس دليل هوية.
- `DEC-033/034` أنواع الأسئلة والـGolden Dataset ما زالت OPEN.
- `DEC-030` وسيط الطابور و`ADR-018/020` و`DEC-028/029` مزود AI/المنطقة/الأسرار/الاحتفاظ ما زالت OPEN.
- `EXT-MDL-*` و`VER-MDL-*` لا تُغلق دون بيئة Moodle المستهدفة وأدلة حية.
- أي عملية كتابة Moodle لا تملك lookup موثوقًا بمفتاح العملية تبقى manual reconciliation عند نتيجة UNKNOWN.

## M. حالة المستندات v2.4

خطوط أساس v2.4 أصبحت مكتملة على مستوى التصميم المقترح وتنتظر اعتماد أصحاب القرار؛ لا يعني READY_FOR_APPROVAL أنها CLOSED. OpenAPI وTool Registry يظلان مسودتين غير قابلتين للاستخدام الإنتاجي، ولا يوجد اختبار حي أو تكامل Moodle مثبت. عند التعارض، تطبق ملاحق v2.4 على عناصر النطاق التي تغطيها، ثم v2.3/v2.2، مع بقاء مواصفات v2.0 baseline للمجالات الأخرى.

### M.1 Owner approval recorded on 2026-11-16

The Project Owner approved v2.4 as the planning baseline and selected Auth0, PostgreSQL, and
AES-256-GCM for the scoped implementation work. The exact approval and residual open items are in
`Planning/Owner_Approval_Record_v2.4_2026-11-16.md`. ADR-017's Backend MVP implementation is now
recorded separately; this does not close live Auth0/device verification, ADR-020, DEC-029,
DEC-030, DEC-031, DEC-032, DEC-033, DEC-034, or any Moodle external/verification item.


## إضافات P0-L التفصيلية
- `moodle.create_quiz` هو durable async command: مهلة 15 ثانية لإقرار الحفظ الدائم، ثم ينفذ Worker الخطوات الخارجية كلًا على حدة بمهلة 30 ثانية لكل خطوة ضمن 900 ثانية للمهمة.
- `max_tool_calls_per_task=30` يعد استدعاءات الأدوات الخارجية في Registry، ولا يعد الخطوات الداخلية للمركب؛ `max_external_steps_per_publish=256` حد منفصل، مع كتابة واحدة متزامنة لكل Moodle connection.
- Idempotency-Key يولده العميل بمصدر عشوائي تشفيري بقوة 128-bit على الأقل؛ يحفظ الخادم HMAC للمفتاح ولا يحفظ النص الخام. IN_PROGRESS يعيد مرجع العملية نفسه/202؛ النتائج النهائية يعاد تشغيلها؛ اختلاف hash يرجع 409.
- حجز ميزانية AI يتم ذريًا في PostgreSQL على مستويي المهمة ودورة المؤسسة قبل بدء التنفيذ؛ تتم تسوية الاستخدام وإرجاع الحجز غير المستهلك.
