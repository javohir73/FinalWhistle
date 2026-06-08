# Post-launch tasks & accepted risks

## CI, monitoring & ops

- **CI** (`.github/workflows/ci.yml`): on every push/PR runs backend `pytest`,
  frontend `npm ci` → `typecheck` → `jest` → `build` (with `NEXT_PUBLIC_API_URL`
  set) → non-blocking `npm audit --omit=dev`.
- **Branch protection** on `main`: CI (`python-tests`, `frontend`) must pass;
  force-pushes and deletions blocked. `enforce_admins` is off so the owner isn't
  locked out; a required PR-review count is intentionally not set (a solo repo
  can't self-approve a PR). To tighten once there's a collaborator:
  `gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input <json>`
  with `required_pull_request_reviews.required_approving_review_count: 1`.
- **Smoke test** (`.github/workflows/smoke.yml`): every 6h + manual; checks the
  live site, key pages, an OG image and `/api/health` (retries for cold starts).
- **Error tracking (Sentry)** — disabled until a DSN is set (safe no-op):
  - Backend: `SENTRY_DSN` on Render → FastAPI auto-instrumented, tagged with
    `model_version` + `ENVIRONMENT`.
  - Frontend: `NEXT_PUBLIC_SENTRY_DSN` on Vercel → client error tracking
    (lazy-loaded). CSP already allows `*.ingest.sentry.io`. Source-map upload and
    Next server-component instrumentation are deferred (post-launch, low-risk).

## Live mode activation (near June 11)

Live in-game updates are a safe no-op until **both** are set on Render:
1. `FOOTBALL_DATA_API_KEY` = a football-data.org key.
2. `LIVE_MODE_ENABLED` = `true`.
Then point a cron (e.g. cron-job.org) at `POST /api/internal/refresh-live` with
the `X-Recompute-Token` header during match windows. `/api/health` reports
`live_updates: ready`, and the Matches page shows a "Live updates on" badge.



Tracking for work intentionally deferred until after the World Cup 2026 group
stage opens (June 11, 2026), so framework-level changes don't risk a
tournament-day regression.

## Accepted temporary risk: Next.js audit advisories

**Status:** Accepted until post-launch (target: review week of 2026-06-15).

`npm audit` reports 1 high + 1 moderate advisory against `next` (and a
transitive `postcss`). We are on **next@14.2.35**, the latest patch in the
14.2.x line. The remaining advisories were only fixed in the **15.x / 16.x**
lines, so the entire 14.2.x range is flagged regardless of patch level.

**Why this is an accepted temporary risk, not an open vulnerability:**

- No custom `middleware.ts` → middleware-bypass / middleware cache-poisoning
  advisories are not reachable.
- No `next/image` usage (flags render via plain `<img>`) → Image Optimizer DoS
  and disk-cache advisories are not reachable.
- No CSP nonces (we ship a static CSP) → the nonce-based XSS advisory is not
  reachable.
- No `beforeInteractive` scripts → that XSS advisory is not reachable.
- No i18n routing → the i18n middleware-bypass advisory is not reachable.
- Hosted on **Vercel** (not self-hosted), which mitigates the "self-hosted"
  classes at the platform/CDN layer.

The 14.2.18 → 14.2.35 bump already pulled in the CVE-2025-29927 middleware
auth-bypass fix and later 14.2.x security patches.

**Exit criteria:** completing the tracked Next 15/16 upgrade below clears the
audit; re-run `npm audit --omit=dev` and confirm 0 high/critical.

## Model precision — validated findings & next levers

A walk-forward study (tune only on pre-tournament data, score on the held-out
tournament; 2014/2018/2022) was run via `pipeline/tune_model.py`. Result: the
served **poisson-elo-v0.1** model is already well-calibrated (fitted temperature
≈ 1.0) and near the achievable ceiling for Elo-only features. None of the tested
upgrades beat it out-of-sample:

- Temperature calibration → T ≈ 1.0 (no real gain; already calibrated).
- Dixon–Coles draw correction + re-tuned base/beta/home_adv → within noise.
- Time-decayed (annual regression-to-mean) Elo → helped 2022, hurt 2014/2018.

So v0.1 stays in production. The infrastructure added (Dixon–Coles + temperature
in `ml/models/poisson.py`, the tuner in `ml/evaluation/tune.py`, `walk_forward`
in `ml/evaluation/backtest.py`, report via `pipeline/tune_model.py`) is the gate
for any future model change: ship a new version only if it beats v0.1 here.

**Real next levers (need new signal, deferred):**
- Squad strength / injuries / availability (the biggest expected gain; needs a
  data source — do not fabricate).
- Market-implied probabilities blended in when odds are available.
- Re-examine recency weighting once squad data exists.

## Analytics event taxonomy

Provider: **Vercel Web Analytics** (`@vercel/analytics`, `<Analytics/>` in the
root layout). Privacy-friendly, no cookie banner required.

- Page views (automatic) — cover methodology views and the team-page
  view/exit funnel (drop-off is read from the pageview path in the dashboard).
- `match_card_click` `{ match_id }` — match card → match detail.
- `favorite_toggle` `{ team, favorited }` — star toggled on/off.
- `bracket_team_click` `{ team, from }` — brackets → team page; `from` is one of
  `title` | `stage` | `bracket` | `thirds` | `groups`.

Events fire through `lib/analytics.ts#trackEvent`, which dynamic-imports the
analytics module on first use (kept out of SSR/tests; failures are swallowed).

## Tracked task: Next.js 15/16 major upgrade

**Priority:** High (technical), post-launch.

Move off the 14.2.x line to the actively-patched major (15.x, then assess 16.x)
to clear the advisories above.

Breaking changes to handle:

- `params` / `searchParams` become async (Promise) — must `await` them in
  `generateMetadata` and in the dynamic pages: `app/match/[id]/page.tsx`,
  `app/team/[id]/page.tsx`, `app/groups/[id]/page.tsx`.
- `fetch` is no longer cached by default — we already pass explicit
  `next: { revalidate }`, so verify each call site still behaves as intended.
- React 19 becomes the default — pin React 18 first to isolate the Next bump,
  then upgrade React separately.

Verification gates for the upgrade PR:

- `npm test` green, `npm run build` green.
- Screenshot regression check on key routes: `/`, `/matches`, `/match/[id]`,
  `/groups/[id]`, `/team/[id]`, `/brackets`, `/methodology` (desktop + 390px).
- `npm audit --omit=dev` reports 0 high/critical.
