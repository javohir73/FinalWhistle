"""API endpoint tests (task 5.9): endpoints, §17 conformance, cache, 404s."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Prediction, Team
from pipeline.generate_predictions import generate_predictions
from pipeline.ingest.wc26_structure import load_structure


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    # Seed: structure + synthetic elos + predictions.
    seed = TestingSession()
    load_structure(seed)
    for i, t in enumerate(seed.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    seed.commit()
    generate_predictions(
        seed, model_version="poisson-elo-v0.1", n_sims=200, tournament_sims=200
    )
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


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["app"] == "FinalWhistle"


def test_upcoming_matches(client):
    r = client.get("/api/matches/upcoming")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 72  # all group matches with teams
    assert data[0]["probabilities"] is not None


def test_match_detail_matches_section_17_shape(client):
    match_id = client.get("/api/matches/upcoming").json()[0]["match_id"]
    r = client.get(f"/api/matches/{match_id}")
    assert r.status_code == 200
    body = r.json()
    for key in [
        "match_id", "model_version", "generated_at", "teams", "is_neutral",
        "probabilities", "predicted_score", "confidence", "reasons",
        "top_features", "head_to_head", "odds_comparison", "disclaimer",
    ]:
        assert key in body
    p = body["probabilities"]
    assert abs(p["home_win"] + p["draw"] + p["away_win"] - 1.0) < 0.01
    assert body["odds_comparison"] == {"available": False}
    assert len(body["reasons"]) >= 3


def test_knockout_odds(client):
    r = client.get("/api/knockout/odds")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 48  # every team has tournament odds
    for row in data:
        for key in [
            "team_id", "team", "make_knockout", "reach_r16", "reach_qf",
            "reach_sf", "reach_final", "win_title",
        ]:
            assert key in row
    # sorted by title probability, descending
    titles = [row["win_title"] for row in data]
    assert titles == sorted(titles, reverse=True)
    # exactly one champion per sim -> title probabilities sum to ~1
    assert abs(sum(titles) - 1.0) < 0.001


def test_match_detail_404(client):
    r = client.get("/api/matches/999999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "match_not_found"


def test_predictions_with_history(client):
    match_id = client.get("/api/matches/upcoming").json()[0]["match_id"]
    r = client.get(f"/api/predictions/{match_id}")
    assert r.status_code == 200
    body = r.json()
    assert "current" in body and "history" in body
    assert len(body["history"]) >= 1


def test_teams_list_and_profile(client):
    teams = client.get("/api/teams").json()
    assert len(teams) == 48
    tid = teams[0]["id"]
    prof = client.get(f"/api/teams/{tid}")
    assert prof.status_code == 200
    assert "recent_form" in prof.json()
    assert client.get("/api/teams/999999").status_code == 404


def test_groups(client):
    groups = client.get("/api/groups").json()
    assert len(groups) == 12
    gid = groups[0]["id"]
    detail = client.get(f"/api/groups/{gid}").json()
    rows = detail["standings"]
    assert len(rows) == 4
    # Table is ranked like a real league table: projected points, then GD, then GF
    # (descending). Qualification prob is a separate column, not the sort key.
    keys = [(r["projected_points"], r["projected_goal_diff"], r["projected_goals_for"]) for r in rows]
    assert keys == sorted(keys, reverse=True)
    assert client.get("/api/groups/999999").status_code == 404


def test_reads_do_not_trigger_model_run(client):
    """Read endpoints must serve cached/stored data, never recompute (PRD §7)."""
    before = None
    # Count predictions via a fresh session through the override.
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    before = db.query(Prediction).count()
    # Hit read endpoints repeatedly.
    for _ in range(3):
        client.get("/api/matches/upcoming")
        client.get("/api/groups")
        client.get("/api/teams")
    after = db.query(Prediction).count()
    assert after == before  # no new predictions written by reads


def test_recompute_disabled_when_token_unset(client, monkeypatch):
    """Fail closed: no configured token => endpoint disabled, never a default."""
    monkeypatch.setattr(settings, "recompute_token", "")
    assert client.post("/api/internal/recompute").status_code == 503
    r = client.post("/api/internal/recompute", headers={"X-Recompute-Token": "anything"})
    assert r.status_code == 503


def test_recompute_requires_token(client, monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "test-secret")
    assert client.post("/api/internal/recompute").status_code == 401
    assert client.post(
        "/api/internal/recompute", headers={"X-Recompute-Token": "wrong"}
    ).status_code == 401
    r = client.post("/api/internal/recompute", headers={"X-Recompute-Token": "test-secret"})
    assert r.status_code == 200
    assert r.json()["recomputed"]["matches_predicted"] == 72


def test_prediction_rows_log_model_version_and_timestamp(client):
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    pred = db.query(Prediction).first()
    assert pred.model_version == "poisson-elo-v0.1"
    assert pred.created_at is not None
