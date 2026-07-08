"""GET /api/nrl/matches, GET /api/nrl/model/record — the read-only NRL API
(Task 6). Mirrors test_model_record_api.py's fixture style, scoped to the
sport_* tables."""
from datetime import datetime, timedelta, timezone

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
    cache.clear()  # module-level cache survives across tests otherwise
    yield TestClient(app), TestingSession
    cache.clear()
    app.dependency_overrides.clear()


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t)
    db.flush()
    return t


def test_matches_returns_rounds_with_latest_prediction(client):
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   kickoff_utc=datetime(2026, 3, 5, 9, tzinfo=timezone.utc),
                   venue="AAMI Park", home_team_id=storm.id, away_team_id=eels.id,
                   status="scheduled")
    db.add(m)
    db.flush()
    # Two predictions for the same match: only the LATER one should surface.
    older = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                            p_home=0.55, p_draw=0.01, p_away=0.44, expected_margin=2.0)
    newer = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            created_at=datetime(2026, 2, 2, tzinfo=timezone.utc),
                            p_home=0.61, p_draw=0.01, p_away=0.38, expected_margin=4.5)
    db.add_all([older, newer])
    db.commit()

    r = c.get("/api/nrl/matches", params={"season": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2026
    assert len(body["rounds"]) == 1
    round1 = body["rounds"][0]
    assert round1["round"] == 1
    assert len(round1["matches"]) == 1
    match = round1["matches"][0]
    assert match["home"] == "Storm"
    assert match["away"] == "Eels"
    assert match["venue"] == "AAMI Park"
    assert match["prediction"]["p_home"] == pytest.approx(0.61)
    assert match["prediction"]["expected_margin"] == pytest.approx(4.5)
    assert match["prediction"]["model_version"] == "nrl-elo-v0.1"


def test_matches_filters_by_round(client):
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    m1 = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                    kickoff_utc=datetime(2026, 3, 5, tzinfo=timezone.utc),
                    home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    m2 = SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                    kickoff_utc=datetime(2026, 3, 12, tzinfo=timezone.utc),
                    home_team_id=eels.id, away_team_id=storm.id, status="scheduled")
    db.add_all([m1, m2])
    db.commit()

    r = c.get("/api/nrl/matches", params={"season": 2026, "round": 2})
    assert r.status_code == 200
    body = r.json()
    assert len(body["rounds"]) == 1
    assert body["rounds"][0]["round"] == 2
    assert len(body["rounds"][0]["matches"]) == 1


def test_matches_unknown_round_404s(client):
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    m1 = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                    kickoff_utc=datetime(2026, 3, 5, tzinfo=timezone.utc),
                    home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m1)
    db.commit()

    r = c.get("/api/nrl/matches", params={"season": 2026, "round": 99})
    assert r.status_code == 404
    assert "detail" in r.json() or "error" in r.json()


def test_matches_unknown_season_404s(client):
    c, _ = client
    r = c.get("/api/nrl/matches", params={"season": 1999})
    assert r.status_code == 404


def test_matches_defaults_to_latest_season(client):
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    old = SportMatch(sport="nrl", season=2017, round=1, match_no=1,
                     kickoff_utc=datetime(2017, 3, 5, tzinfo=timezone.utc),
                     home_team_id=storm.id, away_team_id=eels.id, status="finished",
                     score_home=20, score_away=10)
    new = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                     kickoff_utc=datetime(2026, 3, 5, tzinfo=timezone.utc),
                     home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add_all([old, new])
    db.commit()

    r = c.get("/api/nrl/matches")
    assert r.status_code == 200
    assert r.json()["season"] == 2026


def test_shadow_prediction_is_visible_on_matches_endpoint(client):
    """By design (pre-launch): /api/nrl/matches IS the shadow surface — unlike
    football's public /api/matches, nothing links to /api/nrl yet, so shadow
    predictions (is_shadow=True, the default) are returned as-is rather than
    filtered out the way serializers.latest_prediction filters them for football."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   kickoff_utc=datetime(2026, 3, 5, tzinfo=timezone.utc),
                   home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m)
    db.flush()
    pred = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                           p_home=0.6, p_draw=0.01, p_away=0.39, expected_margin=3.0)
    db.add(pred)
    db.commit()
    assert pred.is_shadow is True  # default, not explicitly set

    r = c.get("/api/nrl/matches", params={"season": 2026})
    body = r.json()
    match = body["rounds"][0]["matches"][0]
    assert match["prediction"] is not None
    assert match["prediction"]["p_home"] == pytest.approx(0.6)


def test_empty_record_is_honest(client):
    c, _ = client
    r = c.get("/api/nrl/model/record")
    assert r.status_code == 200
    body = r.json()
    assert body["evaluated_matches"] == 0
    assert body["winner_accuracy"] is None
    assert body["winner_accuracy_ci95"] is None
    assert body["avg_log_loss"] is None
    assert body["avg_brier"] is None
    assert body["best_streak"] == 0
    assert body["model_version"] == "nrl-elo-v0.1"
    assert "disclaimer" in body


def test_record_aggregates_seeded_ledger(client):
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    kick = datetime(2026, 3, 5, tzinfo=timezone.utc)

    def make(day, winner_ok, brier, ll):
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=day,
                       kickoff_utc=kick + timedelta(days=day),
                       home_team_id=storm.id, away_team_id=eels.id,
                       status="finished", score_home=20, score_away=10)
        db.add(m)
        db.flush()
        p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            p_home=0.7, p_draw=0.01, p_away=0.29, expected_margin=10.0)
        db.add(p)
        db.flush()
        db.add(SportPredictionResult(
            match_id=m.id, prediction_id=p.id, model_version="nrl-elo-v0.1",
            outcome="home", winner_correct=winner_ok, prob_assigned=0.7,
            log_loss=ll, brier=brier, margin_error=2.0,
        ))

    # Kickoff-order pattern T T F T -> best streak 2.
    make(1, True, 0.1, 0.2)
    make(2, True, 0.1, 0.2)
    make(3, False, 0.5, 0.9)
    make(4, True, 0.1, 0.2)
    db.commit()

    body = c.get("/api/nrl/model/record").json()
    assert body["evaluated_matches"] == 4
    assert body["winner_accuracy"] == pytest.approx(0.75)
    assert isinstance(body["winner_accuracy_ci95"], list) and len(body["winner_accuracy_ci95"]) == 2
    lo, hi = body["winner_accuracy_ci95"]
    assert 0.0 <= lo <= hi <= 1.0
    assert body["avg_brier"] == pytest.approx((0.1 + 0.1 + 0.5 + 0.1) / 4, abs=1e-6)
    assert body["avg_log_loss"] == pytest.approx((0.2 + 0.2 + 0.9 + 0.2) / 4, abs=1e-6)
    assert body["best_streak"] == 2
    assert body["model_version"] == "nrl-elo-v0.1"
    assert body["last_updated"] is not None
