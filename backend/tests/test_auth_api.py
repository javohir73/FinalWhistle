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
    assert "password_hash" not in r.json()  # never leak the hash
    assert "fw_session" in r.cookies or "fw_session" in [c.name for c in client.cookies.jar]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Pat"
    assert "password_hash" not in me.json()


def test_session_cookie_attributes(client):
    """The session cookie must stay HttpOnly + SameSite=Lax + Path=/ with a
    30-day Max-Age — the contract the same-origin /backend-api proxy and the
    installed-PWA reload flow both depend on (FR 4.6)."""
    r = client.post("/api/auth/register",
                    json={"email": "cookie@example.com", "password": "supersecret"})
    set_cookie = r.headers.get("set-cookie", "")
    assert set_cookie.startswith("fw_session=")
    lowered = set_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "max-age=2592000" in lowered  # 30 days
    assert "domain=" not in lowered  # host-only: belongs to the frontend origin


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


def test_auth_responses_are_not_shared_cached(client):
    """User-specific auth/bracket responses must be no-store (never CDN-cached),
    while public reads stay cacheable."""
    me = client.get("/api/auth/me")  # 401, but the header is what matters
    assert me.headers.get("cache-control") == "no-store"
    bm = client.get("/api/brackets/me")  # 401 without a session
    assert bm.headers.get("cache-control") == "no-store"
    groups = client.get("/api/groups")
    assert "public" in (groups.headers.get("cache-control") or "")


def test_internal_stats_token_guarded(client):
    from app.config import settings

    assert client.get("/api/internal/stats").status_code == 503  # no token configured
    settings.recompute_token = "testtoken"
    try:
        assert client.get("/api/internal/stats").status_code == 401  # missing token
        ok = client.get("/api/internal/stats", headers={"X-Recompute-Token": "testtoken"})
        assert ok.status_code == 200
        body = ok.json()
        for k in ("users", "signups_last_24h", "brackets", "public_brackets",
                  "latest_signup", "by_country", "by_city"):
            assert k in body
        assert body["users"] == 0
        # Register with Vercel geo headers → captured + aggregated in stats.
        client.post(
            "/api/auth/register",
            json={"email": "s@example.com", "password": "supersecret"},
            headers={"x-vercel-ip-country": "us", "x-vercel-ip-city": "San%20Francisco"},
        )
        after = client.get("/api/internal/stats", headers={"X-Recompute-Token": "testtoken"}).json()
        assert after["users"] == 1 and after["signups_last_24h"] == 1
        assert {"country": "US", "count": 1} in after["by_country"]
        assert after["by_city"][0]["city"] == "San Francisco"
    finally:
        settings.recompute_token = ""


def test_foreign_origin_rejected(client):
    """A foreign Origin is blocked on state-changing auth routes (CSRF guard)."""
    r = client.post("/api/auth/register",
                    json={"email": "w@example.com", "password": "supersecret"},
                    headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"
