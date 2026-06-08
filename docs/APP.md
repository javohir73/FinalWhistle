# FinalWhistle as an App

FinalWhistle is a **PWA (Progressive Web App)** — the website is installable as a
standalone app on phones and desktops, with an icon, splash screen, full-screen
display, and offline app-shell caching. No app store or rewrite required.

## Install it

- **iPhone/iPad (Safari):** open the site → Share → **Add to Home Screen**.
- **Android (Chrome):** open the site → menu → **Install app** (or the install prompt).
- **Desktop (Chrome/Edge):** click the **install** icon in the address bar.

It launches full-screen from the home screen like a native app.

## How it's wired

| Piece | File |
|---|---|
| Web manifest (name, icons, theme, standalone) | `frontend/app/manifest.ts` → served at `/manifest.webmanifest` |
| App icons (192 / 512 / maskable / Apple 180) | `frontend/public/icon-*.png`, `apple-icon-180.png` |
| Service worker (installable + offline shell) | `frontend/public/sw.js` |
| SW registration (production only) | `frontend/components/ServiceWorker.tsx` |
| Apple/theme meta + icons | `frontend/app/layout.tsx` (`metadata`, `viewport`) |

The service worker only handles **same-origin** GETs (app shell), so backend API
calls always hit the network — live data is never served stale. It registers in
**production only** to avoid dev caching issues.

## Later: ship to the App Store / Play Store with Capacitor

The PWA work above carries straight over. When you want store listings:

1. `cd frontend && npm i -D @capacitor/cli && npm i @capacitor/core`
2. `npx cap init FinalWhistle com.finalwhistle.app`
3. Point Capacitor at the hosted site (simplest) — in `capacitor.config.ts`:
   ```ts
   server: { url: "https://fifa-wc26-prediction.vercel.app", cleartext: false }
   ```
   (or do a static export and bundle the assets).
4. `npx cap add ios` / `npx cap add android` → open in Xcode / Android Studio and build.

**Accounts/tools needed:** Apple Developer ($99/yr) + a Mac with Xcode for iOS;
Google Play ($25 one-time) for Android. Add native plugins (e.g. push
notifications) as needed.
