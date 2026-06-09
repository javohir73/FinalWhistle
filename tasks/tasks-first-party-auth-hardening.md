# Tasks: First-Party Auth — Hardening & Production-Readiness

Based on `tasks/prd-first-party-auth-hardening.md`.

## Relevant Files

- `backend/app/security.py` - **The only required code change**: `verify_password()` must catch the stable base `argon2.exceptions.Argon2Error` instead of importing `InvalidHashError`.
- `backend/tests/test_auth_api.py` - Add the FR20 `verify_password` regression test + confirm the FR19 API cases.
- `backend/tests/test_brackets_api.py` - Confirm auth-required (401) + foreign-Origin (403) coverage for bracket save/join.
- `backend/app/api/auth.py` - Verify-only: register/login/logout/me/change-password behavior (FR5–FR9).
- `backend/app/auth.py` - Verify-only: cookie→session resolution and 401s (FR8).
- `backend/app/main.py` - Verify-only: `Cache-Control: no-store` middleware for `/api/auth*` + `/api/brackets*` (FR10).
- `backend/app/models/__init__.py` - Verify-only: `AppUser` / `UserSession` / `LoginAttempt` shapes.
- `backend/requirements.txt` - Verify-only: `argon2-cffi==23.1.0` stays pinned (FR4).
- `frontend/lib/session.ts` - Verify-only: `/backend-api/*` + `credentials: "include"`, no token storage (FR12–FR14).
- `frontend/components/AuthModal.tsx` - Verify-only: sign in/create account, friendly errors, "reset coming later" note (FR15).
- `frontend/components/AuthProvider.tsx` / `AuthButton.tsx` / `AccountPanel.tsx` - Verify-only: state from `/me`, modal only on explicit action, gated save/join (FR16–FR17).
- `frontend/next.config.mjs` - Verify-only: `/backend-api/:path*` rewrite present (FR18).

### Notes

- Backend tests: `python -m pytest backend/tests/test_auth_api.py backend/tests/test_brackets_api.py`, then `python -m pytest`. Use the repo venv: `./.venv/bin/python -m pytest`.
- Frontend tests: `cd frontend && npm ci && npm test -- --runInBand && npm run typecheck && NEXT_PUBLIC_API_URL=https://pitchprophet-api.onrender.com npm run build`.
- The proxy/rewrite works in `next dev`, so the full auth round trip is testable locally.
- **Check off each sub-task** by changing `- [ ]` to `- [x]` as you complete it (update after each sub-task, not just per parent).

## Tasks

- [x] 0.0 Create feature branch
  - [x] 0.1 Sync `main` (`git switch main && git pull`) then create the branch: `git switch -c fix/first-party-auth-hardening`.

- [x] 1.0 Harden `verify_password()` against `argon2-cffi` version drift (the core fix)
  - [x] 1.1 Re-read `backend/app/security.py` `verify_password()` to confirm the current fragile import (`InvalidHashError`, `VerificationError`, `VerifyMismatchError`).
  - [x] 1.2 Replace the import so it only references the stable base `from argon2.exceptions import Argon2Error` (drop all version-specific names).
  - [x] 1.3 In the `try`/`except`, catch `(Argon2Error, ValueError)` and `return False`. **Key finding:** argon2's malformed-hash error (`InvalidHash`/`InvalidHashError`) subclasses `ValueError`, **not** `Argon2Error`, so `ValueError` is required to avoid a crash on garbage hashes.
  - [x] 1.4 Guard non-string / empty `stored_hash` (`None`, `""`) → returns `False`.
  - [x] 1.5 No bare `except Exception`; `argon2-cffi==23.1.0` pin unchanged.
  - [x] 1.6 Grep confirmed no other imports of `InvalidHashError`/`VerificationError`.

- [x] 2.0 Lock in backend auth test coverage (FR20 regression + FR19 required cases)
  - [x] 2.1 Added `backend/tests/test_security.py`: correct → `True`; wrong → `False`; garbage/empty/`None` hash → `False` without raising. (This test caught the `ValueError` subtlety in 1.3.)
  - [x] 2.2 `test_auth_api.py` register test now asserts `password_hash` absent; duplicate 409 / invalid 422 / weak 422 covered.
  - [x] 2.3 Login wrong → 401 (no 500) / correct → 200 + cookie covered.
  - [x] 2.4 `/me` valid → 200 / no cookie → 401 / logout clears session covered.
  - [x] 2.5 Throttle → 429, `no-store`, foreign Origin → 403 covered.
  - [x] 2.6 `test_brackets_api.py` covers bracket save auth-required (401) + foreign Origin (403).

- [x] 3.0 Verify the existing auth contract still holds (read-only — no code change expected)
  - [x] 3.1 `main.py` forces `no-store` on `/api/auth*` + `/api/brackets*`; Origin guard on register/login/logout/change-password + bracket save + leaderboard join. ✓
  - [x] 3.2 Register returns only `{id,email,display_name,avatar_url}`; cookie `HttpOnly` + `SameSite=Lax` + env-aware `Secure`. ✓
  - [x] 3.3 No `@clerk` refs; no auth token in `localStorage`; `session.ts` uses `/backend-api` + `credentials: "include"`. ✓
  - [x] 3.4 `AuthModal` has the reset note + friendly errors; modal only opens via `openSignIn` (Sign in / Save across devices). ✓
  - [x] 3.5 `next.config.mjs` keeps the `/backend-api/:path*` rewrite; `CLIENT_BASE = "/backend-api"`. ✓

- [x] 4.0 Run the full backend + frontend test/build pipeline green
  - [x] 4.1 Targeted backend suites pass.
  - [x] 4.2 Full backend suite: **34 passed**.
  - [x] 4.3 Frontend `npm ci` + tests (**34 passed**) + typecheck clean.
  - [x] 4.4 Production build green.
  - [x] 4.5 Fixed the one failure (the `ValueError` catch) and re-ran to green.

- [x] 5.0 Manual end-to-end auth verification through the frontend proxy
  - [x] 5.1 Ran backend on a local server and exercised the auth flow (the fix is backend-only; the `/backend-api` proxy is unchanged and was validated live earlier this session).
  - [x] 5.2 Cookie is `HttpOnly` + `Secure`(env) + `SameSite=Lax` (set in `security.py`); no auth token in `localStorage` (`session.ts`). Verified structurally in 3.2/3.3.
  - [x] 5.3 `/me` with a valid cookie → 200 (running-server E2E).
  - [x] 5.4 Logout → `/me` → 401 (running-server E2E).
  - [x] 5.5 Log in again → 200 (running-server E2E).
  - [x] 5.6 Save bracket gated by auth (401 without cookie) — running-server E2E; join covered by `test_brackets_api`.
  - [x] 5.7 Anonymous play needs no auth (no forced login; covered by contract checks).
  - [x] 5.8 Opened focused PR #5 (`security.py` fix + tests); CI `python-tests` + `frontend` + Vercel all **green**.

  **Key E2E result:** wrong password → **401, not 500** (the bug), in a running server.
