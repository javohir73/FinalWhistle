"""GET /api/nrl/teams/{slug}/profile — Wave 2 contract endpoint."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportTeam


@pytest.fixture
def client():
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
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _seed(SessionFactory) -> None:
    """3 teams, 2025: Tigers beat Knights twice at Leichhardt (48-10, 30-12);
    Knights beat Cowboys once away (20-16). Tigers: best attack, best defence."""
    db = SessionFactory()
    tigers = SportTeam(sport="nrl", name="Wests Tigers")
    knights = SportTeam(sport="nrl", name="Knights")
    cowboys = SportTeam(sport="nrl", name="Cowboys")
    db.add_all([tigers, knights, cowboys])
    db.flush()

    def match(no, home, away, sh, sa, venue):
        return SportMatch(
            sport="nrl", season=2025, round=no, match_no=1,
            kickoff_utc=datetime(2025, 3, 6, 9, 0, tzinfo=timezone.utc),
            venue=venue, home_team_id=home.id, away_team_id=away.id,
            score_home=sh, score_away=sa, status="finished",
        )

    db.add_all([
        match(1, tigers, knights, 48, 10, "Leichhardt Oval"),
        match(2, tigers, knights, 30, 12, "Leichhardt Oval"),
        match(3, cowboys, knights, 16, 20, "Queensland Country Bank Stadium"),
    ])
    db.commit()
    db.close()


def test_profile_ranks_and_venue_splits(client):
    tc, SessionFactory = client
    _seed(SessionFactory)
    res = tc.get("/api/nrl/teams/wests-tigers/profile")
    assert res.status_code == 200
    body = res.json()
    assert body["team"]["name"] == "Wests Tigers"
    assert body["team"]["slug"] == "wests-tigers"
    assert body["season"] == 2025
    assert body["attack_rank"] == 1          # 39.0 avg for — best attack
    assert body["defence_rank"] == 1         # 11.0 avg against — best defence
    assert body["position_concessions"] == []  # W2: populated after W3 team lists
    splits = body["venue_splits"]
    assert splits == [{
        "venue": "Leichhardt Oval", "played": 2, "wins": 2, "draws": 0,
        "losses": 0, "avg_for": 39.0, "avg_against": 11.0,
    }]


def test_profile_worst_defence_ranks_last(client):
    tc, SessionFactory = client
    _seed(SessionFactory)
    res = tc.get("/api/nrl/teams/knights/profile")
    assert res.status_code == 200
    body = res.json()
    assert body["defence_rank"] == 3         # 31.3 avg against — worst of 3
    # Knights played at two venues; away split present
    venues = {s["venue"] for s in body["venue_splits"]}
    assert venues == {"Leichhardt Oval", "Queensland Country Bank Stadium"}


def test_profile_404_unknown_slug(client):
    tc, SessionFactory = client
    _seed(SessionFactory)
    res = tc.get("/api/nrl/teams/melbourne-storm/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "team_not_found"


def test_profile_404_when_no_data(client):
    tc, _ = client
    res = tc.get("/api/nrl/teams/knights/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "team_not_found"
