"""GET /api/nrl/origin/series and /origin/record — mirrors test_sports_api.py's
fixture style, scoped to sport="origin"."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam


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


def _seed_series(db, season, results):
    """results: list of (home_name, away_name, sh, sa, status, venue)."""
    teams = {}
    for name in ("NSW Blues", "QLD Maroons"):
        t = SportTeam(sport="origin", name=name)
        db.add(t)
        db.flush()
        teams[name] = t
    matches = []
    for i, (home, away, sh, sa, status, venue) in enumerate(results, start=1):
        m = SportMatch(sport="origin", season=season, round=i, match_no=i,
                       kickoff_utc=datetime(season, 5, 20 + i * 2, 10, tzinfo=timezone.utc),
                       venue=venue, home_team_id=teams[home].id,
                       away_team_id=teams[away].id,
                       score_home=sh, score_away=sa, status=status)
        db.add(m)
        db.flush()
        matches.append(m)
    db.commit()
    return teams, matches


def test_series_404_when_no_origin_data(client):
    c, _ = client
    r = c.get("/api/nrl/origin/series")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "no_origin_data"


def test_finished_series_score_winner_and_no_odds(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_series(db, 2026, [
        ("NSW Blues", "QLD Maroons", 22, 20, "finished", "Accor Stadium"),
        ("NSW Blues", "QLD Maroons", 24, 44, "finished", "Melbourne Cricket Ground"),
        ("QLD Maroons", "NSW Blues", 12, 30, "finished", "Suncorp Stadium"),
    ])
    r = c.get("/api/nrl/origin/series", params={"season": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2026 and body["seasons"] == [2026]
    assert body["series"] == {"blues_wins": 2, "maroons_wins": 1, "drawn_games": 0,
                              "winner": "NSW Blues", "odds": None}
    assert body["games"][1]["neutral"] is True   # MCG
    assert body["games"][0]["neutral"] is False


def test_live_series_has_odds_mapped_to_blues_orientation(client):
    c, TestingSession = client
    db = TestingSession()
    teams, matches = _seed_series(db, 2027, [
        ("QLD Maroons", "NSW Blues", 20, 10, "finished", "Suncorp Stadium"),
        ("NSW Blues", "QLD Maroons", None, None, "scheduled", "Accor Stadium"),
        ("QLD Maroons", "NSW Blues", None, None, "scheduled", "Suncorp Stadium"),
    ])
    for m, (ph, pd, pa) in zip(matches[1:], [(0.6, 0.02, 0.38), (0.38, 0.02, 0.6)]):
        db.add(SportPrediction(match_id=m.id, model_version="origin-elo-v0.1",
                               created_at=datetime(2027, 5, 1, tzinfo=timezone.utc),
                               p_home=ph, p_draw=pd, p_away=pa, expected_margin=3.0))
    db.commit()

    body = c.get("/api/nrl/origin/series", params={"season": 2027}).json()
    s = body["series"]
    assert s["blues_wins"] == 0 and s["maroons_wins"] == 1 and s["winner"] is None
    odds = s["odds"]
    assert odds is not None
    # Game 2: blues are HOME (p_blues=0.6); game 3: blues are AWAY (p_blues=0.6).
    # Maroons lead 1-0, so maroons odds must exceed blues odds overall.
    assert odds["maroons"] > odds["blues"]
    assert odds["blues"] + odds["maroons"] + odds["drawn"] == pytest.approx(1.0, abs=1e-6)


def test_series_odds_null_when_a_scheduled_game_lacks_prediction(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_series(db, 2027, [
        ("QLD Maroons", "NSW Blues", None, None, "scheduled", "Suncorp Stadium"),
        ("NSW Blues", "QLD Maroons", None, None, "scheduled", "Accor Stadium"),
        ("QLD Maroons", "NSW Blues", None, None, "scheduled", "Suncorp Stadium"),
    ])
    body = c.get("/api/nrl/origin/series", params={"season": 2027}).json()
    assert body["series"]["odds"] is None


def test_drawn_series_reports_drawn_winner(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_series(db, 1999, [
        ("QLD Maroons", "NSW Blues", 9, 8, "finished", None),
        ("NSW Blues", "QLD Maroons", 10, 10, "finished", None),
        ("QLD Maroons", "NSW Blues", 8, 20, "finished", None),
    ])
    body = c.get("/api/nrl/origin/series", params={"season": 1999}).json()
    assert body["series"] == {"blues_wins": 1, "maroons_wins": 1, "drawn_games": 1,
                              "winner": "drawn", "odds": None}


def test_record_has_backtest_and_empty_live_segments(client):
    c, _ = client
    r = c.get("/api/nrl/origin/record")
    assert r.status_code == 200
    body = r.json()
    # backtest artifact is committed in-repo (Task 4), so it must load.
    assert body["backtest"] is not None
    assert body["backtest"]["n"] > 100
    assert set(body["backtest"]) >= {"model_version", "span", "n", "winner_accuracy",
                                     "avg_log_loss", "avg_brier", "home_baseline_accuracy"}
    assert body["live"]["evaluated_matches"] == 0
    assert body["live"]["winner_accuracy"] is None
    assert body["model_version"] == "origin-elo-v0.1"


def test_nrl_model_record_unchanged_by_refactor(client):
    c, _ = client
    r = c.get("/api/nrl/model/record")
    assert r.status_code == 200
    assert set(r.json()) == {"evaluated_matches", "winner_accuracy", "winner_accuracy_ci95",
                             "avg_log_loss", "avg_brier", "best_streak", "model_version",
                             "last_updated", "disclaimer"}
