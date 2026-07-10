"""Movers = biggest |Δ| between the two most recent snapshot days per key."""
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ProbabilitySnapshot, SportMatch, SportTeam, Team


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


def test_movers_ranked_by_abs_delta():
    client, db = _client()
    usa = Team(name="United States", country_code="USA")
    bra = Team(name="Brazil", country_code="BRA")
    db.add_all([usa, bra]); db.flush()
    d1, d2 = date(2026, 7, 8), date(2026, 7, 9)
    db.add_all([
        ProbabilitySnapshot(sport="football", entity_id=usa.id, market="make_knockout",
                            prob=0.366, snapshot_date=d1),
        ProbabilitySnapshot(sport="football", entity_id=usa.id, market="make_knockout",
                            prob=0.39, snapshot_date=d2),
        ProbabilitySnapshot(sport="football", entity_id=bra.id, market="win_title",
                            prob=0.106, snapshot_date=d1),
        ProbabilitySnapshot(sport="football", entity_id=bra.id, market="win_title",
                            prob=0.09, snapshot_date=d2),
    ])
    db.commit()

    res = client.get("/api/movers?sport=football&limit=3")
    assert res.status_code == 200
    body = res.json()
    assert body["as_of"] == "2026-07-09"
    assert [m["name"] for m in body["movers"]] == ["United States", "Brazil"]
    top = body["movers"][0]
    assert top["market"] == "make_knockout"
    assert round(top["delta"], 3) == 0.024
    assert top["series"] == [0.366, 0.39]
    assert "Not betting advice" in body["disclaimer"]
    app.dependency_overrides.clear()


def test_movers_single_day_returns_null_deltas():
    client, db = _client()
    t = Team(name="Mexico", country_code="MEX")
    db.add(t); db.flush()
    db.add(ProbabilitySnapshot(sport="football", entity_id=t.id, market="win_title",
                               prob=0.05, snapshot_date=date(2026, 7, 9)))
    db.commit()

    body = client.get("/api/movers?sport=football").json()
    assert body["movers"][0]["delta"] is None
    app.dependency_overrides.clear()


def test_nrl_win_match_movers_include_a_match_url():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Storm")
    eels = SportTeam(sport="nrl", name="Eels")
    db.add_all([storm, eels]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=5, match_no=12,
                   home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m); db.flush()
    d1, d2 = date(2026, 7, 8), date(2026, 7, 9)
    db.add_all([
        ProbabilitySnapshot(sport="nrl", entity_id=storm.id, market="win_match",
                            ref_id=m.id, prob=0.55, snapshot_date=d1),
        ProbabilitySnapshot(sport="nrl", entity_id=storm.id, market="win_match",
                            ref_id=m.id, prob=0.63, snapshot_date=d2),
    ])
    db.commit()

    body = client.get("/api/movers?sport=nrl").json()
    row = next(r for r in body["movers"] if r["entity_id"] == storm.id)
    assert row["match_url"] == "/nrl/match/2026/5/12"
    app.dependency_overrides.clear()


def test_nrl_movers_without_a_round_have_no_match_url():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Storm")
    eels = SportTeam(sport="nrl", name="Eels")
    db.add_all([storm, eels]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=None, match_no=12,
                   home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m); db.flush()
    db.add(ProbabilitySnapshot(sport="nrl", entity_id=storm.id, market="win_match",
                               ref_id=m.id, prob=0.55, snapshot_date=date(2026, 7, 9)))
    db.commit()

    body = client.get("/api/movers?sport=nrl").json()
    row = next(r for r in body["movers"] if r["entity_id"] == storm.id)
    assert row["match_url"] is None
    app.dependency_overrides.clear()


def test_football_movers_have_null_match_url():
    client, db = _client()
    usa = Team(name="United States", country_code="USA")
    db.add(usa); db.flush()
    db.add(ProbabilitySnapshot(sport="football", entity_id=usa.id, market="make_knockout",
                               prob=0.4, snapshot_date=date(2026, 7, 9)))
    db.commit()

    body = client.get("/api/movers?sport=football").json()
    assert body["movers"][0]["match_url"] is None
    app.dependency_overrides.clear()
