"""GET /api/internal/shadow-record — production vs shadow comparison (FR-4.6).

Token-guarded like every internal endpoint (fail-closed without a configured
token). The payload is the input to the MANUAL promotion decision (FR-4.8):
matches scored, exact hits, winner accuracy and average Brier for the
production record and the shadow record side by side.
"""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, PredictionResult, Team, Tournament

SHADOW_MV = "poisson-elo-v0.3-shadow"


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSession


def _seed_results(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home = Team(name="Mexico")
    away = Team(name="South Africa")
    db.add_all([wc, home, away])
    db.flush()

    def one(i, *, shadow, exact, winner, brier):
        m = Match(tournament_id=wc.id, stage="group", status="finished",
                  team_home_id=home.id, team_away_id=away.id,
                  score_home=2, score_away=i)
        db.add(m)
        db.flush()
        p = Prediction(match_id=m.id,
                       model_version=SHADOW_MV if shadow else "poisson-elo-v0.2",
                       prob_home_win=0.6, prob_draw=0.25, prob_away_win=0.15,
                       predicted_score_home=2, predicted_score_away=0,
                       is_shadow=shadow)
        db.add(p)
        db.flush()
        db.add(PredictionResult(
            match_id=m.id, prediction_id=p.id, model_version=p.model_version,
            actual_score_home=2, actual_score_away=i, outcome="home",
            winner_correct=winner, exact_score_correct=exact,
            prob_assigned=0.6, brier=brier, log_loss=0.5, goal_error=abs(i),
            is_shadow=shadow,
        ))

    one(0, shadow=False, exact=True, winner=True, brier=0.2)
    one(1, shadow=False, exact=False, winner=True, brier=0.4)
    one(0, shadow=True, exact=True, winner=True, brier=0.1)
    db.commit()


def test_shadow_record_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "")
    client, _ = _client()
    try:
        assert client.get("/api/internal/shadow-record").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        assert client.get("/api/internal/shadow-record").status_code == 401
        assert client.get("/api/internal/shadow-record",
                          headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_compares_production_and_shadow(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        _seed_results(TestingSession())
        r = client.get("/api/internal/shadow-record",
                       headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        body = r.json()
        prod, shad = body["production"], body["shadow"]
        assert prod["n"] == 2 and shad["n"] == 1
        assert prod["exact_hits"] == 1 and shad["exact_hits"] == 1
        assert prod["winner_acc"] == 1.0 and shad["winner_acc"] == 1.0
        assert prod["avg_brier"] == 0.3 and shad["avg_brier"] == 0.1
        assert shad["model_versions"] == [SHADOW_MV]
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_is_honest_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        body = client.get("/api/internal/shadow-record",
                          headers={"X-Recompute-Token": "secret"}).json()
        assert body["production"] == {"n": 0, "exact_hits": 0, "winner_acc": None,
                                      "avg_brier": None, "model_versions": []}
        assert body["shadow"]["n"] == 0
    finally:
        app.dependency_overrides.clear()
