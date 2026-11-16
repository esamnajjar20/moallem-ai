# Mobile app — P1 foundation

This directory contains the Flutter application shell. The toolchain is pinned to **Flutter
3.50.0 / Dart 3.14.0** in `.flutter-version`, `.fvmrc`, and `pubspec.yaml` so local development
and CI use the same framework release.

## One-time bootstrap

Install Flutter 3.50.0, then from the repository root run:

```bash
./scripts/bootstrap_mobile.sh
```

The script creates only the missing Android and/or iOS runner projects, resolves
packages, writes `mobile/pubspec.lock`, formats the Dart sources, and runs analysis and tests.
Review and commit all generated files, especially:

- `mobile/pubspec.lock`
- `mobile/android/`
- `mobile/ios/`

The default native application ID prefix is `com.moallem` and is **provisional**. Set
`MOALLEM_MOBILE_ORG` before bootstrap to use the reverse-DNS prefix approved by the product owner.
Do not publish an app-store build until the identifier is confirmed and registered.

## Local commands

```bash
cd mobile
flutter pub get --enforce-lockfile
dart format --output=none --set-exit-if-changed lib test
flutter analyze --fatal-infos
flutter test
flutter run --dart-define=MOALLEM_API_BASE_URL=https://api.example.invalid/api/v1
flutter build apk --debug
```

Build iOS on macOS only:

```bash
flutter build ios --release --no-codesign
```

No secrets belong in `--dart-define` or in the mobile bundle. `MOALLEM_API_BASE_URL` is a public
API origin, not a credential. Auth tokens and Moodle secrets must never be compiled into the app.

## Scope boundary

P1 proves the app shell, toolchain, native runners, deterministic package resolution, analysis,
tests, and debug builds. Product screens and real authentication remain in later phases.
Riverpod is still provisional under ADR-015; the P1 shell uses only a minimal provider override.
