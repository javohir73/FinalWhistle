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


from app.api.model_record import wilson_ci95


def test_wilson_ci95_known_values():
    lo, hi = wilson_ci95(8, 10)          # 80% of 10
    assert lo == pytest.approx(0.490, abs=0.01)
    assert hi == pytest.approx(0.943, abs=0.01)
    assert wilson_ci95(0, 0) is None      # empty -> None
    lo0, _ = wilson_ci95(0, 20)           # 0 successes -> lower bound pinned at 0
    assert lo0 == 0.0
    lo_all, hi_all = wilson_ci95(20, 20)  # all correct
    assert hi_all == pytest.approx(1.0)   # upper bound is exactly 1.0 at a 100% rate
    assert lo_all < 1.0                   # but Wilson keeps a real lower bound (not a degenerate [1, 1])


def test_record_includes_confidence_intervals(client):
    c, TestingSession = client
    db = TestingSession()
    mex = Team(name="Mexico", country_code="MX", confederation="CONCACAF")
    rsa = Team(name="South Africa", country_code="ZA", confederation="CAF")
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    db.add_all([wc, mex, rsa])
    db.flush()
    m = Match(tournament_id=wc.id, team_home_id=mex.id, team_away_id=rsa.id,
              stage="group", status="finished", score_home=2, score_away=0)
    db.add(m); db.flush()
    p = Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                   prob_home_win=0.81, prob_draw=0.12, prob_away_win=0.07,
                   predicted_score_home=2, predicted_score_away=0)
    db.add(p); db.flush()
    db.add(PredictionResult(
        match_id=m.id, prediction_id=p.id, model_version="poisson-elo-v0.1",
        actual_score_home=2, actual_score_away=0, outcome="home",
        winner_correct=True, exact_score_correct=True,
        prob_assigned=0.81, brier=0.05, log_loss=0.21, goal_error=0,
    ))
    db.commit()

    body = c.get("/api/model/record").json()
    assert body["exact_score_rate"] == pytest.approx(1.0)
    assert isinstance(body["winner_accuracy_ci95"], list) and len(body["winner_accuracy_ci95"]) == 2
    lo, hi = body["winner_accuracy_ci95"]
    assert 0.0 <= lo <= hi <= 1.0
    assert isinstance(body["exact_score_ci95"], list)


def test_empty_record_ci_fields_are_null(client):
    c, _ = client
    body = c.get("/api/model/record").json()
    assert body["evaluated_matches"] == 0
    assert body["winner_accuracy_ci95"] is None
    assert body["exact_score_rate"] is None
    assert body["exact_score_ci95"] is None
