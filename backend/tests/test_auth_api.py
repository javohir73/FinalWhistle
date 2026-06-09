"""First-party auth: register → me → logout, login throttle, and validation."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app

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
    yield TestClient(app, headers={"Origin": ALLOWED_ORIGIN})
    app.dependency_overrides.clear()


def test_register_sets_cookie_and_me_works(client):
    r = client.post("/api/auth/register",
                    json={"email": "Pat@Example.com", "password": "supersecret", "display_name": "Pat"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "pat@example.com"  # normalized
    assert "fw_session" in r.cookies or "fw_session" in [c.name for c in client.cookies.jar]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Pat"


def test_duplicate_email_rejected(client):
    body = {"email": "dup@example.com", "password": "supersecret"}
    assert client.post("/api/auth/register", json=body).status_code == 200
    fresh = TestClient(app, headers={"Origin": ALLOWED_ORIGIN})  # no cookie carried over
    r = fresh.post("/api/auth/register", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_weak_password_and_bad_email(client):
    assert client.post("/api/auth/register",
                       json={"email": "a@b.com", "password": "short"}).status_code == 422
    assert client.post("/api/auth/register",
                       json={"email": "notanemail", "password": "supersecret"}).status_code == 422


def test_login_logout_roundtrip(client):
    client.post("/api/auth/register", json={"email": "u@example.com", "password": "supersecret"})
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    bad = client.post("/api/auth/login", json={"email": "u@example.com", "password": "wrongpass"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"email": "u@example.com", "password": "supersecret"})
    assert good.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_login_throttled_after_failures(client):
    client.post("/api/auth/register", json={"email": "v@example.com", "password": "supersecret"})
    client.post("/api/auth/logout")
    for _ in range(5):
        assert client.post("/api/auth/login",
                           json={"email": "v@example.com", "password": "nope"}).status_code == 401
    # 6th attempt (even with the right password) is throttled.
    r = client.post("/api/auth/login", json={"email": "v@example.com", "password": "supersecret"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_foreign_origin_rejected(client):
    """A foreign Origin is blocked on state-changing auth routes (CSRF guard)."""
    r = client.post("/api/auth/register",
                    json={"email": "w@example.com", "password": "supersecret"},
                    headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"
