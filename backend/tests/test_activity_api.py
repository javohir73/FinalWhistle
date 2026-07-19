"""POST /api/activity/ping — anonymous device-level daily activity ping.

Mirrors test_bridge_api.py's client fixture (Origin header, in-memory SQLite)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.activity as activity_api
from app.db import Base, get_db
from app.main import app
from app.models import DailyActivity, EmailActionAttempt

ALLOWED_ORIGIN = "http://localhost:3000"
DEVICE_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _make_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client():
    TestingSession = _make_engine()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app, headers={"Origin": ALLOWED_ORIGIN}), TestingSession
    app.dependency_overrides.clear()


def test_ping_stores_row_with_utc_day(client):
    c, SessionF = client
    r = c.post("/api/activity/ping", json={"device_id": DEVICE_ID})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    db = SessionF()
    rows = db.query(DailyActivity).all()
    assert len(rows) == 1
    assert rows[0].device_id == DEVICE_ID
    assert rows[0].day == datetime.now(timezone.utc).date()
    assert rows[0].user_id is None
    db.close()


def test_duplicate_same_day_ping_is_idempotent(client):
    c, SessionF = client
    body = {"device_id": DEVICE_ID}
    first = c.post("/api/activity/ping", json=body)
    second = c.post("/api/activity/ping", json=body)
    assert first.status_code == 200 and second.status_code == 200

    db = SessionF()
    assert db.query(DailyActivity).filter_by(device_id=DEVICE_ID).count() == 1
    db.close()


def test_invalid_device_id_rejected(client):
    c, SessionF = client
    r = c.post("/api/activity/ping", json={"device_id": "not-a-uuid"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"

    db = SessionF()
    assert db.query(DailyActivity).count() == 0
    db.close()


def test_non_v4_uuid_rejected(client):
    """A well-formed UUID that isn't version 4 (e.g. a v1 UUID) must still 422 —
    the format check is strict UUID v4, not "any UUID"."""
    c, _ = client
    v1_uuid = "3fa85f64-5717-1562-b3fc-2c963f66afa6"  # version nibble is "1"
    r = c.post("/api/activity/ping", json={"device_id": v1_uuid})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"


def test_malformed_device_id_never_touches_rate_limit_or_attempts(client, monkeypatch):
    """The format check must run BEFORE any DB work — a malformed device_id
    must never cost a rate-limit SELECT or leave an EmailActionAttempt row,
    so a flood of junk from one IP can't burn DB round trips for free."""
    c, SessionF = client

    def _boom(*args, **kwargs):
        raise AssertionError("rate limit check must not run for a malformed device_id")

    monkeypatch.setattr(activity_api, "_email_action_rate_limited", _boom)

    r = c.post("/api/activity/ping", json={"device_id": "not-a-uuid"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"

    db = SessionF()
    assert db.query(EmailActionAttempt).count() == 0
    db.close()


def test_device_id_with_trailing_newline_rejected(client):
    """`$` matches just before a trailing newline, not only end-of-string, so
    "<uuid>\\n" would otherwise pass the old regex and store a 37-char id.
    The anchor must be \\Z."""
    c, SessionF = client
    r = c.post("/api/activity/ping", json={"device_id": f"{DEVICE_ID}\n"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"

    db = SessionF()
    assert db.query(DailyActivity).count() == 0
    db.close()


def test_foreign_origin_rejected(client):
    """A foreign Origin is blocked (CSRF guard), mirroring test_bridge_api.py."""
    c, _ = client
    r = c.post("/api/activity/ping", json={"device_id": DEVICE_ID},
              headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"


def test_signed_in_user_attaches_user_id(client):
    c, SessionF = client
    reg = c.post("/api/auth/register", json={"email": "signedin@example.com", "password": "supersecret"})
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["id"]

    r = c.post("/api/activity/ping", json={"device_id": DEVICE_ID})
    assert r.status_code == 200

    db = SessionF()
    row = db.query(DailyActivity).filter_by(device_id=DEVICE_ID).one()
    assert row.user_id == user_id
    db.close()


def test_rate_limited_per_ip_after_cap(client, monkeypatch):
    """Unauthenticated write with no other guard — mirrors auth.py's register
    throttle (test_bridge_api.py's test_rate_limited_per_ip_after_cap)."""
    c, _ = client
    monkeypatch.setattr(activity_api, "_PING_MAX", 2, raising=False)
    assert c.post("/api/activity/ping", json={"device_id": "11111111-1111-4111-8111-111111111111"}).status_code == 200
    assert c.post("/api/activity/ping", json={"device_id": "22222222-2222-4222-8222-222222222222"}).status_code == 200
    r = c.post("/api/activity/ping", json={"device_id": "33333333-3333-4333-8333-333333333333"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_concurrent_duplicate_ping_is_idempotent_not_a_500(client, monkeypatch):
    """Two concurrent pings can both pass the check-then-insert's pre-check; the
    second's insert must hit the UNIQUE constraint and still resolve as a no-op
    success, never a 500 — simulated by forcing the pre-check to miss a row
    that's already committed (mirrors test_bridge_api.py's race test)."""
    c, SessionF = client
    today = datetime.now(timezone.utc).date()
    db = SessionF()
    db.add(DailyActivity(device_id=DEVICE_ID, day=today))
    db.commit()
    db.close()

    monkeypatch.setattr(activity_api, "_find_ping", lambda db, device_id, day: None, raising=False)

    r = c.post("/api/activity/ping", json={"device_id": DEVICE_ID})
    assert r.status_code == 200, r.text

    db = SessionF()
    assert db.query(DailyActivity).filter_by(device_id=DEVICE_ID).count() == 1
    db.close()
