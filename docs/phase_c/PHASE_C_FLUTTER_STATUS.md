# Phase C — Flutter Teacher App (P8) Status

**Date:** 2026-11-17  
**Scope:** Vertical Slice screens only (not a full product UI)

## Screens delivered

| # | Route | Screen | Purpose |
|---|-------|--------|---------|
| 1 | `/login` | LoginScreen | تسجيل الدخول (Mock أو API) |
| 2 | `/moodle/connect` | ConnectMoodleScreen | ربط Moodle |
| 3 | `/courses` | CoursesScreen | قائمة المقررات |
| 4 | `/courses/:id/generate` | GenerateQuizScreen | طلب توليد اختبار |
| 5 | `/tasks/:id/preview` | QuizPreviewScreen | معاينة الأسئلة + الجودة |
| 6 | `/tasks/:id/approval` | ApprovalScreen | موافقة / رفض |
| 7 | `/tasks/:id/publish` | PublishStatusScreen | حالة النشر في Moodle |
| — | `/home` | HomeScreen | لوحة المعلم |

## Architecture

```
lib/
  core/          config, api client, theme, router, providers
  features/
    auth/        session + repositories
    moodle/      connection + courses
    quiz/        generate, preview, approve, publish
    home/
```

- **Riverpod** for DI and session state
- **go_router** for navigation + auth redirect
- **Mock repositories** when `MOALLEM_USE_MOCKS=true` (full offline demo of the slice)
- **Api* repositories** call `/api/v1` when mocks are off

## Run (mock Vertical Slice)

```bash
cd mobile
flutter pub get
flutter run --dart-define=MOALLEM_USE_MOCKS=true
```

## Run against backend

```bash
flutter run \
  --dart-define=MOALLEM_API_BASE_URL=https://your-api.example/api/v1 \
  --dart-define=MOALLEM_USE_MOCKS=false
```

## Not in this phase

- Real Auth0 PKCE SDK wiring (interface ready; Mock used for demo)
- Full offline caching / SWR
- Admin screens
- Pixel-perfect design system beyond Material 3 seed theme
- iOS/Android store assets

## Tests

- `test/app_config_test.dart`
- `test/quiz_models_test.dart`
- `test/widget_test.dart` (login smoke)

## Next after Phase C

- Bind real Auth0
- Point Api repositories at live Staging
- Polish UX after teacher feedback from Pilot
