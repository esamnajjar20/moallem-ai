# حالة المرحلة P1 — Repository Foundation

**التفسير المعتمد هنا:** "المرحلة الأولى" = P1 في `09_Implementation_Roadmap_v2.0` (أول مرحلة قابلة للبناء).
P0 (قرارات وصلاحيات Moodle/الهوية) تحتاج أصحاب قرار وبيئة staging، ولم تُمس.
**بوابة الخروج (Build + CI green): غير محققة بعد.** لم يُشغَّل CI ولا أي أداة بناء خارجية.

## البنود

| البند | المنجز | الدليل الفعلي | الناقص حتى يُغلق |
|---|---|---|---|
| P1-01 skeleton (API/Worker/Flutter) | `backend/` (API + Worker)، `mobile/` | الشيفرة موجودة؛ `compileall` نجح | **lockfiles** (`uv.lock`, `pubspec.lock`) لم تُنشأ (لا شبكة)؛ مجلدات Flutter للمنصة؛ تثبيت إصدار Flutter |
| P1-02 CI gates | `.github/workflows/ci.yml`: lint/format/mypy/pytest/build/pip-audit، Flutter analyze/test، gitleaks | YAML فقط | **لم يُشغَّل قط**؛ أول تشغيل متوقع أن يفشل حتى تُنشأ lockfiles ويُنفَّذ `ruff format` |
| P1-03 config + health | `config.py` fail-fast، `/healthz`، `/readyz` (TCP reachability) | اختبارات المنطق غير المعتمد على الحزم نجحت (9/9) | اختبارات config وAPI كُتبت ولم تُشغَّل |

## ما تحقق فعلاً مقابل ما لم يتحقق

- **شُغِّل ونجح (9 اختبارات):** إخفاء الأسرار في السجلات، فحص TCP، تطابق `ErrorCode` مع enum في `openapi.draft.yaml`.
- **كُتب ولم يُشغَّل:** `test_config.py`، `test_api.py` (يحتاجان fastapi/pydantic/pytest وغير متاحة هنا)، اختبارات Flutter، `ruff`، `mypy`، `flutter analyze`.
- لا ادعاء بأن mypy أو ruff سيمرّان؛ قد يلزم تعديلات صغيرة عند أول تشغيل.

## قرارات مؤقتة (ليست إغلاقاً)

- ADR-015 → Riverpod، ADR-016 → mypy strict: انظر `docs/adr/`. حالتهما في السجل تبقى `OPEN` حتى توقيع المالكين.
- النطاقات في `pyproject.toml` (`>=,<`) وليست إصدارات مثبتة؛ التثبيت الفعلي مسؤولية `uv.lock`.

## ملاحظات عقد

- `/healthz` و`/readyz` خارج `/api/v1` ولا تدخل ضمن العمليات الـ17 في OpenAPI draft. يلزم قرار: إبقاؤهما تشغيلية فقط (الافتراضي هنا) أو إضافتهما للعقد.
- أخطاء التحقق ترجع `400 VALIDATION_FAILED` (حسب استجابة BadRequest في المسودة) بأسماء الحقول فقط دون القيم.
- ربط أخطاء HTTP العامة (404 وغيره) بالـ`ErrorCode` تقريب في P1؛ يُراجع مع اعتماد عقد الأخطاء.
- `X-Request-ID`: يُقبل إن طابق `[A-Za-z0-9._-]{1,128}` وإلا يُولَّد `req_<uuid>`.

## عمداً خارج P1

Auth/membership (P2)، Moodle (P3)، DB/outbox/queue (P4، وDEC-030 مفتوح)، حدود الوكيل وميزانيات التكلفة (لا قيم افتراضية بالتصميم)، Dockerfile/نشر، OpenTelemetry.

## الخطوات التالية الأقصر لإغلاق البوابة

1. `cd backend && uv lock && uv run ruff format . && uv run ruff check --fix . && uv run mypy && uv run pytest` ثم إصلاح أي مخرجات.
2. `cd mobile && flutter create --platforms=android --project-name moallem_mobile . && flutter pub get`، ثم `flutter analyze && flutter test`، وتثبيت إصدار Flutter في CI.
3. إدخال `uv.lock` و`pubspec.lock` ثم تشغيل CI على PR؛ تثبيت actions بـSHA.
4. توقيع ADR-015/016 (أو استبدالهما) وتحديث السجل والـbacklog (P0-06/P0-07).
