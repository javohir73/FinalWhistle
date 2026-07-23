"""Regression: /api/model/record and /api/model/market-record never mix the
WC26/international ledger with the EPL ("poisson-elo-club-v0.1") one, even
though both write into the same predictions/prediction_results/odds tables
(league pivot, deliverable 7)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Odds, Prediction, PredictionResult, Team, Tournament


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def _wc26_match(db, wc):
    mex, rsa = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([mex, rsa])
    db.flush()
    m = Match(tournament_id=wc.id, team_home_id=mex.id, team_away_id=rsa.id,
             stage="group", status="finished", score_home=2, score_away=0,
             kickoff_utc=datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc))
    db.add(m)
    db.flush()
    p = Prediction(match_id=m.id, model_version="poisson-elo-v0.5",
                   prob_home_win=0.81, prob_draw=0.13, prob_away_win=0.06,
                   predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                   created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc))
    db.add(p)
    db.flush()
    db.add(PredictionResult(
        match_id=m.id, prediction_id=p.id, model_version="poisson-elo-v0.5",
        actual_score_home=2, actual_score_away=0, outcome="home",
        winner_correct=True, exact_score_correct=True,
        prob_assigned=0.81, brier=0.05, log_loss=0.21, goal_error=0,
    ))
    db.add(Odds(match_id=m.id, bookmaker="median",
               odds_home=1.6, odds_draw=3.8, odds_away=6.0,
               implied_prob_home=0.60, implied_prob_draw=0.26, implied_prob_away=0.14,
               captured_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)))
    return m


def _epl_match(db, epl):
    ars, che = Team(name="Arsenal"), Team(name="Chelsea")
    db.add_all([ars, che])
    db.flush()
    m = Match(tournament_id=epl.id, team_home_id=ars.id, team_away_id=che.id,
             stage="group", status="finished", score_home=3, score_away=3,
             kickoff_utc=datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc))
    db.add(m)
    db.flush()
    # Deliberately a WRONG, over-confident call so it would show up as the
    # worst miss / drag down accuracy if it leaked into the WC26 aggregate.
    p = Prediction(match_id=m.id, model_version="poisson-elo-club-v0.1",
                   prob_home_win=0.95, prob_draw=0.03, prob_away_win=0.02,
                   predicted_score_home=3, predicted_score_away=0, is_shadow=False,
                   created_at=datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc))
    db.add(p)
    db.flush()
    db.add(PredictionResult(
        match_id=m.id, prediction_id=p.id, model_version="poisson-elo-club-v0.1",
        actual_score_home=3, actual_score_away=3, outcome="draw",
        winner_correct=False, exact_score_correct=False,
        prob_assigned=0.03, brier=1.79, log_loss=3.51, goal_error=3,
    ))
    db.add(Odds(match_id=m.id, bookmaker="median",
               odds_home=1.3, odds_draw=5.0, odds_away=9.0,
               implied_prob_home=0.75, implied_prob_draw=0.16, implied_prob_away=0.09,
               captured_at=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)))
    return m


def test_model_record_excludes_epl_rows(client):
    c, TestingSession = client
    db = TestingSession()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    epl = Tournament(name="Premier League 2026-27", year=2026, home_advantage_mode="home")
    db.add_all([wc, epl])
    db.flush()
    _wc26_match(db, wc)
    _epl_match(db, epl)
    db.commit()

    body = c.get("/api/model/record").json()
    assert body["evaluated_matches"] == 1  # only the WC26 row
    assert body["winners_correct"] == 1
    assert body["winner_accuracy"] == 1.0
    assert body["biggest_misses"] == []  # the EPL miss never enters this ledger


def test_market_record_excludes_epl_rows(client):
    c, TestingSession = client
    db = TestingSession()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    epl = Tournament(name="Premier League 2026-27", year=2026, home_advantage_mode="home")
    db.add_all([wc, epl])
    db.flush()
    _wc26_match(db, wc)
    _epl_match(db, epl)
    db.commit()

    body = c.get("/api/model/market-record").json()
    assert body["status"] == "ready"
    assert body["n_matches"] == 1  # only the WC26 match was benchmarked
