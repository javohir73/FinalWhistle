"""GET /api/nrl/matches/{id}, GET /api/nrl/projections,
GET /api/nrl/matches/{id}/prob-history -- Wave 1's rich match-detail surface.
Mirrors test_sports_api.py's fixture style."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    NrlProjection, ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam,
)


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
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _team(db, name, elo=None):
    t = SportTeam(sport="nrl", name=name, elo_rating=elo)
    db.add(t); db.flush()
    return t


def test_match_detail_404s_for_unknown_id(client):
    c, _ = client
    r = c.get("/api/nrl/matches/999")
    assert r.status_code == 404


def test_match_detail_returns_prediction_form_h2h_factors(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm", elo=1560.0)
    away = _team(db, "Eels", elo=1490.0)
    third = _team(db, "Titans")

    # Prior meeting between these two exact sides (h2h).
    db.add(SportMatch(sport="nrl", season=2025, round=10, match_no=50,
                      kickoff_utc=datetime(2025, 6, 1, tzinfo=timezone.utc),
                      home_team_id=home.id, away_team_id=away.id,
                      score_home=24, score_away=12, status="finished"))
    # Home team's prior form -- against a DIFFERENT opponent, so it doesn't
    # also count as a head-to-head meeting between home and away.
    db.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                      kickoff_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
                      home_team_id=home.id, away_team_id=third.id,
                      score_home=20, score_away=10, status="finished"))
    m = SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                   kickoff_utc=datetime(2026, 3, 8, tzinfo=timezone.utc),
                   venue="AAMI Park", home_team_id=home.id, away_team_id=away.id,
                   status="scheduled")
    db.add(m); db.flush()
    db.add(SportPrediction(
        match_id=m.id, model_version="nrl-elo-v0.1",
        p_home=0.62, p_draw=0.01, p_away=0.37,
        expected_margin=5.0, predicted_margin=6.1, predicted_total=41.0,
        preview_text="Storm are the model's pick.",
    ))
    db.commit()

    r = c.get(f"/api/nrl/matches/{m.id}")
    assert r.status_code == 200
    body = r.json()

    assert body["match"]["id"] == m.id
    assert body["match"]["home"] == "Storm"
    assert body["match"]["away"] == "Eels"

    pred = body["prediction"]
    assert pred["home_prob"] == pytest.approx(0.62)
    assert pred["away_prob"] == pytest.approx(0.37)
    assert pred["draw_prob"] == pytest.approx(0.01)
    assert pred["predicted_margin"] == pytest.approx(6.1)
    assert pred["predicted_total"] == pytest.approx(41.0)
    assert pred["preview_text"] == "Storm are the model's pick."
    assert pred["model_version"] == "nrl-elo-v0.1"

    assert len(body["form"]["home"]["last5"]) == 1
    assert body["form"]["home"]["last5"][0]["result"] == "W"
    assert body["form"]["home"]["avg_margin"] == 10.0

    assert len(body["h2h"]) == 1
    assert body["h2h"][0]["score_home"] == 24

    keys = {f["key"] for f in body["factors"]}
    assert keys == {"elo_gap", "form_composite", "home_advantage"}
    weights = {f["key"]: f["weight"] for f in body["factors"]}
    assert weights["elo_gap"] == pytest.approx(0.5)
    assert weights["form_composite"] == pytest.approx(0.3)
    assert weights["home_advantage"] == pytest.approx(0.2)
    home_adv = next(f for f in body["factors"] if f["key"] == "home_advantage")
    assert home_adv["favors"] == "home"
    elo_gap = next(f for f in body["factors"] if f["key"] == "elo_gap")
    assert elo_gap["favors"] == "home"  # Storm's elo_rating (1560) > Eels' (1490)


def test_match_detail_handles_no_prediction_yet(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.commit()

    r = c.get(f"/api/nrl/matches/{m.id}")
    assert r.status_code == 200
    assert r.json()["prediction"] is None


def test_projections_empty_when_none_computed(client):
    c, _ = client
    r = c.get("/api/nrl/projections")
    assert r.status_code == 200
    body = r.json()
    assert body["teams"] == []
    assert body["computed_at"] is None


def test_projections_returns_seeded_rows(client):
    c, TestingSession = client
    db = TestingSession()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    db.add(NrlProjection(team="Storm", top8=0.95, top4=0.4, minor_premiership=0.1,
                         computed_at=now))
    db.commit()

    body = c.get("/api/nrl/projections").json()
    assert body["computed_at"] is not None
    assert body["teams"] == [
        {"team": "Storm", "top8": 0.95, "top4": 0.4, "minor_premiership": 0.1}
    ]


def test_prob_history_404s_for_unknown_match(client):
    c, _ = client
    assert c.get("/api/nrl/matches/999/prob-history").status_code == 404


def test_prob_history_returns_snapshots_for_the_match(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()
    db.add_all([
        ProbabilitySnapshot(sport="nrl", entity_id=home.id, market="win_match",
                            ref_id=m.id, prob=0.55, snapshot_date=date(2026, 7, 1)),
        ProbabilitySnapshot(sport="nrl", entity_id=away.id, market="win_match",
                            ref_id=m.id, prob=0.44, snapshot_date=date(2026, 7, 1)),
        ProbabilitySnapshot(sport="nrl", entity_id=home.id, market="win_match",
                            ref_id=m.id, prob=0.61, snapshot_date=date(2026, 7, 2)),
        ProbabilitySnapshot(sport="nrl", entity_id=away.id, market="win_match",
                            ref_id=m.id, prob=0.38, snapshot_date=date(2026, 7, 2)),
    ])
    db.commit()

    body = c.get(f"/api/nrl/matches/{m.id}/prob-history").json()
    assert len(body["points"]) == 2
    assert body["points"][0]["date"] == "2026-07-01"
    assert body["points"][0]["p_home"] == pytest.approx(0.55)
    assert body["points"][1]["p_home"] == pytest.approx(0.61)
    assert "disclaimer" in body


def test_matches_endpoint_now_includes_match_id(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.commit()

    body = c.get("/api/nrl/matches", params={"season": 2026}).json()
    assert body["rounds"][0]["matches"][0]["id"] == m.id
