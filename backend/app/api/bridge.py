"""WC26 retention bridge: post-final "what's next" email capture.

The World Cup final's traffic wedge expires the moment the final whistle blows.
This is the one write path behind the frontend's post-final banner — it converts
World Cup visitors into (a) NRL users right now (a CTA, no backend involvement)
and (b) an email list for the domestic-league launch in mid-August. Same-origin
+ email validation mirror app/api/auth.py; user_id attachment mirrors the
optional-auth pattern used by /api/auth/resend-verification; the rate limit
mirrors auth.py's register throttle (an unauthenticated write needs the same
existence-agnostic EmailActionAttempt guard against a scripted flood).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.api.auth import _EMAIL_RE, _email_action_rate_limited, _normalize_email
from app.auth import get_current_user_optional
from app.db import get_db
from app.models import AppUser, BridgeSignup, EmailActionAttempt
from app.security import client_ip, hash_ip, require_same_origin

router = APIRouter(prefix="/api/bridge", tags=["bridge"])

# Closed allowlist: this endpoint only ever serves the post-final banner, so an
# unrecognized source is rejected rather than silently stored.
_ALLOWED_SOURCES = {"wc26_final_bridge"}
# _EMAIL_RE has no length bound, so a pathological address would otherwise
# reach the column and, on Postgres (unlike the sqlite test DB), raise
# StringDataRightTruncation -> 500. 254 is RFC 5321's practical email cap.
_MAX_EMAIL_LEN = 254
# Unauthenticated write, no other guard -> mirrors auth.py's register throttle
# (_REGISTER_MAX/_REGISTER_WINDOW_MIN): a scripted flood must not bloat the
# free-tier Postgres or poison the launch list. IP is the stable dimension
# (email varies under attack) — _email_action_rate_limited already checks
# both, so this is effectively IP-keyed in practice.
_BRIDGE_MAX = 10
_BRIDGE_WINDOW_MIN = 60


def _find_signup(db: Session, email: str, source: str) -> BridgeSignup | None:
    """Split out from notify() so the check-then-insert race (two concurrent
    requests both passing this check) is easy to force in tests."""
    return db.query(BridgeSignup).filter_by(email=email, source=source).one_or_none()


@router.post("/notify", dependencies=[Depends(require_same_origin)])
def notify(
    payload: schemas.BridgeNotifyIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_current_user_optional),
):
    email = _normalize_email(payload.email)
    ip_h = hash_ip(client_ip(request))
    if _email_action_rate_limited(db, "bridge", email, ip_h, _BRIDGE_MAX, _BRIDGE_WINDOW_MIN):
        raise HTTPException(status_code=429, detail={"code": "too_many_attempts",
                                                     "message": "Too many attempts. Try again later."})
    db.add(EmailActionAttempt(action="bridge", email=email, ip_hash=ip_h))
    if not _EMAIL_RE.match(email) or len(email) > _MAX_EMAIL_LEN:
        raise HTTPException(status_code=422, detail={"code": "invalid_email",
                                                     "message": "Enter a valid email address."})
    source = payload.source.strip()[:50]
    if source not in _ALLOWED_SOURCES:
        raise HTTPException(status_code=422, detail={"code": "invalid_source",
                                                     "message": "Unknown signup source."})
    existing = _find_signup(db, email, source)
    if existing is None:
        db.add(BridgeSignup(email=email, source=source, user_id=user.id if user else None))
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with a concurrent identical submit (both passed the
            # check above before either committed) — the row exists either
            # way, so this is still a no-op success, never a 500.
            db.rollback()
    else:
        db.commit()  # still persist the recorded EmailActionAttempt row
    # Idempotent either way: a resubmit of the same (email, source) is a no-op
    # success, never a second row and never an error.
    return {"ok": True}
