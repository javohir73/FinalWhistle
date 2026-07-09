"""Orchestrator: mapping, de-vig, idempotent hourly writes, never-raises sources."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import MarketOddsSnapshot, Match, Team, Tournament

from pipeline import market_intel


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


NOW = datetime(2026, 7, 10, 14, 40)


def _seed_football(db):
    t = Tournament(name="WC26", year=2026)
    fra, mar = Team(name="France"), Team(name="Morocco")
    db.add_all([t, fra, mar]); db.flush()
    match = Match(tournament_id=t.id, stage="QF", team_home_id=fra.id,
                  team_away_id=mar.id, status="scheduled",
                  kickoff_utc=NOW + timedelta(hours=16))
    db.add(match); db.commit()
    return fra, mar, match


def _match_rows(price_home=0.63, price_draw=0.27, price_away=0.15,
                home="France", away="Morocco"):
    def row(outcome, team, price, ext):
        return {"source": "polymarket", "external_id": ext, "group": "g1",
                "kind": "match", "home_name": home, "away_name": away,
                "outcome": outcome, "team_name": team, "price": price}
    return [row("home", home, price_home, "m-home"),
            row("draw", None, price_draw, "m-draw"),
            row("away", away, price_away, "m-away")]


def test_match_group_mapped_and_devigged():
    db = _session()
    _fra, _mar, match = _seed_football(db)
    n = market_intel._to_rows(db, "football", _match_rows(), NOW)
    assert len(n) == 3
    by = {r.outcome: r for r in n}
    assert by["home"].match_id == match.id and by["home"].market_type == "match_winner"
    # de-vig: 0.63 / (0.63+0.27+0.15) = 0.6
    assert by["home"].implied_prob == pytest.approx(0.6)
    assert by["draw"].implied_prob == pytest.approx(0.2571, abs=1e-3)


def test_reversed_orientation_swaps_outcomes():
    db = _session()
    fra, _mar, match = _seed_football(db)
    rows = _match_rows(home="Morocco", away="France",
                       price_home=0.15, price_draw=0.27, price_away=0.63)
    by = {r.outcome: r for r in market_intel._to_rows(db, "football", rows, NOW)}
    # Exchange's "home" (Morocco) is OUR away side.
    assert by["home"].match_id == match.id
    assert by["home"].implied_prob == pytest.approx(0.6)  # France = our home


def test_incomplete_football_group_skipped():
    db = _session()
    _seed_football(db)
    rows = [r for r in _match_rows() if r["outcome"] != "draw"]
    assert market_intel._to_rows(db, "football", rows, NOW) == []


def test_title_rows_map_by_team_and_skip_unknown():
    db = _session()
    fra, _mar, _match = _seed_football(db)
    rows = [
        {"source": "kalshi", "external_id": "t-fra", "group": "t", "kind": "title",
         "home_name": None, "away_name": None, "outcome": "win",
         "team_name": "France", "price": 0.31},
        {"source": "kalshi", "external_id": "t-zzz", "group": "t", "kind": "title",
         "home_name": None, "away_name": None, "outcome": "win",
         "team_name": "Narnia", "price": 0.02},
    ]
    out = market_intel._to_rows(db, "football", rows, NOW)
    assert [(r.team_id, r.market_type) for r in out] == [(fra.id, "title_winner")]
    # lone mapped title outcome sums to 0.31 < 0.9 -> raw price kept (no inflation)
    assert out[0].implied_prob == pytest.approx(0.31)


def test_run_idempotent_per_hour_and_prunes(monkeypatch):
    db = _session()
    _seed_football(db)
    monkeypatch.setattr(market_intel, "CONFIGS", [
        market_intel.SourceConfig("football", "polymarket", lambda: _match_rows()),
    ])
    db.add(MarketOddsSnapshot(  # 15 days old -> pruned
        sport="football", source="polymarket", market_type="title_winner",
        team_id=1, outcome="win", implied_prob=0.5, external_id="old",
        fetched_at=NOW - timedelta(days=15)))
    db.commit()
    assert market_intel.run(db, NOW) == 3
    assert market_intel.run(db, NOW) == 3  # same hour re-run: replaced, not duped
    assert db.query(MarketOddsSnapshot).count() == 3  # old row pruned


def test_run_raises_only_when_all_sources_empty(monkeypatch):
    db = _session()
    _seed_football(db)

    def boom():
        raise RuntimeError("api down")

    monkeypatch.setattr(market_intel, "CONFIGS", [
        market_intel.SourceConfig("football", "polymarket", boom),
        market_intel.SourceConfig("football", "kalshi", lambda: _match_rows()),
    ])
    assert market_intel.run(db, NOW) == 3  # one source down: no raise

    monkeypatch.setattr(market_intel, "CONFIGS", [
        market_intel.SourceConfig("football", "polymarket", boom),
    ])
    with pytest.raises(RuntimeError):
        market_intel.run(db, NOW)
