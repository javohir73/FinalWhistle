"""Opportunistic live-score refresh: traffic on the matches board keeps scores
fresh during match windows (no external every-minute cron), capped at one
upstream call per interval, and free of API calls outside live windows."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.live_refresh as live_refresh
from app.cache import cache
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Match


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    """Live mode on by default for these tests; rate-limit window reset."""
    live_refresh._last_attempt = 0.0
    cache.clear()
    monkeypatch.setattr(settings, "live_mode_enabled", True)
    monkeypatch.setattr(settings, "football_data_api_key", "test-key")


def _factory_with(*matches):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)
    s = TestingSession()
    s.add_all(matches)
    s.commit()
    s.close()
    return TestingSession


def test_skips_entirely_when_live_mode_is_off(monkeypatch):
    monkeypatch.setattr(settings, "live_mode_enabled", False)
    calls = []
    monkeypatch.setattr("pipeline.ingest.live_scores.refresh_live", lambda db: calls.append(1))
    factory = _factory_with(Match(tournament_id=1, stage="group", status="in_play"))

    assert live_refresh.maybe_refresh_live(session_factory=factory) is None
    assert calls == []


def test_refreshes_when_a_match_is_live_and_clears_cache(monkeypatch):
    summary = {"updated": 3, "live": 1, "finished": 2}
    calls = []

    def fake_refresh(db):
        calls.append(db)
        return summary

    monkeypatch.setattr("pipeline.ingest.live_scores.refresh_live", fake_refresh)
    cache.set("matches:upcoming", ["stale scores"])
    factory = _factory_with(Match(tournament_id=1, stage="group", status="in_play"))

    assert live_refresh.maybe_refresh_live(session_factory=factory) == summary
    assert len(calls) == 1
    assert cache.get("matches:upcoming") is None  # stale board evicted


def test_rate_limited_to_one_attempt_per_interval(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: calls.append(1) or {"updated": 0, "live": 0, "finished": 0},
    )
    factory = _factory_with(Match(tournament_id=1, stage="group", status="in_play"))

    live_refresh.maybe_refresh_live(session_factory=factory)
    live_refresh.maybe_refresh_live(session_factory=factory)

    assert len(calls) == 1


def test_skips_outside_any_live_window(monkeypatch):
    calls = []
    monkeypatch.setattr("pipeline.ingest.live_scores.refresh_live", lambda db: calls.append(1))
    factory = _factory_with(
        Match(tournament_id=1, stage="group", status="scheduled",
              kickoff_utc=_now() + timedelta(days=2)),
        Match(tournament_id=1, stage="group", status="finished",
              kickoff_utc=_now() - timedelta(days=1)),
    )

    assert live_refresh.maybe_refresh_live(session_factory=factory) is None
    assert calls == []


def test_recent_kickoff_counts_as_live_window(monkeypatch):
    """A match that kicked off 30 min ago may be in play even if our DB still
    says 'scheduled' — the window must cover the scheduled→live transition."""
    calls = []
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: calls.append(1) or {"updated": 1, "live": 1, "finished": 0},
    )
    factory = _factory_with(
        Match(tournament_id=1, stage="group", status="scheduled",
              kickoff_utc=_now() - timedelta(minutes=30)),
    )

    live_refresh.maybe_refresh_live(session_factory=factory)
    assert len(calls) == 1


# ---- endpoint wiring: the matches board drives the refresh ----

def _client_with_empty_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_matches_board_schedules_a_live_refresh(monkeypatch):
    scheduled = []
    monkeypatch.setattr("app.api.matches.maybe_refresh_live", lambda: scheduled.append(1))
    client = _client_with_empty_db()
    try:
        assert client.get("/api/matches/upcoming").status_code == 200
        assert scheduled == [1]
    finally:
        app.dependency_overrides.clear()


def test_matches_board_skips_scheduling_when_live_mode_off(monkeypatch):
    monkeypatch.setattr(settings, "live_mode_enabled", False)
    scheduled = []
    monkeypatch.setattr("app.api.matches.maybe_refresh_live", lambda: scheduled.append(1))
    client = _client_with_empty_db()
    try:
        assert client.get("/api/matches/upcoming").status_code == 200
        assert scheduled == []
    finally:
        app.dependency_overrides.clear()
