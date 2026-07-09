"""GET /api/nrl/teams/{id} — the club profile endpoint. Fixture style follows
test_sports_api.py (in-memory SQLite, dependency override, cache cleared)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam


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
    cache.clear()
    yield TestClient(app), TestingSession
    cache.clear()
    app.dependency_overrides.clear()


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t)
    db.flush()
    return t


def _match(db, no, home, away, *, round=1, sh=None, sa=None, status="scheduled",
           kickoff=None, venue=None):
    m = SportMatch(sport="nrl", season=2026, round=round, match_no=no,
                   kickoff_utc=kickoff, venue=venue,
                   home_team_id=home.id, away_team_id=away.id,
                   score_home=sh, score_away=sa, status=status)
    db.add(m)
    db.flush()
    return m


def _seed_season(db):
    """Warriors' 2026: W 30–10 (h, Storm), L 12–26 (a, Eels), W 20–18 (h, Eels),
    W 22–4 (a, Storm) — then a scheduled Storm home game with a prediction."""
    warriors = _team(db, "Warriors")
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    kick = lambda d: datetime(2026, 3, d, 9, tzinfo=timezone.utc)  # noqa: E731
    _match(db, 1, warriors, storm, round=1, sh=30, sa=10, status="finished", kickoff=kick(5))
    _match(db, 2, eels, warriors, round=2, sh=26, sa=12, status="finished", kickoff=kick(12))
    _match(db, 3, warriors, eels, round=3, sh=20, sa=18, status="finished", kickoff=kick(19))
    _match(db, 4, storm, warriors, round=4, sh=4, sa=22, status="finished", kickoff=kick(26))
    nxt = _match(db, 5, warriors, storm, round=5, status="scheduled",
                 kickoff=datetime(2026, 4, 2, 9, tzinfo=timezone.utc), venue="Go Media Stadium")
    return warriors, storm, eels, nxt


def test_team_profile_record_splits_and_streak(client):
    c, TestingSession = client
    db = TestingSession()
    warriors, _, _, _ = _seed_season(db)
    db.commit()

    r = c.get(f"/api/nrl/teams/{warriors.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2026
    assert body["team"]["name"] == "Warriors"

    s = body["summary"]
    assert (s["played"], s["wins"], s["losses"], s["draws"]) == (4, 3, 1, 0)
    assert s["points_for"] == 30 + 12 + 20 + 22
    assert s["points_against"] == 10 + 26 + 18 + 4
    assert s["home"] == {"wins": 2, "draws": 0, "losses": 0}
    assert s["away"] == {"wins": 1, "draws": 0, "losses": 1}
    # Last two games won → a 2-game winning streak.
    assert s["streak"] == {"result": "W", "length": 2}
    assert s["biggest_win"]["opponent"] == "Storm"
    assert s["biggest_win"]["score_for"] == 30
    assert s["biggest_loss"]["opponent"] == "Eels"

    # Ladder slot comes from the computed ladder (3 wins × 2 pts = 6, rank 1).
    assert body["ladder"]["rank"] == 1
    assert body["ladder"]["points"] == 6


def test_team_results_are_most_recent_first_with_ledger_grading(client):
    c, TestingSession = client
    db = TestingSession()
    warriors, storm, eels, _ = _seed_season(db)
    # Grade round 1 in the ledger: model called it. Round 2–4 stay ungraded.
    m1 = db.query(SportMatch).filter(SportMatch.match_no == 1).one()
    pred = SportPrediction(match_id=m1.id, model_version="nrl-elo-v0.1",
                           created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                           p_home=0.7, p_draw=0.01, p_away=0.29, expected_margin=8.0)
    db.add(pred)
    db.flush()
    db.add(SportPredictionResult(match_id=m1.id, prediction_id=pred.id,
                                 model_version="nrl-elo-v0.1", outcome="home",
                                 winner_correct=True, prob_assigned=0.7,
                                 log_loss=0.36, brier=0.09,
                                 evaluated_at=datetime(2026, 3, 6, tzinfo=timezone.utc)))
    db.commit()

    body = c.get(f"/api/nrl/teams/{warriors.id}").json()
    results = body["results"]
    assert [x["round"] for x in results] == [4, 3, 2, 1]
    assert [x["result"] for x in results] == ["W", "W", "L", "W"]
    assert results[3]["model_called"] is True       # graded via the ledger
    assert results[0]["model_called"] is None       # ungraded stays None
    assert results[3]["opponent"] == "Storm"
    assert results[3]["was_home"] is True
    assert results[2]["was_home"] is False
    assert body["model"] == {"graded": 1, "called": 1, "accuracy": 1.0}


def test_team_upcoming_maps_win_prob_to_the_clubs_side(client):
    c, TestingSession = client
    db = TestingSession()
    warriors, storm, _, nxt = _seed_season(db)
    # Two predictions; only the later one should surface. Warriors are home.
    db.add(SportPrediction(match_id=nxt.id, model_version="nrl-elo-v0.1",
                           created_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
                           p_home=0.5, p_draw=0.02, p_away=0.48, expected_margin=0.5))
    db.add(SportPrediction(match_id=nxt.id, model_version="nrl-elo-v0.1",
                           created_at=datetime(2026, 3, 28, tzinfo=timezone.utc),
                           p_home=0.64, p_draw=0.02, p_away=0.34, expected_margin=6.0))
    db.commit()

    body = c.get(f"/api/nrl/teams/{warriors.id}").json()
    assert len(body["upcoming"]) == 1
    up = body["upcoming"][0]
    assert up["opponent"] == "Storm"
    assert up["was_home"] is True
    assert up["venue"] == "Go Media Stadium"
    assert up["win_prob"] == pytest.approx(0.64)

    # The same fixture from Storm's side flips to p_away.
    body = c.get(f"/api/nrl/teams/{storm.id}").json()
    assert body["upcoming"][0]["was_home"] is False
    assert body["upcoming"][0]["win_prob"] == pytest.approx(0.34)


def test_team_with_no_finished_matches_has_null_summary(client):
    c, TestingSession = client
    db = TestingSession()
    warriors = _team(db, "Warriors")
    storm = _team(db, "Storm")
    _match(db, 1, warriors, storm, status="scheduled")
    db.commit()

    body = c.get(f"/api/nrl/teams/{warriors.id}").json()
    assert body["summary"] is None
    assert body["ladder"] is None
    assert body["model"] is None
    assert body["results"] == []
    assert len(body["upcoming"]) == 1


def test_unknown_team_404s(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_season(db)
    db.commit()

    r = c.get("/api/nrl/teams/9999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "team_not_found"


def test_unknown_season_404s(client):
    c, TestingSession = client
    db = TestingSession()
    warriors, _, _, _ = _seed_season(db)
    db.commit()

    r = c.get(f"/api/nrl/teams/{warriors.id}", params={"season": 1999})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "season_not_found"


def test_matches_payload_now_carries_team_ids(client):
    c, TestingSession = client
    db = TestingSession()
    warriors, storm, _, _ = _seed_season(db)
    db.commit()

    body = c.get("/api/nrl/matches", params={"season": 2026, "round": 1}).json()
    match = body["rounds"][0]["matches"][0]
    assert match["home_team_id"] == warriors.id
    assert match["away_team_id"] == storm.id
