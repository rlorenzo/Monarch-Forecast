#!/usr/bin/env bash
#
# Sign, package (DMG), notarize, and staple the macOS build of Monarch Forecast.
#
# This script is the single source of truth for macOS release signing. It is
# designed to run BYTE-FOR-BYTE identically on a developer's Mac and in CI —
# the only difference is where the signing identity and notary credentials
# come from (a login keychain locally; a temporary keychain + secrets in CI).
#
# ---------------------------------------------------------------------------
# What it does, in order:
#   1. Sign every nested Mach-O binary (dylibs, .so C-extensions, helper
#      executables, frameworks) inside-out with the hardened runtime.
#   2. Sign the outer .app bundle with the hardened runtime + entitlements.
#   3. Verify the signature (codesign --verify --deep --strict).
#   4. Build a DMG (app + drag-to-Applications shortcut) and sign the DMG.
#   5. Submit the DMG to Apple's notary service and wait for the verdict.
#   6. Staple the notarization ticket onto the DMG and validate.
#
# ---------------------------------------------------------------------------
# Required environment:
#   SIGN_IDENTITY   Developer ID Application identity string, e.g.
#                   "Developer ID Application: Rex Lorenzo (TEAMID1234)".
#                   Find it with: security find-identity -v -p codesigning
#
# Notary credentials — provide EITHER a stored keychain profile:
#   NOTARY_PROFILE  Name passed to `notarytool store-credentials` (local dev).
# OR the raw App Store Connect API key (CI):
#   NOTARY_KEY      Path to the AuthKey_XXXXXX.p8 file.
#   NOTARY_KEY_ID   The key's Key ID (10 chars).
#   NOTARY_ISSUER   The App Store Connect Issuer ID (a UUID).
#
# Optional environment:
#   APP_BUNDLE      Path to the built .app (default: build/macos/Monarch Forecast.app).
#   DMG_OUT         Output DMG path (default: build/Monarch Forecast.dmg).
#   VOL_NAME        DMG volume name (default: Monarch Forecast).
#   ENTITLEMENTS    Entitlements plist (default: alongside this script).
#   SKIP_NOTARIZE   If set to "1", sign + build DMG + verify only, no upload.
#                   Use for a fast local dry run before you have notary creds.
#
# Exit status is non-zero if any step fails; on notarization rejection the
# full notary log is printed so you can see exactly which binary was flagged.
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

APP_BUNDLE="${APP_BUNDLE:-$REPO_ROOT/build/macos/Monarch Forecast.app}"
DMG_OUT="${DMG_OUT:-$REPO_ROOT/build/Monarch Forecast.dmg}"
VOL_NAME="${VOL_NAME:-Monarch Forecast}"
ENTITLEMENTS="${ENTITLEMENTS:-$SCRIPT_DIR/entitlements.plist}"
SKIP_NOTARIZE="${SKIP_NOTARIZE:-0}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------
[ -n "${SIGN_IDENTITY:-}" ] || die "SIGN_IDENTITY is not set (see header)."
[ -d "$APP_BUNDLE" ]        || die "app bundle not found: $APP_BUNDLE (build it with 'flet build macos' first)."
[ -f "$ENTITLEMENTS" ]      || die "entitlements not found: $ENTITLEMENTS"

# Match against a captured string, not a `... | grep -q` pipeline: under
# `set -o pipefail` grep can exit on first match and SIGPIPE the upstream
# `security`, surfacing a spurious failure.
CODESIGN_IDS="$(security find-identity -v -p codesigning)"
case "$CODESIGN_IDS" in
  *"$SIGN_IDENTITY"*) : ;;
  *) die "signing identity not found in keychain:
    $SIGN_IDENTITY
  Available identities:
$(printf '%s\n' "$CODESIGN_IDS" | sed 's/^/    /')" ;;
esac

# Build the notarytool auth argument array once, up front, so a credential
# mistake fails before we spend time signing.
NOTARY_AUTH=()
if [ "$SKIP_NOTARIZE" != "1" ]; then
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    NOTARY_AUTH=(--keychain-profile "$NOTARY_PROFILE")
  elif [ -n "${NOTARY_KEY:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER:-}" ]; then
    [ -f "$NOTARY_KEY" ] || die "NOTARY_KEY file not found: $NOTARY_KEY"
    NOTARY_AUTH=(--key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER")
  else
    die "no notary credentials: set NOTARY_PROFILE, or NOTARY_KEY + NOTARY_KEY_ID + NOTARY_ISSUER (or SKIP_NOTARIZE=1)."
  fi
fi

# --- 0. prune build cruft --------------------------------------------------
# Remove problematic symlinks and .DS_Store files before signing. `flet build`
# leaves serious_python's `site-packages/.pod` symlink pointing at an ABSOLUTE
# path in the builder's ~/.pub-cache (e.g. /Users/runner/.pub-cache/.../darwin).
# codesign rejects any bundle symlink whose destination escapes the bundle, and
# this one fails verification two different ways depending on where you build:
#   - on a dev Mac that path is missing, so the link *dangles* and verify fails
#     with "No such file or directory";
#   - on the CI builder that path EXISTS, so the link resolves but verify fails
#     with "invalid destination for symbolic link in bundle".
# Either way it's build cruft with no runtime purpose, so prune a symlink if it
# dangles OR its target is absolute. Legitimate bundle symlinks (framework
# `Versions/Current`) are RELATIVE and internal, so they survive.
log "Pruning bundle-escaping / dangling symlinks + .DS_Store"
while IFS= read -r -d '' link; do
  target="$(readlink "$link")"
  if [ ! -e "$link" ] || [ "${target#/}" != "$target" ]; then
    printf '  pruning symlink: %s -> %s\n' "$link" "$target"
    rm -f "$link"
  fi
done < <(find "$APP_BUNDLE" -type l -print0)
find "$APP_BUNDLE" -name '.DS_Store' -print -delete || true

# --- 1 + 2. sign the bundle inside-out ------------------------------------
# Sign nested code deepest-first so each container bundle seals contents that
# are already signed. We sign every Mach-O file plus every nested bundle
# (.framework, .bundle, .app, .xpc). A Flet bundle nests bundles several
# levels deep — e.g. embedded-Python .so files live inside a python.bundle
# inside serious_python_darwin.framework, and each Flutter plugin ships a
# resource-only *_privacy.bundle. Every dir with an Info.plist is treated as
# nested code by `codesign --deep --strict`, so all of them must be signed as
# bundles or verification/notarization rejects the outer app.
# Entitlements are applied only to the outer .app (its main executable is the
# launched process — nested dylibs inherit that process's entitlements).
# NUL-delimited throughout because the bundle name contains a space.
# The .app's main executable must NOT be signed as a loose file — codesign
# rejects that with "unsealed contents present in the bundle root". It is
# signed correctly when we seal the whole .app at the end (with entitlements),
# so skip it in the per-file pass below.
MAIN_EXE_NAME="$(/usr/bin/defaults read "$APP_BUNDLE/Contents/Info" CFBundleExecutable 2>/dev/null || basename "$APP_BUNDLE" .app)"
MAIN_EXE_PATH="$APP_BUNDLE/Contents/MacOS/$MAIN_EXE_NAME"

log "Signing nested binaries in: $APP_BUNDLE"
{
  # Every Mach-O file (dylibs, .so C-extensions, executables) except the
  # app's own main executable (sealed with the bundle at the end).
  find "$APP_BUNDLE" -type f -print0 | while IFS= read -r -d '' f; do
    [ "$f" = "$MAIN_EXE_PATH" ] && continue
    if /usr/bin/file -b "$f" | grep -q 'Mach-O'; then
      printf '%s\0' "$f"
    fi
  done
  # Every nested bundle. -mindepth 1 excludes the outer .app itself (it is
  # signed last, with entitlements). Resource-only bundles (no Mach-O) are
  # fine to sign this way — codesign just writes their _CodeSignature seal.
  find "$APP_BUNDLE" -mindepth 1 -type d \
    \( -name '*.framework' -o -name '*.bundle' -o -name '*.app' -o -name '*.xpc' \) \
    -print0
} | \
  # Prefix each path with its depth (count of '/') for deepest-first sorting.
  while IFS= read -r -d '' p; do
    depth=$(printf '%s' "$p" | tr -cd '/' | wc -c | tr -d ' ')
    printf '%s\t%s\0' "$depth" "$p"
  done | \
  sort -z -rn -k1,1 | \
  while IFS=$'\t' read -r -d '' _depth path; do
    codesign --force --timestamp --options runtime \
      --sign "$SIGN_IDENTITY" "$path" \
      || die "codesign failed on nested item: $path"
  done

log "Signing app bundle with entitlements"
codesign --force --timestamp --options runtime \
  --entitlements "$ENTITLEMENTS" \
  --sign "$SIGN_IDENTITY" "$APP_BUNDLE" \
  || die "codesign failed on app bundle"

# --- 3. verify -------------------------------------------------------------
log "Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE" \
  || die "signature verification failed"
# Confirm the hardened runtime flag is actually set. Capture to a variable and
# match with bash rather than piping into `grep -q`: under `set -o pipefail`,
# grep -q exits on first match and closes the pipe, codesign then takes SIGPIPE
# (exit 141) on its next write, and pipefail would surface that 141 as a
# spurious failure even though the flag was present.
CS_INFO="$(codesign --display --verbose=2 "$APP_BUNDLE" 2>&1)"
case "$CS_INFO" in
  *"(runtime)"*) : ;;
  *) die "hardened runtime flag missing on $APP_BUNDLE" ;;
esac

# --- 4. build + sign the DMG ----------------------------------------------
# Prefer a styled installer window (paper background, arrow, "drag to
# Applications") via create-dmg; fall back to a plain hdiutil DMG so the
# pipeline still works without the extra dependency. create-dmg drives Finder
# via AppleScript to place the icons + background, so it needs a GUI session
# (present on dev Macs and on GitHub's macOS runners).
APP_NAME="$(basename "$APP_BUNDLE")"
BG_1X="$SCRIPT_DIR/dmg-background.png"
BG_2X="$SCRIPT_DIR/dmg-background@2x.png"
STAGING="$(mktemp -d)"
BG_WORK="$(mktemp -d)"
trap 'rm -rf "$STAGING" "$BG_WORK"' EXIT
cp -R "$APP_BUNDLE" "$STAGING/"
rm -f "$DMG_OUT"

# Build a HiDPI (Retina) background: a two-representation TIFF (1x @72dpi +
# 2x @144dpi) via `tiffutil -cathidpicheck`. create-dmg 1.3.0 does NOT combine
# an @2x image itself, and a bare 1x PNG renders blurry on Retina displays
# (Finder scales it up 2x). Fall back to the 1x PNG if the 2x art or tiffutil
# is unavailable.
BACKGROUND="$BG_1X"
if [ -f "$BG_1X" ] && [ -f "$BG_2X" ] && command -v tiffutil >/dev/null 2>&1; then
  if sips -s format tiff "$BG_1X" --out "$BG_WORK/1x.tiff" >/dev/null 2>&1 \
     && sips -s format tiff "$BG_2X" --out "$BG_WORK/2x.tiff" >/dev/null 2>&1 \
     && tiffutil -cathidpicheck "$BG_WORK/1x.tiff" "$BG_WORK/2x.tiff" \
          -out "$BG_WORK/dmg-background.tiff" >/dev/null 2>&1; then
    BACKGROUND="$BG_WORK/dmg-background.tiff"
  fi
fi

# Plain, functional DMG (app + Applications shortcut, no styling). Used when
# create-dmg is unavailable, and as a fallback if it fails — create-dmg drives
# Finder via AppleScript, which can occasionally hiccup on CI, and a release
# should never break over cosmetics.
build_plain_dmg() {
  hdiutil detach "/Volumes/$VOL_NAME" >/dev/null 2>&1 || true
  rm -f "$DMG_OUT"
  ln -sf /Applications "$STAGING/Applications"
  hdiutil create -volname "$VOL_NAME" -srcfolder "$STAGING" \
    -ov -format UDZO "$DMG_OUT" >/dev/null \
    || die "hdiutil failed to create DMG"
}

if command -v create-dmg >/dev/null 2>&1 && [ -f "$BACKGROUND" ]; then
  log "Building styled DMG with create-dmg: $DMG_OUT"
  # Icon positions MUST match packaging/macos/make_dmg_background.py.
  if ! create-dmg \
      --volname "$VOL_NAME" \
      --background "$BACKGROUND" \
      --window-pos 200 120 \
      --window-size 660 400 \
      --icon-size 128 \
      --icon "$APP_NAME" 170 200 \
      --hide-extension "$APP_NAME" \
      --app-drop-link 490 200 \
      --no-internet-enable \
      "$DMG_OUT" "$STAGING"; then
    log "create-dmg failed — falling back to a plain hdiutil DMG"
    build_plain_dmg
  fi
else
  log "Building plain DMG with hdiutil (create-dmg / background unavailable): $DMG_OUT"
  build_plain_dmg
fi

log "Signing DMG"
codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_OUT" \
  || die "codesign failed on DMG"

if [ "$SKIP_NOTARIZE" = "1" ]; then
  log "SKIP_NOTARIZE=1 — signed DMG ready (not notarized): $DMG_OUT"
  log "Note: an un-notarized DMG will still show a Gatekeeper warning."
  exit 0
fi

# --- 5. notarize -----------------------------------------------------------
log "Submitting to Apple notary service (this can take 1-15 min)…"
SUBMIT_OUT="$(xcrun notarytool submit "$DMG_OUT" "${NOTARY_AUTH[@]}" --wait 2>&1)" || {
  echo "$SUBMIT_OUT"
  # Pull the submission id out of the output and dump the detailed log so a
  # rejection tells us WHICH binary/entitlement was the problem.
  SUB_ID="$(printf '%s\n' "$SUBMIT_OUT" | awk '/id:/ {print $2; exit}')"
  if [ -n "${SUB_ID:-}" ]; then
    log "Fetching notary log for submission $SUB_ID"
    xcrun notarytool log "$SUB_ID" "${NOTARY_AUTH[@]}" || true
  fi
  die "notarization failed"
}
echo "$SUBMIT_OUT"
printf '%s\n' "$SUBMIT_OUT" | grep -q 'status: Accepted' || die "notarization not Accepted"

# --- 6. staple + validate --------------------------------------------------
log "Stapling notarization ticket"
xcrun stapler staple "$DMG_OUT" || die "stapler failed"
xcrun stapler validate "$DMG_OUT" || die "staple validation failed"

# Gatekeeper's own assessment — this is what a user's Mac runs on open.
log "Gatekeeper assessment"
spctl -a -t open --context context:primary-signature -vvv "$DMG_OUT" || true

log "Done. Notarized, stapled DMG: $DMG_OUT"
