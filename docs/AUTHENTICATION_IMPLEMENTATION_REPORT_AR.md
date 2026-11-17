# تقرير تنفيذ مرحلة Authentication — Moallem AI

**التاريخ:** 2026-11-17  
**الحالة:** تنفيذ Backend MVP مكتمل محليًا؛ قبول Auth0 والأجهزة الفعلية ما زال بوابة خارجية قبل Pilot.  
**القرار:** Auth0 كما اختاره مالك المشروع في 2026-11-16 (ADR-017).

## 1. النتيجة التنفيذية

تم تنفيذ حد المصادقة الخلفي على أساس أن Flutter تطبيق OIDC عام (Public Client)، وأن FastAPI مورد API يتحقق من Access Token. لا يستقبل Backend كلمات مرور أو Authorization Codes أو Refresh Tokens، ولا يصدر رموزًا خاصة به. تسجيل الدخول وتجديد الجلسة والخروج لدى Auth0 عبر SDK الأصلي، باستخدام Authorization Code + PKCE، مع تخزين بيانات الاعتماد في مخزن النظام الآمن.

**لا توجد واجهات `/login` أو `/refresh` أو `/logout` في Moallem API عمدًا.** هذا ليس نقصًا في واجهة API؛ بل فصل مسؤوليات المصادقة عن واجهة المنتج ومنع تمرير Refresh Token إلى الخادم.

## 2. البنود المنفذة في Backend

- Auth0 Resource Server مفعّل عند ضبط `MOALLEM_AUTH_ISSUER`, `MOALLEM_AUTH_AUDIENCE`, و`MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS`.
- Auth0 مطلوب في بيئتي staging وproduction؛ وتُرفض إعدادات المصادقة الجزئية أو Issuer غير HTTPS أو غير الدقيق.
- قبول RS256 فقط والتحقق من التوقيع بواسطة JWKS مستمد من Issuer المهيأ فقط.
- رفض مفاتيح RSA الأضعف من 2048 بت، وحصر حجم JWT وJWKS، وتخزين JWKS مؤقتًا مع تحديد معدل تحديث المفتاح المجهول.
- منع JWKS من إعادة التوجيه إلى HTTP أو إلى Origin مختلف.
- التحقق الدقيق من `iss` و`aud` و`sub` و`exp` و`iat` و`nbf` عند وجوده، مع حد أقصى لعمر Access Token يبلغ 900 ثانية وسماح زمني 30 ثانية. القيم العددية غير المنتهية مثل NaN وInfinity مرفوضة.
- ربط `(iss, sub)` بمستخدم تم إنشاؤه مسبقًا في PostgreSQL. لا يوجد Auto-provisioning عند أول تسجيل دخول، ولا تُؤخذ هوية المستخدم أو المؤسسة أو الدور من ترويسات العميل أو Claims غير موثوقة.
- إضافة `users.auth_status` بقيم `ACTIVE`, `SUSPENDED`, `REVOKED` وقيد قاعدة بيانات. لا يُقبل إلا ACTIVE؛ والتعليق أو الإلغاء يمنع طلبات API التالية مباشرة عبر فحص PostgreSQL.
- إضافة أمر إداري محلي لإنشاء ربط Auth0 وعضوية TEACHER أولية، أو تعليق/إلغاء المستخدم. لا توجد واجهة عامة تمنح العضويات.
- منع حقن Authenticator أو Membership Repository مخصص خارج بيئة TEST، ومنع فحوص الصحة المخصصة من تجاوز فحوص PostgreSQL وJWKS الإلزامية في بيئات التشغيل.
- فحص جاهزية JWKS ومخطط `auth_status` في `/readyz`.
- `GET /api/v1/me` يعيد هوية المستخدم وعضوياته من الخادم، ولا يحتاج `X-Active-Membership-ID`، والاستجابة `Cache-Control: no-store`.
- أخطاء المصادقة موحّدة إلى `401 AUTHENTICATION_REQUIRED` وتتضمن `WWW-Authenticate: Bearer` ولا تُخزّن مؤقتًا.
- `X-Dev-User-ID` محصور في development/test، ولا يمكن استعماله بدل Auth0 في staging/production.
- تحديث ADR-017 ودليل Flutter وعقد OpenAPI وحالة P2 وسجل القرارات.

## 3. ملفات التنفيذ الرئيسية

- `backend/src/moallem/api/app.py`
- `backend/src/moallem/api/deps.py`
- `backend/src/moallem/api/jwks.py`
- `backend/src/moallem/api/me.py`
- `backend/src/moallem/domain/identity.py`
- `backend/src/moallem/domain/rs256.py`
- `backend/src/moallem/persistence/models.py`
- `backend/src/moallem/persistence/repositories.py`
- `backend/alembic/versions/f4a2d9c61b80_auth_user_lifecycle.py`
- `backend/scripts/manage_auth_identity.py`
- `docs/adr/ADR-017-authentication-and-session.md`
- `docs/AUTHENTICATION_MVP.md`

## 4. قاعدة البيانات

أُضيف ترحيل Alembic:

- Revision: `f4a2d9c61b80`
- Parent: `d61f8a2c9e34`
- Column: `users.auth_status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'`
- Check constraint: القيم المحصورة `ACTIVE`, `SUSPENDED`, `REVOKED`.

تم التحقق من رأس Alembic ومن توليد SQL offline. لم يتم تطبيق الترحيل على PostgreSQL فعلي في بيئة هذا الفحص؛ يجب تطبيقه على قاعدة الاختبار ثم staging.

## 5. نتائج الاختبارات المحلية

- اختبارات Authentication المركزة: **37 passed**.
- مجموعة Backend: **421 passed, 45 skipped, 1 deselected**.
- الاختبارات الـ45 المتجاوزة تحتاج `MOALLEM_TEST_DATABASE_URL` وقاعدة PostgreSQL فعلية مع تطبيق الترحيلات.
- الاختبار المستبعد `test_docs_disabled_in_production` يحتاج مشغل PostgreSQL `psycopg` غير متاح في بيئة الفحص؛ لم يُستبدل باختبار شكلي.
- فحص `compileall` وفحص Alembic offline مطلوبان عند إعادة التحقق بعد نقل الحزمة.
- Ruff وmypy لم يُعاد تشغيلهما على تعديلات Authentication في بيئة الفحص الحالية، ولا تُعد النتائج التاريخية للمشروع إثباتًا لذلك.

## 6. التهيئة اللازمة قبل قبول Auth0

تُنفذ على Auth0 Tenant حقيقي وبصلاحيات المالك:

1. إنشاء API بمعرّف ثابت وتوقيع RS256.
2. إنشاء Native Application لـAndroid/iOS، بلا Client Secret داخل التطبيق.
3. ضبط Callback وLogout URLs حسب Bundle ID وAndroid applicationId / redirect scheme الفعلي.
4. فرض MFA على حسابات Pilot.
5. تفعيل Refresh Token grant مع Rotation وReuse Detection، وتحديد حدود الخمول والمدة القصوى.
6. ضبط Access Token lifetime إلى 900 ثانية أو أقل.
7. ضبط Issuer وAudience وقاعدة PostgreSQL في بيئة Staging.
8. تنفيذ PKCE وتخزين Android Keystore وiOS Keychain واختبار التجديد بعد إعادة تشغيل التطبيق والخروج.
9. اختبار دوران مفاتيح JWKS، وتوقف Issuer، ورفض Subject غير مسجل، ورفض SUSPENDED/REVOKED.
10. اختبار إبطال Refresh Token عند فقدان الجهاز، وتوثيق أن Access Token JWT المنسوخ قد يبقى صالحًا تشفيريًا حتى انتهاء مدته؛ تعليق حساب Moallem يمنع استعماله على API فورًا.

## 7. الحدود التي لا يغلقها Authentication

- مصفوفة Authorization (DEC-027) وسياسات TEACHER/ADMIN/SUPPORT ما زالت قرارًا مستقلًا ومفتوحًا. الافتراضي `DenyAllPolicy` ما زال فعّالًا؛ لم تُفتح صلاحيات غير معتمدة.
- إدارة المؤسسات وعزلها وKMS/Secret Manager وRLS لا تُعد مغلقة بهذا التنفيذ.
- لا يمكن إعلان القبول النهائي لـAuth0 أو Android/iOS قبل تزويد بيانات المستأجر الفعلية وتشغيل اختبارات الأجهزة وقاعدة PostgreSQL.
- لذلك ADR-017 منفذ برمجيًا في Backend MVP، لكن P2 كمرحلة كاملة تبقى NOT CLOSED.

## 8. أوامر التحقق والتشغيل

```bash
cd backend
uv run alembic upgrade head
uv run pytest -q tests/test_bearer_api.py tests/test_config.py tests/test_jwks.py \
  tests/domain/test_rs256.py tests/test_auth_identity_persistence.py
uv run pytest -q
```

متغيرات التشغيل:

```dotenv
MOALLEM_ENV=staging
MOALLEM_AUTH_ISSUER=https://YOUR_TENANT.auth0.com/
MOALLEM_AUTH_AUDIENCE=https://api.your-domain.example
MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS=900
MOALLEM_DATABASE_URL=postgresql://...
```

راجع `docs/AUTHENTICATION_MVP.md` لأمر provisioning وعقد Flutter.
