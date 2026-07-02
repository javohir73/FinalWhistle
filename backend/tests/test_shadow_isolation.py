"""Shadow-prediction isolation (exact-score program FR-4.5).

Shadow rows (model_version poisson-elo-v0.3-shadow, is_shadow=True) exist ONLY
for the internal production-vs-shadow comparison. One test per mandated
exclusion: serving endpoints, bracket scoring, the public model record, and
the prediction-coverage detector must all behave as if shadow rows do not
exist. (The frozen-prediction exclusion at evaluation time is covered in
pipeline/shadow_predictions_test.py next to the learning loop.)
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import (
    AppUser,
    Bracket,
    BracketGroupPick,
    Match,
    Prediction,
    PredictionResult,
    Team,
    Tournament,
)

SHADOW_MV = "poisson-elo-v0.3-shadow"


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


def _seed_match(db) -> Match:
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home = Team(name="Mexico")
    away = Team(name="South Africa")
    db.add_all([wc, home, away])
    db.flush()
    m = Match(tournament_id=wc.id, stage="group", status="scheduled",
              team_home_id=home.id, team_away_id=away.id,
              kickoff_utc=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(m)
    db.flush()
    return m


def _prediction(m: Match, *, shadow: bool, created_at: datetime,
                probs=(0.5, 0.3, 0.2), score=(1, 0)) -> Prediction:
    return Prediction(
        match_id=m.id,
        model_version=SHADOW_MV if shadow else "poisson-elo-v0.2",
        created_at=created_at,
        prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
        predicted_score_home=score[0], predicted_score_away=score[1],
        is_shadow=shadow,
    )


def test_serving_endpoint_ignores_shadow_rows(client):
    """Exclusion 1 (serving): even a NEWER shadow row must never be served —
    neither as the current prediction nor in the trend-chart history."""
    c, TestingSession = client
    db = TestingSession()
    m = _seed_match(db)
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    db.add(_prediction(m, shadow=False, created_at=t0, probs=(0.5, 0.3, 0.2)))
    db.add(_prediction(m, shadow=True, created_at=t0 + timedelta(minutes=5),
                       probs=(0.9, 0.05, 0.05), score=(3, 0)))
    db.commit()

    r = c.get(f"/api/predictions/{m.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["current"]["model_version"] == "poisson-elo-v0.2"
    assert body["current"]["probabilities"]["home_win"] == 0.5
    assert [h["model_version"] for h in body["history"]] == ["poisson-elo-v0.2"]


def test_model_record_ignores_shadow_results(client):
    """Exclusion 2 (public record): shadow PredictionResult rows must not move
    the audited /api/model/record numbers."""
    c, TestingSession = client
    db = TestingSession()
    m = _seed_match(db)
    m.status = "finished"
    m.score_home, m.score_away = 1, 0
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    prod = _prediction(m, shadow=False, created_at=t0)
    shad = _prediction(m, shadow=True, created_at=t0, probs=(0.9, 0.05, 0.05), score=(3, 0))
    db.add_all([prod, shad])
    db.flush()

    def result(pred, *, shadow, exact):
        return PredictionResult(
            match_id=m.id, prediction_id=pred.id, model_version=pred.model_version,
            actual_score_home=1, actual_score_away=0, outcome="home",
            winner_correct=True, exact_score_correct=exact,
            prob_assigned=pred.prob_home_win, brier=0.1, log_loss=0.2,
            goal_error=0, is_shadow=shadow,
        )

    db.add(result(prod, shadow=False, exact=True))
    db.add(result(shad, shadow=True, exact=False))  # a shadow miss must not dilute
    db.commit()

    body = c.get("/api/model/record").json()
    assert body["evaluated_matches"] == 1
    assert body["exact_score_hits"] == 1
    assert body["winner_accuracy"] == 1.0


def test_bracket_scoring_ignores_shadow_rows(client):
    """Exclusion 3 (bracket scoring): points come from real results only —
    identical scores with and without shadow rows for the same match."""
    from app.scoring import recompute_scores

    _, TestingSession = client
    db = TestingSession()
    m = _seed_match(db)
    m.status = "finished"
    m.score_home, m.score_away = 2, 0
    user = AppUser(email="u@example.com", password_hash="x")
    db.add(user)
    db.flush()
    bracket = Bracket(user_id=user.id)
    db.add(bracket)
    db.flush()
    db.add(BracketGroupPick(bracket_id=bracket.id, match_id=m.id, pick="home"))
    db.commit()

    recompute_scores(db)
    baseline = bracket.score.total_points
    assert baseline == 3  # correct group pick

    # A shadow row calling the match for AWAY must change nothing.
    db.add(_prediction(m, shadow=True, created_at=datetime.now(timezone.utc),
                       probs=(0.1, 0.1, 0.8), score=(0, 2)))
    db.commit()
    recompute_scores(db)
    assert bracket.score.total_points == baseline


def test_prediction_coverage_ignores_shadow_rows(client):
    """Exclusion 4 (coverage detector): a match holding ONLY a shadow row has
    no frozen production prediction — it must still be flagged missing."""
    from app.prediction_coverage import matches_missing_prediction

    _, TestingSession = client
    db = TestingSession()
    m = _seed_match(db)
    db.add(_prediction(m, shadow=True, created_at=datetime.now(timezone.utc)))
    db.commit()

    missing = matches_missing_prediction(db)
    assert [x.id for x in missing] == [m.id]

    db.add(_prediction(m, shadow=False, created_at=datetime.now(timezone.utc)))
    db.commit()
    assert matches_missing_prediction(db) == []
