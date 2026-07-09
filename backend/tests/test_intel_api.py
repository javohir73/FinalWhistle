"""Intel = model-vs-market for upcoming fixtures + biggest 24h market moves."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    MarketOddsSnapshot, Match, Prediction, SportMatch, SportPrediction,
    SportTeam, Team, Tournament,
)

# Naive UTC timestamps: SQLite returns naive datetimes for tz-aware columns;
# the endpoint's _aware() shim normalizes them back to UTC.
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


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


def _snap(**overrides):
    base = dict(sport="football", source="polymarket", market_type="match_winner",
                match_id=None, team_id=None, outcome="home", implied_prob=0.6,
                external_id="x", fetched_at=NOW)
    base.update(overrides)
    return MarketOddsSnapshot(**base)


def _seed_match(db, hours_ahead=12):
    t = Tournament(name="WC26", year=2026)
    fra, mar = Team(name="France"), Team(name="Morocco")
    db.add_all([t, fra, mar]); db.flush()
    m = Match(tournament_id=t.id, stage="QF", team_home_id=fra.id,
              team_away_id=mar.id, status="scheduled",
              kickoff_utc=NOW + timedelta(hours=hours_ahead))
    db.add(m); db.flush()
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.55, prob_draw=0.27, prob_away_win=0.18))
    db.commit()
    return fra, mar, m


def test_empty_db_has_no_data():
    client, _db = _client()
    body = client.get("/api/intel?sport=football").json()
    assert body["has_data"] is False
    assert body["matches"] == [] and body["storylines"] == []
    assert body["updated_at"] is None
    app.dependency_overrides.clear()


def test_stale_snapshots_have_no_data():
    client, db = _client()
    db.add(_snap(fetched_at=NOW - timedelta(hours=30))); db.commit()
    assert client.get("/api/intel?sport=football").json()["has_data"] is False
    app.dependency_overrides.clear()


def test_match_comparison_and_disagreement():
    client, db = _client()
    fra, mar, m = _seed_match(db)
    db.add_all([
        _snap(match_id=m.id, outcome="home", implied_prob=0.60, external_id="h"),
        _snap(match_id=m.id, outcome="draw", implied_prob=0.257, external_id="d"),
        _snap(match_id=m.id, outcome="away", implied_prob=0.143, external_id="a"),
    ])
    db.commit()
    body = client.get("/api/intel?sport=football").json()
    assert body["has_data"] is True
    entry = body["matches"][0]
    assert entry["home"]["name"] == "France" and entry["away"]["name"] == "Morocco"
    assert entry["model"] == {"home": 0.55, "draw": 0.27, "away": 0.18}
    assert entry["market"] == [{"source": "polymarket", "home": 0.6, "draw": 0.257,
                                "away": 0.143,
                                "fetched_at": entry["market"][0]["fetched_at"]}]
    assert entry["disagreement"] == 0.05
    assert "Not betting advice" in body["disclaimer"]
    app.dependency_overrides.clear()


def test_kicked_off_matches_excluded():
    client, db = _client()
    _fra, _mar, m = _seed_match(db, hours_ahead=-2)
    db.add(_snap(match_id=m.id, external_id="h")); db.commit()
    body = client.get("/api/intel?sport=football").json()
    assert body["has_data"] is True and body["matches"] == []
    app.dependency_overrides.clear()


def test_storylines_top_moves_exclude_draw_and_stale():
    client, db = _client()
    fra, mar, m = _seed_match(db)
    old = NOW - timedelta(hours=24)
    db.add_all([
        # title: France 0.24 -> 0.31 (|0.07| = biggest move)
        _snap(market_type="title_winner", team_id=fra.id, outcome="win",
              implied_prob=0.24, external_id="t-fra", fetched_at=old),
        _snap(market_type="title_winner", team_id=fra.id, outcome="win",
              implied_prob=0.31, external_id="t-fra"),
        # match home: 0.60 -> 0.63
        _snap(match_id=m.id, outcome="home", implied_prob=0.60,
              external_id="h", fetched_at=old),
        _snap(match_id=m.id, outcome="home", implied_prob=0.63, external_id="h"),
        # draw moved too but draw storylines are excluded
        _snap(match_id=m.id, outcome="draw", implied_prob=0.20,
              external_id="d", fetched_at=old),
        _snap(match_id=m.id, outcome="draw", implied_prob=0.30, external_id="d"),
        # stale market (latest snapshot 6h old > LIVE_HOURS): excluded
        _snap(market_type="title_winner", team_id=mar.id, outcome="win",
              implied_prob=0.02, external_id="t-mar", fetched_at=old),
        _snap(market_type="title_winner", team_id=mar.id, outcome="win",
              implied_prob=0.09, external_id="t-mar",
              fetched_at=NOW - timedelta(hours=6)),
    ])
    db.commit()
    body = client.get("/api/intel?sport=football").json()
    lines = body["storylines"]
    assert [(s["market_type"], s["prob_from"], s["prob_to"]) for s in lines] == [
        ("title_winner", 0.24, 0.31),
        ("match_winner", 0.6, 0.63),
    ]
    assert lines[0]["team"]["name"] == "France"
    assert lines[1]["team"]["name"] == "France" and lines[1]["match_id"] == m.id
    assert lines[0]["window_hours"] == 24
    app.dependency_overrides.clear()


def test_nrl_scoped_to_sport_tables():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Melbourne Storm")
    roosters = SportTeam(sport="nrl", name="Sydney Roosters")
    db.add_all([storm, roosters]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=19, match_no=1,
                   home_team_id=storm.id, away_team_id=roosters.id,
                   status="scheduled", kickoff_utc=NOW + timedelta(hours=20))
    db.add(m); db.flush()
    db.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                           p_home=0.61, p_draw=0.04, p_away=0.35))
    db.add_all([
        _snap(sport="nrl", match_id=m.id, outcome="home", implied_prob=0.66,
              external_id="n-h"),
        _snap(sport="nrl", match_id=m.id, outcome="away", implied_prob=0.34,
              external_id="n-a"),
    ])
    db.commit()
    body = client.get("/api/intel?sport=nrl").json()
    entry = body["matches"][0]
    assert entry["home"]["name"] == "Melbourne Storm"
    assert entry["model"]["home"] == 0.61
    assert entry["market"][0]["draw"] is None
    # football endpoint unaffected by nrl rows
    assert client.get("/api/intel?sport=football").json()["has_data"] is False
    app.dependency_overrides.clear()


def test_bad_sport_422():
    client, _db = _client()
    assert client.get("/api/intel?sport=cricket").status_code == 422
    app.dependency_overrides.clear()
