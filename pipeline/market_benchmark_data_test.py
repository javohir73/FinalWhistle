"""Builder eligibility and exclusion accounting against a real schema."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Match,
    Prediction,
    Team,
    Tournament,
    VenueMarket,
    VenuePriceTick,
)
from pipeline.market_benchmark_data import build_observations

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


def _fixture(db, *, match_id=None, status="finished", home=2, away=1,
             kickoff=KICKOFF):
    tournament = db.query(Tournament).first()
    if tournament is None:
        tournament = Tournament(name="Premier League 2026-27", year=2026)
        arsenal, chelsea = Team(name="Arsenal"), Team(name="Chelsea")
        db.add_all([tournament, arsenal, chelsea])
        db.flush()
    teams = db.query(Team).order_by(Team.id).all()
    match = Match(tournament_id=tournament.id, stage="league",
                  team_home_id=teams[0].id, team_away_id=teams[1].id,
                  status=status, kickoff_utc=kickoff,
                  score_home=home if status == "finished" else None,
                  score_away=away if status == "finished" else None)
    db.add(match)
    db.commit()
    return match


def _prediction(db, match, *, created=None, shadow=False,
                probs=(0.5, 0.3, 0.2)):
    db.add(Prediction(
        match_id=match.id, model_version="poisson-elo-v0.5",
        created_at=created or (KICKOFF - timedelta(days=1)),
        prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
        is_shadow=shadow))
    db.commit()


def _markets(db, match, *, venue="kalshi", outcomes=("home", "draw", "away")):
    rows = []
    for outcome in outcomes:
        row = VenueMarket(
            venue=venue, venue_key=f"{venue}-{match.id}-{outcome}",
            sport="football", market_type="match_winner",
            raw_title="Arsenal v Chelsea", mapping_status="mapped",
            canonical_event_id=match.id, canonical_outcome=outcome,
            status="settled", first_seen=KICKOFF - timedelta(days=7),
            last_seen=KICKOFF)
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def _tick(db, market, *, ts=None, mid=0.35, transport="polling"):
    ts = ts or (KICKOFF - timedelta(hours=2))
    db.add(VenuePriceTick(
        venue_market_id=market.id, ts=ts, observed_at=ts, transport=transport,
        observation_key=f"cycle:{market.id}:{ts.isoformat()}",
        scheduled_cycle_at=ts, in_play_state_supported=False,
        yes_bid=None if mid is None else mid - 0.01,
        yes_ask=None if mid is None else mid + 0.01,
        mid=mid,
        raw_payload_ref="mem://raw"))
    db.commit()


def _complete(db, match, *, venue="kalshi", mids=(0.55, 0.30, 0.25)):
    markets = _markets(db, match, venue=venue)
    for market, mid in zip(markets, mids):
        _tick(db, market, mid=mid)
    return markets


def test_a_fully_eligible_fixture_becomes_one_observation(db):
    match = _fixture(db)
    _prediction(db, match)
    _complete(db, match)

    result = build_observations(db)

    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.match_id == match.id
    assert observation.outcome == "home"
    assert observation.venue_probs_raw == (0.55, 0.30, 0.25)
    assert observation.model_probs[0] == pytest.approx(0.5)
    assert result.exclusions == {}
    assert result.coverage["eligible_observations"] == 1


def test_incomplete_1x2_sets_are_excluded_and_named(db):
    match = _fixture(db)
    _prediction(db, match)
    markets = _markets(db, match, outcomes=("home", "draw"))
    for market in markets:
        _tick(db, market)

    result = build_observations(db)

    assert result.observations == []
    assert result.exclusions == {"incomplete_1x2_set": 1}
    assert any("missing mapped outcome(s): away" in n for n in result.notes)


def test_conflicting_duplicate_outcomes_exclude_the_group(db):
    match = _fixture(db)
    _prediction(db, match)
    _complete(db, match)
    extra = VenueMarket(
        venue="kalshi", venue_key=f"kalshi-{match.id}-home-dup",
        sport="football", market_type="match_winner", raw_title="dup",
        mapping_status="mapped", canonical_event_id=match.id,
        canonical_outcome="home", status="settled",
        first_seen=KICKOFF - timedelta(days=7), last_seen=KICKOFF)
    db.add(extra)
    db.commit()

    result = build_observations(db)

    assert result.observations == []
    assert result.exclusions == {"conflicting_duplicate_outcome": 1}


def test_unfinished_or_scoreless_fixtures_are_excluded(db):
    match = _fixture(db, status="in_play")
    _prediction(db, match)
    _complete(db, match)

    scoreless = _fixture(db, kickoff=KICKOFF + timedelta(days=7))
    db.query(Match).filter_by(id=scoreless.id).update({"score_home": None})
    db.commit()
    _prediction(db, scoreless)
    _complete(db, scoreless, mids=(0.5, 0.31, 0.27))

    result = build_observations(db)

    assert result.observations == []
    assert result.exclusions == {"no_final_outcome": 2}


def test_post_kickoff_ticks_never_become_the_snapshot(db):
    """The latest PRE-kickoff tick wins; anything after kickoff is invisible
    even when it is newer."""
    match = _fixture(db)
    _prediction(db, match)
    markets = _markets(db, match)
    for market, mid in zip(markets, (0.55, 0.30, 0.25)):
        _tick(db, market, ts=KICKOFF - timedelta(hours=3), mid=mid)
        _tick(db, market, ts=KICKOFF + timedelta(minutes=30), mid=0.99,
              transport="streaming")

    result = build_observations(db)

    assert len(result.observations) == 1
    assert result.observations[0].venue_probs_raw == (0.55, 0.30, 0.25)


def test_missing_and_one_sided_and_stale_quotes_are_excluded(db):
    no_quote = _fixture(db)
    _prediction(db, no_quote)
    _markets(db, no_quote)

    one_sided = _fixture(db, kickoff=KICKOFF + timedelta(days=7))
    _prediction(db, one_sided)
    for market in _markets(db, one_sided, venue="polymarket"):
        _tick(db, market, ts=one_sided.kickoff_utc - timedelta(hours=1),
              mid=None)

    stale = _fixture(db, kickoff=KICKOFF + timedelta(days=14))
    _prediction(db, stale)
    for market in _markets(db, stale, venue="stalevenue"):
        _tick(db, market, ts=stale.kickoff_utc - timedelta(days=5), mid=0.33)

    result = build_observations(db)

    assert result.observations == []
    assert result.exclusions == {
        "no_prekickoff_quote": 1,
        "no_two_sided_quote": 1,
        "stale_prekickoff_quote": 1,
    }


def test_shadow_and_post_kickoff_predictions_do_not_count(db):
    match = _fixture(db)
    _complete(db, match)
    _prediction(db, match, shadow=True)
    _prediction(db, match, created=KICKOFF + timedelta(hours=1))

    result = build_observations(db)

    assert result.observations == []
    assert result.exclusions == {"no_prekickoff_prediction": 1}


def test_an_implausible_book_is_excluded_not_normalized(db):
    match = _fixture(db)
    _prediction(db, match)
    _complete(db, match, mids=(0.7, 0.5, 0.4))  # sum 1.6

    result = build_observations(db)

    assert result.observations == []
    assert result.exclusions == {"invalid_observation": 1}
    assert any("book sum" in n for n in result.notes)


def test_proposed_and_ambiguous_mappings_never_enter(db):
    match = _fixture(db)
    _prediction(db, match)
    for status in ("proposed", "ambiguous", "unmapped"):
        db.add(VenueMarket(
            venue="kalshi", venue_key=f"kalshi-{status}",
            sport="football", market_type="match_winner", raw_title="x",
            mapping_status=status, canonical_event_id=None,
            canonical_outcome=None, status="open",
            first_seen=KICKOFF, last_seen=KICKOFF))
    db.commit()

    result = build_observations(db)

    assert result.observations == []
    assert result.coverage["mapped_fixture_venue_groups"] == 0


def test_two_venues_for_one_match_give_two_observations(db):
    match = _fixture(db)
    _prediction(db, match)
    _complete(db, match, venue="kalshi")
    _complete(db, match, venue="polymarket", mids=(0.5, 0.31, 0.27))

    result = build_observations(db)

    assert {o.venue for o in result.observations} == {"kalshi", "polymarket"}
    assert all(o.match_id == match.id for o in result.observations)


def test_the_build_is_deterministic(db):
    for offset in range(3):
        match = _fixture(db, kickoff=KICKOFF + timedelta(days=offset))
        _prediction(db, match)
        _complete(db, match)

    first = build_observations(db)
    second = build_observations(db)

    assert [(o.venue, o.match_id) for o in first.observations] == \
        [(o.venue, o.match_id) for o in second.observations]
    assert first.exclusions == second.exclusions
    assert first.notes == second.notes


def test_the_full_artifact_is_deterministic_and_marked_experimental(db):
    """CLI-level contract: same DB, same clock, same seed -> byte-identical
    artifact, carrying lineage, exclusions and health."""
    import json

    from pipeline.run_market_benchmark_report import build_artifact

    for offset in range(4):
        match = _fixture(db, kickoff=KICKOFF + timedelta(days=offset))
        _prediction(db, match)
        _complete(db, match)
    now = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    first = build_artifact(db, holdout_fraction=0.3, min_matches=50,
                           n_bootstrap=100, seed=1, now=now)
    second = build_artifact(db, holdout_fraction=0.3, min_matches=50,
                            n_bootstrap=100, seed=1, now=now)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["experimental"] is True
    assert "not a deployment signal" in first["role"]
    assert first["lineage"]["outcome_side"].startswith("Match full-time")
    assert first["benchmark"]["groups"][0]["status"] == "NOT_READY"
    assert first["health"]["denominator"] == "fixtures and markets, never ticks"
