# ملفات الإصلاح — ضعها فوق جذر المشروع (استبدل الموجود)

احذف هذا الملف القديم (استُبدل بـ tests/worker/test_publish_handler.py):
- backend/tests/worker/test_publish_path_fake.py

بعد النسخ:
1. backend:  make check   (ruff format + ruff check + mypy + pytest)
2. mobile:   cd mobile && flutter pub get && dart format lib test && make mobile-check
