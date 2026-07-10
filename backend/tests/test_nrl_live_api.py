from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def test_live_404_for_unknown_match():
    client, _ = _client()
    try:
        assert client.get("/api/nrl/matches/999/live").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_live_pre_state_before_kickoff_with_no_poll_yet():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        now = datetime.now(timezone.utc)
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="scheduled",
                        kickoff_utc=now + timedelta(days=2))
        db.add(m); db.flush()
        db.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                p_home=0.62, p_draw=0.01, p_away=0.37))
        db.commit()

        body = client.get(f"/api/nrl/matches/{m.id}/live").json()
        assert body["status"] == "pre"
        assert body["score_home"] is None
        assert body["live_home_prob"] == 0.62
        assert body["events"] == []
        assert "odds" not in body and "value" not in body
    finally:
        app.dependency_overrides.clear()


def test_live_state_reads_persisted_poll_and_events():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        now = datetime.now(timezone.utc)
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="scheduled",
                        kickoff_utc=now - timedelta(minutes=20))
        db.add(m); db.flush()
        db.add(NrlLiveState(match_id=m.id, status="live", minute=20,
                             score_home=6, score_away=0, live_home_prob=0.81))
        db.add(NrlLiveEvent(match_id=m.id, minute=12, type="score", team="home",
                             player=None, prob_after=0.75))
        db.commit()

        body = client.get(f"/api/nrl/matches/{m.id}/live").json()
        assert body["status"] == "live"
        assert body["score_home"] == 6
        assert len(body["events"]) == 1
        assert body["events"][0]["team"] == "home"
    finally:
        app.dependency_overrides.clear()


def test_live_final_state_from_finished_match_without_ever_being_polled():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="finished",
                        score_home=24, score_away=10)
        db.add(m); db.commit()

        body = client.get(f"/api/nrl/matches/{m.id}/live").json()
        assert body["status"] == "final"
        assert body["score_home"] == 24 and body["score_away"] == 10
        assert body["live_home_prob"] == 1.0
    finally:
        app.dependency_overrides.clear()
