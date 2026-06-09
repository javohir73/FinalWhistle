"""Authentication dependency.

Verifies a Clerk session JWT (RS256, validated against Clerk's JWKS) and maps it
to a local AppUser row. Dormant until CLERK_JWKS_URL is configured — protected
endpoints then return 503 instead of trusting unverified callers. All routes
stay public; this only guards the account-only actions (save across devices,
join leaderboard, restore).

PyJWT is imported lazily so local/test environments (which override this
dependency) don't require it at import time.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AppUser


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "unauthorized",
                                                     "message": "Missing bearer token"})
    return authorization.split(" ", 1)[1].strip()


def verify_clerk_token(token: str) -> dict:
    """Validate a Clerk JWT against the configured JWKS; return its claims."""
    import jwt  # lazy: only needed when auth is actually configured
    from jwt import PyJWKClient

    try:
        signing_key = PyJWKClient(settings.clerk_jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False, "verify_iss": bool(settings.clerk_issuer)},
        )
    except Exception as exc:  # invalid/expired/forged token
        raise HTTPException(status_code=401, detail={"code": "unauthorized",
                                                     "message": "Invalid token"}) from exc


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AppUser:
    """Resolve (and lazily create) the AppUser for the bearer token's subject."""
    if not settings.auth_configured:
        raise HTTPException(status_code=503, detail={"code": "auth_disabled",
                                                     "message": "Accounts are not enabled yet."})
    claims = verify_clerk_token(_bearer(authorization))
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail={"code": "unauthorized",
                                                     "message": "Token has no subject"})
    user = db.query(AppUser).filter_by(auth_provider_user_id=sub).one_or_none()
    if user is None:
        user = AppUser(
            auth_provider_user_id=sub,
            display_name=claims.get("name") or claims.get("username"),
            avatar_url=claims.get("picture"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
