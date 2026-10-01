#!/usr/bin/env bash
# Print the path of a copy of Flet's build template with the macOS
# deployment target raised to 12.0, for `flet build macos --template`.
#
# Xcode 27 rejects anything below macOS 12.0, and Flet's template still
# pins 11.0 (Runner) while FlutterMacOS's podspec asks for 10.15. Remove
# this script once flet-dev/flet#6874 ships.
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
rm -f "$MACOS"/Podfile.bak "$MACOS"/Runner.xcodeproj/project.pbxproj.bak

# Fail loudly if upstream changed the template and a pattern stopped matching.
[ "$(grep -c "MACOSX_DEPLOYMENT_TARGET = ${MIN};" "$MACOS/Runner.xcodeproj/project.pbxproj")" -ge 3 ]
grep -q "platform :osx, '${MIN}'" "$MACOS/Podfile"
grep -q "build_settings\['MACOSX_DEPLOYMENT_TARGET'\] = '${MIN}'" "$MACOS/Podfile"

echo "$OUT/build"
