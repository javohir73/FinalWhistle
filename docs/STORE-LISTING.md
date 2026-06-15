# Store listing — FinalWhistle

App Store + Play Store submission package. Pair with [NATIVE-SHELL.md](NATIVE-SHELL.md)
(shell architecture & build runbook). Screenshots live in `store-assets/`.

## Identifiers

| | |
| --- | --- |
| iOS bundle identifier | `com.finalwhistle.app` |
| Android applicationId | `com.finalwhistle.app` |
| App name | FinalWhistle |
| Category | Sports |
| Age rating | 4+ / Everyone (no gambling, no user-generated media, no ads) |
| Privacy policy URL | https://fifa-wc26-prediction.vercel.app/privacy |
| Terms / support URL | https://fifa-wc26-prediction.vercel.app/terms |
| Support email | javohirazizov48@gmail.com |

## App Store (iOS)

**Name (30):** `FinalWhistle: WC26 Predictor`
**Subtitle (30):** `AI World Cup 2026 predictions`

**Promotional text (170):**
> Live scores are in — see how the AI's bracket is holding up, check the real
> group tables, and race your own picks up the leaderboard.

**Description:**
> Pick your nation. See what the AI thinks. Prove it wrong.
>
> FinalWhistle turns the FIFA World Cup 2026 into a playground for football
> brains: an explainable prediction model — Elo ratings, a Poisson goals model,
> and thousands of Monte-Carlo tournament simulations built from 49,000
> historical internationals — forecasts every match, group, and the full
> knockout bracket. Then it hands you the controls.
>
> • FOLLOW YOUR TEAM — choose your country and get a personalized hub: form,
> strengths, fixtures, group table, and the AI's honest odds on how far you'll go.
> • MAKE YOUR CALLS — predict every match and see instantly whether you agree
> with the model or you're calling an upset.
> • BUILD YOUR BRACKET — group stage to final, all 104 matches. No account
> needed; picks stay on your device.
> • LIVE SCORES — real-time scores, match clocks, and live group standings
> through the tournament.
> • CLIMB THE LEADERBOARD — optionally create a free account, publish your
> bracket, and score points as real results land.
> • SEE THE WHY — every probability is explainable: ratings, recent form, and
> simulation counts, not a black box.
>
> For analytics and entertainment only. No betting, no real-money play, no
> prizes — just football, numbers, and bragging rights.
> Not affiliated with or endorsed by FIFA.

**Keywords (100):**
`world cup,2026,predictions,bracket,football,soccer,live scores,fifa,simulator,stats,elo,pickem`

## Play Store (Android)

**Title (30):** `FinalWhistle: WC26 Predictor`
**Short description (80):**
> AI World Cup 2026 predictions, live scores, brackets & leaderboards.

**Full description:** reuse the App Store description above (Play allows 4000 chars).

## Privacy labels / data-safety declarations

Source of truth: the running system (verified against `backend/app/api/auth.py`,
`backend/app/security.py`, `frontend/lib/analytics.ts`, Sentry init).

### Apple "App Privacy" answers

| Data type | Collected? | Linked to identity? | Tracking? | Purpose |
| --- | --- | --- | --- | --- |
| Email address | Yes (account holders only) | Yes | No | App functionality (login, account recovery) |
| Name (display name) | Optional | Yes | No | App functionality (leaderboard display) |
| User content (bracket/match picks) | Yes (account holders; otherwise on-device only) | Yes | No | App functionality |
| Product interaction (analytics events) | Yes | **No** (anonymous, aggregated) | No | Analytics |
| Coarse location (country/city at signup, from request headers) | Yes (account holders) | Yes | No | Fraud prevention / aggregate stats |
| Crash data (Sentry) | Yes | No | No | App functionality |
| Identifiers / advertising data / precise location / contacts / photos | **Not collected** | — | — | — |

"Data used to track you": **none**. No third-party advertising or data brokers.

### Google Play Data safety answers

- Collects: email, display name (optional), user-generated picks, coarse
  location (signup country/city), crash logs, anonymous analytics.
- Shared with third parties: **none** (processors only: Vercel hosting/analytics,
  Render hosting, Sentry crash reporting).
- Data encrypted in transit: yes (TLS everywhere). Deletion: on request via
  javohirazizov48@gmail.com (in-app link on /privacy).
- Account creation optional; core features work without an account.

## Review-compliance check (betting/gambling wording)

Reviewed all user-facing copy (site + this listing) on 2026-06-12:

- The app contains **no wagering, no real-money play, no prizes, no odds in a
  bookmaker sense** — "odds" appears only as statistical probability output and
  every surface carries the standing disclaimer *"For analytics and
  entertainment only. Not betting advice."* (persistent banner + footer + /terms).
- Apple 5.3 (gambling) / Play Real-Money Gambling policy: **not applicable** —
  declare "no gambling" in both questionnaires; age rating stays 4+/Everyone.
- Avoided in listing copy: "betting", "odds boost", "win money", "wager",
  "tips" — checked above.
- FIFA trademark: name "FIFA World Cup 2026" is used descriptively; the app
  states non-affiliation in /terms and the description. **Residual risk:**
  stores sometimes push back on third-party IP in metadata — if challenged,
  rename metadata to "World Cup 2026" phrasing without "FIFA". The bundle id,
  app name and branding ("FinalWhistle") contain no FIFA marks.
- Apple 4.2 (minimum functionality, remote-shell risk): mitigations — installed
  app behaves natively (standalone, offline page, safe areas); roadmap adds
  push notifications before/with first submission (see NATIVE-SHELL.md).

## Screenshots

`store-assets/` (captured from production at device-accurate viewports):

- **App Store 6.7" (1290×2796):** `appstore-67-*.png` — home/team hub, matches
  + live scores, bracket builder, leaderboard.
- **Play Store phone (1080×2340):** `play-phone-*.png` — same four scenes.
- Regenerate any time with the runbook in NATIVE-SHELL.md → "Screenshots".

## Submission checklist (status 2026-06-12)

- [x] iOS bundle identifier / Android applicationId (`com.finalwhistle.app`)
- [x] Production app icons + splash screens, both platforms (`@capacitor/assets`)
- [x] Privacy policy URL live (/privacy)
- [x] Terms/support URL live (/terms)
- [x] App Store + Play Store screenshots (`store-assets/`)
- [x] Description, subtitle/short description, keywords (this file)
- [x] Data collection / privacy label answers (this file)
- [x] Betting/advice wording review (this file)
- [ ] **BLOCKED — needs Apple Developer account ($99/yr):** signing certs,
      TestFlight upload (`xcodebuild archive` + Transporter), real-iPhone test.
      Also update Xcode first — 15.1's actool is incompatible with this macOS
      (only the asset-catalog compile step fails; all sources build cleanly).
      (Owner decision 2026-06-12: paused.)
- [x] Signed Android release artifacts — `app-release.aab` (Play-ready) and
      `app-release.apk` (sideload testing), built and signature-verified with
      the external upload keystore (see NATIVE-SHELL.md → Android release
      signing). Artifacts: `frontend/android/app/build/outputs/`.
- [ ] **BLOCKED — needs Play Console account ($25):** internal testing track
      upload, real-Android-device test. (Owner decision 2026-06-12: paused.)
- [ ] Recommended before submission: push notifications (Apple 4.2 mitigation).
