# mobile

Flutter skeleton (P1). Platform folders are not committed in this skeleton because the Flutter
SDK was not available when it was generated. Create them once, locally:

```bash
cd mobile
flutter create --platforms=android --project-name moallem_mobile .
flutter pub get          # generates pubspec.lock: commit it
flutter analyze && flutter test
flutter run --dart-define=MOALLEM_API_BASE_URL=https://api.example.invalid/api/v1
```

`flutter create .` does not overwrite existing `lib/`, `test/`, `pubspec.yaml`, or
`analysis_options.yaml`; check `git diff` after running it to be sure.
