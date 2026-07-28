from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CaptureHeartbeat, VenueMarket, VenuePriceTick
from pipeline.report_market_coverage import build_coverage_report


NOW = datetime(2026, 7, 27, 10, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def market(db, key, **overrides):
    values = dict(venue="kalshi", venue_key=key, sport="football", market_type="match_winner", raw_title=key, mapping_status="unmapped", status="open", first_seen=NOW, last_seen=NOW)
    values.update(overrides)
    row = VenueMarket(**values)
    db.add(row); db.flush()
    return row


def test_zero_denominators_are_explicit(db):
    report = build_coverage_report(db)
    assert report["registry"]["markets"] == 0
    assert report["registry"]["mapping_coverage"] == 0
    assert report["raw_payloads"]["reference_coverage"] == 0


def test_filters_utc_boundaries_gaps_and_unresolved_drilldown(db):
    mapped = market(db, "MAPPED", mapping_status="mapped", canonical_event_id=7, canonical_outcome="home")
    unresolved = market(db, "UNRESOLVED", venue="polymarket", mapping_status="ambiguous", resolution_context={"candidate_event_ids": [7, 8]})
    db.add_all([
        VenuePriceTick(venue_market_id=mapped.id, ts=NOW, transport="polling", observation_key="cycle:1", raw_payload_ref="raw/1"),
        VenuePriceTick(venue_market_id=unresolved.id, ts=NOW, transport="polling", observation_key="cycle:2", raw_payload_ref=""),
        CaptureHeartbeat(worker="w", venue="kalshi", scheduled_cycle_at=NOW, completed_at=NOW, intended_cadence_seconds=60, markets_seen=1, success_count=1, error_count=0, retry_count=0, rate_limit_count=0, cycle_duration_ms=1),
        CaptureHeartbeat(worker="w", venue="kalshi", scheduled_cycle_at=NOW + timedelta(minutes=3), completed_at=NOW + timedelta(minutes=3), intended_cadence_seconds=60, markets_seen=1, success_count=0, error_count=1, retry_count=1, rate_limit_count=1, cycle_duration_ms=1),
    ])
    db.commit()

    report = build_coverage_report(db, start=NOW, end=NOW + timedelta(hours=1))
    assert report["registry"]["by_mapping_status"] == {"mapped": 1, "unmapped": 0, "ambiguous": 1}
    assert report["registry"]["mapping_coverage"] == 0.5
    assert report["capture"]["heartbeat_gap_count"] == 1
    assert report["raw_payloads"]["tick_refs_missing"] == 1
    assert report["unresolved"][0]["resolution_context"]["candidate_event_ids"] == [7, 8]

    filtered = build_coverage_report(db, venue="polymarket", status="ambiguous")
    assert filtered["registry"]["markets"] == 1
    assert filtered["capture"]["observed_ticks"] == 1


def test_settlement_completeness_is_separate_from_mapping(db):
    market(db, "DONE", status="settled", settled_at=NOW)
    market(db, "WAIT", status="closed")
    db.commit()
    report = build_coverage_report(db)
    assert report["settlements"] == {"closed_candidates": 2, "complete": 1, "incomplete": 1, "coverage": 0.5}
