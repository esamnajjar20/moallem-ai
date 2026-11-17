#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MOBILE_DIR="$ROOT_DIR/mobile"
EXPECTED_FLUTTER_VERSION=$(tr -d '\r\n' < "$MOBILE_DIR/.flutter-version")

fail() {
  echo "P1 mobile prerequisite failed: $1" >&2
  exit 1
}

command -v flutter >/dev/null 2>&1 || fail "Flutter SDK $EXPECTED_FLUTTER_VERSION is not installed."
ACTUAL_FLUTTER_VERSION=$(flutter --version --machine | python3 -c 'import json,sys; print(json.load(sys.stdin)["frameworkVersion"])')
[ "$ACTUAL_FLUTTER_VERSION" = "$EXPECTED_FLUTTER_VERSION" ] || fail "expected Flutter $EXPECTED_FLUTTER_VERSION, found $ACTUAL_FLUTTER_VERSION."
[ -f "$MOBILE_DIR/pubspec.lock" ] || fail "mobile/pubspec.lock is missing; run scripts/bootstrap_mobile.sh and commit it."
if [ ! -f "$MOBILE_DIR/android/app/build.gradle.kts" ] && [ ! -f "$MOBILE_DIR/android/app/build.gradle" ]; then
  fail "Android runner is missing; run scripts/bootstrap_mobile.sh and commit mobile/android/."
fi
[ -f "$MOBILE_DIR/ios/Runner.xcodeproj/project.pbxproj" ] || fail "iOS runner is missing; generate it on a macOS/Flutter setup and commit mobile/ios/."
