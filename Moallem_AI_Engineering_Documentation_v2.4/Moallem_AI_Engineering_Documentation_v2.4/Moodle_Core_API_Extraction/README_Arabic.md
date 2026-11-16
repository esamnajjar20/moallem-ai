# استخراج Moodle Core Web Services لمشروع Moallem AI — v2.0

**النطاق:** Moodle بصورة عامة، مع Moodle 5.3 LTS كخط أساس، ومستوى التصحيح 5.3.1 كأحدث إصدار نقطي تحققنا منه بتاريخ 15 نوفمبر 2026. هذه الوثيقة لا تخص جامعة بعينها.

## 1. نتيجة الاستخراج

- إجمالي سجلات القدرات: **248**.
- أسماء الدوال الفريدة: **239**.
- فجوات الميزات المسجلة: **12**.
- الأساس التاريخي: كتالوج MoodleDocs الموسوم Moodle 3.11، مع فصل تغييرات Moodle 5.1 و5.3 بدل اعتبار القائمة القديمة مرجعًا حديثًا.
- هذه قائمة منتقاة للدوال ذات الصلة بميزات Moallem AI، وليست كل دوال Moodle أو الإضافات الخارجية.

## 2. النطاق حسب المجال

| المجال | عدد السجلات |
|---|---:|
| المقررات والأقسام | 28 |
| الملفات والموارد | 20 |
| الاختبارات والمحاولات | 19 |
| بنك الأسئلة | 3 |
| الواجبات والتسليمات | 24 |
| الدرجات والتقييم | 16 |
| التقويم والمواعيد | 16 |
| المجموعات | 17 |
| إكمال الأنشطة والتقدم | 5 |
| المنتديات والنقاشات | 20 |
| نشاط Feedback | 12 |
| نشاط Database | 11 |
| نشاط Lesson | 14 |
| نشاط Wiki | 9 |
| نشاط Glossary | 9 |
| نشاط Workshop | 19 |
| H5P ومحتوى تفاعلي | 1 |
| الاختبارات وتقاريرها | 1 |
| الواجبات والتصحيح | 1 |
| الواجبات والاستثناءات | 3 |

## 3. تحديثات Moodle 5.1 و5.3 التي تحققت منها

| الدالة / العنصر | النوع | النتيجة |
|---|---|---|
| `mod_quiz_get_user_quiz_attempts` | Web Service | البديل الموصى به لـ`mod_quiz_get_user_attempts` منذ Moodle 5.1، ويشمل حالات المحاولة الجديدة. |
| `mod_quiz_get_user_attempts` | Web Service | أصبحت deprecated لصالح الدالة السابقة. لا تستخدمها في تكامل جديد. |
| `mod_quiz_get_users_in_report` | Web Service | إضافة Moodle 5.3 لتوفير قائمة المستخدمين في تقارير الاختبارات، بما يدعم البحث والتصفية. |
| `mod_assign_get_overrides` | Web Service | قراءة استثناءات الواجب في Moodle 5.3. |
| `mod_assign_save_overrides` | Web Service | إنشاء/تحديث استثناءات الواجب في Moodle 5.3. |
| `mod_assign_delete_overrides` | Web Service | حذف استثناءات الواجب في Moodle 5.3. |
| `mod_assign_get_submission_status` | Response update | استجابة Moodle 5.3 قد تتضمن `markerfeedback` لكل مصحح عند تفعيل marking workflow/allocation. |
| `mod_forum_set_read_state` | Web Service | تحديد حالة قراءة/عدم قراءة منشور في المنتدى عند توفر الإعداد والصلاحية. |
| `gradereport_user_get_grade_items` | Response update | تتضمن الاستجابة حقل `parentcategoryid` اختياريًا لعناصر الدرجات من نوع category في Moodle 5.3. |

### تحديث نقطة الإصدار 5.3.1 (12 نوفمبر 2026)

حتى تاريخ 15 نوفمبر 2026، الإصدار النقطي المنشور الأحدث في سلسلة 5.3 هو 5.3.1. تتضمن ملاحظاته إصلاحات تؤثر في H5P offline، ورفع الملفات ذات أسماء أطول من 255 حرفًا، وبعض حالات الواجبات/عناصر الدرجات، وتحديثات completion override، وتعامل طلبات API مع الرموز المنتهية أو الملغاة. هذه إصلاحات إصدار وليست أسماء Web Services جديدة؛ يجب أخذها في الحسبان عند تثبيت baseline واختبارات التكامل.

## 4. أهم النتائج الهندسية لـMoallem

### المقررات والمحتوى

توجد دوال أساسية لاستكشاف المقررات ومحتوياتها وأقسامها ووحداتها، مثل `core_course_get_courses`, `core_course_get_courses_by_field`, `core_course_get_contents`, `core_course_get_course_module`, `core_course_edit_section`, و`core_course_edit_module`. هذا يغطي جزءًا مهمًا من القراءة وإدارة الظهور، لكنه لا يثبت وجود CRUD موحد لكل أنواع الأنشطة.

### الملفات والموارد

تتضمن المجموعة `core_files_get_files`, `core_files_upload`, `mod_resource_get_resources_by_courses` وواجهات قراءة لموارد مثل Page/Book/Folder. الوصول إلى الملفات يعتمد على file area والسياق والصلاحية، وقد يلزم استخدام واجهات رفع/تنزيل الملفات المخصصة بدل افتراض أن كل ملف متاح من دالة عامة واحدة.

### الاختبارات وبنك الأسئلة

تغطي الدوال القياسية المدرجة استكشاف الاختبارات، وقراءة المحاولات والمراجعات والدرجات، وعمليات محاولة الطالب. لكنها لا توفر ضمن الكتالوج المدرج مسارًا مثبتًا مكتملًا لإنشاء Quiz وتكوين إعداداته وإنشاء أسئلة بكل أنواعها وإضافة question slots إلى الاختبار. لذلك يظل Quiz Creation MVP محتاجًا إثباتًا برمجيًا من إصدار Moodle المستهدف أو Local Plugin مخصص.

### الواجبات والتصحيح

تغطي `mod_assign_*` قراءة الواجبات والمشاركين والتسليمات والحالة والدرجات، وحفظ التصحيح والامتدادات وقفل/فتح التسليمات. أضيفت واجهات إدارة overrides في 5.3. إنشاء assignment كاملًا ما زال غير مثبت في هذه المجموعة المختارة، ويجب التحقق من نسخة Moodle أو بناء Local Plugin.

### الدرجات والتحليلات

توجد واجهات قراءة grades وgrade items وتقارير المستخدم، وواجهات كتابة درجات مثل `core_grade_update_grades` و`mod_assign_save_grades`. لا ينبغي التعامل مع كتابة الدرجات كعملية تلقائية؛ يجب أن تمر عبر مراجعة المدرس وتسجيل audit والتحقق من الأثر.

### AI / RAG

توليد الشروح والملخصات وخطط المحاضرات والترجمة وتوليد الأسئلة وتحليل المقالات ليست وظائف Moodle Web Services بذاتها. Moodle يوفّر مصادر المحتوى وبيانات الأنشطة، بينما ينفذ Moallem التحليل والتوليد والتحقق في طبقة AI الخاصة به.

## 5. حدود ما تم استخراجه

1. كتالوج MoodleDocs المتاح تاريخي وموسوم 3.11، وهو مرجع لأسماء وظائف كثيرة لكنه ليس فهرسًا حديثًا كاملاً.
2. توثيق Moodle 5.3 الرسمي يشرح آلية بناء الخدمات وتغييرات الإصدار، لكنه لا يقدم في صفحة واحدة جدولًا شاملاً بكل دوال Web Services ذات معاملات الاستدعاء والنتائج.
3. المصفوفة تتضمن أسماء ووظائف مختارة؛ لا تتضمن schema تفصيليًا لكل parameter/return لكل endpoint.
4. وجود دالة في Core لا يجعلها تلقائيًا متاحة في خدمة خارجية أو لحساب teacher؛ يجب أن تكون الدالة مضافة للخدمة، والبروتوكول مفعّلًا، والحساب مالكًا للصلاحيات المطلوبة.
5. لا تفترض توافقًا بين الإصدارات؛ يجب تثبيت نسخة مستهدفة وقراءة Upgrade Notes عند الانتقال بين الإصدارات.

## 6. طريقة الاستخدام في التنفيذ

استخدم ملف Excel للفرز والتصفية، وJSON للتغذية الآلية لأدوات التحليل. عند تنفيذ كل وظيفة، حوّلها إلى عقد API محدد يتضمن function name, input parameters, output schema, required capability, idempotency, error mapping, verification query, وtest fixture. لا تبدأ أي كتابة خارجية قبل اختبارها في بيئة Moodle تجريبية.

## 7. المصادر

- [Moodle 5.3 LTS Release Notes](https://moodledev.io/general/releases/5.3) — الإصدار المستهدف المرجعي؛ تاريخ الإصدار 5 أكتوبر 2026؛ يسرد إضافات Web Services في 5.3.
- [Moodle 5.3 External Services](https://moodledev.io/docs/5.3/apis/subsystems/external) — إطار Web Services ويفرق بين توثيق المطور والتوثيق الحي الخاص بموقع Moodle.
- [Moodle 5.3 Function Declarations](https://moodledev.io/docs/5.3/apis/subsystems/external/description) — كل دالة يجب إعلانها في db/services.php، وتخزن تعريفاتها عبر عملية اكتشاف الخدمات عند التثبيت/الترقية.
- [Moodle 5.3 Function Definitions](https://moodledev.io/docs/5.3/apis/subsystems/external/functions) — تعريف المعلمات، القيم المعادة، التنفيذ، وحالة deprecation.
- [Moodle 5.3 Questions API](https://moodledev.io/docs/5.3/apis/subsystems/question) — يفصل محرك الأسئلة عن Question Bank وإدارة إنشاء/تحرير الأسئلة؛ لا يثبت وحده وجود Web Service CRUD.
- [Legacy MoodleDocs Web service API functions](https://docs.moodle.org/dev/Web_service_API_functions) — كتالوج تاريخي موسوم Moodle 3.11؛ مرجع لاستخراج أسماء الدوال، وليس فهرسًا حديثًا كاملًا.
- [Moodle 5.3 Quiz upgrade notes](https://github.com/moodle/moodle/blob/main/public/mod/quiz/UPGRADING.md) — يوثق إضافة mod_quiz_get_users_in_report واستبدال mod_quiz_get_user_attempts بـ mod_quiz_get_user_quiz_attempts.
- [Moodle 5.3 Assignment override change](https://fossies.org/diffs/moodle/5.2.4_vs_5.3/UPGRADING.md-diff.html) — مصدر مقارنة إصدار 5.2.4 مع 5.3 يؤكد أسماء mod_assign_save_overrides وmod_assign_get_overrides وmod_assign_delete_overrides.
- [Moodle 5.3 Forum set read state](https://fossies.org/dox/moodle-5.3/classmod__forum_1_1external_1_1set__read__state.html) — توثيق Doxygen لفئة set_read_state ومدخلاتها postid وtargetstate.

- [Moodle 5.3.1 Release Notes](https://moodledev.io/general/releases/5.3/5.3.1) — أحدث patch release تم التحقق منه في 15 نوفمبر 2026.
- [Moodle supported versions](https://moodledev.io/versions) — للتحقق من إصدارات Moodle المدعومة حاليًا.


## تدقيق بيانات المصدر في v2.3
- تحتوي المصفوفة على 248 سجل قدرة و239 اسم دالة فريدًا و12 فجوة وظيفية.
- وُسم 237 سجلًا حرفيًا بعبارة مرجع كتالوج MoodleDocs التاريخي 3.11.
- يوجد سجل تاريخي إضافي MCAPI-245 يشير إلى تحديث response في Moodle 5.3؛ لا يُحسب ضمن عدد السجلات الموسومة حرفيًا بعبارة 3.11.
- أُكملت بيانات مرجع الإصدار للسجلات MCAPI-246 إلى MCAPI-248 بوصفها إضافات Moodle 5.3 ضمن MDL-86513.
- تبقى المصفوفة جردًا عامًا منتقى، ولا تثبت إتاحة الدوال في خدمة Web Services الخاصة بمؤسسة بعينها.
