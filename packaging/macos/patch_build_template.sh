#!/usr/bin/env bash
# Print the path of a copy of Flet's build template, patched for
# `flet build macos --template`:
#
# 1. Deployment target raised to 12.0. Xcode 27 rejects anything below
#    macOS 12.0, and Flet's template still pins 11.0 (Runner) while
#    FlutterMacOS's podspec asks for 10.15. Drop this part once
#    flet-dev/flet#6874 ships.
# 2. Sparkle embedded and started from AppDelegate, so the app shows the
#    standard macOS "new version available" dialog and installs updates
#    itself. Its feed URL and public key come from [tool.flet.macos.info]
#    in pyproject.toml; packaging/macos/README.md covers the release side.
#
# Usage: packaging/macos/patch_build_template.sh <out-dir>
set -euo pipefail

OUT="$1"
MIN="12.0"
VERSION="$(uv run python -c 'import flet.version as v; print(v.flet_version)')"

rm -rf "$OUT" && mkdir -p "$OUT"
curl -fsSL "https://github.com/flet-dev/flet/releases/download/v${VERSION}/flet-build-template.zip" -o "$OUT/template.zip"
unzip -q "$OUT/template.zip" -d "$OUT"

MACOS="$OUT/build/{{cookiecutter.out_dir}}/macos"
sed -i.bak "s/MACOSX_DEPLOYMENT_TARGET = 11.0;/MACOSX_DEPLOYMENT_TARGET = ${MIN};/" "$MACOS/Runner.xcodeproj/project.pbxproj"
sed -i.bak "s/^platform :osx, '11.0'/platform :osx, '${MIN}'/" "$MACOS/Podfile"
# Pods keep their own podspec minimum (FlutterMacOS: 10.15); override it.
perl -pi -e "s/^(    flutter_additional_macos_build_settings\(target\)\n)/\$1    target.build_configurations.each { |c| c.build_settings['MACOSX_DEPLOYMENT_TARGET'] = '${MIN}' }\n/" "$MACOS/Podfile"

# Sparkle: CocoaPods trunk stops at 2.9.x; keep SPARKLE_VERSION in build.yml
# (the sign_update tool) on the same release.
perl -pi -e "s/^(  flutter_install_all_macos_pods .*\n)/\$1  pod 'Sparkle', '2.9.6'\n/" "$MACOS/Podfile"
perl -pi -e 's/^(import FlutterMacOS\n)/$1import Sparkle\n/' "$MACOS/Runner/AppDelegate.swift"
perl -pi -e 's/^(class AppDelegate: FlutterAppDelegate \{\n)/$1  \/\/ Polls SUFeedURL in the background (daily) and runs the whole update flow.\n  let updaterController = SPUStandardUpdaterController(\n    startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)\n\n/' "$MACOS/Runner/AppDelegate.swift"
rm -f "$MACOS"/Podfile.bak "$MACOS"/Runner.xcodeproj/project.pbxproj.bak

# Fail loudly if upstream changed the template and a pattern stopped matching.
[ "$(grep -c "MACOSX_DEPLOYMENT_TARGET = ${MIN};" "$MACOS/Runner.xcodeproj/project.pbxproj")" -ge 3 ]
grep -q "platform :osx, '${MIN}'" "$MACOS/Podfile"
grep -q "build_settings\['MACOSX_DEPLOYMENT_TARGET'\] = '${MIN}'" "$MACOS/Podfile"
grep -q "pod 'Sparkle'" "$MACOS/Podfile"
grep -q "^import Sparkle" "$MACOS/Runner/AppDelegate.swift"
grep -q "SPUStandardUpdaterController(" "$MACOS/Runner/AppDelegate.swift"

echo "$OUT/build"
