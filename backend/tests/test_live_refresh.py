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


def test_final_whistle_triggers_post_results_chain(monkeypatch):
    """A refresh that transitions a match to finished must run the learning
    chain (evaluate → ratings → predictions → brackets) and report it."""
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: {"updated": 1, "live": 0, "finished": 1, "newly_finished": 1},
    )
    chain_calls = []
    monkeypatch.setattr(
        "pipeline.learning_loop.run_post_results_chain",
        lambda db, mv, **kw: chain_calls.append(mv) or {"learning": {"evaluated_new": 1}},
    )
    factory = _factory_with(Match(tournament_id=1, stage="group", status="in_play"))

    summary = live_refresh.maybe_refresh_live(session_factory=factory)

    assert chain_calls == [settings.model_version]
    assert summary["post_results"] == {"learning": {"evaluated_new": 1}}


def test_chain_failure_keeps_the_refresh_summary(monkeypatch):
    """The chain is best-effort: scores are committed either way, so a chain
    crash must be swallowed (the next trigger or the daily run retries)."""
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: {"updated": 1, "live": 0, "finished": 1, "newly_finished": 1},
    )

    def boom(db, mv, **kw):
        raise RuntimeError("simulation blew up")

    monkeypatch.setattr("pipeline.learning_loop.run_post_results_chain", boom)
    factory = _factory_with(Match(tournament_id=1, stage="group", status="in_play"))

    summary = live_refresh.maybe_refresh_live(session_factory=factory)

    assert summary["updated"] == 1
    assert "post_results" not in summary


# ---- retry/sweep: a single missed transition event must not strand a match ----

def _finished_unprocessed():
    """A finished match (teams + scores known) that no COMPLETED chain covers —
    e.g. its chain crashed mid-run, or it finished while the process was down."""
    return Match(tournament_id=1, stage="R32", status="finished",
                 score_home=1, score_away=0, team_home_id=1, team_away_id=2,
                 kickoff_utc=_now() - timedelta(hours=4))


def test_pending_finish_is_swept_by_next_refresh_without_transition(monkeypatch):
    """No new whistle in this pass, but an uncovered finish exists: the chain
    must run anyway (and with the slimmer opportunistic simulation counts)."""
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live",
        lambda db: {"updated": 1, "live": 1, "finished": 1, "newly_finished": 0},
    )
    chain_kwargs = []
    monkeypatch.setattr(
        "pipeline.learning_loop.run_post_results_chain",
        lambda db, mv, **kw: chain_kwargs.append(kw) or {"learning": {"evaluated_new": 1}},
    )
    factory = _factory_with(
        Match(tournament_id=1, stage="group", status="in_play"),
        _finished_unprocessed(),
    )

    summary = live_refresh.maybe_refresh_live(session_factory=factory)

    assert len(chain_kwargs) == 1
    assert chain_kwargs[0] == {
        "n_sims": settings.chain_n_sims,
        "tournament_sims": settings.chain_tournament_sims,
    }
    assert "post_results" in summary


def test_owed_chain_retries_even_outside_live_window(monkeypatch):
    """After the day's last final whistle the live window closes — board
    traffic must still retry an owed chain (no upstream fetch involved)."""
    upstream = []
    monkeypatch.setattr(
        "pipeline.ingest.live_scores.refresh_live", lambda db: upstream.append(1)
    )
    chain_calls = []
    monkeypatch.setattr(
        "pipeline.learning_loop.run_post_results_chain",
        lambda db, mv, **kw: chain_calls.append(1) or {"learning": {"evaluated_new": 1}},
    )
    factory = _factory_with(_finished_unprocessed())

    summary = live_refresh.maybe_refresh_live(session_factory=factory)

    assert upstream == []      # window closed: no API call spent
    assert chain_calls == [1]  # but the owed chain ran
    assert summary["post_results"]["learning"]["evaluated_new"] == 1


def test_completed_chain_is_not_rerun(monkeypatch):
    """The success watermark covers the finish: subsequent polls stay quiet."""
    monkeypatch.setattr("pipeline.ingest.live_scores.refresh_live", lambda db: None)
    chain_calls = []
    monkeypatch.setattr(
        "pipeline.learning_loop.run_post_results_chain",
        lambda db, mv, **kw: chain_calls.append(1) or {"learning": {"evaluated_new": 1}},
    )
    factory = _factory_with(_finished_unprocessed())

    live_refresh.maybe_refresh_live(session_factory=factory)
    second = live_refresh.maybe_refresh_live(session_factory=factory)

    assert chain_calls == [1]
    assert second is None


def test_failed_chain_retries_only_after_backoff(monkeypatch):
    """A crashing chain must not be hammered on every 30s poll — it retries
    once the backoff elapses, keeping a dying free-tier instance breathing."""
    monkeypatch.setattr("pipeline.ingest.live_scores.refresh_live", lambda db: None)
    chain_calls = []

    def counting_boom(db, mv, **kw):
        chain_calls.append(1)
        raise RuntimeError("killed mid-simulation")

    monkeypatch.setattr("pipeline.learning_loop.run_post_results_chain", counting_boom)
    factory = _factory_with(_finished_unprocessed())

    assert live_refresh.maybe_refresh_live(session_factory=factory) is None
    assert live_refresh.maybe_refresh_live(session_factory=factory) is None
    assert chain_calls == [1]  # second poll inside the backoff window: no retry

    monkeypatch.setattr(live_refresh, "CHAIN_RETRY_SECONDS", 0.0)
    live_refresh.maybe_refresh_live(session_factory=factory)
    assert chain_calls == [1, 1]  # backoff elapsed: retried


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
