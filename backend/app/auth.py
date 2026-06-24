"""Authentication dependency.

Resolves the signed-in AppUser from the opaque session cookie (`fw_session`): we
hash the raw token, look up a live (non-revoked, unexpired) UserSession, and
return its user. All routes stay public; this only guards the account-only
actions (save across devices, join leaderboard, restore). No external service.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AppUser, UserSession
from app.security import SESSION_COOKIE, hash_token, to_aware_utc


def _session_from_request(request: Request, db: Session) -> UserSession | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    sess = (
        db.query(UserSession)
        .filter_by(session_token_hash=hash_token(raw))
        .one_or_none()
    )
    if sess is None or sess.revoked_at is not None:
        return None
    if to_aware_utc(sess.expires_at) <= datetime.now(timezone.utc):
        return None
    return sess


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    """Resolve the AppUser for the request's session cookie, or 401."""
    sess = _session_from_request(request, db)
    if sess is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Sign in to continue."},
        )
    return sess.user


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> AppUser | None:
    """Like get_current_user but returns None instead of raising (for endpoints
    whose response varies by auth without requiring it)."""
    sess = _session_from_request(request, db)
    return sess.user if sess else None
