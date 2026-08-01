"""Tests for GET /api/tournaments/active (league pivot D6)."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Team, Tournament
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


def test_ucl_qualifier_does_not_advertise_a_bracket():
    def seed(db):
        tournament = Tournament(
            name="UEFA Champions League 2026-27",
            year=2026,
            host_countries="",
            home_advantage_mode="home",
        )
        home = Team(name="Mjallby AIF", is_host=False)
        away = Team(name="Slovan Bratislava", is_host=False)
        db.add_all([tournament, home, away])
        db.flush()
        db.add(
            Match(
                tournament_id=tournament.id,
                stage="qualifying",
                match_no=None,
                team_home_id=home.id,
                team_away_id=away.id,
                kickoff_utc=datetime(2026, 8, 5, tzinfo=timezone.utc),
                status="scheduled",
                is_neutral=False,
            )
        )
        db.commit()

    client = _make_client(seed)
    scoped = client.get("/api/tournaments/ucl")
    assert scoped.status_code == 200
    assert scoped.json()["format"] == "league"
    assert scoped.json()["has_brackets"] is False

    active = client.get("/api/tournaments/active")
    assert active.status_code == 200
    assert active.json()["name"] == "UEFA Champions League 2026-27"
    assert active.json()["has_brackets"] is False
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


def test_active_cache_entry_uses_a_bounded_short_ttl():
    """Opus review of PR #171, item 2: this key's staleness must be bounded
    well under the ~600s default (the pipeline writer runs in a separate
    process, so a short TTL — not in-process invalidation — is what actually
    keeps a WC26 -> EPL cutover from serving the stale answer for a full
    cache lifetime)."""
    import time

    def seed(db):
        load_structure(db)

    client = _make_client(seed)
    r = client.get("/api/tournaments/active")
    assert r.status_code == 200

    expires_at, _ = cache._store["tournaments:active"]
    assert expires_at - time.time() <= 65  # bounded short, not the ~600s default
    app.dependency_overrides.clear()
    cache.clear()
