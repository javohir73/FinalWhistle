"""GET /api/matches/{id}/summary — the match-page scoreboard feed: actual
status/score/minute next to the model's predicted score, in one payload."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, Team, Tournament


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    seed = TestingSession()
    seed.add(Tournament(id=1, name="WC26", year=2026))
    seed.add_all([Team(id=10, name="Mexico"), Team(id=20, name="South Africa")])
    seed.add(
        Match(id=1, tournament_id=1, stage="group", team_home_id=10, team_away_id=20,
              status="finished", score_home=2, score_away=0)
    )
    seed.add(
        Prediction(match_id=1, model_version="test", prob_home_win=0.6, prob_draw=0.25,
                   prob_away_win=0.15, predicted_score_home=1, predicted_score_away=0,
                   predicted_score_prob=0.18)
    )
    seed.commit()
    seed.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    cache.clear()


def test_live_endpoints_are_never_shared_cacheable(client):
    # The frontend reaches these through Vercel's /backend-api/* rewrite, and the
    # edge honors origin Cache-Control. A public max-age let the CDN answer the
    # 30s live polls with stale "scheduled" payloads for minutes after kickoff —
    # and starved the opportunistic live refresh those polls are meant to drive.
    for path in ("/api/matches/upcoming", "/api/matches/1/summary"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["Cache-Control"] == "no-store", path


def test_slow_moving_reads_keep_shared_cache(client):
    res = client.get("/api/teams")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "public, max-age=60, stale-while-revalidate=300"


def test_summary_returns_actual_and_predicted_side_by_side(client):
    res = client.get("/api/matches/1/summary")
    assert res.status_code == 200
    body = res.json()
    # Actual result…
    assert body["status"] == "finished"
    assert (body["score_home"], body["score_away"]) == (2, 0)
    # …and the model's call, in the same payload.
    assert body["predicted_score"] == {"home": 1, "away": 0, "probability": 0.18}
    assert body["predicted_winner"] == "Mexico"
    assert body["teams"] == {"home": "Mexico", "away": "South Africa"}


def test_summary_404_for_unknown_match(client):
    res = client.get("/api/matches/999/summary")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "match_not_found"
