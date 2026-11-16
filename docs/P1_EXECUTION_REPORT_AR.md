# تقرير استكمال P1 — أساس المستودع

**تاريخ التقرير:** 16 نوفمبر 2026  
**الحالة:** أُنجزت تعديلات التأسيس الممكنة في هذه البيئة، لكن بوابة P1 لا تزال **مفتوحة** حتى توليد ملفات Flutter الأصلية وتشغيل CI فعلياً.

## ما تم تنفيذه في نسخة المشروع

1. تثبيت إصدار Python للخلفية على `3.12.16` في `backend/.python-version`.
2. تثبيت Flutter على `3.50.0` عبر `mobile/.flutter-version` و`mobile/.fvmrc`، وتحديث قيود Dart والحزم المباشرة بما يتوافق مع الإصدار المختار.
3. تقوية GitHub Actions: تثبيت الإجراءات الخارجية على commit SHAs، وترقية Gitleaks من v2 إلى v3، وإضافة بوابات Backend وAndroid وiOS وفحص الأسرار.
4. إضافة `scripts/bootstrap_mobile.sh` لتوليد Android وiOS بواسطة Flutter نفسه، وإنشاء `mobile/pubspec.lock` الحقيقي، ثم إجراء format/analyze/test.
5. إضافة `scripts/check_mobile_prerequisites.sh` لمنع CI من إعطاء انطباع نجاح زائف قبل حفظ ملفات المنصات والقفل.
6. تحديث Makefile وREADME وتقارير المرحلتين P1 وP2 وملاحظات ADR-016 لتوحيد حالة التنفيذ وتجنب اعتبار الاختبارات التاريخية دليلاً جديداً.

## نتائج التحقق المنفذة هنا

| الفحص | النتيجة |
|---|---|
| اختبارات Backend | `82 passed` تحت Python `3.13.5` المتاح في بيئة التنفيذ |
| Python 3.12.16 المقفل | لم يُشغّل؛ لم يكن مثبتاً وتعذر تنزيله بسبب تعذر DNS |
| Flutter/Dart | لم يُشغّلا؛ SDK غير مثبت وتعذر تنزيله |
| Ruff وmypy وpip-audit | لم تُعَد في هذه البيئة؛ النتائج السابقة موثقة كتاريخية فقط |
| GitHub Actions | لم يُشغّل على المستودع؛ ملف Workflow جرى فحصه محلياً فقط |
| ملفات Android/iOS وpubspec.lock | لم تُنشأ يدوياً؛ يجب توليدها باستخدام Flutter 3.50.0 |

## ما يمنع إغلاق P1

- لا توجد بعد `mobile/pubspec.lock`.
- لا توجد بعد مشاريع `mobile/android/` و`mobile/ios/` الأصلية.
- لا يوجد دليل على نجاح كل وظائف GitHub Actions على commit مرفوع.
- لم تُثبت بعد نتائج backend lint/typecheck/build/audit باستخدام Python 3.12.16 المقفل.

## إجراء الاستكمال المطلوب

على جهاز أو بيئة تطوير مثبت عليها Flutter `3.50.0`:

```bash
./scripts/bootstrap_mobile.sh
```

راجع معرّف التطبيق قبل النشر. القيمة الافتراضية `com.moallem` مؤقتة ويمكن تغييرها عبر `MOALLEM_MOBILE_ORG` قبل التوليد.

بعد نجاح الأمر، احفظ الملفات التالية في Git:

```text
mobile/pubspec.lock
mobile/android/
mobile/ios/
```

ثم نفّذ:

```bash
cd backend && uv sync --locked --python 3.12.16
cd .. && make check
```

وارفع التغييرات إلى GitHub. لا تُغلق P1 إلا بعد نجاح وظائف Backend وAndroid وiOS وفحص الأسرار في GitHub Actions.

## حدود النطاق

هذا التقرير لا يعتبر P2 أو P3 أو P4 مكتملة. وجود نماذج Domain أولية لا يعني وجود مصادقة إنتاجية أو قاعدة بيانات دائمة أو Moodle Adapter أو Queue فعلي. كما أن اعتماد ADR-015 وADR-016 من أصحاب القرار يبقى منفصلاً عن اجتياز بوابة CI التقنية.
