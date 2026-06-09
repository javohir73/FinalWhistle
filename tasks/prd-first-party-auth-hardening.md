# PRD: First-Party Auth — Hardening & Production-Readiness

**Status:** Ready for implementation
**Owner:** (you)
**Scope size:** Small, focused (one real code fix + test coverage + verification)
**Repo:** https://github.com/javohir73/fifa-wc26-prediction

---

## 1. Introduction / Overview

FinalWhistle already has a first-party email/password authentication system (FastAPI
backend owns auth; Argon2 password hashing; opaque random session tokens with only
their SHA-256 hash stored in the DB; an `fw_session` HttpOnly cookie; a same-origin
Next.js rewrite `/backend-api/*`; browser calls use `credentials: "include"`).
Anonymous use of the app works without logging in. The system has been verified
working in production.

There is **one concrete defect** plus a need to **lock the behavior in with tests**:

`backend/app/security.py → verify_password()` imports
`InvalidHashError` from `argon2.exceptions` *inside the function, before the `try`*.
On `argon2-cffi` versions that do not export that exact name, the import raises
`ImportError: cannot import name 'InvalidHashError'` on **every** call to
`verify_password` — so **every login attempt crashes (HTTP 500)**, not just wrong
passwords. It currently works only because the pinned version (`argon2-cffi==23.1.0`)
happens to export the name; it fails on a local dev machine running a different
version.

**Goal:** make `verify_password` robust across supported `argon2-cffi` versions
(invalid hashes and mismatches return `False`, never crash), add a regression test
that proves it, and confirm — with tests and a manual checklist — that the rest of
the already-built auth flow behaves correctly. **Do not rebuild auth. Do not
introduce JWT. Do not bring back Clerk.**

---

## 2. Goals

1. `verify_password()` never raises on a wrong password, a malformed/garbage stored
   hash, or a version that lacks a specific exception name — it returns `False`.
2. Login works on any supported `argon2-cffi` version (fixes the local-dev failure).
3. Test coverage proves all required auth behaviors so regressions are caught in CI.
4. The full backend + frontend test/build pipeline is green.
5. The manual end-to-end auth flow (sign up → stay signed in → save → join → logout →
   anonymous still works) passes.

---

## 3. User Stories

- **As a developer running tests locally,** I want the auth tests to pass regardless
  of my installed `argon2-cffi` patch version, so I'm not blocked by an `ImportError`.
- **As a visitor,** I can create an account with email + password, and a wrong
  password tells me "incorrect email or password" instead of erroring the server.
- **As a signed-in user,** I stay signed in across page refreshes and can sign out.
- **As an anonymous user,** I can keep building a bracket without ever being forced to
  sign in; the sign-in modal only appears when I ask for it.

---

## 4. Functional Requirements

### A. The fix (the only required code change)

1. `verify_password(stored_hash, password)` MUST return `False` (never raise) for:
   a wrong password, a malformed/garbage/empty stored hash, and any
   argon2 verification error.
2. It MUST NOT depend on importing fragile exception names that vary by
   `argon2-cffi` version (e.g. `InvalidHashError`). Catch the **stable base**
   `argon2.exceptions.Argon2Error` (which covers `VerifyMismatchError`,
   `VerificationError`, `InvalidHashError`, `HashingError`). `VerifyMismatchError`
   may also be caught explicitly for clarity since it is an `Argon2Error` subclass.
3. A correct password MUST still return `True`.
4. Keep `argon2-cffi==23.1.0` pinned in `backend/requirements.txt` (no version
   change required); the fix is about not crashing if the installed version differs.

### B. Backend behavior that MUST hold (already implemented — verify, don't rebuild)

5. `POST /api/auth/register`: accepts email, password, optional `display_name`;
   normalizes email to lowercase; rejects invalid email/password with **422**;
   rejects duplicate email with **409**; hashes the password with Argon2; creates the
   user + a session; sets the `fw_session` HttpOnly cookie; returns **only**
   `{id, email, display_name, avatar_url}` and never the password hash.
6. `POST /api/auth/login`: **401** for wrong credentials; never crashes on a wrong
   password or bad stored hash (guaranteed by FR1–FR2); throttles repeated failures;
   on success creates a session and sets the cookie.
7. `POST /api/auth/logout`: revokes the current session if present; clears the cookie;
   is safe to call when already logged out.
8. `GET /api/auth/me`: returns the user for a valid session cookie; returns **401**
   for missing/invalid/expired/revoked sessions.
9. `POST /api/auth/change-password`: requires a valid session; verifies the current
   password; updates the hash; revokes the user's other sessions.
10. All auth, bracket, and user-specific responses MUST send `Cache-Control: no-store`.
11. State-changing auth/bracket endpoints MUST keep the Origin/CSRF guard
    (`require_same_origin`).

### C. Frontend behavior that MUST hold (already implemented — verify, don't rebuild)

12. No Clerk anywhere; no JWT or auth token in `localStorage`.
13. Auth state comes from `GET /backend-api/api/auth/me`.
14. Register/login/logout call `/backend-api/api/auth/*` with `credentials: "include"`.
15. The auth modal supports sign in + create account, shows friendly backend error
    messages, and shows the "password reset coming later" note.
16. Save bracket / load saved / join leaderboard work only after sign-in; anonymous
    bracket play still works without login.
17. The sign-in modal appears **only** when the user clicks **Sign in**, **Save across
    devices**, or **Join leaderboard** — never as a forced/auto popup.
18. `frontend/next.config.mjs` keeps the rewrite `/backend-api/:path*` → backend, and
    client-side API calls go through `/backend-api/...` (never directly to Render), so
    the cookie belongs to the frontend origin.

### D. Tests (add/update so all are green)

19. Backend tests MUST cover: register success; duplicate email → 409; invalid
    email/password → 422; logout clears the session; login wrong password → 401;
    login correct password → 200; `/me` with valid cookie → 200; `/me` with no cookie
    → 401; repeated wrong logins throttle; auth responses are `no-store`; foreign
    Origin rejected.
20. Add a **regression test for the fix**: `verify_password()` returns `False` (does
    not raise) for a garbage/invalid stored hash and for a wrong password, and returns
    `True` for a correct password. (Selected option **4B**.)

---

## 5. Non-Goals (Out of Scope)

- Rebuilding or re-architecting auth; switching to JWT/bearer tokens; reintroducing
  Clerk or any third-party auth.
- Email verification and self-serve password reset (explicitly deferred).
- OAuth / social login.
- The **security cleanup** identified separately — rotating the exposed
  `RECOMPUTE_TOKEN` and `TRUNCATE`-ing the smoke-test accounts — is **tracked
  separately**, not part of this PRD (per decision 3B).
- A multi-version `argon2-cffi` CI matrix (we chose 4B, not 4C).

---

## 6. Design Considerations

No UI changes. The existing `AuthModal` / `AuthButton` / `AccountPanel` /
`AuthProvider` and their copy (including the "password reset coming later" note) stay
as-is. This is a backend-correctness + test PRD.

---

## 7. Technical Considerations

- **Files in play:**
  - Change: `backend/app/security.py` (`verify_password` only).
  - Tests: `backend/tests/test_auth_api.py` (add the FR20 regression test; FR19
    coverage largely exists — fill any gap).
  - Verify-only (no change expected): `backend/app/api/auth.py`,
    `backend/app/auth.py`, `backend/app/models/__init__.py`,
    `backend/app/main.py` (the `no-store` middleware), `frontend/lib/session.ts`,
    `frontend/components/AuthProvider.tsx`, `frontend/components/AuthModal.tsx`,
    `frontend/components/AccountPanel.tsx`, `frontend/next.config.mjs`.
- **Why catch `Argon2Error`:** it is the long-standing base class for argon2 errors,
  so it's stable across versions; `InvalidHashError` is not guaranteed to exist.
  Importing `Argon2Error` (and optionally `VerifyMismatchError`) avoids the
  `ImportError`. Do not fall back to a bare `except Exception` (would mask real bugs).
- **Architecture to preserve (do not change):** FastAPI-owned auth, Argon2 hashing,
  opaque tokens with SHA-256-at-rest, `fw_session` HttpOnly cookie, same-origin
  `/backend-api` rewrite, `credentials: "include"`, env-aware cookie `Secure` flag,
  anonymous-first UX.

---

## 8. Success Metrics

- `python -m pytest backend/tests/test_auth_api.py backend/tests/test_brackets_api.py`
  → all pass.
- `python -m pytest` → all pass (including the new FR20 regression test).
- Frontend: `cd frontend && npm ci && npm test -- --runInBand && npm run typecheck &&
  NEXT_PUBLIC_API_URL=https://pitchprophet-api.onrender.com npm run build` → all green.
- `verify_password` returns `False` (not an exception) for a garbage hash — proven by
  the new test.
- **Manual checklist passes** (through the frontend proxy, local/preview/live):
  1. Create an account.
  2. `fw_session` cookie is `HttpOnly`.
  3. No auth token in `localStorage`.
  4. Refresh the page → still signed in.
  5. Logout → `/me` returns 401.
  6. Login again → `/me` returns the user.
  7. Save a bracket.
  8. Join the leaderboard.
  9. After logout, anonymous bracket play still works.

---

## 9. Open Questions

- None blocking. The separate security cleanup (token rotation + test-data purge,
  decision 3B) should be tracked as its own task before/around public launch.
