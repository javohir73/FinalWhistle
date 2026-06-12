# Native shell (Capacitor) — spike outcome & runbook

**Status:** decision made, scaffold ready to generate. Native projects are NOT
committed yet (deliberately — see "Why not in the repo yet").
**Date:** 2026-06-12 · relates to PRD FR 4.8 (tasks 7.x).

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

## Store submission checklist (deferred)

- [ ] Apple Developer + Play Console accounts
- [ ] Push notifications (guideline 4.2 mitigation + retention)
- [ ] Privacy policy URL + data-collection declarations (both stores)
- [ ] Screenshots per device class
- [ ] TestFlight / internal-track dry run
