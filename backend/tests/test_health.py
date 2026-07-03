"""Tests for the health endpoint (task 1.10)."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app

client = TestClient(app)


def test_health_returns_200_and_payload():
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["app"] == "FinalWhistle"
    assert "model_version" in body


def _client_with_db():
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


def test_health_reports_learning_chain_heartbeat():
    """Silent chain deaths are invisible in responses by design — /api/health
    must surface the last attempt/success/error and whether work is owed."""
    from app.models import Match

    c, session_factory = _client_with_db()
    try:
        chain = c.get("/api/health").json()["learning_chain"]
        assert chain["pending"] is False  # empty DB: nothing owed
        assert chain["last_success_at"] is None

        # A finished match no chain has covered => pending flips true.
        s = session_factory()
        s.add(Match(tournament_id=1, stage="R32", status="finished",
                    score_home=1, score_away=0, team_home_id=1, team_away_id=2))
        s.commit()

        chain = c.get("/api/health").json()["learning_chain"]
        assert chain["pending"] is True

        # A completed chain covers it and stamps success.
        from app.chain_status import record_success
        record_success(s, covered_finished=1, trigger="test")
        s.close()

        chain = c.get("/api/health").json()["learning_chain"]
        assert chain["pending"] is False
        assert chain["last_success_at"] is not None
        assert chain["last_trigger"] == "test"
    finally:
        app.dependency_overrides.clear()


def test_health_reports_prediction_coverage():
    """FR-1.3: a scheduled match with teams, kicking off within 48h, and no
    frozen prediction row must surface as prediction_coverage.missing so
    external monitors can alert before it becomes a guaranteed zero."""
    from datetime import datetime, timedelta, timezone

    from app.models import Match, Prediction

    c, session_factory = _client_with_db()
    try:
        cov = c.get("/api/health").json()["prediction_coverage"]
        assert cov["missing"] == 0  # empty DB: nothing due

        s = session_factory()
        m = Match(tournament_id=1, stage="R32", status="scheduled",
                  team_home_id=1, team_away_id=2,
                  kickoff_utc=datetime.now(timezone.utc) + timedelta(hours=12))
        s.add(m)
        s.commit()

        cov = c.get("/api/health").json()["prediction_coverage"]
        assert cov["missing"] == 1

        s.add(Prediction(match_id=m.id, model_version="poisson-elo-test",
                         prob_home_win=0.5, prob_draw=0.3, prob_away_win=0.2))
        s.commit()
        s.close()

        cov = c.get("/api/health").json()["prediction_coverage"]
        assert cov["missing"] == 0
    finally:
        app.dependency_overrides.clear()


def test_health_reports_shadow_progress_without_accuracy():
    """Task 4.9: monitors need to SEE the shadow sample growing without the
    comparison numbers going public (those stay behind /api/internal/shadow-record's
    token per FR-4.6). Health exposes the pair count only."""
    from app.models import PredictionResult

    c, session_factory = _client_with_db()
    try:
        sp = c.get("/api/health").json()["shadow_progress"]
        assert sp["pairs"] == 0

        s = session_factory()
        s.add(PredictionResult(match_id=1, prediction_id=1, model_version="poisson-elo-v0.2",
                               actual_score_home=1, actual_score_away=0, outcome="home",
                               winner_correct=True, exact_score_correct=False,
                               prob_assigned=0.5, brier=0.5, log_loss=0.7, goal_error=1,
                               is_shadow=False))
        s.add(PredictionResult(match_id=1, prediction_id=2, model_version="poisson-elo-v0.3-shadow",
                               actual_score_home=1, actual_score_away=0, outcome="home",
                               winner_correct=True, exact_score_correct=False,
                               prob_assigned=0.5, brier=0.5, log_loss=0.7, goal_error=1,
                               is_shadow=True))
        s.commit(); s.close()

        sp = c.get("/api/health").json()["shadow_progress"]
        assert sp["pairs"] == 1
        assert "exact_hits" not in sp and "winner_acc" not in sp  # numbers stay internal
    finally:
        app.dependency_overrides.clear()


def test_live_ping_is_tiny_and_triggers_refresh(monkeypatch):
    """The every-minute cron hits this instead of the large /matches/upcoming
    payload: it must return a minuscule body (so response-size-limited cron
    services never fail on it) while scheduling the same live refresh."""
    calls = []
    monkeypatch.setattr("app.main.maybe_refresh_live", lambda *a, **k: calls.append(1))

    r = client.get("/api/live/ping")

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(r.content) < 40  # a handful of bytes — never "output too large"
    # FastAPI runs the scheduled BackgroundTask after the response is sent;
    # TestClient executes it synchronously, so the refresh was triggered.
    assert calls == [1]
