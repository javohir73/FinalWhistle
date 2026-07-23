"""Tests for GET /api/tournaments/active (league pivot D6)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match
from pipeline.ingest import league_structure as ls_mod
from pipeline.ingest.league_structure import load_league_structure
from pipeline.ingest.wc26_structure import load_structure


def _make_client(seed_fn):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    seed = TestingSession()
    seed_fn(seed)
    seed.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    client = TestClient(app)
    return client


def _fixture(fid, home, away, kickoff="2026-08-21T19:00:00+00:00", status="NS"):
    return {
        "fixture": {"id": fid, "date": kickoff, "status": {"short": status}},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": None, "away": None},
    }


def test_wc26_only_db_resolves_to_wc26_knockout(monkeypatch):
    def seed(db):
        load_structure(db)

    client = _make_client(seed)
    r = client.get("/api/tournaments/active")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "FIFA World Cup 2026"
    assert data["year"] == 2026
    assert data["format"] == "knockout"
    assert data["has_brackets"] is True
    app.dependency_overrides.clear()
    cache.clear()


def test_epl_with_scheduled_matches_resolves_to_league(monkeypatch):
    def seed(db):
        load_structure(db)  # WC26 finished/archived — no scheduled matches left
        for m in db.query(Match).all():
            m.status = "finished"
            m.score_home, m.score_away = 1, 0
        db.commit()
        monkeypatch.setattr(
            ls_mod, "fetch_fixtures",
            lambda *a, **k: [_fixture(1, "Arsenal", "Chelsea")],
        )
        load_league_structure(db, api_key="x")

    client = _make_client(seed)
    r = client.get("/api/tournaments/active")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Premier League 2026-27"
    assert data["format"] == "league"
    assert data["has_brackets"] is False
    app.dependency_overrides.clear()
    cache.clear()


def test_falls_back_to_most_recent_when_nothing_scheduled(monkeypatch):
    def seed(db):
        load_structure(db)
        from app.models import Match

        for m in db.query(Match).all():
            m.status = "finished"
            m.score_home, m.score_away = 1, 0
        db.commit()

    client = _make_client(seed)
    r = client.get("/api/tournaments/active")
    assert r.status_code == 200
    assert r.json()["name"] == "FIFA World Cup 2026"
    app.dependency_overrides.clear()
    cache.clear()


def test_empty_db_returns_404():
    client = _make_client(lambda db: None)
    r = client.get("/api/tournaments/active")
    assert r.status_code == 404
    app.dependency_overrides.clear()
    cache.clear()
