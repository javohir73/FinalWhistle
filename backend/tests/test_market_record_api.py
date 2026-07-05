from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Odds, Prediction, Team, Tournament


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client():
    TestingSession = _make_session()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    yield TestClient(app), TestingSession
    cache.clear()
    app.dependency_overrides.clear()


def test_market_record_empty_is_pending(client):
    c, _ = client
    r = c.get("/api/model/market-record")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["n_matches"] == 0
    assert body["model"] is None


def test_market_record_ready_when_benchmarkable(client):
    c, TestingSession = client
    db = TestingSession()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = Match(tournament_id=wc.id, team_home_id=home.id, team_away_id=away.id,
              stage="group", status="finished", score_home=2, score_away=0, kickoff_utc=ko)
    db.add(m); db.flush()
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)))
    db.add(Odds(match_id=m.id, bookmaker="median",
                odds_home=1.6, odds_draw=3.8, odds_away=6.0,
                implied_prob_home=0.60, implied_prob_draw=0.26, implied_prob_away=0.14,
                captured_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)))
    db.commit()

    body = c.get("/api/model/market-record").json()
    assert body["status"] == "ready"
    assert body["n_matches"] == 1
    assert body["verdict"]
