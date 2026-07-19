# macOS code signing & notarization

Monarch Forecast's macOS DMG is signed with a **Developer ID Application**
certificate, notarized by Apple, and stapled so Gatekeeper opens it with no
warnings. This directory holds everything that isn't a secret:

- `entitlements.plist` — hardened-runtime exceptions the embedded Python
  interpreter needs (see below).
- `sign_notarize.sh` — signs the `.app`, builds the DMG, notarizes, staples.
  Runs identically on a dev Mac and in CI.

### The entitlements, and why each is there

Notarization requires the hardened runtime (`codesign --options runtime`). A
plain Flutter app needs no exceptions, but `flet build macos` embeds a full
CPython interpreter plus ~70 C-extension `.so` files, and the hardened runtime
blocks things that embedded Python relies on. Each key is an exception that
keeps the bundle working once the runtime is hardened:

| Entitlement | Why |
| --- | --- |
| `com.apple.security.cs.allow-jit` | some CPython C-extensions / Skia paths allocate JIT memory |
| `com.apple.security.cs.allow-unsigned-executable-memory` | same — writable-executable memory, else the process is killed on first use |
| `com.apple.security.cs.disable-library-validation` | the interpreter `dlopen()`s `.so` files from PyPI wheels not sealed under our Team ID |
| `com.apple.security.cs.allow-dyld-environment-variables` | Flet's launcher sets `DYLD_*` to locate the embedded frameworks at startup |

These are Developer-ID-only exceptions (App Sandbox / App Store would reject
some). They do **not** grant network or keychain access — outbound HTTPS to
Monarch and `keyring` work under the hardened runtime with no entitlement.

> **Do not add XML comments to `entitlements.plist`.** codesign parses it with
> AMFI's minimal XML parser, which rejects comments with
> `AMFIUnserializeXML: syntax error`. Keep the file a bare plist; document
> here instead.

## One-time Apple setup

You only do this once per developer machine / Apple account.

### 1. Create a Developer ID Application certificate

Only the **Account Holder** of the Apple Developer account can create these.
Easiest path (Xcode installed):

1. Xcode → **Settings… → Accounts**.
2. Add your Apple ID if it isn't there, select the team, click
   **Manage Certificates…**.
3. Click **+** → **Developer ID Application**. Xcode creates the cert and its
   private key directly in your login keychain.

Manual path (no Xcode): create a CSR in Keychain Access
(*Certificate Assistant → Request a Certificate From a Certificate Authority →
Saved to disk*), upload it at
<https://developer.apple.com/account/resources/certificates/add> choosing
**Developer ID Application**, download the `.cer`, and double-click to install.

Confirm it's installed and grab the identity string:

```bash
security find-identity -v -p codesigning
# → "Developer ID Application: Your Name (TEAMID1234)"
```

### 2. Create an App Store Connect API key for notarytool

1. <https://appstoreconnect.apple.com> → **Users and Access → Integrations →
   App Store Connect API**.
2. Generate a key. **Access: Developer** is enough for notarization. (If a
   later submission returns an auth/permission error, regenerate with
   **App Manager**.)
3. **Download the `.p8` — you can only download it once.** Note the **Key ID**
   and, at the top of the Keys page, the **Issuer ID** (a UUID).

Store the credentials in your keychain so the script (and you) never handle
the raw key again:

```bash
xcrun notarytool store-credentials "monarch-notary" \
  --key ~/path/AuthKey_XXXXXXXXXX.p8 \
  --key-id XXXXXXXXXX \
  --issuer 11111111-2222-3333-4444-555555555555
```

## Local release (do this first to prove the pipeline)

```bash
# 1. Build the .app (needs Flutter + CocoaPods — see repo README).
#    --exclude keeps .venv/.git/tests/etc. out of the bundled app.zip.
#    Without it, flet sweeps the whole project dir (incl. the ~55 MB .venv,
#    whose unsigned Mach-O binaries make notarization FAIL) into app.zip.
uv run flet build macos \
  --project "Monarch Forecast" --org "com.monarchforecast" \
  --product "Monarch Forecast" \
  --description "Financial forecasting powered by Monarch Money" \
  --build-version "$(uv run python -c 'import importlib.metadata as m; print(m.version("monarch-forecast"))')" \
  --exclude .venv .git tests .github screenshots design web packaging \
  --compile-app --compile-packages --cleanup-app --cleanup-packages

# 2. (optional) Dry run: sign + build DMG, skip the Apple round-trip.
SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID1234)" \
SKIP_NOTARIZE=1 \
  ./packaging/macos/sign_notarize.sh

# 3. Full run: sign, notarize, staple.
SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID1234)" \
NOTARY_PROFILE="monarch-notary" \
  ./packaging/macos/sign_notarize.sh
```

The output is `build/Monarch Forecast.dmg`, notarized and stapled. Verify the
end-user experience:

```bash
xcrun stapler validate "build/Monarch Forecast.dmg"
spctl -a -t open --context context:primary-signature -vvv "build/Monarch Forecast.dmg"
# Best test: AirDrop/copy the DMG to another Mac and open it — no warning = success.
```

## CI (wired into `.github/workflows/build.yml`)

The same script runs on the `macos-latest` runner. Required repository secrets:

| Secret | What it is |
| --- | --- |
| `MACOS_CERT_P12` | base64 of the Developer ID cert exported as `.p12` |
| `MACOS_CERT_PASSWORD` | password you set when exporting the `.p12` |
| `MACOS_SIGN_IDENTITY` | `Developer ID Application: Your Name (TEAMID1234)` |
| `NOTARY_KEY_P8` | contents of the `AuthKey_XXXX.p8` file |
| `NOTARY_KEY_ID` | the key's Key ID |
| `NOTARY_ISSUER` | the App Store Connect Issuer ID |

Export the `.p12` from Keychain Access (right-click the **private key** under
*My Certificates* → Export), then:

```bash
base64 -i DeveloperID.p12 | pbcopy   # paste into the MACOS_CERT_P12 secret
```

CI imports the `.p12` into a throwaway keychain, writes the `.p8` to a temp
file, and calls `sign_notarize.sh` with `NOTARY_KEY`/`NOTARY_KEY_ID`/
`NOTARY_ISSUER`. See the `Sign & notarize (macOS)` step in `build.yml`.
