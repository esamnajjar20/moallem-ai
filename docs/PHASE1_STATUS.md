# حالة المرحلة P1 — Repository Foundation

**التفسير المعتمد هنا:** "المرحلة الأولى" = P1 في `09_Implementation_Roadmap_v2.0` (أول مرحلة قابلة للبناء).
P0 (قرارات وصلاحيات Moodle/الهوية) تحتاج أصحاب قرار وبيئة staging، ولم تُمس.

**بوابة الخروج (Build + CI green): شبه مغلقة محلياً (Backend).** لم يُشغَّل CI على GitHub بعد. Flutter lockfile ومنصات لم تُنشأ (لا Flutter في هذه البيئة).

**آخر تشغيل تحقق:** 2026-11-16

## البنود

| البند | المنجز | الدليل الفعلي | الناقص حتى يُغلق |
|---|---|---|---|
| P1-01 skeleton (API/Worker/Flutter) | `backend/` (API + Worker)، `mobile/`، **`uv.lock` موجود** | `uv.lock` (887 سطر)، 82 اختباراً | **`pubspec.lock`** + مجلدات Flutter للمنصة؛ تثبيت إصدار Flutter |
| P1-02 CI gates | `.github/workflows/ci.yml`: lint/format/mypy/pytest/build/pip-audit، Flutter analyze/test، gitleaks | YAML موجود | **لم يُشغَّل على GitHub بعد**؛ Backend محلياً أخضر |
| P1-03 config + health | `config.py` fail-fast، `/healthz`، `/readyz` | 82/82 اختباراً نجحت (يشمل config/api/me) | لا شيء جوهري لـ Backend |

## ما تحقق فعلاً (2026-11-16)

| الفحص | النتيجة |
|--------|---------|
| `uv lock` | نجح → `backend/uv.lock` |
| `ruff format` | 39 files unchanged |
| `ruff check` | All checks passed |
| `mypy --strict` | Success: no issues found in 24 source files |
| `pytest` (كامل) | **82 passed** |
| Domain only | 56 passed |
| Flutter | غير متاح في هذه البيئة |

## قرارات مؤقتة (ليست إغلاقاً)

- ADR-015 → Riverpod، ADR-016 → mypy strict: انظر `docs/adr/`. حالتهما في السجل تبقى `OPEN` حتى توقيع المالكين.
- النطاقات في `pyproject.toml` (`>=,<`) وليست إصدارات مثبتة؛ التثبيت الفعلي عبر `uv.lock` (موجود الآن).

## ملاحظات عقد

- `/healthz` و`/readyz` خارج `/api/v1` ولا تدخل ضمن العمليات الـ17 في OpenAPI draft. يلزم قرار: إبقاؤهما تشغيلية فقط (الافتراضي هنا) أو إضافتهما للعقد.
- أخطاء التحقق ترجع `400 VALIDATION_FAILED` (حسب استجابة BadRequest في المسودة) بأسماء الحقول فقط دون القيم.
- ربط أخطاء HTTP العامة (404 وغيره) بالـ`ErrorCode` تقريب في P1؛ يُراجع مع اعتماد عقد الأخطاء.
- `X-Request-ID`: يُقبل إن طابق `[A-Za-z0-9._-]{1,128}` وإلا يُولَّد `req_<uuid>`.

## عمداً خارج P1

Auth/membership الحقيقي (P2)، Moodle (P3)، DB/outbox/queue الفعلي (P4، وDEC-030 مفتوح)، حدود الوكيل وميزانيات التكلفة، Dockerfile/نشر، OpenTelemetry.

## الخطوات المتبقية لإغلاق البوابة بالكامل

1. ~~`uv lock` + ruff + mypy + pytest~~ **تم محلياً.**
2. على جهاز فيه Flutter:
   ```bash
   cd mobile && flutter create --platforms=android,ios --project-name moallem_mobile .
   flutter pub get
   flutter analyze && flutter test
   ```
   ثم إدخال `pubspec.lock`.
3. دفع `uv.lock` (+ `pubspec.lock` عند الجاهزية) وتشغيل CI على PR؛ تثبيت actions بـSHA.
4. توقيع ADR-015/016 (أو استبدالهما) وتحديث السجل والـbacklog (P0-06/P0-07).
