from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, get_db
from app.models import Match, Player, Prediction, Team


def _client_with_data():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    db = S()
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    db.add(Prediction(match_id=m.id, model_version="v", prob_home_win=0.6, prob_draw=0.2,
                      prob_away_win=0.2, lambda_home=2.0, lambda_away=0.8, rho=-0.1))
    db.add(Player(provider_player_id=1, name="HStriker", team_id=h.id, position="F",
                  club_goals=18, club_minutes=2700, wc_goals=2, wc_minutes=270))
    db.commit()
    mid = m.id
    db.close()

    def override():
        s = S()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = override
    return TestClient(app), mid


def test_goalscorers_endpoint_returns_block():
    client, mid = _client_with_data()
    try:
        r = client.get(f"/api/matches/{mid}/goalscorers")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "squad"
        assert body["home"][0]["name"] == "HStriker"
    finally:
        app.dependency_overrides.clear()


def test_goalscorers_endpoint_404_for_missing_match():
    client, _ = _client_with_data()
    try:
        assert client.get("/api/matches/99999/goalscorers").status_code == 404
    finally:
        app.dependency_overrides.clear()
