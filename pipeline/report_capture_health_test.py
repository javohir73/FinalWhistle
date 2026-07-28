from datetime import datetime, timedelta, timezone

import pytest

from app.models import CaptureHeartbeat, VenueMarket, VenuePriceTick
from pipeline.report_capture_health import build_capture_health

NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)


def _market(db, key, **kwargs):
    row = VenueMarket(
        venue="kalshi",
        venue_key=key,
        sport="football",
        market_type="moneyline",
        raw_title=key,
        mapping_status=kwargs.pop("mapping_status", "unmapped"),
        status=kwargs.pop("status", "open"),
        first_seen=NOW - timedelta(days=2),
        last_seen=NOW,
        **kwargs,
    )
    db.add(row)
    db.flush()
    return row


def _heartbeat(db, at, **kwargs):
    row = CaptureHeartbeat(
        worker="worker-1",
        venue="kalshi",
        scheduled_cycle_at=at,
        completed_at=at + timedelta(seconds=1),
        intended_cadence_seconds=30,
        markets_seen=2,
        success_count=kwargs.pop("success_count", 1),
        error_count=kwargs.pop("error_count", 0),
        retry_count=kwargs.pop("retry_count", 0),
        rate_limit_count=kwargs.pop("rate_limit_count", 0),
        cycle_duration_ms=1000,
        errors=kwargs.pop("errors", None),
        **kwargs,
    )
    db.add(row)
    return row


def test_report_aggregates_coverage_gaps_errors_staleness_and_settlement(db_session):
    active = _market(db_session, "ACTIVE", mapping_status="mapped")
    _market(
        db_session,
        "CLOSED",
        status="closed",
        closed_at=NOW - timedelta(days=2),
    )
    db_session.add(
        VenuePriceTick(
            venue_market_id=active.id,
            ts=NOW - timedelta(minutes=2),
            transport="polling",
            observation_key="cycle:1",
            scheduled_cycle_at=NOW - timedelta(minutes=2),
            raw_payload_ref="memory://quote",
            validation_flags=["stale_source_timestamp"],
        )
    )
    _heartbeat(db_session, NOW - timedelta(minutes=3))
    _heartbeat(
        db_session,
        NOW - timedelta(minutes=1),
        success_count=0,
        error_count=1,
        retry_count=2,
        rate_limit_count=1,
        errors=[
            {"category": "raw_store", "message": "offline"},
            {"category": "rate_limit", "message": "429"},
        ],
    )
    db_session.commit()

    report = build_capture_health(
        db_session,
        start=NOW - timedelta(hours=1),
        end=NOW,
        now=NOW,
    )["venues"]["kalshi"]

    assert report["markets_discovered"] == 2
    assert (report["mapped"], report["unmapped"]) == (1, 1)
    assert (report["intended_ticks"], report["observed_ticks"]) == (2, 1)
    assert report["heartbeat_gaps"] == 1
    assert report["estimated_missed_cycles"] == 3
    assert report["adapter_errors"] == 1
    assert report["retries"] == 2
    assert report["rate_limits"] == 1
    assert report["raw_payload_failures"] == 1
    assert report["stale_ticks"] == 1
    assert report["unsettled_exceptions"][0]["venue_key"] == "CLOSED"


def test_report_uses_half_open_utc_window_and_handles_empty_database(db_session):
    assert build_capture_health(
        db_session, start=NOW - timedelta(hours=1), end=NOW, now=NOW
    )["venues"] == {}

    with pytest.raises(ValueError, match="later"):
        build_capture_health(db_session, start=NOW, end=NOW)
