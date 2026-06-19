# App Store Launch — Readiness & Checklist

Status of the iOS (Capacitor) submission for **FinalWhistle** (`com.finalwhistle.app`).
Companion to `STORE-LISTING.md` (copy/metadata) and `NATIVE-SHELL.md` (architecture).

## ✅ Done in code (this branch)

- **In-app account deletion** (Apple Guideline 5.1.1(v)) — `POST /api/auth/delete-account`
  (re-auth with password) + a **Delete account** item in the account menu with a confirm
  dialog. Model: **anonymize, keep leaderboard** — personal data is wiped, every session
  revoked, the email freed for re-registration; a public leaderboard entry survives as
  "Deleted user" with its score intact.
- **Privacy manifest** — `ios/App/App/PrivacyInfo.xcprivacy` (NSPrivacyTracking = false,
  declared data types, UserDefaults required-reason `CA92.1`). **One manual step:** in Xcode,
  drag this file into the **App** target (Target → Build Phases → it should appear under the
  app, "Target Membership" ticked) — the classic `.pbxproj` doesn't auto-include it.
- **App icon** — verified the single **1024×1024, no-alpha, RGB** icon is valid (Xcode
  "single-size" App Icon). No regeneration needed.
- **Version** — `package.json` bumped to `1.0.0` to match native `MARKETING_VERSION = 1.0`.
- **Info.plist** — removed the obsolete `armv7` `UIRequiredDeviceCapabilities` entry.

## 🔑 Remaining — only you can do these (Apple-gated)

1. **Apple Developer Program** enrollment ($99/yr).
2. In Xcode: set **Signing → Team** (auto-signing), then **Product → Archive** and validate.
3. **App Store Connect**: create the app record (bundle id `com.finalwhistle.app`), upload the
   build via TestFlight, fill the listing from `STORE-LISTING.md`, attach the 6.7" screenshots
   in `store-assets/`, and set the **privacy policy URL** (`/privacy`) + **support URL**.
4. Submit for review.

## App Privacy "nutrition label" (App Store Connect → App Privacy)

Data **collected**, all **linked to the user** unless noted, **not used for tracking**:

| Data | Linked | Purpose |
|---|---|---|
| Email address | Yes | App Functionality (account) |
| Name (display name) | Yes | App Functionality (leaderboard) |
| Other user content (bracket / match picks) | Yes | App Functionality |
| Coarse location (country/city from headers at signup) | Yes | App Functionality (abuse prevention) |
| Crash data (Sentry) | No | App Functionality |
| Product interaction (Vercel Analytics) | No | Analytics |

**Tracking:** No. No third-party ad networks, no IDFA, no cross-app/site tracking.

## Age rating (App Store Connect questionnaire)

- **Contests / Simulated Gambling:** the bracket game is free, with **no real-money wagering** —
  answer **None / No** to gambling questions. The app shows statistical predictions and a
  free prediction game; it is explicitly **"not betting advice"** (see `/terms`, `/privacy`).
- Expected rating: **4+** (or 9+/12+ if the questionnaire nudges on "Contests"). Nothing here
  warrants 17+.

## ⚠️ Guideline 4.2 (minimum functionality / web wrapper) — the main review risk

The app loads the Vercel site in a webview (`capacitor.config.ts` → `server.url`). Pure web
wrappers are sometimes rejected. Mitigations / review-notes strategy:

- In **App Review notes**, describe native value: installable full-screen experience, offline
  shell via service worker, home-screen presence, and (planned) push notifications for match
  reminders / score alerts.
- **Strongest fix (post-this-branch):** ship **push notifications** (match kickoff & live-score
  alerts) — already flagged in `NATIVE-SHELL.md` as the intended 4.2 mitigation. Recommended
  before submission if the first attempt is rejected.

## Should-fix before / shortly after launch

- **Self-serve password reset** — currently "contact support" (see `/terms`). Needs an email
  provider. Not a hard blocker, but expect user lockouts without it.
- **iPad screenshots** — only required if the app ships iPad support; otherwise keep it
  iPhone-only in App Store Connect.

## Submission checklist

- [ ] Apple Developer enrollment complete
- [ ] PrivacyInfo.xcprivacy added to the App target in Xcode
- [ ] Signing team set; archive validates
- [ ] App Store Connect record created; build uploaded via TestFlight
- [ ] Listing copy, keywords, category from `STORE-LISTING.md`
- [ ] 6.7" screenshots attached (`store-assets/appstore-67-*.png`)
- [ ] Privacy policy URL + support URL set
- [ ] App Privacy label filled per the table above
- [ ] Age rating questionnaire answered (no real-money gambling)
- [ ] Review notes explain native value (Guideline 4.2)
- [ ] Tested end-to-end on a real device, incl. **create account → delete account**
