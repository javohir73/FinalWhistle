from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import NrlTeamList, SportMatch, SportTeam
from app.models import NrlTryEvent


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


def test_scorers_404_for_unknown_match():
    client, _ = _client()
    try:
        assert client.get("/api/nrl/matches/999/scorers").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_scorers_returns_bare_array_with_team_field_no_odds():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        home = SportTeam(sport="nrl", name="Broncos")
        away = SportTeam(sport="nrl", name="Storm")
        db.add_all([home, away]); db.flush()
        m = SportMatch(sport="nrl", season=2026, round=3, match_no=1, status="scheduled",
                        home_team_id=home.id, away_team_id=away.id)
        db.add(m); db.flush()
        db.add(NrlTeamList(match_id=m.id, team="Broncos", jersey=2, player="A. Wing", position="WG"))
        db.add(NrlTryEvent(match_id=m.id, team="Broncos", player="A. Wing",
                            minute=10, score_home=4, score_away=0))
        db.commit()

        r = client.get(f"/api/nrl/matches/{m.id}/scorers")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert body[0]["player"] == "A. Wing"
        assert body[0]["team"] == "home"
        assert 0.0 <= body[0]["p_anytime"] <= 1.0
        assert "odds" not in body[0] and "value" not in body[0]
    finally:
        app.dependency_overrides.clear()


def test_scorers_empty_list_when_no_team_list_yet():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        m = SportMatch(sport="nrl", season=2026, round=3, match_no=2, status="scheduled")
        db.add(m); db.commit()
        r = client.get(f"/api/nrl/matches/{m.id}/scorers")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()
