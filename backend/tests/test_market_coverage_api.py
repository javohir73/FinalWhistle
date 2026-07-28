from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import VenueMarket


def client_and_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    def override_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), sessions


def test_coverage_api_fails_closed_and_is_no_store(monkeypatch):
    client, _sessions = client_and_session()
    try:
        monkeypatch.setattr(settings, "recompute_token", "")
        response = client.get("/api/internal/market-coverage")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


def test_coverage_api_is_token_guarded_and_filterable(monkeypatch):
    client, sessions = client_and_session()
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    with sessions() as db:
        db.add(VenueMarket(venue="kalshi", venue_key="K1", sport="football", market_type="match_winner", raw_title="A v B", mapping_status="unmapped", status="open", first_seen=now, last_seen=now))
        db.commit()
    try:
        monkeypatch.setattr(settings, "recompute_token", "secret")
        assert client.get("/api/internal/market-coverage", headers={"X-Recompute-Token": "wrong"}).status_code == 401
        response = client.get("/api/internal/market-coverage?venue=kalshi&status=unmapped", headers={"X-Recompute-Token": "secret"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["registry"]["markets"] == 1
        invalid = client.get("/api/internal/market-coverage?status=guess", headers={"X-Recompute-Token": "secret"})
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
