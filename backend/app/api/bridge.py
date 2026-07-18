"""WC26 retention bridge: post-final "what's next" email capture.

The World Cup final's traffic wedge expires the moment the final whistle blows.
This is the one write path behind the frontend's post-final banner — it converts
World Cup visitors into (a) NRL users right now (a CTA, no backend involvement)
and (b) an email list for the domestic-league launch in mid-August. Same-origin
+ email validation mirror app/api/auth.py; user_id attachment mirrors the
optional-auth pattern used by /api/auth/resend-verification.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.api.auth import _EMAIL_RE, _normalize_email
from app.auth import get_current_user_optional
from app.db import get_db
from app.models import AppUser, BridgeSignup
from app.security import require_same_origin

router = APIRouter(prefix="/api/bridge", tags=["bridge"])

# Closed allowlist: this endpoint only ever serves the post-final banner, so an
# unrecognized source is rejected rather than silently stored.
_ALLOWED_SOURCES = {"wc26_final_bridge"}


@router.post("/notify", dependencies=[Depends(require_same_origin)])
def notify(
    payload: schemas.BridgeNotifyIn,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_current_user_optional),
):
    email = _normalize_email(payload.email)
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail={"code": "invalid_email",
                                                     "message": "Enter a valid email address."})
    source = payload.source.strip()[:50]
    if source not in _ALLOWED_SOURCES:
        raise HTTPException(status_code=422, detail={"code": "invalid_source",
                                                     "message": "Unknown signup source."})
    existing = db.query(BridgeSignup).filter_by(email=email, source=source).one_or_none()
    if existing is None:
        db.add(BridgeSignup(email=email, source=source, user_id=user.id if user else None))
        db.commit()
    # Idempotent either way: a resubmit of the same (email, source) is a no-op
    # success, never a second row and never an error.
    return {"ok": True}
