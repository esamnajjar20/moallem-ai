# Moallem AI — سجل القرارات والعوائق الموحد v2.2

**الحالة:** سجل التخطيط المرجعي الوحيد اعتباراً من 15 نوفمبر 2026. يحل هذا السجل محل ترقيم `BLK-*` المتعارض بين سجل Markdown وورقة Excel في v2.1. احتُفظ بمعرفات ADR-015 إلى ADR-025 كما هي لتجنب كسر الإحالات التاريخية.

## قواعد المعرفات والحالات

- `ADR-*` قرار معماري/منتجي مسجل؛ يبقى مفتوحاً حتى يملك قراراً ومالكاً وأساساً وأثرًا وتاريخ مراجعة.
- `DEC-*` قرار إضافي لم يكن له ADR مستقل؛ يجب نقله لاحقاً إلى ADR رسمي عند اعتماده.
- `EXT-*` مدخل خارجي مطلوب من مسؤول أو جهة أخرى.
- `VER-*` تحقق تجريبي لا يثبت بمجرد قراءة وثيقة عامة.
- `GAP-*` فجوة في الوثائق أو العقد يجب تصحيحها قبل تجميد مواصفات التنفيذ.

الحالات: `BASELINED` مبدأ موثق لا يعني التنفيذ؛ `PROPOSED` اقتراح لم يعتمد؛ `OPEN` قرار غير محسوم؛ `BLOCKED` ينتظر مدخلاً/قراراً؛ `VERIFY` يحتاج دليلاً تجريبياً؛ `CLOSED` لا يستخدم إلا بعد إرفاق دليل أو قرار معتمد.

## A. قرارات ADR قائمة

| ID | القرار | الحالة | المالك | بوابة الإغلاق / معيار القرار |
|---|---|---|---|---|
| ADR-015 | Flutter state management (Riverpod vs Bloc) | OPEN | Mobile Lead | Prototype صغير + قابلية الاختبار والصيانة وتوافق الفريق؛ لا يُعد مانعاً لقرارات Moodle. |
| ADR-016 | Python type checker (Pyright vs mypy) | OPEN | Backend Lead | تجربة CI صارمة على مشروع نموذجي وتوثيق سياسة strictness. |
| ADR-017 | Identity/authentication/session flow | OPEN | Product + Security | اختيار issuer/subject mapping، access/refresh، rotation/revocation، MFA، logout/session invalidation. |
| ADR-018 | AI provider/model/data region | OPEN | Product + Privacy | العربية، جودة التعليم، شروط البيانات، الاحتفاظ، region، التكلفة، latency وfallback. |
| ADR-019 | SSE vs polling | OPEN | Backend + Mobile | مقارنة على شبكة ضعيفة/بطارية/عدد الاتصالات؛ GET task status يبقى مصدر الحالة. |
| ADR-020 | Hosting provider/region/network | OPEN | Product + Infra | residency، egress، availability، budget، backup، اتصال Moodle ومزود AI. |
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
| DEC-029 | Object Storage/KMS/region/lifecycle | OPEN | Infra + Security | مزود/منطقة/تشفير/نسخ/حماية حذف/تكلفة/سياسة signed URLs. | اختيار موثق واختبار وصول وعزل وحذف واستعادة. |
| DEC-030 | Queue delivery/persistence/retry/DLQ/visibility | OPEN | Backend + Ops | Celery/Redis أو وسيط آخر؛ ack timing؛ lease؛ retry/backoff؛ dead-letter؛ ordering. | ADR واختبارات crash/duplicate/poison message وقيود عدم ضياع outbox. |
| DEC-031 | PK strategy وDDL النهائي | OPEN | Tech Lead | UUID داخلي؛ external IDs منفصلة؛ تاريخ العضويات/المفاتيح المركبة. | DDL review + migration/upgrade tests. |
| DEC-032 | RLS أم عزل التطبيق والمفاتيح المركبة أم الجمع بينهما؟ | OPEN | Backend + Security | RLS defense-in-depth مقابل كلفة إدارة session context وpooling. | threat analysis واختبارات عزل worker/API/cache/storage، لا قرار شكلي فقط. |
| DEC-033 | أنواع الأسئلة التي تدخل MVP وQuestion DTO | OPEN | Product + Education | اختيار نوع/أنواع بداية محدودة، بنية الإجابة والتصحيح والمشتتات والوسائط. | Scope واضح + discriminated schema + golden examples + Moodle mapping. |
| DEC-034 | النطاق التعليمي وعتبات الجودة | OPEN | Education Lead | صف/مرحلة/مادة/منهاج/لغة؛ دقة المصدر؛ طريقة التحكيم واتفاق المراجعين. | Golden Dataset ومقياس قبول/رفض محدد ومبرر. |
| DEC-035 | External operation identity/idempotency | OPEN | Integration + Backend | Local Plugin يحتفظ بمفتاح عملية؛ أو آلية بحث موثوقة مكافئة؛ أو manual reconciliation بلا retry آلي. | إثبات timeout-after-success وlookup/replay دون duplicate. |
| DEC-036 | التعامل مع partial Moodle writes | OPEN | Integration + Backend | تنفيذ مركب بخطوات مسجلة؛ أو endpoint ذري عبر Plugin؛ أو تعويض/إصلاح محدود. | تعريف حدود كل خطوة، forward recovery/compensation، وسلوك الفشل الجزئي. |
| DEC-037 | دورة حياة ربط Moodle والاعتمادات | OPEN | Product + Security | من يبدأ الربط؟ من يدخل token؟ كيف يتحقق site ownership؟ كيف يتم rotate/revoke/disconnect؟ | sequence diagram + endpoints/UX + secret storage + abuse tests. |
| DEC-038 | Offline drafts/cache وبيانات الهاتف | OPEN | Product + Security + Mobile | ما الذي يحفظ محلياً؟ TTL؟ تشفير؟ حذف عند logout/revoke؟ هل المسودة المحلية مستقلة عن Snapshot server-side؟ | سياسة لكل نوع بيانات وحالات device loss/account switch. |

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
| GAP-API-001 | اختلاف العمليات والمسارات بين Word وOpenAPI | PARTIALLY-CORRECTED | `02_API_Contract_Spec_v2.0.docx`, `openapi.draft.yaml` | OpenAPI الآن يحتوي العمليات الـ13 والمسار الموحد `/snapshot`; يجب اعتماد Word v2.2 النهائي بعد حسم schemas. |
| GAP-API-002 | QuizSpec وQuestion DTO ليسا نهائيين | OPEN | OpenAPI + API Spec + Flutter | `QuizSpec` typed مبدئياً في YAML؛ question union والحدود والأنواع لا تزال قراراً. |
| GAP-API-003 | Idempotency مذكور عاماً وغير متصل بكل الكتابات | PARTIALLY-CORRECTED | OpenAPI + API Spec | أضيفت الرؤوس إلى revisions/approvals/cancel/validation؛ يلزم تحديد retention/expiry وatomic storage. |
| GAP-API-004 | العميل يرسل destination ضمن ApprovalRequest | CORRECTED-IN-DRAFT | OpenAPI + API Spec | أزيل destination من الطلب؛ يؤخذ من snapshot المحفوظ على الخادم. |
| GAP-DATA-001 | canonical hash بلا خوارزمية تطبيع دقيقة | OPEN | DB + Agent | تحديد canonical JSON، Unicode normalization، number/time encoding، schema version وtest vectors. |
| GAP-DATA-002 | سباق concurrent edit/approval غير معرف | OPEN | DB + API + Agent | optimistic concurrency عبر base snapshot version/hash، رفض stale revision/approval ذرياً. |
| GAP-AGENT-001 | نتيجة timeout لا يمكن البحث عنها إذا لم يصل external_quiz_ref | OPEN | Tool Registry + DB | ربط كل محاولة بـexternal_operation_key مع lookup من طرف Moodle أو manual-only fallback. |
| GAP-AGENT-002 | partial write (shell created, questions incomplete) غير مفصل | OPEN | Agent + Ops | state per sub-step، recovery/repair/compensation وخيار تدخل يدوي. |
| GAP-PRIV-001 | data flow/retention/deletion غير مكتمل | OPEN | Security + DB + Ops | Data inventory and lifecycle incl. embeddings, logs, backups, provider copies. |
| GAP-TEST-001 | traceability لا تغطي كل قرارات ومكونات الرحلة | OPEN | Requirements CSV + Test Plan | ربط requirement→artifact→test→evidence→owner→status. |
| GAP-OPS-001 | semantics queue/lease/retry/DLQ لم تحسم | OPEN | DB + Ops + Agent | ADR + fault-injection acceptance. |
| GAP-UX-001 | دورة ربط Moodle غير معرفة من البداية للنهاية | OPEN | PRD + Flutter + API | ربط/تجديد/إبطال/فصل connection sequence. |

## F. مرجع mapping للمعرفات القديمة

- سجلات `BLK-001..BLK-022` في Markdown v2.1 و`BLK-001..BLK-008` في Excel v2.0 ليست namespace موحدة. لا تنقل المعرفات القديمة إلى ملاحظات جديدة.
- `BLK-001` في السجلين كان حول Moodle site، ويمكن ربطه بـ`EXT-MDL-001`.
- `BLK-002` في Markdown كان تفعيل Web Services، بينما `BLK-002` في Excel كان Quiz create/question/slot mappings؛ أصبحا `EXT-MDL-002` و`VER-MDL-003..005` على التوالي.
- بقية mapping يتبع الموضوع لا الرقم؛ هذا السجل هو المرجع المعتمد لأي إحالة جديدة.

## G. قاعدة الإغلاق

لا يغلق أي `DEC/ADR` بمجرد كتابة اختيار؛ يجب تسجيل المبررات والبدائل المرفوضة والآثار والمالك والتاريخ. ولا يغلق `EXT/VER` دون evidence من المصدر/البيئة المعنية. لا يعني `CLOSED` أن التنفيذ اكتمل إلا إذا كان دليل التنفيذ/الاختبار جزءاً من الإغلاق.
