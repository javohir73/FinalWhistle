from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_nrl_refresh_live_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "")
    client = _client()
    try:
        assert client.post("/api/internal/nrl-refresh-live").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_nrl_refresh_live_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        r = client.post("/api/internal/nrl-refresh-live", headers={"X-Recompute-Token": "wrong"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_nrl_refresh_live_ok_with_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        r = client.post("/api/internal/nrl-refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["live"] == {"candidates": 0, "polled": 0}
    finally:
        app.dependency_overrides.clear()


def test_nrl_refresh_live_does_not_clear_cache_when_nothing_polled(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")

    import pipeline.sports.nrl_live_poll as nrl_live_poll_module

    monkeypatch.setattr(
        nrl_live_poll_module, "poll_live_matches",
        lambda db, provider: {"candidates": 1, "polled": 0},
    )

    from app.api import internal as internal_module

    cleared = []
    monkeypatch.setattr(internal_module.cache, "clear", lambda: cleared.append(True))

    client = _client()
    try:
        r = client.post("/api/internal/nrl-refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert r.json()["live"] == {"candidates": 1, "polled": 0}
        assert cleared == []
    finally:
        app.dependency_overrides.clear()


def test_nrl_refresh_live_clears_cache_when_something_polled(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")

    import pipeline.sports.nrl_live_poll as nrl_live_poll_module

    monkeypatch.setattr(
        nrl_live_poll_module, "poll_live_matches",
        lambda db, provider: {"candidates": 1, "polled": 1},
    )

    from app.api import internal as internal_module

    cleared = []
    monkeypatch.setattr(internal_module.cache, "clear", lambda: cleared.append(True))

    client = _client()
    try:
        r = client.post("/api/internal/nrl-refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert r.json()["live"] == {"candidates": 1, "polled": 1}
        assert cleared == [True]
    finally:
        app.dependency_overrides.clear()
