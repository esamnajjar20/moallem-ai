#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MOBILE_DIR="$ROOT_DIR/mobile"
EXPECTED_FLUTTER_VERSION=$(tr -d '\r\n' < "$MOBILE_DIR/.flutter-version")
MOBILE_ORG=${MOALLEM_MOBILE_ORG:-com.moallem}

if ! command -v flutter >/dev/null 2>&1; then
  echo "ERROR: Flutter is not installed. Install Flutter $EXPECTED_FLUTTER_VERSION first." >&2
  exit 1
fi

ACTUAL_FLUTTER_VERSION=$(flutter --version --machine | python3 -c 'import json,sys; print(json.load(sys.stdin)["frameworkVersion"])')
if [ "$ACTUAL_FLUTTER_VERSION" != "$EXPECTED_FLUTTER_VERSION" ]; then
  echo "ERROR: expected Flutter $EXPECTED_FLUTTER_VERSION, found $ACTUAL_FLUTTER_VERSION." >&2
  exit 1
fi

cd "$MOBILE_DIR"
echo "Native application ID prefix: $MOBILE_ORG (provisional; confirm before store release)."
if [ ! -f android/app/build.gradle.kts ] && [ ! -f android/app/build.gradle ]; then
  echo "Generating Android runner with Flutter $EXPECTED_FLUTTER_VERSION."
  flutter create --platforms=android --project-name moallem_mobile --org "$MOBILE_ORG" --no-pub .
else
  echo "Android runner already exists; leaving its native project files unchanged."
fi

if [ ! -f ios/Runner.xcodeproj/project.pbxproj ]; then
  echo "Generating iOS runner with Flutter $EXPECTED_FLUTTER_VERSION."
  flutter create --platforms=ios --project-name moallem_mobile --org "$MOBILE_ORG" --no-pub .
else
  echo "iOS runner already exists; leaving its native project files unchanged."
fi

flutter pub get

dart format lib test
flutter analyze
flutter test

if [ ! -f pubspec.lock ]; then
  echo "ERROR: flutter pub get did not create mobile/pubspec.lock." >&2
  exit 1
fi

printf '\nBootstrap complete. Review and commit these generated files:\n'
printf '  mobile/pubspec.lock\n  mobile/android/\n  mobile/ios/\n'
printf '\nConfirm the provisional application ID prefix (%s) before publishing.\n' "$MOBILE_ORG"
