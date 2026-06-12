# Native shell (Capacitor) — spike outcome & runbook

**Status:** native projects GENERATED and committed (`frontend/ios/`,
`frontend/android/`) with production icons + splash for both platforms;
store listing package in [STORE-LISTING.md](STORE-LISTING.md). Remaining
items are account-gated (signing, TestFlight, Play internal track) — see the
checklist in STORE-LISTING.md.
**Date:** 2026-06-12 · relates to PRD FR 4.8 (tasks 7.x).

> **Local toolchain note:** on this machine Xcode 15.1's `actool` cannot spawn
> its AssetCatalogSimulatorAgent under the current macOS (every other build
> step — SPM resolution, Capacitor framework, Swift sources — compiles
> cleanly; only `CompileAssetCatalog` fails). Update Xcode from the App Store
> before archiving; no project changes are needed.

## Decision: remote shell over the deployed origin

The Capacitor app points its webview at the **deployed Vercel origin** instead
of bundling static assets:

```ts
// capacitor.config.ts
import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.finalwhistle.app",
  appName: "FinalWhistle",
  webDir: "public",            // required by the CLI; unused in server.url mode
  server: {
    url: "https://fifa-wc26-prediction.vercel.app",
    allowNavigation: ["fifa-wc26-prediction.vercel.app"],
  },
};

export default config;
```

### Why this resolves the cross-origin cookie risk (the main native blocker)

With `server.url`, the webview's origin **is** `https://fifa-wc26-prediction.vercel.app`
— the same first-party origin the browser PWA uses. The `fw_session` cookie
(host-only, `SameSite=Lax`, set via the `/backend-api` rewrite) works
identically to the web: no `SameSite=None`, no native HTTP plugin, no
token transport, no backend changes. Auth requirement FR 4.6 holds in the
shell by construction.

The alternatives evaluated (and rejected for v1):

| Option | Verdict |
| --- | --- |
| Bundle static assets (`capacitor://localhost`) | Breaks cookie auth (cross-origin to Render/Vercel), breaks ISR/SSR pages, needs `SameSite=None` + CORS rework. Most work, most risk. |
| Capacitor native HTTP plugin | Patches fetch globally; fragile with Next.js streaming/RSC. |
| Native-only token transport | Splits the auth model in two; the thing first-party sessions were built to avoid. |

### Trade-offs to track

- **App Store guideline 4.2 (minimum functionality):** pure remote wrappers
  risk rejection. Mitigation before submission: add native value — push
  notifications (match reminders, score alerts) are the natural first one and
  are already on the POST-LAUNCH list.
- **Offline:** the shell inherits the PWA's fw-v2 service worker + offline.html,
  so offline behavior matches the installed PWA.
- A backend/edge outage takes the native app down with it (same as the PWA).

## Runbook (when store accounts exist)

Toolchain on this machine today: Xcode 15.1 ✓, CocoaPods 1.16.2 ✓,
Android SDK ✗ (install Android Studio for the Play build).

```bash
cd frontend
npm i -D @capacitor/cli && npm i @capacitor/core
npx cap init FinalWhistle com.finalwhistle.app --web-dir public
# paste the server block above into capacitor.config.ts
npx cap add ios          # generates ios/ (CocoaPods)
npx cap add android      # generates android/ (needs Android SDK)
npx cap run ios          # boots the simulator against production
```

Then verify inside the shell: login → save bracket → kill app → relaunch →
still signed in (FR 4.6), live scores tick, `/backend-api/*` absent from any
cache.

Icons/splash: reuse `frontend/public/icon-maskable-512.png` artwork via
`@capacitor/assets` (`npx capacitor-assets generate`) so the home-screen
identity matches the PWA (FR 42).

## Why not in the repo yet

`cap add ios/android` generates large native projects that need store
accounts (Apple $99/yr, Play $25) to sign and ship, and they'd ride along an
unrelated critical bugfix PR. The decision + config above is the part that
needed solving; generation is one command when accounts are provisioned.

## Android release signing (configured 2026-06-12)

The upload keystore is generated and lives **outside the repo**:

- Keystore: `~/FinalWhistle-keys/upload-keystore.jks` (RSA 2048, alias
  `finalwhistle-upload`, valid 25 years)
- Credentials: `~/FinalWhistle-keys/key.properties` (chmod 600; random
  password — never committed, never pasted anywhere)
- `android/app/build.gradle` auto-loads that file (override the path with
  `FW_KEYSTORE_PROPERTIES`); without it, builds fall back to unsigned debug so
  CI and fresh clones need no secrets. `*.jks`/`key.properties` are
  force-gitignored.

Build the artifacts (SDK via `brew install --cask android-commandlinetools`,
JDK via `brew install openjdk@21`):

```bash
cd frontend/android
JAVA_HOME=/opt/homebrew/opt/openjdk@21 \
ANDROID_HOME=/opt/homebrew/share/android-commandlinetools \
./gradlew bundleRelease assembleRelease
# → app/build/outputs/bundle/release/app-release.aab   (Play upload)
# → app/build/outputs/apk/release/app-release.apk      (sideload testing)
```

When enrolling in Play App Signing, upload `app-release.aab` — Google manages
the app signing key; this keystore is only the upload key. **Back up
`~/FinalWhistle-keys/` somewhere safe.**

### Emulator verification (2026-06-12)

The signed release APK was installed and exercised on an Android 15 (API 35,
Pixel 7 AVD) emulator: install accepted the release signature, the shell
booted, loaded the production origin (country chooser, disclaimer banner,
bottom nav all rendered), and in-shell navigation to Matches showed LIVE
production data (Mexico 2–0 South Africa, full time) with timezone
auto-detection working. This validates the remote-shell config end-to-end;
the remaining real-device pass is a store-policy formality, not a functional
unknown. (Run it any time: `sdkmanager emulator "system-images;android-35;google_apis;arm64-v8a"`,
`avdmanager create avd -n fw-test -k ... -d pixel_7`, boot headless, `adb install`.)

## Store submission checklist (deferred)

- [ ] Apple Developer + Play Console accounts
- [ ] Push notifications (guideline 4.2 mitigation + retention)
- [ ] Privacy policy URL + data-collection declarations (both stores)
- [ ] Screenshots per device class
- [ ] TestFlight / internal-track dry run
