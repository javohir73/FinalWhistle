"""Anonymous device-level daily activity ping: the source of truth for D7/D14
retention cohorts measured from the WC26 final (2026-07-19, see
app/api/retention.py). Most site traffic never signs up (18 registered users
total), so the cohort key is a client-generated device id, not user_id.
Same-origin + device_id format checks mirror app/api/auth.py; user_id
attachment mirrors the optional-auth pattern used by /api/bridge/notify; the
rate limit reuses auth.py's existence-agnostic EmailActionAttempt guard
(action "ping", device_id standing in for "email") against a scripted flood.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.api.auth import _email_action_rate_limited
from app.auth import get_current_user_optional
from app.db import get_db
from app.models import AppUser, DailyActivity, EmailActionAttempt
from app.security import client_ip, hash_ip, require_same_origin

router = APIRouter(prefix="/api/activity", tags=["activity"])

# Strict UUID v4 (the frontend mints this once via crypto.randomUUID()) — a
# malformed/junk key is rejected before insert rather than bloating the table.
_DEVICE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
# Unauthenticated write, no other guard -> mirrors auth.py's register throttle:
# a scripted flood must not bloat the free-tier Postgres. Capped generously
# per IP (multi-device households / NAT'd offices share one) since this is a
# once-per-device-per-day ping, not a form submit.
_PING_MAX = 60
_PING_WINDOW_MIN = 60


def _find_ping(db: Session, device_id: str, day) -> DailyActivity | None:
    """Split out from ping() so the check-then-insert race (two concurrent
    requests both passing this check) is easy to force in tests."""
    return db.query(DailyActivity).filter_by(device_id=device_id, day=day).one_or_none()


@router.post("/ping", dependencies=[Depends(require_same_origin)])
def ping(
    payload: schemas.ActivityPingIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_current_user_optional),
):
    device_id = payload.device_id
    ip_h = hash_ip(client_ip(request))
    if _email_action_rate_limited(db, "ping", device_id, ip_h, _PING_MAX, _PING_WINDOW_MIN):
        raise HTTPException(status_code=429, detail={"code": "too_many_attempts",
                                                     "message": "Too many attempts. Try again later."})
    db.add(EmailActionAttempt(action="ping", email=device_id, ip_hash=ip_h))
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})
    today = datetime.now(timezone.utc).date()
    existing = _find_ping(db, device_id, today)
    if existing is None:
        db.add(DailyActivity(device_id=device_id, day=today, user_id=user.id if user else None))
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with a concurrent identical ping (both passed the
            # check above before either committed) — the row exists either
            # way, so this is still a no-op success, never a 500.
            db.rollback()
    else:
        db.commit()  # still persist the recorded EmailActionAttempt row
    # Idempotent either way: a resubmit of the same (device_id, day) is a no-op
    # success, never a second row and never an error.
    return {"ok": True}
