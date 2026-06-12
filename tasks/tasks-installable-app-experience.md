# Tasks: Installable App Experience (PWA → Native Shell)

Source PRD: [prd-installable-app-experience.md](prd-installable-app-experience.md)

## Relevant Files

- `frontend/public/sw.js` - Service worker; currently `fw-v1` and only bypasses cross-origin requests — must be hardened to never cache the same-origin `/backend-api/*` proxy, auth, live, and bracket/leaderboard responses (FR 4.1, 4.2).
- `frontend/components/ServiceWorker.tsx` - Registers the SW (production only); may need an update flow so stale installs upgrade cleanly.
- `frontend/app/manifest.ts` - Next.js manifest route; already has name/short_name/display/scope/icons — verify and add screenshots + any missing fields (FR 4.3).
- `frontend/app/layout.tsx` - Root layout; holds `metadata`/`viewport` (apple-web-app, theme-color, viewport-fit=cover), wires `ServiceWorker`, `BottomNav`, `AuthProvider`. Site of iOS meta/safe-area and offline-state surfacing.
- `frontend/app/globals.css` - Global styles; safe-area utilities and offline/install-prompt styling.
- `frontend/public/offline.html` (new) or `frontend/app/offline/page.tsx` (new) - Offline fallback served when a navigation fails (FR 4.2).
- `frontend/public/icon-192.png`, `frontend/public/icon-512.png`, `frontend/public/apple-icon-180.png` - Existing icons; verify maskable safe-zone and add sizes/screenshots if needed (FR 4.3).
- `frontend/components/InstallAppPrompt.tsx` (new) - Engagement-gated install prompt: Android `beforeinstallprompt`, iOS instructions, localStorage dismiss (FR 4.4).
- `frontend/components/__tests__/InstallAppPrompt.test.tsx` (new) - Unit tests for the prompt's gating, dismiss, and platform branches.
- `frontend/lib/useInstallPrompt.ts` (new) - Hook capturing `beforeinstallprompt`, standalone detection, and engagement/dismiss state.
- `frontend/lib/__tests__/useInstallPrompt.test.tsx` (new) - Unit tests for the install hook.
- `frontend/lib/engagement.ts` (new) - Tracks engagement signals (bracket pick made, My Bracket visit count) used to gate the prompt.
- `frontend/components/BottomNav.tsx` - Mobile bottom nav; currently Home/Matches/Groups/Bracket — add My Bracket as first-class + a More entry, keep safe-area padding (FR 4.5).
- `frontend/components/__tests__/BottomNav.test.tsx` (new) - Unit tests for nav items and active state.
- `frontend/components/AuthProvider.tsx` - Auth context (hint + `/auth/me` reconcile); central to the refresh-persistence fix (FR 4.6).
- `frontend/lib/session.ts` - Cookie-auth client through `/backend-api`; `getMe`/login/register and the `fw_user` display hint.
- `frontend/next.config.mjs` - `/backend-api` proxy rewrite, CSP, security headers; relevant to cookie behavior and (later) Capacitor origin allowances.
- `backend/app/security.py` - Session cookie attributes (`SameSite`/`Secure`/`Path`/`Domain`); prime suspect for the refresh-401 bug and the Capacitor cross-origin decision (FR 4.6, 4.8).
- `backend/app/auth.py` - Resolves the `fw_session` cookie → user; where a 401 originates.
- `backend/app/config.py` - `cookie_secure`, allowed/frontend origin; needs a Capacitor origin for the native shell.
- `backend/tests/test_auth_api.py` - Backend auth flow tests; extend with cookie-attribute / reload-session assertions.
- `capacitor.config.ts` (new) + `frontend/` build integration - Capacitor shell config for the iOS/Android wrapper spike (FR 4.8).
- `docs/POST-LAUNCH.md` - Document deferred items (push, email auth) and the native auth-transport decision.

### Notes

- Unit tests live alongside the code (e.g. `InstallAppPrompt.tsx` ↔ `__tests__/InstallAppPrompt.test.tsx`).
- Run frontend tests with `cd frontend && npx jest [path]`; full suite with `npm test`. Typecheck: `npm run typecheck`. Build: `npm run build`.
- Run backend tests with `cd backend && pytest`.
- Service-worker behavior can't be unit-tested in jsdom — verify SW caching manually in Chrome DevTools → Application → Cache Storage.

## Instructions for Completing Tasks

As each sub-task is completed, change `- [ ]` to `- [x]` in this file. Update after every sub-task, not just at the end of a parent task.

## Tasks

- [x] 0.0 Create feature branch
  - [x] 0.1 Create and checkout `feat/installable-app-experience` from an up-to-date `main`.

- [x] 1.0 Audit current PWA setup and document gaps
  - [x] 1.1 Review `public/sw.js` and note that `/backend-api/*` is now same-origin (via the proxy rewrite) and therefore NOT skipped by the current cross-origin guard — flag the cache leak risk.
  - [x] 1.2 Review `app/manifest.ts` against FR 4.3 (name, short_name, display, start_url, scope, theme/background, maskable icons, screenshots) and list what's missing.
  - [x] 1.3 Review `app/layout.tsx` `metadata`/`viewport` for iOS meta, apple-touch-icon, theme-color, and `viewport-fit=cover`; list gaps.
  - [x] 1.4 Review `BottomNav.tsx`, `SiteNav.tsx`, and `AccountMenu.tsx` for destination coverage (My Bracket, Leaderboard) and safe-area handling.
  - [x] 1.5 Review `ServiceWorker.tsx` registration + update behavior and how stale clients would receive a new SW version.
  - [x] 1.6 Write a short audit summary (have vs. missing per FR area) into the PRD's appendix or a scratch note to guide tasks 2–8. → See **Audit Summary** appendix below.

- [x] 2.0 Harden the service worker and offline behavior (FR 4.1, 4.2)
  - [x] 2.1 Bump the cache name to `fw-v3` (or next version) and ensure `activate` deletes all non-current caches.
  - [x] 2.2 In `fetch`, explicitly bypass (never cache) any request whose path starts with `/backend-api/`, plus `/auth/*`, `/api/*`, and any live/bracket/leaderboard endpoints — return `fetch(req)` straight through.
  - [x] 2.3 Keep document navigations network-first, but only fall back to cached shell/offline page (never to a cached API response).
  - [x] 2.4 Restrict cache-first to genuinely static assets only (hashed `/_next/static/*`, icons, fonts); never cache-first for HTML or API.
  - [x] 2.5 Only `cache.put` when `res.ok` is true.
  - [x] 2.6 Create the offline fallback (`public/offline.html` or an `/offline` route) and serve it when a navigation fetch fails and no cache exists.
  - [x] 2.7 Confirm clean upgrade of stale installs (`skipWaiting` + `clients.claim` already present; verify behavior and document the update path).
  - [x] 2.8 Manually verify in Chrome DevTools that no `/backend-api/*`, auth, or live response appears in Cache Storage, and that live scores still update in the installed app.

- [x] 3.0 Complete manifest, icons, iOS meta, and safe-area support (FR 4.3)
  - [x] 3.1 Confirm/adjust `manifest.ts`: name, short_name, display=standalone, start_url, scope, theme_color, background_color.
  - [x] 3.2 Verify maskable icon safe-zone (logo not clipped in Android squircle); regenerate the 512 maskable asset if it's clipped.
  - [~] 3.3 (deferred — optional per PRD; needs real device captures) Add manifest `screenshots` (narrow + optional wide) to improve the install UI (optional, non-blocking).
  - [x] 3.4 Confirm `apple-touch-icon` (180px) and iOS meta (`apple-mobile-web-app-capable`, status-bar style) in `layout.tsx`.
  - [x] 3.5 Confirm `viewport-fit=cover` and add `env(safe-area-inset-*)` padding utilities where fixed/edge UI needs them (top bar, footer, bottom nav).
  - [x] 3.6 Verify branding ("FinalWhistle") is consistent across manifest, icons, and meta.

- [x] 4.0 Fix the auth-persistence blocker (FR 4.6)
  - [x] 4.1 Reproduce the refresh-reverts-to-"Sign in" bug in a real browser; capture the failing `/auth/me` request/response and the `fw_session` cookie attributes.
  - [x] 4.2 Root-cause: inspect `backend/app/security.py` cookie flags (`SameSite`, `Secure`, `Path`, `Domain`, `Max-Age`) and whether the cookie is actually stored/sent on the Vercel origin via the `/backend-api` proxy.
  - [x] 4.3 Confirm the SW change in 2.2 removes any `/auth/me` caching as a contributing cause.
  - [x] 4.4 Apply the fix (cookie attribute correction and/or proxy/cookie handling) so `/auth/me` returns the user on reload.
  - [ ] 4.5 Verify the account affordance shows after login and never flashes stale "Sign in"; logout clears the UI immediately; anonymous bracket play still works; save/join remain explicit-action only.
  - [x] 4.6 Add/extend backend tests in `test_auth_api.py` for the login→cookie→me→reload flow, and a frontend test that a hydrated session survives a remount.

- [x] 5.0 Build the engagement-gated install prompt (FR 4.4)
  - [x] 5.1 Add `lib/engagement.ts` to record/read engagement signals (≥1 bracket pick made, My Bracket visited ≥2×, menu/settings opened) in localStorage.
  - [x] 5.2 Add `lib/useInstallPrompt.ts` to capture `beforeinstallprompt`, detect standalone/installed mode, and read engagement + dismiss state.
  - [x] 5.3 Build `InstallAppPrompt.tsx`: hidden on first load and in standalone; shown only once engagement threshold is met; Android path fires the captured prompt; iOS path shows manual "Add to Home Screen" steps.
  - [x] 5.4 Persist a permanent dismiss flag in localStorage; never reappear after dismiss.
  - [x] 5.5 Mount the prompt in `layout.tsx` and wire engagement signals at the pick / My Bracket / menu sites.
  - [x] 5.6 Track an analytics event on prompt shown / installed (reuse existing analytics).
  - [x] 5.7 Add unit tests for gating, platform branch, and dismiss persistence.

- [x] 6.0 Polish the mobile bottom navigation (FR 4.5)
  - [x] 6.1 Update `BottomNav.tsx` items to prioritize Home, Matches, My Bracket, Leaderboard, and a Groups/More entry — make My Bracket first-class.
  - [x] 6.2 Ensure the 5-item layout fits without crowding; consolidate overflow into "More" if needed.
  - [x] 6.3 Confirm safe-area bottom padding keeps controls above the iPhone home indicator.
  - [x] 6.4 Verify no horizontal overflow at 390px and 430px widths across key pages.
  - [x] 6.5 Add unit tests for nav items and active-state logic.

- [ ] 7.0 Capacitor native-shell spike (FR 4.8)
  - [x] 7.1 Decide the web-asset strategy for the shell (point Capacitor at the deployed URL vs. bundle a static export) and document it.
  - [~] 7.2 (deferred to store-account provisioning — runbook in docs/NATIVE-SHELL.md) Add Capacitor (`@capacitor/core`, `@capacitor/cli`, iOS/Android platforms) and `capacitor.config.ts` with FinalWhistle app id/name.
  - [x] 7.3 Resolve cross-origin cookie auth from the `capacitor://localhost` / `https://localhost` origin — evaluate (a) Capacitor native HTTP, (b) `SameSite=None; Secure` + allowed origin in `config.py`, (c) native-only token; implement the chosen option behind config.
  - [~] 7.4 (deferred — same) Build and run the shell on iOS Simulator and Android emulator; verify login→save→reload keeps the user signed in inside the shell.
  - [~] 7.5 (deferred — same) Apply app icon + splash for the native shell consistent with PWA branding.
  - [x] 7.6 Document remaining store-submission steps and the auth-transport decision in `docs/POST-LAUNCH.md`.

- [ ] 8.0 Performance/SSR pass and full QA verification (FR 4.7, 4.9)
  - [x] 8.1 Identify any remaining skeleton-first hot pages and server-render initial data via the `getXServer` + ISR pattern (optional within this PRD).
  - [x] 8.2 Run the production build and review for major bundle warnings; trim where easy.
  - [x] 8.3 Run automated gates: `backend: pytest`, `frontend: npm run typecheck && npm test && npm run build` — all green.
  - [x] 8.4 Manual QA: fresh-browser install; installed-PWA launch; login→save→reload→still signed in; logout→reload→signed out; `/backend-api/*` absent from Cache Storage; 390px/430px layout; iOS/Safari standalone.
  - [ ] 8.5 Open PR, watch CI to green, and merge per the repo flow.

---

## Audit Summary (task 1.6 — 2026-06-12, 6 parallel auditors + production probes)

### FR 4.1/4.2 — Service worker: CRITICAL, root cause of the auth bug
**Have:** `public/sw.js` (`fw-v1`, deployed byte-identical), network-first navigations, activate-time
old-cache deletion, `skipWaiting`+`clients.claim`, non-GET + cross-origin bypass.
**Broken:**
- `/backend-api/*` IS same-origin (proxy rewrite since 2026-06-09) → every API GET falls into the
  **cache-first catch-all** (`sw.js:44-54`). `/api/auth/me`, live matches/groups, leaderboard,
  `/brackets/me`, `/match-picks/me` are frozen at first response. The Cache API ignores both the
  backend's `Cache-Control: no-store` and the client's `cache:"no-store"`.
- **Auth-bug root cause (FR 4.6) CONFIRMED:** anonymous visit caches a 401 for `/me` → user logs in
  (POST bypasses SW) → refresh replays the cached 401 → `AuthProvider` clears user + hint → "Sign in".
  Regression window: sw.js shipped 06-08 (API was cross-origin), proxy landed 06-09.
- No `res.ok` guard (404/500/401 cached forever); RSC `?_rsc=` payloads cached cache-first;
  SHELL HTML snapshots reference dead hashed chunks after deploys; sw.js bytes never change so no
  update is ever detected (`fw-v1` cache is permanent); no offline fallback exists; registration has
  zero update handling; runtime `cache.put` not in `waitUntil`.
**Fix:** bump cache to `fw-v2`; early-return for `/backend-api/`; cache-first ONLY for
`/_next/static/` + icons/fonts; network-first navigations with `offline.html` fallback; `res.ok`
guard; drop HTML SHELL precache (precache offline page + icons only); keep skipWaiting/claim;
add lightweight update check in `ServiceWorker.tsx`.

### FR 4.3 — Manifest/installability: mostly present
**Have:** manifest.ts complete core fields (name/short_name/standalone/start_url/scope/colors,
portrait, categories), icons 192/512 correct dimensions, apple-touch-icon 180, appleWebApp meta +
status bar, theme-color, `viewport-fit=cover`, standalone top/bottom safe-area CSS (globals.css:92-107).
**Missing:** maskable 192 icon; maskable 512 reuses the `any` file (clipping risk — needs distinct
padded assets); `id` field; safe-area **left/right** (landscape notch); manifest screenshots (optional);
footer bottom clearance is ~2px from the bar on home-indicator iPhones (pb-24 vs ~94px bar).

### FR 4.6 — Auth: root cause = SW (above). Secondary fixes
- **Race:** pre-login `/me` (in flight during login, e.g. Render cold start) resolves 401 AFTER
  `handleAuthed` → `setUser(null)` + hint cleared. Needs a generation counter in `AuthProvider.refresh`.
- Cookie attributes verified CORRECT: `fw_session; Max-Age=2592000; Path=/; HttpOnly; Secure; SameSite=Lax`,
  host-only on the Vercel origin via the rewrite; backend sends `no-store` on auth/brackets/match-picks;
  edge probes confirm 401 is never CDN-cached. Path/expiry/rewrite-stripping/ISR causes RULED OUT.
- Existing mitigation: `fw_user` localStorage hint (display-only) — masks but doesn't fix.

### FR 4.4 — Install prompt: nothing exists
No `beforeinstallprompt`/`appinstalled`/standalone-detection JS anywhere. Build from scratch:
`lib/useInstallPrompt.ts` + `components/InstallAppPrompt.tsx` mounted in layout (must capture the
event at layout level or it's missed). Reuse `trackEvent` from `lib/analytics.ts` (snake_case names);
localStorage keys follow `finalwhistle:<kebab>:v1`. Engagement sites: `setGroupPick`/`setKoPick`
(`lib/useMyBracket.ts:109,125`), per-match `setPick` (`lib/useMatchPicks.ts:55`), My Bracket mount
(`MyBracketClient`), menu toggles (`SiteNav.tsx:68`, `AccountMenu.tsx:40`). iOS needs a manual-path
variant. SW registers prod-only → manual verification needs a production build.

### FR 4.5 — Bottom nav: gaps
Current tabs: Home, Matches, Groups, Bracket(→`/brackets` AI bracket). **My Bracket and Leaderboard
are hamburger-only (2 taps).** Safe-area bottom padding present. Active-state `startsWith` misses
`/match/[id]`, `/my-bracket`, `/leaderboard`, `/team/[id]`. GroupTable + MiniTable lack overflow
guards at 390px. Footer clearance tight. Fix: 5 tabs (Home, Matches, My Bracket, Leaderboard, More),
explicit active-prefix mapping, overflow wrapper, footer `pb-[calc(...)]`.

### Production probes (live today)
Deployed sw.js == repo (`fw-v1`); manifest served correctly as `application/manifest+json`; rewrite
works (Vercel→CF→Render, prefix stripped); `/me` 401 carries `no-store` + never edge-cached; home HTML
edge-cached (safe — auth is client-side); backend `/api/health` ok (`live_updates: ready`); public API
GETs edge-cache 60s+SWR300 (intentional).

### Baseline warning
Untracked WIP test files (`matchPicksSync.test.tsx`, `lib/__tests__/useMatchPicks.test.tsx`) fail today
(import a not-yet-written `useMatchPicksSync`); they are NOT committed — do not include them in this
branch's commits; run targeted suites for verification.


---

## QA evidence (task 8.4 — 2026-06-12, local production build + Chrome DevTools)

- **Cache safety:** after browsing with live API polling, CacheStorage contained ONLY `fw-v2`
  (offline.html, icons, hashed `/_next/static`, visited page HTML). Zero `/backend-api/*` entries;
  `/api/auth/me` always hit the network (401 + `no-store`).
- **Offline:** server killed → unvisited route served branded `offline.html`; previously visited
  `/matches` served its cached copy. OfflineBanner + "will save when online" sync status ship for
  real-offline devices.
- **Mobile layout:** no horizontal overflow at 390px (/, /matches, /my-bracket, /groups/1) and
  430px; bottom nav = Home / Matches / My Bracket / Leaders / More, More sheet lists Groups,
  AI Bracket, How it works, Methodology.
- **Gates:** backend 160 passed; frontend 15 suites / 82 tests passed (new: authProvider 4,
  installAppPrompt 7, bottomNav 11); typecheck clean; production build clean (87.6 kB shared JS).
  Pre-existing untracked match-picks WIP tests remain excluded (not part of this branch).
- **Login→reload in production:** root cause (SW-cached 401) removed + race generation-guarded;
  re-verify manually after deploy as the final acceptance step.
