# Auth launch-readiness — design + sequenced plan

**Date:** 2026-06-24
**Status:** Approved direction (diagnose + design + adversarial review complete via workflow)

## Root cause of "auth doesn't work end to end" (canonical vercel.app URL)
The backend API works (register/login/me/logout/delete-account all 200 on the
allow-listed origin). The real-user failures are client/environment, ranked:
1. **Render free-tier cold start + no fetch timeout (HIGH).** `frontend/lib/session.ts`
   `request()` has no `AbortController`; after idle the backend wakes in 30–60s, so
   the sign-in button hangs past the 4s "slow" hint — reads as broken.
2. **Stale `fw-v1` service worker (MEDIUM)** can replay a cached `401 /auth/me` →
   sign-out until hard reload. `fw-v2` already skips `/backend-api/*` (correct).
3. **Safari ITP / private mode (MEDIUM)** can silently drop the cookie.

Separately confirmed: the backend origin allow-list (`CORS_ORIGINS`) contains only
`https://fifa-wc26-prediction.vercel.app`; any other origin (custom domain, `www.`,
Vercel preview) gets **403 "Origin not allowed"**, shown raw to users.

## Sequenced plan (incorporates the adversarial review's fixes)
- **STEP 0 — shared email/config prerequisite (one PR, lands first):** create
  `backend/app/email.py` (`EmailSender` protocol + `ConsoleEmailSender` that logs the
  link and makes no network call + `get_email_sender()` factory keyed on
  `settings.email_provider`). Add config **once**: `public_base_url`
  (default the vercel URL), `email_provider` (default `console`), a **single**
  `email_api_key`/`EMAIL_API_KEY` (default ""), `email_from`. Promote `_aware()`
  (currently private in `app/auth.py`) to a shared util. Update root `.env.example`
  + `render.yaml` (`sync:false`).
- **STEP 1 — origin/error hardening + cold-start UX (this branch, no DB/email dep):**
  - Backend: `Settings.allowed_origins` (auto-add the www/apex sibling; never expand
    bare-IP/localhost) + `cors_origin_regex` from `CORS_PREVIEW_REGEX`
    (**default empty → None**; anchored `^…$`; compile-once, **fail closed** on a bad
    pattern). Route **both** `CORSMiddleware` (`main.py`) and `require_same_origin`
    (`security.py`, via `re.fullmatch`) through the single `allowed_origins` source.
  - Frontend: add `AbortController` timeout (~30s) to `session.ts` `request()`; add a
    pure `friendlyAuthError(e, {offline})` mapper (never surfaces `forbidden_origin`/
    "Origin not allowed"); `AuthModal` routes catch→`friendlyAuthError`, pre-checks
    `navigator.onLine`, and clears the offline error on `online`.
- **STEP 2 — rate-limiting** for `register` and an **existence-agnostic** limiter for
  request-reset / resend (keyed on email+IP-hash, recorded for every call — the
  token-row-count limiter throttles nothing for unknown emails). Do this **before**
  wiring any outbound email.
- **STEP 3 — password reset:** `PasswordResetToken` (hashed-at-rest, single-use via an
  **atomic conditional UPDATE … WHERE used_at IS NULL**, ~30min expiry) + migration
  (`down_revision` = current head `f1a2b3c4d5e6`, **fresh** rev id). `request-reset`
  always 200 (no enumeration) and dispatches email in a **BackgroundTask** (timing
  parity); `reset-password` revokes **all** sessions, sets `email_verified_at`,
  consumes sibling tokens. Frontend: `AuthModal` "Forgot password?", `/reset-password`
  page (Suspense-wrapped `useSearchParams`, scrub token from URL). Explicit cleanup in
  `delete_account` (account is anonymized, not row-deleted → ORM cascade won't fire).
- **STEP 4 — email verification (non-blocking):** `EmailVerificationToken` + migration
  (**fresh** rev id, chained onto STEP 3's migration → single linear head; do **not**
  reuse `e5f6a7b8c9d0`). Send best-effort on register (only after STEP 2 throttle),
  verify/resend endpoints, `email_verified` on `UserOut`/`SessionUser` (treat missing
  as unknown to avoid a banner flash), banner + `/verify-email` page (POST-consume).
  **Gate public leaderboard join on `email_verified_at`.**
- **STEP 5 — guards:** CI check that `alembic heads` returns exactly one; startup
  assertion that `public_base_url ∈ allowed_origins`. Then flip `EMAIL_PROVIDER` to a
  real provider in Render with the user's key + verified sending domain.

## Infra the user must do (cannot be coded here)
- Render `pitchprophet-api` env: keep `CORS_ORIGINS=https://fifa-wc26-prediction.vercel.app`
  (the www/apex expansion + a future custom domain are additive); set `PUBLIC_BASE_URL`;
  later `EMAIL_PROVIDER` + `EMAIL_API_KEY`. Leave `CORS_PREVIEW_REGEX` unset in prod.
- Pick an email provider (Resend/SendGrid) and verify the sending domain.
- Cold-start: the code timeout makes it graceful; a true fix is Render paid tier or a
  keep-alive ping.

## Non-negotiable security properties (preserve/add)
Argon2id; opaque tokens hashed at rest (SHA-256, like sessions); single-use + expiry;
no user-enumeration (constant response shape; rate-limit keyed on input); CSRF via
`require_same_origin` on every state-changing route; `Cache-Control: no-store` on
`/api/auth`; preview-origin regex anchored + off by default (loose `*.vercel.app` is a
CSRF hole); no secrets invented (provider key from env; absent key → console fallback).

## Deploy posture
All steps build on branches with TDD; **prod deploys gated on user sign-off** (auth is
security-critical + outward-facing).
