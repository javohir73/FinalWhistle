"""GET /api/nrl/matches/{id}/stats — Wave 2 contract endpoint."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import NrlMatchStat, NrlTryEvent, SportMatch, SportTeam


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _seed(SessionFactory) -> int:
    db = SessionFactory()
    home = SportTeam(sport="nrl", name="Knights")
    away = SportTeam(sport="nrl", name="Cowboys")
    db.add_all([home, away])
    db.flush()
    match = SportMatch(
        sport="nrl", season=2025, round=1, match_no=1,
        kickoff_utc=datetime(2025, 3, 6, 9, 0, tzinfo=timezone.utc),
        venue="McDonald Jones Stadium",
        home_team_id=home.id, away_team_id=away.id,
        score_home=28, score_away=18, status="finished",
    )
    db.add(match)
    db.flush()
    db.add_all([
        NrlMatchStat(match_id=match.id, team="Knights", tries=5, conversions=4,
                     penalties_conceded=6, errors=8, set_restarts=4,
                     run_metres=1650, line_breaks=6, tackles=310,
                     tackle_efficiency=91.3),
        NrlMatchStat(match_id=match.id, team="Cowboys", tries=3, conversions=3,
                     penalties_conceded=8, errors=11, set_restarts=6,
                     run_metres=1432, line_breaks=3, tackles=345,
                     tackle_efficiency=88.7),
        NrlTryEvent(match_id=match.id, team="Cowboys", player="S. Drinkwater",
                    minute=23, score_home=6, score_away=6),
        NrlTryEvent(match_id=match.id, team="Knights", player="K. Ponga",
                    minute=7, score_home=6, score_away=0),
    ])
    match_id = match.id
    db.commit()
    db.close()
    return match_id


def test_stats_returns_contract_shape(client):
    tc, SessionFactory = client
    match_id = _seed(SessionFactory)
    res = tc.get(f"/api/nrl/matches/{match_id}/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["home"] == {
        "tries": 5, "conversions": 4, "penalties_conceded": 6, "errors": 8,
        "set_restarts": 4, "run_metres": 1650, "line_breaks": 6,
        "tackles": 310, "tackle_efficiency": 91.3,
    }
    assert body["away"]["tries"] == 3
    # try_timeline ordered by minute regardless of insert order
    assert [e["minute"] for e in body["try_timeline"]] == [7, 23]
    assert body["try_timeline"][0] == {
        "minute": 7, "team": "Knights", "player": "K. Ponga",
        "score_home": 6, "score_away": 0,
    }


def test_stats_404_when_match_missing(client):
    tc, _ = client
    res = tc.get("/api/nrl/matches/99999/stats")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "match_not_found"


def test_stats_404_when_no_stats_ingested(client):
    tc, SessionFactory = client
    db = SessionFactory()
    match = SportMatch(sport="nrl", season=2025, round=1, match_no=9,
                       status="finished", score_home=10, score_away=8)
    db.add(match)
    db.commit()
    match_id = match.id
    db.close()
    res = tc.get(f"/api/nrl/matches/{match_id}/stats")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "stats_not_available"
