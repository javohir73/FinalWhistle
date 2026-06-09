"""Password hashing, opaque session tokens, cookie helpers, and the Origin check.

Security choices (per OWASP Authentication / Session-Management cheat sheets):
- Passwords hashed with argon2id (argon2-cffi), never stored in plaintext.
- Session tokens are opaque random strings; only their SHA-256 hash is stored, so
  a database leak can't be replayed as a live session.
- The session cookie is HttpOnly + SameSite=Lax + Secure (env-aware), host-only
  (no Domain) so it binds to the proxying frontend host.
- A second-line Origin check guards state-changing requests against CSRF.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request, Response

from app.config import settings

SESSION_COOKIE = "fw_session"
SESSION_TTL = timedelta(days=30)
MAX_PASSWORD_LEN = 200  # guard argon2 against pathologically large inputs

_hasher = None


def _ph():
    """Lazily construct the argon2 PasswordHasher (kept out of import time)."""
    global _hasher
    if _hasher is None:
        from argon2 import PasswordHasher

        _hasher = PasswordHasher()
    return _hasher


def hash_password(password: str) -> str:
    return _ph().hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """True iff the password matches the stored argon2 hash; never raises.

    A wrong password, or a malformed/garbage/empty stored hash, returns False.
    We catch argon2's stable base ``Argon2Error`` (wrong-password mismatches) **and**
    ``ValueError``: a malformed hash raises ``InvalidHash``/``InvalidHashError``,
    which subclasses ``ValueError`` (not ``Argon2Error``) and whose exact name varies
    by argon2-cffi version — so importing that name directly would crash every login
    on some versions. Catching the stable bases keeps verification version-proof."""
    from argon2.exceptions import Argon2Error

    if not isinstance(stored_hash, str) or not stored_hash:
        return False
    try:
        return _ph().verify(stored_hash, password)
    except (Argon2Error, ValueError):
        return False


def new_session_token() -> str:
    """A fresh, URL-safe opaque token. ~256 bits of entropy."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """SHA-256 hex of a raw token — what we persist and look up by."""
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_ip(ip: str | None) -> str | None:
    """Hash an IP before storage (we never keep raw IPs)."""
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()


def client_ip(request: Request) -> str | None:
    """Best-effort client IP, honoring the proxy chain (Vercel → Render)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_same_origin(request: Request) -> None:
    """CSRF defense-in-depth for POST/PUT/PATCH/DELETE: the request's Origin must
    match a configured allowed origin. Browsers always send Origin on cross-site
    state-changing requests; a missing Origin is allowed outside production (curl,
    tests) but rejected in production."""
    origin = request.headers.get("origin")
    if origin is None:
        if settings.environment == "production":
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden_origin", "message": "Missing Origin header"},
            )
        return
    if origin not in settings.cors_origin_list:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden_origin", "message": "Origin not allowed"},
        )
