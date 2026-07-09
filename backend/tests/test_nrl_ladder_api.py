"""Ladder: 2/1/0 points from finished matches; points then diff ordering."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportTeam


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), TestingSession()


def test_ladder_points_and_ordering():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Storm")
    broncos = SportTeam(sport="nrl", name="Broncos")
    panthers = SportTeam(sport="nrl", name="Panthers")
    db.add_all([storm, broncos, panthers]); db.flush()

    def played(no, h, a, sh, sa):
        db.add(SportMatch(sport="nrl", season=2026, round=1, match_no=no,
                          home_team_id=h.id, away_team_id=a.id,
                          score_home=sh, score_away=sa, status="finished"))

    played(1, storm, broncos, 30, 10)    # storm win
    played(2, panthers, storm, 12, 12)   # draw
    played(3, broncos, panthers, 20, 22) # panthers win
    # scheduled matches must not count:
    db.add(SportMatch(sport="nrl", season=2026, round=2, match_no=4,
                      home_team_id=storm.id, away_team_id=panthers.id, status="scheduled"))
    db.commit()

    body = client.get("/api/nrl/ladder?season=2026").json()
    rows = body["rows"]
    assert [r["name"] for r in rows] == ["Storm", "Panthers", "Broncos"]
    assert [r["points"] for r in rows] == [3, 3, 0]      # storm diff +20 beats panthers +2
    assert rows[0]["diff"] == 20 and rows[0]["played"] == 2
    assert rows[0]["rank"] == 1
    app.dependency_overrides.clear()


def test_ladder_unknown_season_404s():
    client, db = _client()
    # Seed one team and one finished 2026 match
    storm = SportTeam(sport="nrl", name="Storm")
    broncos = SportTeam(sport="nrl", name="Broncos")
    db.add_all([storm, broncos])
    db.flush()

    db.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                      home_team_id=storm.id, away_team_id=broncos.id,
                      score_home=20, score_away=10, status="finished"))
    db.commit()

    # Request unknown season 1999
    res = client.get("/api/nrl/ladder?season=1999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "season_not_found"
    app.dependency_overrides.clear()


def test_ladder_season_without_finished_matches_returns_empty_rows():
    client, db = _client()
    # Seed a season with ONLY scheduled matches
    storm = SportTeam(sport="nrl", name="Storm")
    broncos = SportTeam(sport="nrl", name="Broncos")
    db.add_all([storm, broncos])
    db.flush()

    db.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                      home_team_id=storm.id, away_team_id=broncos.id,
                      status="scheduled"))
    db.commit()

    # Request that season
    res = client.get("/api/nrl/ladder?season=2026")
    assert res.status_code == 200
    body = res.json()
    assert body["rows"] == []
    app.dependency_overrides.clear()
