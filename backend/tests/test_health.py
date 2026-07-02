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
