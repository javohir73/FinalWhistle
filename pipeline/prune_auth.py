"""Prune aged auth bookkeeping rows (runs in the daily refresh).

login_attempts exist only to throttle recent failures (15-minute window) and
user_sessions only matter until they expire or are revoked — both otherwise
grow without bound. Deleting old rows keeps the free-tier Postgres small and
is safe: the throttle never reads attempts beyond its window, and dead
sessions can never authenticate again.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import LoginAttempt, UserSession

# Keep failures well past the 15-min throttle window for incident forensics.
ATTEMPT_RETENTION = timedelta(days=7)
# Expired/revoked sessions are kept briefly for the same reason, then dropped.
SESSION_GRACE = timedelta(days=7)


def prune_auth_rows(db: Session) -> dict:
    """Delete throttle rows older than the retention window and sessions that
    have been dead (expired or revoked) for longer than the grace period."""
    now = datetime.now(timezone.utc)

    attempts = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.attempted_at < now - ATTEMPT_RETENTION)
        .delete(synchronize_session=False)
    )

    cutoff = now - SESSION_GRACE
    sessions = (
        db.query(UserSession)
        .filter(
            or_(
                UserSession.expires_at < cutoff,
                and_(UserSession.revoked_at.isnot(None), UserSession.revoked_at < cutoff),
            )
        )
        .delete(synchronize_session=False)
    )

    db.commit()
    return {"login_attempts_deleted": attempts, "sessions_deleted": sessions}
