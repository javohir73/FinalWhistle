"""POST /api/internal/refresh-live must run the post-results chain itself when
its ingestion pass finishes a match. The external cron is a first-class path:
it must not depend on board traffic (maybe_refresh_live) to get predictions
evaluated, ratings updated, and brackets rescored after a final whistle."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app


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
    return TestClient(app)


def test_refresh_live_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        assert client.post("/api/internal/refresh-live").status_code == 401
        assert client.post("/api/internal/refresh-live",
                           headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_finish_transition_triggers_post_results_chain(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: {"updated": 2, "live": 0, "finished": 1, "newly_finished": 1},
    )
    chain_calls = []
    monkeypatch.setattr(
        "pipeline.learning_loop.run_post_results_chain",
        lambda db, mv, **kw: chain_calls.append(mv) or {"learning": {"evaluated_new": 1}},
    )
    client = _client()
    try:
        r = client.post("/api/internal/refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert chain_calls == [settings.model_version]
        assert r.json()["live"]["post_results"] == {"learning": {"evaluated_new": 1}}
    finally:
        app.dependency_overrides.clear()


def test_no_chain_when_nothing_newly_finished(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: {"updated": 1, "live": 1, "finished": 0, "newly_finished": 0},
    )
    chain_calls = []
    monkeypatch.setattr(
        "pipeline.learning_loop.run_post_results_chain",
        lambda db, mv, **kw: chain_calls.append(mv),
    )
    client = _client()
    try:
        r = client.post("/api/internal/refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert chain_calls == []
        assert "post_results" not in r.json()["live"]
    finally:
        app.dependency_overrides.clear()


def test_chain_failure_never_fails_the_response(monkeypatch):
    """A learning-chain crash must not fail the cron's request — scores are
    already committed, and the next trigger or the daily run retries."""
    monkeypatch.setattr(settings, "recompute_token", "secret")
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: {"updated": 1, "live": 0, "finished": 1, "newly_finished": 1},
    )

    def boom(db, mv, **kw):
        raise RuntimeError("simulation blew up")

    monkeypatch.setattr("pipeline.learning_loop.run_post_results_chain", boom)
    client = _client()
    try:
        r = client.post("/api/internal/refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert "post_results" not in r.json()["live"]
    finally:
        app.dependency_overrides.clear()
