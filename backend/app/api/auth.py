"""First-party email + password auth: register / login / logout / me / change-password.

Sessions are opaque tokens in an HttpOnly cookie (see app/security.py). Accounts
are optional — they only unlock save-across-devices and the leaderboard; anonymous
play never touches these routes. There is no email sending yet, so no self-serve
password reset (documented limitation).
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import schemas
from app.auth import get_current_user
from app.db import get_db
from app.models import AppUser, Bracket, LoginAttempt, MatchPick, UserSession
from app.security import (
    SESSION_COOKIE,
    SESSION_TTL,
    clear_session_cookie,
    client_ip,
    hash_ip,
    hash_password,
    hash_token,
    new_session_token,
    require_same_origin,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8
_MAX_PASSWORD = 200
_THROTTLE_MAX_FAILURES = 5
_THROTTLE_WINDOW_MIN = 15


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_credentials(email: str, password: str) -> None:
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail={"code": "invalid_email",
                                                     "message": "Enter a valid email address."})
    if not (_MIN_PASSWORD <= len(password) <= _MAX_PASSWORD):
        raise HTTPException(status_code=422, detail={"code": "weak_password",
                                                     "message": f"Password must be at least {_MIN_PASSWORD} characters."})


def _create_session(db: Session, request: Request, user: AppUser) -> str:
    raw = new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            session_token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + SESSION_TTL,
            user_agent=(request.headers.get("user-agent") or "")[:400] or None,
            ip_hash=hash_ip(client_ip(request)),
        )
    )
    return raw


def _signup_geo(request: Request) -> tuple[str | None, str | None]:
    """Best-effort country/city from Vercel's edge headers (present when the
    request came through the frontend proxy). City is URL-encoded by Vercel."""
    country = request.headers.get("x-vercel-ip-country")
    city = request.headers.get("x-vercel-ip-city")
    country = country.strip().upper()[:2] if country else None
    city = unquote(city).strip()[:120] if city else None
    return country or None, city or None


def _user_out(u: AppUser) -> schemas.UserOut:
    return schemas.UserOut(id=u.id, email=u.email, display_name=u.display_name,
                           avatar_url=u.avatar_url)


@router.post("/register", response_model=schemas.UserOut, dependencies=[Depends(require_same_origin)])
def register(payload: schemas.RegisterIn, request: Request, response: Response,
             db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    _validate_credentials(email, payload.password)
    if db.query(AppUser).filter_by(email=email).first() is not None:
        raise HTTPException(status_code=409, detail={"code": "email_taken",
                                                     "message": "An account with that email already exists."})
    country, city = _signup_geo(request)
    user = AppUser(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or "").strip()[:60] or None,
        signup_country=country,
        signup_city=city,
    )
    db.add(user)
    db.flush()
    raw = _create_session(db, request, user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, raw)
    return _user_out(user)


@router.post("/login", response_model=schemas.UserOut, dependencies=[Depends(require_same_origin)])
def login(payload: schemas.LoginIn, request: Request, response: Response,
          db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    ip_h = hash_ip(client_ip(request))

    # Throttle: too many recent failures for this email+IP → 429.
    window_start = datetime.now(timezone.utc).timestamp() - _THROTTLE_WINDOW_MIN * 60
    recent_failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.email == email,
            LoginAttempt.ip_hash == ip_h,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= datetime.fromtimestamp(window_start, tz=timezone.utc),
        )
        .count()
    )
    if recent_failures >= _THROTTLE_MAX_FAILURES:
        raise HTTPException(status_code=429, detail={"code": "too_many_attempts",
                                                     "message": "Too many attempts. Try again later."})

    user = db.query(AppUser).filter_by(email=email).first()
    ok = user is not None and verify_password(user.password_hash, payload.password)
    db.add(LoginAttempt(email=email, ip_hash=ip_h, success=ok))
    if not ok:
        db.commit()
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials",
                                                     "message": "Incorrect email or password."})
    raw = _create_session(db, request, user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, raw)
    return _user_out(user)


@router.post("/logout", dependencies=[Depends(require_same_origin)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        sess = db.query(UserSession).filter_by(session_token_hash=hash_token(raw)).one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = datetime.now(timezone.utc)
            db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=schemas.UserOut)
def me(user: AppUser = Depends(get_current_user)):
    return _user_out(user)


@router.post("/delete-account", dependencies=[Depends(require_same_origin)])
def delete_account(payload: schemas.DeleteAccountIn, response: Response,
                   user: AppUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """In-app account deletion (Apple Guideline 5.1.1(v)). Re-auth with the
    current password, then *anonymize* rather than hard-delete: personal data is
    wiped and every session revoked, but the user's public leaderboard entry is
    kept (under "Deleted user") so standings/history stay intact. The real email
    is released so it can be used to register a fresh account."""
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials",
                                                     "message": "Current password is incorrect."})
    old_email = user.email
    # Anonymize the identity. The email becomes a unique tombstone (frees the
    # real address) and the password hash an unguessable value (login is now
    # impossible — there is no reset flow back into a deleted account).
    user.email = f"deleted-{user.id}@deleted.finalwhistle.app"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.display_name = None
    user.avatar_url = None
    user.signup_country = None
    user.signup_city = None
    user.email_verified_at = None

    # Keep the bracket (it carries the leaderboard score) but strip the only
    # personal field on it — the public display name.
    bracket = db.query(Bracket).filter_by(user_id=user.id).one_or_none()
    if bracket is not None:
        bracket.display_name = "Deleted user" if bracket.visibility == "public" else None

    # Drop personal per-match picks and every session, plus stale login-attempt
    # rows tied to the old email (they hold the real address).
    db.query(MatchPick).filter_by(user_id=user.id).delete()
    db.query(UserSession).filter_by(user_id=user.id).delete()
    db.query(LoginAttempt).filter(LoginAttempt.email == old_email).delete()
    db.commit()

    clear_session_cookie(response)
    return {"ok": True}


@router.post("/change-password", dependencies=[Depends(require_same_origin)])
def change_password(payload: schemas.ChangePasswordIn, request: Request,
                    user: AppUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials",
                                                     "message": "Current password is incorrect."})
    if not (_MIN_PASSWORD <= len(payload.new_password) <= _MAX_PASSWORD):
        raise HTTPException(status_code=422, detail={"code": "weak_password",
                                                     "message": f"Password must be at least {_MIN_PASSWORD} characters."})
    user.password_hash = hash_password(payload.new_password)
    # Revoke every other session (keep the caller signed in via their cookie).
    keep = request.cookies.get(SESSION_COOKIE)
    keep_hash = hash_token(keep) if keep else None
    now = datetime.now(timezone.utc)
    for s in db.query(UserSession).filter_by(user_id=user.id, revoked_at=None).all():
        if s.session_token_hash != keep_hash:
            s.revoked_at = now
    db.commit()
    return {"ok": True}
