"""Email verification (STEP 4) — NON-BLOCKING: register/login still succeed and
set the session; verification is prompted, not gated. Tokens mirror the reset
ones (hashed at rest, single-use, expiring). resend is enumeration-safe + rate
limited. register is rate-limited (it now triggers an outbound email).
"""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.auth as auth_api
from app.db import Base, get_db
from app.main import app
from app.models import AppUser, EmailVerificationToken

ALLOWED_ORIGIN = "http://localhost:3000"
PW = "supersecret"


class FakeSender:
    def __init__(self):
        self.verify_calls = []

    def send_password_reset(self, to_email, reset_url):  # pragma: no cover
        pass

    def send_verification(self, to_email, verify_url):
        self.verify_calls.append((to_email, verify_url))


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
    return client.post("/api/auth/register", json={"email": email, "password": password})


def _verify_token(fake):
    _to, url = fake.verify_calls[-1]
    return parse_qs(urlparse(url).query)["token"][0]


# ---- register now issues verification + reports state ----

def test_register_is_unverified_and_sends_verification(ctx):
    r = _register(ctx.client)
    assert r.status_code == 200
    assert r.json()["email_verified"] is False
    assert len(ctx.email.verify_calls) == 1
    to_email, url = ctx.email.verify_calls[0]
    assert to_email == "pat@example.com" and "/verify-email?token=" in url
    db = ctx.Session()
    rows = db.query(EmailVerificationToken).all()
    assert len(rows) == 1 and rows[0].token_hash != _verify_token(ctx.email)  # hashed
    db.close()


def test_register_succeeds_even_if_sender_raises(ctx, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(ctx.email, "send_verification", boom)
    r = _register(ctx.client, email="resilient@example.com")
    assert r.status_code == 200  # signup must never fail on a verification-email error
    assert r.json()["email_verified"] is False


def test_register_is_rate_limited_per_ip(ctx, monkeypatch):
    monkeypatch.setattr(auth_api, "_REGISTER_MAX", 2)
    assert _register(ctx.client, email="a@example.com").status_code == 200
    assert _register(ctx.client, email="b@example.com").status_code == 200
    r = _register(ctx.client, email="c@example.com")
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


# ---- verify-email ----

def test_verify_email_happy_path(ctx):
    _register(ctx.client)
    token = _verify_token(ctx.email)
    r = ctx.client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200 and r.json()["already_verified"] is False
    assert ctx.client.get("/api/auth/me").json()["email_verified"] is True


def test_verify_email_is_idempotent_for_reclicked_link(ctx):
    _register(ctx.client)
    token = _verify_token(ctx.email)
    assert ctx.client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    again = ctx.client.post("/api/auth/verify-email", json={"token": token})
    assert again.status_code == 200 and again.json()["already_verified"] is True


def test_verify_email_works_without_a_session(ctx):
    _register(ctx.client)
    token = _verify_token(ctx.email)
    fresh = TestClient(app, headers={"Origin": ALLOWED_ORIGIN})  # no cookie
    r = fresh.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200  # the token is the bearer of proof


def test_verify_email_expired_and_unknown_rejected(ctx):
    _register(ctx.client)
    token = _verify_token(ctx.email)
    from datetime import datetime, timedelta, timezone
    db = ctx.Session()
    db.query(EmailVerificationToken).one().expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()
    assert ctx.client.post("/api/auth/verify-email", json={"token": token}).status_code == 400
    assert ctx.client.post("/api/auth/verify-email", json={"token": "garbage"}).status_code == 400


def test_verify_email_foreign_origin_rejected(ctx):
    r = ctx.client.post("/api/auth/verify-email", json={"token": "x"},
                        headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403


# ---- resend-verification ----

def test_resend_sends_for_signed_in_unverified_user(ctx):
    _register(ctx.client)
    ctx.email.verify_calls.clear()
    r = ctx.client.post("/api/auth/resend-verification")
    assert r.status_code == 200
    assert len(ctx.email.verify_calls) == 1


def test_resend_no_leak_when_signed_out(ctx):
    fresh = TestClient(app, headers={"Origin": ALLOWED_ORIGIN})
    r = fresh.post("/api/auth/resend-verification")
    assert r.status_code == 200 and ctx.email.verify_calls == []  # no session → no send


def test_resend_no_send_when_already_verified(ctx):
    _register(ctx.client)
    token = _verify_token(ctx.email)
    ctx.client.post("/api/auth/verify-email", json={"token": token})
    ctx.email.verify_calls.clear()
    r = ctx.client.post("/api/auth/resend-verification")
    assert r.status_code == 200 and ctx.email.verify_calls == []  # already verified → no send


def test_resend_is_rate_limited(ctx, monkeypatch):
    monkeypatch.setattr(auth_api, "_VERIFY_RESEND_MAX", 1)
    _register(ctx.client)
    assert ctx.client.post("/api/auth/resend-verification").status_code == 200
    assert ctx.client.post("/api/auth/resend-verification").status_code == 429


def test_delete_account_purges_verification_tokens(ctx):
    _register(ctx.client, email="gone@example.com")
    db = ctx.Session()
    assert db.query(EmailVerificationToken).count() >= 1
    db.close()
    ctx.client.post("/api/auth/delete-account", json={"password": PW})
    db = ctx.Session()
    assert db.query(EmailVerificationToken).count() == 0
    db.close()
