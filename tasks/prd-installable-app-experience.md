# PRD: Installable App Experience (PWA → Native Shell)

**Status:** Draft for review
**Author:** Generated with Claude Code
**Date:** 2026-06-12
**Owner:** Javohir (javohirazizov48@gmail.com)

---

## 1. Introduction / Overview

FinalWhistle is a web app (Next.js 14 frontend on Vercel, FastAPI backend on
Render) that lets anyone predict the FIFA World Cup 2026 — pick brackets, follow
a country, and join a leaderboard. Today it is a website. When a user adds it to
their phone's home screen it does not yet feel like a real app: caching is not
safe for live/auth data, the manifest and icons are incomplete, there is no
guided install flow, the mobile navigation is not tuned for one-handed use, and
**signed-in state is lost on refresh** in some cases.

This feature turns FinalWhistle into a polished, **installable app** that
launches fast, looks native on the home screen, stays usable on small phones,
and never shows stale live scores or stale auth. It is delivered as a hardened
**PWA first**, then **wrapped in a Capacitor native shell** so it can be
submitted to the App Store and Google Play. We are **not** rebuilding the app in
React Native/Expo — the same Next.js build powers the web app, the PWA, and the
native shell.

**Goal:** A user can install FinalWhistle from their phone and have it feel like
a real app — proper icon, standalone launch, safe offline behavior, app-like
navigation, and a session that persists across reloads.

---

## 2. Goals

1. **Installable & app-like:** FinalWhistle is installable on Android (Chrome)
   and iOS (Safari "Add to Home Screen") with a correct icon, splash, standalone
   display, and safe-area handling — no browser chrome when launched.
2. **Safe caching:** The service worker never serves stale live, auth, bracket,
   or leaderboard data, and stale installs upgrade cleanly to the new version.
3. **Clear install path:** Engaged users see a non-intrusive prompt to install,
   with correct platform-specific instructions, and can dismiss it permanently.
4. **One-handed mobile nav:** A bottom navigation bar exposes the core
   destinations (including My Bracket as a first-class item), respects the iPhone
   home indicator, and never overflows on small phones (390px / 430px).
5. **Persistent auth:** A signed-in user stays signed in across reloads and in
   standalone/PWA mode; the "Sign in" affordance is never shown to a logged-in
   user. (Fixes the current refresh-reverts-to-"Sign in" bug.)
6. **Store-ready foundation:** The above is structured so a Capacitor native
   shell can wrap the existing build for App Store / Google Play submission,
   with the cross-origin auth implications understood and resolved.

---

## 3. User Stories

- **As a first-time visitor**, I can play with a bracket without an account so I
  am not blocked, and only see an install prompt once I am clearly engaged.
- **As an engaged Android user**, after I make picks I see a subtle "Install
  FinalWhistle" prompt; tapping it triggers the native install, and the app then
  launches full-screen from my home screen.
- **As an iPhone user**, I get clear "Add to Home Screen" instructions (since iOS
  has no automatic prompt), and once installed the app launches standalone with
  the status bar styled correctly and content clear of the home indicator.
- **As a returning signed-in user**, when I reopen or refresh the installed app I
  am still signed in — I see my account, not "Sign in."
- **As a user on a poor connection**, the app shell still loads, I can keep
  editing my local bracket, and I get honest "couldn't save / will save when
  online" feedback rather than a silent failure or a false "live" label.
- **As a one-handed mobile user**, I can reach Home, Matches, My Bracket,
  Leaderboard, and More from a bottom bar without the buttons hiding behind the
  home indicator.
- **As a product owner**, I can submit FinalWhistle to the App Store and Google
  Play using a native shell around the same web build, without maintaining a
  separate native codebase.

---

## 4. Functional Requirements

### 4.1 Service worker & caching (MUST)

1. The service worker MUST bump its cache version (e.g. `fw-v3`) so existing
   installs receive the new logic.
2. The service worker MUST **never** cache any request to `/backend-api/*`.
3. The service worker MUST **never** cache auth, user, bracket, leaderboard, or
   live-score responses (these are dynamic and/or per-user).
4. The service worker MUST only cache responses where `res.ok` is true.
5. Document navigations (HTML) MUST use a **network-first** strategy, falling
   back to cache/offline page when offline.
6. Only safe static assets (app icons, fonts, hashed Next.js build assets) MAY
   use a **cache-first** strategy.
7. On `activate`, the service worker MUST delete caches that do not match the
   current version.
8. The new version MUST take over stale installs cleanly (e.g. `skipWaiting` +
   `clients.claim`, or a controlled update-on-next-launch flow) without leaving
   users stranded on an old shell.

### 4.2 Offline behavior (MUST)

9. The app MUST provide a simple offline fallback page or offline state for
   navigations that fail while offline.
10. While offline, the cached public shell MAY load and the user MUST be able to
    continue editing their **local** bracket.
11. Any server save attempted while offline MUST show clear feedback — e.g.
    "Will save when online" or "Couldn't save" — and MUST NOT silently fail.
12. The app MUST NOT present live data (scores, minute, standings) as fresh when
    the device is offline or the data is stale.

### 4.3 Manifest & installability (MUST)

13. `manifest.json` MUST include: `name` ("FinalWhistle"), `short_name`,
    `display: "standalone"`, `start_url`, `scope`, `theme_color`,
    `background_color`.
14. `manifest.json` MUST include **maskable** icons at the required sizes
    (minimum 192px and 512px) plus any-purpose icons.
15. The app MUST include an `apple-touch-icon`.
16. The app MUST include iOS standalone meta tags
    (`apple-mobile-web-app-capable`, status-bar style) and a `theme-color` meta.
17. The layout MUST support iOS safe areas (`viewport-fit=cover` +
    `env(safe-area-inset-*)`), so content is not clipped by the notch or home
    indicator.
18. Branding MUST be consistently "FinalWhistle" across manifest, icons, and
    meta.
19. App screenshots SHOULD be added to the manifest where they improve the
    install UI (optional, not blocking).

### 4.4 Install prompt UX (MUST)

20. The app MUST provide an `InstallAppPrompt` component.
21. The prompt MUST NOT appear on first page load.
22. The prompt MUST appear only after meaningful engagement — defined for v1 as
    **any** of: the user has made at least one bracket pick, OR the user has
    visited My Bracket twice, OR the user opens the menu/settings.
23. On Android/Chrome, the prompt MUST use the `beforeinstallprompt` event to
    trigger the native install flow.
24. On iOS/Safari, the prompt MUST show manual "Add to Home Screen"
    instructions (since `beforeinstallprompt` is unavailable).
25. The prompt MUST store a dismiss state in `localStorage` and MUST NOT
    reappear after the user dismisses it.
26. The prompt MUST NOT show when the app is already running in standalone /
    installed mode.

### 4.5 Mobile bottom navigation (MUST)

27. The mobile bottom navigation MUST prioritize: **Home, Matches, My Bracket,
    Leaderboard, Groups/More**.
28. **My Bracket** MUST be a first-class bottom-nav item, not buried in a
    secondary menu.
29. The bottom nav MUST apply safe-area bottom padding so controls are not
    hidden behind the iPhone home indicator.
30. The app MUST have no horizontal overflow at 390px and 430px viewport widths.

### 4.6 Auth persistence in app mode (MUST — blocker)

31. A signed-in user MUST remain signed in across reloads, including in
    standalone/PWA mode. (Fixes the current bug where refresh reverts to
    "Sign in" despite a valid `fw_session` Set-Cookie.)
32. The account affordance (account circle / display name) MUST appear after
    login and MUST NOT show a stale "Sign in."
33. Logout MUST clear the UI immediately.
34. Anonymous bracket play MUST remain fully usable without auth.
35. Saving across devices / joining the leaderboard MUST require an explicit
    user action (sign in), never a forced/auto popup.
36. The service worker MUST NOT contribute to stale auth state (no caching of
    `/auth/*` or `/me`); if SW caching is found to cause the bug, that path MUST
    be fixed as part of this work.

### 4.7 Performance (SHOULD)

37. Hot pages SHOULD render real content server-side rather than a skeleton-only
    first screen, reusing the existing `getXServer` ISR pattern.
38. The app SHOULD avoid unnecessary client fetches where server-rendered data
    already exists.
39. The production build SHOULD be inspected for major bundle warnings, and the
    JS bundle kept lean.

### 4.8 Native shell (Capacitor) — store readiness

40. The product MUST be wrappable in a **Capacitor** native shell around the same
    web build (no React Native/Expo rewrite, no separate native UI codebase).
41. Cookie-based auth (`fw_session`) MUST work inside the Capacitor shell origin
    (`capacitor://localhost` on iOS / `https://localhost` on Android), OR the
    auth transport MUST be adapted for the shell so requirement 4.6 holds in the
    native app too. (See Technical Considerations — this is the main native
    risk.)
42. The native shell MUST present FinalWhistle branding (app name, icon, splash)
    consistent with the PWA.

### 4.9 QA / acceptance (MUST)

43. Automated: backend tests, frontend tests, typecheck, and production build
    MUST all pass.
44. Manual verification MUST cover: fresh-browser install flow; installed-PWA
    launch; login → save bracket → reload → still signed in; logout → reload →
    signed out; `/backend-api/*` is **never** served from CacheStorage; mobile
    viewport at 390px and 430px; iOS/Safari standalone behavior.

---

## 5. Non-Goals (Out of Scope)

- **Rebuilding in React Native or Expo** — explicitly excluded; the web build is
  the single source.
- **Email-dependent auth features** — email verification, self-serve password
  reset, magic-link, OAuth — deferred (no email provider yet).
- **Push notifications** — not in this round (can follow once the native shell
  exists).
- **Background sync / full offline-first data** — beyond the local-bracket
  editing and offline shell described above.
- **Changing the prediction model, scoring, or leaderboard logic.**
- **A new design system / visual rebrand** — this is packaging and polish, not a
  redesign.
- **Store listing assets/marketing** (descriptions, ASO, review responses) —
  tracked separately from the engineering work, even though the shell makes
  submission possible.

---

## 6. Design Considerations

- **Bottom nav:** 5 destinations max for thumb reach; active state clearly
  indicated; icons + short labels; persistent across app pages; respects
  `env(safe-area-inset-bottom)`. My Bracket gets a visually prominent slot.
- **Install prompt:** subtle, dismissible, bottom-anchored card or banner — never
  a blocking modal on load. iOS variant illustrates the Share → "Add to Home
  Screen" steps.
- **Splash / icon:** maskable icon must look correct inside Android's circle/squircle
  masks (keep the logo within the safe zone). Splash/background color matches the
  app theme so launch feels seamless.
- **Offline state:** branded, friendly, honest ("You're offline — showing your
  last saved view"), not a raw browser error.
- **Status bar (iOS standalone):** styled to match the app theme, not the default
  white.
- Reuse existing components and styles; do not introduce a new aesthetic.

---

## 7. Technical Considerations

- **Stack:** Next.js 14 App Router (Vercel), FastAPI (Render), first-party cookie
  auth (`fw_session`) routed through the same-origin `/backend-api` proxy. A PWA
  setup already partially exists (`frontend/public/manifest.json`,
  `frontend/public/sw.js`, `frontend/components/ServiceWorker.tsx`,
  `frontend/app/layout.tsx`, mobile nav components) — **audit current state
  first** before changing.
- **Auth bug (requirement 4.6) is the riskiest item.** The current symptom: a
  valid `fw_session` Set-Cookie is issued but a subsequent `/me` returns 401 in a
  real browser, so the UI reverts to "Sign in" on refresh. Root-cause this before
  building on top of it; candidate causes include cookie attributes
  (`SameSite`/`Secure`/`Domain`/`Path`), the cross-origin Vercel→Render hop, or
  SW caching of `/me`. The fix must hold in **both** the PWA and the eventual
  Capacitor shell.
- **Capacitor cross-origin cookies (requirement 4.8) is the main native risk.**
  Inside Capacitor the web app runs from a `capacitor://localhost` (iOS) or
  `https://localhost` (Android) origin, talking to the Render API cross-origin.
  Browser-style `SameSite=Lax`/host-only cookies that work for the Vercel PWA may
  not be sent from the shell. Options to evaluate during design:
  (a) Capacitor's native HTTP plugin / cookie handling,
  (b) a configured allowed origin + `SameSite=None; Secure` cookies,
  (c) a token transport for the native shell only.
  This decision should be settled before native submission, not after.
- **Service worker:** treat `/backend-api/*`, `/auth/*`, `/me`, live scores,
  brackets, and leaderboard as never-cache. Keep the cache allowlist to static
  build output, icons, and fonts.
- **SSR reuse:** the `getXServer` + ISR pattern already used by `match/[id]` and
  the country home should be the template for any hot-page server rendering.
- **Do not regress** the recently shipped anonymous country-first flow, live
  scores/clock, or live group table.

---

## 8. Success Metrics

1. **Installability:** Chrome/Lighthouse PWA install criteria pass; the app is
   installable on Android and iOS and launches in standalone mode.
2. **Cache safety:** In DevTools, `/backend-api/*` and auth/live/bracket/
   leaderboard responses are verifiably absent from CacheStorage; live scores
   update correctly in the installed app.
3. **Auth persistence:** 0 reproductions of the refresh-reverts-to-"Sign in" bug
   across reload, standalone launch, and (later) the native shell.
4. **Mobile layout:** No horizontal overflow and no controls clipped by the home
   indicator at 390px and 430px.
5. **Install conversion (directional):** measurable installs from the prompt
   (tracked via the existing analytics events), prompt shown only post-engagement.
6. **Quality gate:** backend tests, frontend tests, typecheck, and production
   build all green.
7. **Store readiness:** a Capacitor shell can build and run the app on iOS and
   Android with working auth (proof-of-concept before submission).

---

## 9. Open Questions

1. **Native timing:** The PWA hardening is the prerequisite for a solid native
   shell. Confirm the intended sequence — ship the hardened PWA to production
   first, then add the Capacitor shell — versus building both before any
   release. (This PRD assumes PWA-first, shell-second.)
2. **Native auth transport:** Which approach for Capacitor cookies (native HTTP
   plugin vs `SameSite=None; Secure` + allowed origin vs native-only token) do we
   want to commit to? Needs a spike before native submission.
3. **Store accounts:** Are Apple Developer ($99/yr) and Google Play ($25 one-time)
   accounts already provisioned? Submission is blocked without them.
4. **Engagement threshold:** Is "1 pick OR 2 My-Bracket visits OR opening
   menu/settings" the right trigger for the install prompt, or should it be
   tightened/loosened after launch?
5. **Offline scope:** Confirm offline editing is limited to the **local** bracket
   only (no offline leaderboard/standings), as assumed here.
6. **Push notifications:** Out of scope now — confirm they're a fast-follow once
   the native shell lands (match reminders, score alerts), as they're a common
   reason to go native.

---

## Appendix: Suggested delivery order

Small, focused, independently deployable commits:

1. **Audit** current PWA setup (manifest, sw.js, ServiceWorker.tsx, layout, mobile
   nav) — document what exists vs. what's missing.
2. **Service worker + offline** — safe caching rules, version bump, clean upgrade,
   offline fallback (FR 4.1, 4.2).
3. **Manifest + icons + iOS meta + safe-area** (FR 4.3).
4. **Auth persistence fix** — root-cause and fix refresh-reverts-to-"Sign in"
   (FR 4.6). *Blocker; do early so later work builds on solid auth.*
5. **Install prompt UX** (FR 4.4).
6. **Bottom nav polish + responsive checks** (FR 4.5).
7. **Performance / SSR hot pages** (FR 4.7) — optional within this PRD.
8. **Capacitor shell spike** — wrap the build, resolve cross-origin auth, run on
   iOS/Android (FR 4.8).
9. **QA pass** — automated + manual checklist (FR 4.9).
