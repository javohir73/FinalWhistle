"""Self-serve password reset (STEP 3). Security contract (per the adversarial
review): request-reset is enumeration-safe (identical 200 for any input; the only
non-200 is a rate-limit keyed on the input), tokens are hashed at rest, single-use
and expiring, and a reset revokes every session. A fake EmailSender captures the
emailed link so tests can extract the raw token without parsing logs.
"""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AppUser, PasswordResetToken, UserSession
from app.security import to_aware_utc

ALLOWED_ORIGIN = "http://localhost:3000"
PW = "supersecret"
NEW_PW = "newpassword123"


class FakeSender:
    def __init__(self):
        self.reset_calls = []  # (to_email, reset_url)

    def send_password_reset(self, to_email, reset_url):
        self.reset_calls.append((to_email, reset_url))

    def send_verification(self, to_email, verify_url):  # pragma: no cover
        pass


@pytest.fixture
def ctx(monkeypatch):
    TestingSession = sessionmaker(
        bind=create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        ),
        future=True,
    )
    Base.metadata.create_all(TestingSession.kw["bind"])

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    fake = FakeSender()
    monkeypatch.setattr("app.api.auth.get_email_sender", lambda: fake)
    client = TestClient(app, headers={"Origin": ALLOWED_ORIGIN})
    yield SimpleNamespace(client=client, Session=TestingSession, email=fake)
    app.dependency_overrides.clear()


def _register(client, email="pat@example.com", password=PW):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


def _token_from_last_email(fake):
    _to, url = fake.reset_calls[-1]
    return parse_qs(urlparse(url).query)["token"][0]


# ---- request-reset ----

def test_unknown_email_returns_200_and_sends_nothing(ctx):
    r = ctx.client.post("/api/auth/request-reset", json={"email": "nobody@example.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert ctx.email.reset_calls == []


def test_real_user_gets_link_and_token_is_hashed_at_rest(ctx):
    _register(ctx.client)
    r = ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    assert r.status_code == 200
    assert len(ctx.email.reset_calls) == 1
    to_email, url = ctx.email.reset_calls[0]
    assert to_email == "pat@example.com"
    assert "/reset-password?token=" in url
    raw = _token_from_last_email(ctx.email)
    db = ctx.Session()
    rows = db.query(PasswordResetToken).all()
    assert len(rows) == 1 and rows[0].token_hash != raw  # stored hashed, not raw
    db.close()


def test_response_is_identical_for_known_and_unknown(ctx):
    _register(ctx.client, email="known@example.com")
    a = ctx.client.post("/api/auth/request-reset", json={"email": "known@example.com"})
    b = ctx.client.post("/api/auth/request-reset", json={"email": "ghost@example.com"})
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == {"ok": True}


def test_malformed_email_still_returns_200(ctx):
    r = ctx.client.post("/api/auth/request-reset", json={"email": "notanemail"})
    assert r.status_code == 200  # no 422 — would leak which inputs are "real"


def test_request_reset_is_rate_limited(ctx):
    for _ in range(3):
        assert ctx.client.post("/api/auth/request-reset", json={"email": "a@b.com"}).status_code == 200
    r = ctx.client.post("/api/auth/request-reset", json={"email": "a@b.com"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_deleted_tombstone_gets_no_link(ctx):
    _register(ctx.client, email="gone@example.com")
    assert ctx.client.post("/api/auth/delete-account", json={"password": PW}).status_code == 200
    ctx.email.reset_calls.clear()
    r = ctx.client.post("/api/auth/request-reset", json={"email": "gone@example.com"})
    assert r.status_code == 200 and ctx.email.reset_calls == []


def test_foreign_origin_rejected_on_request_reset(ctx):
    r = ctx.client.post(
        "/api/auth/request-reset", json={"email": "a@b.com"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403


# ---- reset-password ----

def test_happy_path_changes_password(ctx):
    _register(ctx.client)
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    token = _token_from_last_email(ctx.email)
    r = ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    assert r.status_code == 200, r.text
    # Old password no longer works; new one does.
    assert ctx.client.post("/api/auth/login", json={"email": "pat@example.com", "password": PW}).status_code == 401
    assert ctx.client.post("/api/auth/login", json={"email": "pat@example.com", "password": NEW_PW}).status_code == 200


def test_reset_revokes_all_sessions_and_verifies_email(ctx):
    _register(ctx.client)
    db = ctx.Session()
    uid = db.query(AppUser).one().id
    assert db.query(UserSession).filter_by(user_id=uid, revoked_at=None).count() >= 1
    db.close()
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    token = _token_from_last_email(ctx.email)
    ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    db = ctx.Session()
    assert db.query(UserSession).filter_by(user_id=uid, revoked_at=None).count() == 0
    assert db.get(AppUser, uid).email_verified_at is not None  # reset proves email control
    db.close()


def test_token_is_single_use(ctx):
    _register(ctx.client)
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    token = _token_from_last_email(ctx.email)
    assert ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PW}).status_code == 200
    r = ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": "anotherpw123"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"


def test_expired_token_rejected(ctx):
    _register(ctx.client)
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    token = _token_from_last_email(ctx.email)
    from datetime import datetime, timedelta, timezone
    db = ctx.Session()
    row = db.query(PasswordResetToken).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()
    r = ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"


def test_unknown_token_rejected(ctx):
    r = ctx.client.post("/api/auth/reset-password", json={"token": "nope", "new_password": NEW_PW})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"


def test_weak_password_rejected_without_consuming_token(ctx):
    _register(ctx.client)
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    token = _token_from_last_email(ctx.email)
    r = ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    # Token must NOT be consumed — the user can retry with a valid password.
    assert ctx.client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PW}).status_code == 200


def test_requesting_new_token_invalidates_the_prior_one(ctx):
    _register(ctx.client)
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    first = _token_from_last_email(ctx.email)
    ctx.client.post("/api/auth/request-reset", json={"email": "pat@example.com"})
    # The first link is now dead; only the latest works.
    assert ctx.client.post("/api/auth/reset-password", json={"token": first, "new_password": NEW_PW}).status_code == 400


def test_foreign_origin_rejected_on_reset_password(ctx):
    r = ctx.client.post(
        "/api/auth/reset-password", json={"token": "x", "new_password": NEW_PW},
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403
