"""POST /api/bridge/notify — WC26 retention bridge email capture.

Mirrors test_auth_api.py's client fixture (Origin header, in-memory SQLite)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import BridgeSignup

ALLOWED_ORIGIN = "http://localhost:3000"


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


def test_valid_email_stores_row(client):
    c, SessionF = client
    r = c.post("/api/bridge/notify", json={"email": "Fan@Example.com"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    db = SessionF()
    rows = db.query(BridgeSignup).all()
    assert len(rows) == 1
    assert rows[0].email == "fan@example.com"  # normalized, like auth
    assert rows[0].source == "wc26_final_bridge"
    assert rows[0].user_id is None
    db.close()


def test_duplicate_email_and_source_is_idempotent(client):
    c, SessionF = client
    body = {"email": "dup@example.com", "source": "wc26_final_bridge"}
    first = c.post("/api/bridge/notify", json=body)
    second = c.post("/api/bridge/notify", json=body)
    assert first.status_code == 200 and second.status_code == 200

    db = SessionF()
    assert db.query(BridgeSignup).filter_by(email="dup@example.com").count() == 1
    db.close()


def test_invalid_email_rejected(client):
    c, _ = client
    r = c.post("/api/bridge/notify", json={"email": "not-an-email"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_email"


def test_disallowed_source_rejected(client):
    c, SessionF = client
    r = c.post("/api/bridge/notify", json={"email": "x@example.com", "source": "some_other_funnel"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_source"

    db = SessionF()
    assert db.query(BridgeSignup).count() == 0
    db.close()


def test_foreign_origin_rejected(client):
    """A foreign Origin is blocked (CSRF guard), mirroring test_auth_api.py."""
    c, _ = client
    r = c.post("/api/bridge/notify", json={"email": "w@example.com"},
              headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"


def test_signed_in_user_attaches_user_id(client):
    c, SessionF = client
    reg = c.post("/api/auth/register", json={"email": "signedin@example.com", "password": "supersecret"})
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["id"]

    r = c.post("/api/bridge/notify", json={"email": "signedin@example.com"})
    assert r.status_code == 200

    db = SessionF()
    row = db.query(BridgeSignup).filter_by(email="signedin@example.com").one()
    assert row.user_id == user_id
    db.close()
