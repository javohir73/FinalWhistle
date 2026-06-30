from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.config import settings


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


def test_refresh_players_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        assert client.post("/api/internal/refresh-players").status_code == 401
        assert client.post("/api/internal/refresh-players",
                           headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_refresh_players_runs_with_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    monkeypatch.setattr(settings, "live_provider", "api_football")
    monkeypatch.setattr(settings, "api_football_api_key", "k")
    import app.api.internal as internal_mod
    monkeypatch.setattr(
        internal_mod, "_run_refresh_players",
        lambda db, key, league: {"teams_linked": 2, "squads_ingested": 2, "players_refreshed": 10},
    )
    client = _client()
    try:
        r = client.post("/api/internal/refresh-players", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert r.json()["players_refreshed"] == 10
    finally:
        app.dependency_overrides.clear()
