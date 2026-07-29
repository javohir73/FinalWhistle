"""Health denominators are fixtures/markets, never ticks."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import CaptureHeartbeat, Match, Team, Tournament, VenueMarket, VenuePriceTick
from pipeline.report_market_health import build_health

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _match(db):
    tournament = Tournament(name="Premier League 2026-27", year=2026)
    home, away = Team(name="Arsenal"), Team(name="Chelsea")
    db.add_all([tournament, home, away])
    db.flush()
    match = Match(tournament_id=tournament.id, stage="league",
                  team_home_id=home.id, team_away_id=away.id,
                  status="finished", kickoff_utc=KICKOFF,
                  score_home=1, score_away=0)
    db.add(match)
    db.commit()
    return match


def _market(db, key, *, mapped_to=None, outcome=None, status="mapped"):
    row = VenueMarket(
        venue="kalshi", venue_key=key, sport="football",
        market_type="match_winner", raw_title="x",
        mapping_status=status if mapped_to else "unmapped",
        canonical_event_id=mapped_to, canonical_outcome=outcome,
        status="open", first_seen=KICKOFF - timedelta(days=7),
        last_seen=NOW)
    db.add(row)
    db.commit()
    return row


def _tick(db, market, *, ts, transport="polling"):
    db.add(VenuePriceTick(
        venue_market_id=market.id, ts=ts, observed_at=ts, transport=transport,
        observation_key=f"{transport}:{market.id}:{ts.isoformat()}",
        in_play_state_supported=False, mid=0.4, raw_payload_ref="mem://raw"))
    db.commit()


def test_a_market_counts_once_however_many_ticks_it_wrote(db):
    """The whole point of the denominator rule: 500 ticks on one market must
    not read as 500 units of coverage while a silent market reads as one."""
    match = _match(db)
    loud = _market(db, "KX-LOUD", mapped_to=match.id, outcome="home")
    _market(db, "KX-SILENT", mapped_to=match.id, outcome="draw")
    for minute in range(500):
        _tick(db, loud, ts=KICKOFF - timedelta(minutes=minute + 1))

    health = build_health(db, now=NOW)

    venue = health["venues"]["kalshi"]
    assert venue["markets_total"] == 2
    assert venue["markets_with_any_quote"] == 1
    assert venue["markets_without_any_quote"] == ["KX-SILENT"]
    assert health["denominator"] == "fixtures and markets, never ticks"


def test_incomplete_and_conflicting_1x2_fixtures_are_enumerated(db):
    match = _match(db)
    _market(db, "KX-H", mapped_to=match.id, outcome="home")
    _market(db, "KX-D", mapped_to=match.id, outcome="draw")
    # no away market: incomplete

    health = build_health(db, now=NOW)

    venue = health["venues"]["kalshi"]
    assert venue["mapped_fixtures"] == 1
    assert venue["fixtures_with_complete_1x2"] == 0
    assert venue["fixtures_incomplete_1x2"] == [match.id]


def test_mapping_statuses_and_missing_prematch_quotes_are_visible(db):
    match = _match(db)
    for outcome in ("home", "draw", "away"):
        _market(db, f"KX-{outcome}", mapped_to=match.id, outcome=outcome)
    _market(db, "KX-UNMAPPED")

    health = build_health(db, now=NOW)

    venue = health["venues"]["kalshi"]
    assert venue["mapping"] == {"mapped": 3, "unmapped": 1}
    assert venue["fixtures_with_complete_1x2"] == 1
    # No market has any tick: the complete fixture lacks a pre-match quote.
    assert venue["fixtures_missing_prematch_quote"] == [match.id]


def test_freshness_groups_by_venue_and_worker_and_transport(db):
    match = _match(db)
    market = _market(db, "KX-1", mapped_to=match.id, outcome="home")
    _tick(db, market, ts=NOW - timedelta(minutes=10), transport="polling")
    _tick(db, market, ts=NOW - timedelta(minutes=2), transport="streaming")
    for worker, age in (("worker-a", 5), ("worker-b", 120)):
        db.add(CaptureHeartbeat(
            worker=worker, venue="kalshi",
            scheduled_cycle_at=NOW - timedelta(minutes=age),
            completed_at=NOW - timedelta(minutes=age),
            intended_cadence_seconds=300))
    db.commit()

    health = build_health(db, now=NOW)

    freshness = health["heartbeat_freshness_by_venue_worker"]
    assert set(freshness) == {"kalshi/worker-a", "kalshi/worker-b"}
    assert freshness["kalshi/worker-a"]["age_seconds"] == 300
    assert freshness["kalshi/worker-b"]["age_seconds"] == 7200

    transports = health["venues"]["kalshi"]["quote_freshness_by_transport"]
    assert transports["polling"]["age_seconds"] == 600
    assert transports["streaming"]["age_seconds"] == 120


def test_health_is_deterministic(db):
    match = _match(db)
    for outcome in ("home", "draw", "away"):
        market = _market(db, f"KX-{outcome}", mapped_to=match.id, outcome=outcome)
        _tick(db, market, ts=KICKOFF - timedelta(hours=1))

    assert build_health(db, now=NOW) == build_health(db, now=NOW)
