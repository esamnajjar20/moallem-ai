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

# Normalize native identifiers across Android and iOS.
APP_ID="com.moallem.mobile"

python3 - "$MOBILE_DIR" "$APP_ID" <<'PY_NORMALIZE'
import re
import sys
from pathlib import Path

mobile = Path(sys.argv[1])
app_id = sys.argv[2]

gradle = mobile / "android/app/build.gradle.kts"
if gradle.exists():
    content = gradle.read_text()
    content, ns_count = re.subn(
        r'(?m)^(\s*namespace\s*=\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{app_id}"',
        content,
    )
    content, app_count = re.subn(
        r'(?m)^(\s*applicationId\s*=\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{app_id}"',
        content,
    )
    if ns_count != 1 or app_count != 1:
        raise SystemExit("Unexpected Android namespace/applicationId configuration.")
    gradle.write_text(content)

kotlin_root = mobile / "android/app/src/main/kotlin"
activities = list(kotlin_root.rglob("MainActivity.kt")) if kotlin_root.exists() else []

if len(activities) > 1:
    raise SystemExit("Multiple MainActivity.kt files found; refusing ambiguous migration.")

if activities:
    source = activities[0]
    content = source.read_text()
    content, count = re.subn(
        r'(?m)^package\s+[^\n]+',
        f'package {app_id}',
        content,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not update MainActivity package declaration.")

    target = kotlin_root / "com/moallem/mobile/MainActivity.kt"
    target.parent.mkdir(parents=True, exist_ok=True)

    if target != source and target.exists():
        raise SystemExit(f"Target already exists: {target}")

    target.write_text(content)
    if target != source:
        source.unlink()

ios = mobile / "ios/Runner.xcodeproj/project.pbxproj"
if ios.exists():
    content = ios.read_text()
    content, count = re.subn(
        r'(PRODUCT_BUNDLE_IDENTIFIER\s*=\s*)[^;]+;',
        lambda m: m.group(1) + (
            app_id + ".RunnerTests"
            if m.group(0).rstrip().endswith("RunnerTests;")
            else app_id
        ) + ";",
        content,
    )
    if count < 2:
        raise SystemExit("Unexpected iOS bundle identifier configuration.")
    ios.write_text(content)

print(f"Native identifiers normalized to {app_id}.")
PY_NORMALIZE

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
