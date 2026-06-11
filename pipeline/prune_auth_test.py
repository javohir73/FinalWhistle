"""prune_auth: old throttle rows and dead sessions go; live data stays."""
from datetime import datetime, timedelta, timezone

from app.models import AppUser, LoginAttempt, UserSession
from pipeline.prune_auth import prune_auth_rows


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_prunes_old_attempts_and_dead_sessions(db_session):
    user = AppUser(email="p@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()

    db_session.add_all([
        # Throttle rows: one stale, one current.
        LoginAttempt(email="p@example.com", attempted_at=_now() - timedelta(days=8), success=False),
        LoginAttempt(email="p@example.com", attempted_at=_now() - timedelta(minutes=1), success=False),
        # Sessions: expired long ago, revoked long ago, and one live.
        UserSession(user_id=user.id, session_token_hash="dead-expired",
                    expires_at=_now() - timedelta(days=9)),
        UserSession(user_id=user.id, session_token_hash="dead-revoked",
                    expires_at=_now() + timedelta(days=20),
                    revoked_at=_now() - timedelta(days=9)),
        UserSession(user_id=user.id, session_token_hash="alive",
                    expires_at=_now() + timedelta(days=20)),
    ])
    db_session.commit()

    result = prune_auth_rows(db_session)

    assert result == {"login_attempts_deleted": 1, "sessions_deleted": 2}
    assert db_session.query(LoginAttempt).count() == 1
    remaining = [s.session_token_hash for s in db_session.query(UserSession).all()]
    assert remaining == ["alive"]


def test_recently_dead_sessions_survive_the_grace_period(db_session):
    user = AppUser(email="g@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserSession(user_id=user.id, session_token_hash="just-expired",
                               expires_at=_now() - timedelta(hours=2)))
    db_session.commit()

    result = prune_auth_rows(db_session)

    assert result["sessions_deleted"] == 0
    assert db_session.query(UserSession).count() == 1
