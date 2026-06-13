"""GET /api/model/record — the audited AI-record endpoint (learning loop)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, PredictionResult, Team, Tournament


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
    cache.clear()  # the module-level cache survives across tests otherwise
    yield TestClient(app), TestingSession
    cache.clear()
    app.dependency_overrides.clear()


def test_empty_record_is_honest(client):
    c, _ = client
    r = c.get("/api/model/record")
    assert r.status_code == 200
    body = r.json()
    assert body["evaluated_matches"] == 0
    assert body["winner_accuracy"] is None
    assert body["exact_score_hits"] == 0
    assert "disclaimer" in body


def test_record_aggregates_match_evaluations(client):
    c, TestingSession = client
    db = TestingSession()
    mex = Team(name="Mexico", country_code="MX", confederation="CONCACAF")
    rsa = Team(name="South Africa", country_code="ZA", confederation="CAF")
    kor = Team(name="South Korea", country_code="KR", confederation="AFC")
    cze = Team(name="Czechia", country_code="CZ", confederation="UEFA")
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    db.add_all([wc, mex, rsa, kor, cze])
    db.flush()

    def make(home, away, probs, pred_score, actual, winner_ok, exact_ok, brier, ll):
        m = Match(tournament_id=wc.id, team_home_id=home.id, team_away_id=away.id,
                  stage="group", status="finished",
                  score_home=actual[0], score_away=actual[1])
        db.add(m)
        db.flush()
        p = Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                       prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                       predicted_score_home=pred_score[0], predicted_score_away=pred_score[1])
        db.add(p)
        db.flush()
        db.add(PredictionResult(
            match_id=m.id, prediction_id=p.id, model_version="poisson-elo-v0.1",
            actual_score_home=actual[0], actual_score_away=actual[1],
            outcome="home", winner_correct=winner_ok, exact_score_correct=exact_ok,
            prob_assigned=probs[0], brier=brier, log_loss=ll, goal_error=0,
        ))

    # Matchday 1, as it really happened.
    make(mex, rsa, (0.8104, 0.1258, 0.0638), (2, 0), (2, 0), True, True, 0.0558, 0.2102)
    make(kor, cze, (0.4623, 0.2512, 0.2865), (1, 0), (2, 1), True, False, 0.4339, 0.7714)
    db.commit()

    r = c.get("/api/model/record")
    body = r.json()
    assert body["evaluated_matches"] == 2
    assert body["winners_correct"] == 2
    assert body["winner_accuracy"] == 1.0
    assert body["exact_score_hits"] == 1
    assert body["avg_brier"] == pytest.approx((0.0558 + 0.4339) / 2, abs=1e-3)
    assert len(body["best_calls"]) == 2
    assert body["best_calls"][0]["label"].startswith("Mexico")
    assert body["biggest_misses"] == []  # both winners called
    assert body["last_updated"] is not None
    assert isinstance(body["calibration"], list)
