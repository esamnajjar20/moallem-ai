# Moallem AI — سجل القرارات والعوائق الموحد v2.3

**الحالة:** سجل التخطيط المرجعي الوحيد اعتباراً من 15 نوفمبر 2026؛ وتضاف إليه نتائج تدقيق الاتساق v2.3. يحل هذا السجل محل ترقيم `BLK-*` المتعارض بين سجل Markdown وورقة Excel في v2.1. احتُفظ بمعرفات ADR-015 إلى ADR-025 كما هي لتجنب كسر الإحالات التاريخية.

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


## H. قرارات وفجوات أضيفت في تدقيق الاتساق v2.3

### H.1 قرارات مفتوحة جديدة

| ID | النوع | القرار | الحالة | المالك | بوابة الإغلاق / معيار القرار |
|---|---|---|---|---|---|
| DEC-039 | DEC / Identity & Tenancy | طريقة تمرير سياق العضوية النشطة في الطلبات متعددة المؤسسات | OPEN | Backend + Security + Product | مقارنة header selector مع server-side session context؛ في كلتا الحالتين يعيد الخادم التحقق من ملكية العضوية وحالتها ACTIVE ولا يعامل المعرف كدليل صلاحية. |
| DEC-040 | DEC / Moodle Connection | دورة إنشاء/ربط اتصال Moodle وإدارة بيانات الاعتماد | OPEN | Product + Security + Integration | اعتماد sequence للربط وإثبات ملكية الموقع/الصلاحية، secret custody، rotation، revocation، disconnect، audit، والتعامل مع المهام المفتوحة؛ لا يُعتمد token flow قبل مراجعة الأمن. |
| DEC-041 | DEC / Reliability | هرم معرفات نية النشر والعملية الخارجية والخطوة الخارجية | PROPOSED | Backend + Integration | اعتماد publish_intent_id وexternal_operation_key وexternal_step_key منفصلة؛ attempt_no عداد محاولة فقط. إثبات عدم التكرار على كل خطوة مركبة. |
| DEC-042 | DEC / Task Lifecycle | سلوك الإلغاء بعد إرسال كتابة خارجية | OPEN | Backend + Product + Integration | قبل dispatch يمكن إيقاف التنفيذ؛ بعد dispatch لا تصبح الحالة CANCELLED إلا بعد إثبات عدم الأثر أو المصالحة، وإلا تدخل NEEDS_RECONCILIATION/manual review. |
| DEC-043 | DEC / Agent Runtime | حدود تشغيل الوكيل والمهام والأدوات والميزانيات | OPEN | Agent + Ops + Security | تحديد max duration/steps/tool calls/parallel calls/tokens/cost/retry budgets وقواعد الإيقاف الآمن قبل الإنتاج. |
| DEC-044 | DEC / Events & API | ترتيب أحداث المهمة وسلوك cursor عند إعادة الاتصال | OPEN | Backend + Mobile | sequence رتيب ومستقر أو مفتاح ترتيب مكافئ، cursor حصري/شامل محدد، replay بلا فقد، وGET task status يبقى المصدر السلطوي للحالة. |

### H.2 فجوات جديدة

| ID | المجال | الفجوة | الحالة | الإجراء المطلوب |
|---|---|---|---|---|
| GAP-API-005 | API/Identity | لا يوجد سياق عضوية نشطة صريح ومتحقق منه في كل طلب tenant-scoped رغم أن GET /me يعيد عضويات متعددة. | OPEN | اعتماد DEC-039؛ X-Active-Membership-ID مقترح فقط في OpenAPI ولا يمنح صلاحية؛ يجب أن يتحقق الخادم من أن العضوية تخص المستخدم الموثق وغير ملغاة. |
| GAP-API-006 | API/Moodle Connection | عمليات list/validate لا تغطي link/enrollment/rotation/revocation/disconnect، ولا توجد دورة اعتماد بيانات اعتماد معلنة. | OPEN | استكمال journey والـAPI والواجهة وsecret custody وسحب الاتصال ومصير المهام المفتوحة قبل تجميد العقد. |
| GAP-API-007 | API Contract | بعض DTOs والحقول والـerror codes وpagination/event cursor ما زالت عامة أو غير مقيدة. | OPEN | استكمال schemas/required/enums/nullability/ranges، ربط Error Codes بالمزود والمرحلة، تحديد Retry-After وcursor semantics. |
| GAP-AGENT-003 | Agent/Tool Registry | JSON الحالي يسرد input/output كقوائم أسماء ولا يقدم JSON Schemas أو permission/tenant/risk/timeout/retry/budget/approval/verifier/audit contracts كاملة. | OPEN | جعل registry غير قابل للتنفيذ حتى اكتمال schemas والإجراءات والقيود؛ validate لكل Tool output قبل استهلاكه. |
| GAP-DATA-003 | Data/Queue | تفاصيل idempotency_records وoutbox_events وinbox_deduplication وtool_invocations ليست محددة بما يكفي كعقد بيانات وتشغيل. | OPEN | حسم request hash, scope, retention/expiry, status, lease, attempt, next_attempt_at, last_error, transaction boundaries, reclaim/dead-letter. |
| GAP-TASK-001 | Task Lifecycle | لا توجد دلالات نهائية للإلغاء عندما تكون الكتابة الخارجية قد أُرسلت أو أصبحت نتيجتها مجهولة. | OPEN | تعريف الانتقالات والحالات المسموحة وحارس الانتقال والمسؤول البشري ودليل المصالحة؛ منع CANCELLED غير المثبت. |
| GAP-OPS-002 | Agent/Operations | لم تُحدد حدود تنفيذ الوكيل والميزانيات ومكابح loop/tool explosion. | OPEN | اعتماد DEC-043 ووضع حدود قابلة للقياس واختبارات تجاوزها قبل أي نشر. |
| GAP-TEST-002 | QA/Governance | يوجد عدد من Test IDs المشار إليها في Traceability دون فهرس موحد يعرّف النطاق والدليل والمالك. | OPEN | اعتماد Test_ID_Catalog_v2.3.csv، ومنع استخدام ID جديد قبل تسجيل تعريفه. |
| GAP-MATRIX-001 | Moodle Inventory | اختلاف عنوان إصدار XLSX عن JSON/اسم الملف، وثلاثة سجلات جديدة كانت تفتقد حالة مرجع الإصدار، وعدد السجلات التاريخية كان يوصف بإجمال غير دقيق. | CORRECTED-IN-DRAFT | توحيد title على v2.0 وإكمال MCAPI-246..248 وتوضيح 237 سجلًا موسومًا صراحةً بـ3.11 + سجل MCAPI-245 التاريخي ذي تحديث response في 5.3. |

## I. بوابات قبول التخطيط v2.3

| البوابة | المطلوب قبل إغلاقها | الحالة |
|---|---|---|
| P0-H Membership Context | اعتماد DEC-039، تحديد مصدر السياق، واختبار مستخدم متعدد العضويات/عضوية موقوفة/عضوية مستخدم آخر | OPEN |
| P0-I Connection Lifecycle | Sequence ومخطط API/UX وأمن الأسرار والتدوير والإبطال والفصل ومصير المهام المفتوحة | OPEN |
| P0-J Contract Completeness | typed DTOs وError Model وcursor/retry semantics وroute parity | OPEN |
| P0-K Tool Contract | versioned input/output JSON Schema + authorization/tenant/risk/side-effect/runtime/audit contract لكل أداة | OPEN |
| P0-L Reliability & Cancel | هرم المفاتيح وسجل الخطوات وOutbox/Inbox/Idempotency details وحالات الإلغاء والمصالحة | OPEN |
| P1-M Test Governance | فهرس شامل للـTest IDs وربط كل requirement باختبار معرف ودليل | PROPOSED |
| P1-N Matrix Hygiene | اتساق JSON/XLSX/README ومرجع الإصدار والسجلات الحديثة | CORRECTED-IN-DRAFT |

## J. ملاحظات مرجعية على مصفوفة Moodle

- العدد الفعلي: 248 سجلًا، 239 اسم دالة فريدًا، 12 فجوة وظيفية.
- 237 سجلًا تحمل صراحةً عبارة مرجع كتالوج MoodleDocs التاريخي 3.11.
- MCAPI-245 سجل تاريخي منفصل وموثق كتحديث response في Moodle 5.3، وليس من السجلات الموسومة حرفيًا بعبارة 3.11.
- MCAPI-246 إلى MCAPI-248 إضافات Moodle 5.3 مرتبطة بـMDL-86513؛ أُكملت قيمة مرجع الإصدار لها في بيانات v2.3.
- إصدار Moodle 5.3.1 هو آخر patch منشور في سلسلة 5.3 بتاريخ فحص 15 نوفمبر 2026؛ لا تعني هذه المعلومة أن موقع الجامعة يعمل بهذا الإصدار أو يتيح الوظائف.

## K. حالة المستندات v2.3

هذه الإضافات تخطيطية. لا تعني أن قرارات DEC-039..044 أُغلقت، أو أن OpenAPI أصبح عقدًا نهائيًا، أو أن Tool Registry قابل للتنفيذ، أو أن أي اختبار اجتاز التنفيذ. عند التعارض، تكون ملاحق v2.3 مرجعًا تخطيطيًا مكملًا لمواصفات v2.0 وملاحق v2.2، إلى أن تعتمد نسخة موحدة نهائية.
