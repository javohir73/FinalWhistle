"""Schema contract for the additive prediction-market capture tables."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    CanonicalEntity,
    CaptureHeartbeat,
    EntitySourceMap,
    MarketOddsSnapshot,
    VenueMarket,
    VenuePriceTick,
)

NOW = datetime(2026, 7, 26, 5, 0, tzinfo=timezone.utc)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, future=True)()


def _market(**overrides):
    values = {
        "venue": "kalshi",
        "venue_key": "KX-1",
        "sport": "football",
        "market_type": "match_winner",
        "raw_title": "France v Morocco",
        "mapping_status": "unmapped",
        "status": "open",
        "first_seen": NOW,
        "last_seen": NOW,
    }
    values.update(overrides)
    return VenueMarket(**values)


def _tick(market_id, **overrides):
    values = {
        "venue_market_id": market_id,
        "ts": NOW,
        "transport": "polling",
        "observation_key": "cycle:2026-07-26T05:00:00+00:00",
        "scheduled_cycle_at": NOW,
        "yes_bid": 0.44,
        "yes_ask": 0.48,
        "last": 0.46,
        "mid": 0.46,
        "bid_size": 3.0,
        "ask_size": 2.0,
        "book_top_n": {"yes_bids": [[0.44, 3.0]], "yes_asks": [[0.48, 2.0]]},
        "raw_payload_ref": "raw/kalshi/KX-1/2026-07-26T05:00:00Z.json",
    }
    values.update(overrides)
    return VenuePriceTick(**values)


def test_all_five_capture_tables_build_alongside_legacy_table():
    engine, _db = _session()
    tables = set(inspect(engine).get_table_names())

    assert {
        "canonical_entity",
        "entity_source_map",
        "venue_market",
        "venue_price_tick",
        "capture_heartbeat",
        "market_odds_snapshots",
    }.issubset(tables)


def test_capture_foreign_keys_and_operational_indexes_exist():
    engine, _db = _session()
    schema = inspect(engine)
    entity_fks = schema.get_foreign_keys("entity_source_map")
    tick_fks = schema.get_foreign_keys("venue_price_tick")
    market_indexes = {item["name"] for item in schema.get_indexes("venue_market")}
    tick_indexes = {item["name"] for item in schema.get_indexes("venue_price_tick")}
    heartbeat_indexes = {
        item["name"] for item in schema.get_indexes("capture_heartbeat")
    }

    assert any(fk["referred_table"] == "canonical_entity" for fk in entity_fks)
    assert any(fk["referred_table"] == "venue_market" for fk in tick_fks)
    assert "ix_venue_market_mapping_coverage" in market_indexes
    assert "ix_venue_market_settlement_queue" in market_indexes
    assert "ix_venue_price_tick_market_ts" in tick_indexes
    assert "ix_venue_price_tick_transport_ts" in tick_indexes
    assert "ix_capture_heartbeat_venue_cycle" in heartbeat_indexes


def test_capture_timestamps_are_declared_timezone_aware():
    columns = [
        VenueMarket.__table__.c.first_seen,
        VenueMarket.__table__.c.last_seen,
        VenuePriceTick.__table__.c.ts,
        VenuePriceTick.__table__.c.source_ts,
        CaptureHeartbeat.__table__.c.scheduled_cycle_at,
        CaptureHeartbeat.__table__.c.completed_at,
    ]

    assert all(column.type.timezone is True for column in columns)


def test_canonical_entity_identity_is_unique_and_kind_is_constrained():
    _engine, db = _session()
    db.add(CanonicalEntity(sport="football", kind="team", canonical_name="France"))
    db.commit()

    db.add(CanonicalEntity(sport="football", kind="team", canonical_name="France"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(CanonicalEntity(sport="football", kind="player", canonical_name="Player"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_source_key_maps_to_only_one_entity_but_is_scoped_by_source():
    _engine, db = _session()
    france = CanonicalEntity(sport="football", kind="team", canonical_name="France")
    morocco = CanonicalEntity(sport="football", kind="team", canonical_name="Morocco")
    db.add_all([france, morocco])
    db.flush()
    db.add_all(
        [
            EntitySourceMap(
                entity_id=france.id,
                source="kalshi",
                source_key="FRA",
                confidence=1.0,
                verified_at=NOW,
                verified_by="fixture",
            ),
            EntitySourceMap(
                entity_id=morocco.id,
                source="polymarket",
                source_key="FRA",
                confidence=0.9,
                verified_at=NOW,
                verified_by="fixture",
            ),
        ]
    )
    db.commit()

    db.add(
        EntitySourceMap(
            entity_id=morocco.id,
            source="kalshi",
            source_key="FRA",
            confidence=1.0,
            verified_at=NOW,
            verified_by="fixture",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_source_mapping_confidence_is_bounded(confidence):
    _engine, db = _session()
    entity = CanonicalEntity(sport="football", kind="team", canonical_name="France")
    db.add(entity)
    db.flush()
    db.add(
        EntitySourceMap(
            entity_id=entity.id,
            source="kalshi",
            source_key="FRA",
            confidence=confidence,
            verified_at=NOW,
            verified_by="fixture",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_venue_market_identity_and_mapping_status_are_constrained():
    _engine, db = _session()
    db.add(_market())
    db.commit()

    db.add(_market(raw_title="A renamed title"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(_market(venue_key="KX-2", mapping_status="guessed"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": ""},
        {"first_seen": NOW, "last_seen": NOW - timedelta(seconds=1)},
        {"opened_at": NOW, "closed_at": NOW - timedelta(seconds=1)},
    ],
)
def test_venue_market_rejects_empty_status_or_invalid_lifecycle(overrides):
    _engine, db = _session()
    db.add(_market(**overrides))

    with pytest.raises(IntegrityError):
        db.commit()


def test_unmapped_market_and_settlement_history_roundtrip():
    _engine, db = _session()
    market = _market(
        raw_title="",
        status="settled",
        settled_at=NOW,
        settled_outcome="yes",
        settlement_source="markets/KX-1",
        settlement_history=[
            {"status": "settled", "outcome": "no", "observed_at": NOW.isoformat()}
        ],
    )
    db.add(market)
    db.commit()

    stored = db.query(VenueMarket).one()
    assert stored.mapping_status == "unmapped"
    assert stored.raw_title == ""
    assert stored.settlement_history[0]["outcome"] == "no"


def test_resolution_context_and_mapping_history_roundtrip():
    _engine, db = _session()
    market = _market(
        mapping_status="ambiguous",
        resolution_context={"reason": "multiple fixtures", "candidate_event_ids": [1, 2]},
        mapping_history=[{"from": "unmapped", "to": "ambiguous", "verified_by": "operator"}],
    )
    db.add(market)
    db.commit()

    stored = db.query(VenueMarket).one()
    assert stored.resolution_context["candidate_event_ids"] == [1, 2]
    assert stored.mapping_history[0]["from"] == "unmapped"


def test_distinct_ticks_are_appendable_but_exact_replay_is_rejected():
    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add(_tick(market.id))
    db.add(
        _tick(
            market.id,
            ts=NOW + timedelta(minutes=1),
            observation_key="cycle:2026-07-26T05:01:00+00:00",
            scheduled_cycle_at=NOW + timedelta(minutes=1),
            mid=0.47,
        )
    )
    db.commit()

    assert db.query(VenuePriceTick).count() == 2
    db.add(_tick(market.id, mid=0.45))
    with pytest.raises(IntegrityError):
        db.commit()


def test_distinct_stream_events_at_same_timestamp_are_preserved():
    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add_all(
        [
            _tick(
                market.id,
                transport="streaming",
                observation_key="event:41",
                source_event_id="41",
                scheduled_cycle_at=None,
            ),
            _tick(
                market.id,
                transport="streaming",
                observation_key="event:42",
                source_event_id="42",
                scheduled_cycle_at=None,
            ),
        ]
    )
    db.commit()

    assert db.query(VenuePriceTick).count() == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"yes_bid": -0.01},
        {"yes_ask": 1.01},
        {"last": 1.01},
        {"mid": -0.01},
        {"yes_bid": 0.51, "yes_ask": 0.50},
        {"bid_size": 0},
        {"ask_size": -1},
        {"transport": "batch"},
    ],
)
def test_tick_rejects_invalid_normalized_values(overrides):
    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add(_tick(market.id, **overrides))

    with pytest.raises(IntegrityError):
        db.commit()


def test_heartbeat_cycle_is_unique_and_counts_are_nonnegative():
    _engine, db = _session()
    values = {
        "worker": "capture-1",
        "venue": "kalshi",
        "scheduled_cycle_at": NOW,
        "completed_at": NOW + timedelta(seconds=2),
        "intended_cadence_seconds": 60,
        "markets_seen": 8,
        "success_count": 7,
        "error_count": 1,
        "retry_count": 1,
        "rate_limit_count": 0,
        "cycle_duration_ms": 2000,
        "errors": [{"venue_key": "KX-8", "code": "timeout"}],
    }
    db.add(CaptureHeartbeat(**values))
    db.commit()

    db.add(CaptureHeartbeat(**values))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(CaptureHeartbeat(**{**values, "scheduled_cycle_at": NOW + timedelta(minutes=1), "error_count": -1}))
    with pytest.raises(IntegrityError):
        db.commit()


def test_heartbeat_cannot_complete_before_its_cycle():
    _engine, db = _session()
    db.add(
        CaptureHeartbeat(
            worker="capture-1",
            venue="kalshi",
            scheduled_cycle_at=NOW,
            completed_at=NOW - timedelta(milliseconds=1),
            intended_cadence_seconds=60,
            cycle_duration_ms=0,
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_unsupported_in_play_state_cannot_carry_match_detail():
    """A venue that reports no live state may not imply one at the row level.

    The contract refuses this too, but the constraint is what makes it true of
    every writer, including one that assembles columns by hand.
    """
    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add(_tick(market.id, in_play_state_supported=False, home_score=0, away_score=0))

    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"in_play_state_supported": True, "home_score": 1},
        {"in_play_state_supported": True, "away_cards": 1},
        {"in_play_state_supported": True, "home_score": -1, "away_score": 0},
        {"in_play_state_supported": True, "home_cards": 0, "away_cards": -1},
        {"in_play_state_supported": True, "minute": -1.0},
        {"in_play_state_supported": False, "clock_state": "63'"},
        {"in_play_state_supported": False, "is_in_play": True},
    ],
)
def test_tick_rejects_incoherent_in_play_state(overrides):
    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add(_tick(market.id, **overrides))

    with pytest.raises(IntegrityError):
        db.commit()


def test_supported_but_unreported_state_is_storable_and_distinct():
    """Three cases, three rows: unsupported, supported-and-silent, reported."""
    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add_all([
        _tick(market.id, observation_key="cycle:a", in_play_state_supported=False),
        _tick(market.id, observation_key="cycle:b", in_play_state_supported=True),
        _tick(market.id, observation_key="cycle:c", in_play_state_supported=True,
              is_in_play=True, clock_state="63'", period="second_half",
              minute=63.0, home_score=1, away_score=1, home_cards=2, away_cards=0),
    ])
    db.commit()

    rows = {row.observation_key: row for row in db.query(VenuePriceTick)}
    assert rows["cycle:a"].in_play_state_supported is False
    assert rows["cycle:b"].in_play_state_supported is True
    assert rows["cycle:b"].home_score is None
    assert rows["cycle:c"].home_score == 1 and rows["cycle:c"].away_cards == 0


def test_in_play_contract_maps_onto_the_tick_columns_exactly():
    """The contract's column mapping and the table cannot drift apart."""
    from pipeline.ingest.venues import InPlayState

    state = InPlayState(supported=True, is_in_play=True, clock_label="63'",
                        period="second_half", minute=63, score=(1, 1), cards=(2, 0))
    columns = state.as_columns()
    assert set(columns) <= set(VenuePriceTick.__table__.c.keys())

    _engine, db = _session()
    market = _market()
    db.add(market)
    db.flush()
    db.add(_tick(market.id, **columns))
    db.commit()

    stored = db.query(VenuePriceTick).one()
    assert (stored.home_score, stored.away_score) == (1, 1)
    assert (stored.home_cards, stored.away_cards) == (2, 0)
    assert stored.minute == 63.0


def test_legacy_market_snapshot_still_roundtrips_unchanged():
    _engine, db = _session()
    db.add(
        MarketOddsSnapshot(
            sport="football",
            source="kalshi",
            market_type="match_winner",
            match_id=7,
            team_id=None,
            outcome="home",
            implied_prob=0.62,
            external_id="legacy-KX-1",
            fetched_at=NOW,
        )
    )
    db.commit()

    assert db.query(MarketOddsSnapshot).one().implied_prob == 0.62
