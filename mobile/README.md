# Mobile app — Phase C (Teacher Vertical Slice)

Flutter **3.50.0** / Dart **3.14.x** (see `.flutter-version`).

## Features in this drop

Arabic RTL teacher flow:

1. Login  
2. Connect Moodle  
3. List courses  
4. Generate quiz  
5. Preview + quality  
6. Approve / reject  
7. Publish status  

## Quick start (mocks)

```bash
flutter pub get
flutter run --dart-define=MOALLEM_USE_MOCKS=true
```

## Against API

```bash
flutter run --dart-define=MOALLEM_API_BASE_URL=https://HOST/api/v1
```

See `docs/phase_c/PHASE_C_FLUTTER_STATUS.md`.
