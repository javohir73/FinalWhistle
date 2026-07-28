from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import VenueMarket, VenuePriceTick
from pipeline.ingest.venues.types import OrderBook, OrderBookLevel, Quote
from worker.raw_store import FileRawPayloadStore
from worker.streaming import StreamGuard, StreamSupervisor, persist_stream_quote

NOW = datetime(2026, 7, 27, 10, tzinfo=timezone.utc)


def quote(event="1", *, at=NOW):
    return Quote(venue="polymarket", venue_key="P1", observed_at=at, source_ts=at, source_event_id=event, transport="streaming", book=OrderBook((OrderBookLevel(.4, 2),), (OrderBookLevel(.5, 3),)), raw_payload={"event": event})


def test_guard_accepts_detects_duplicate_gap_and_out_of_order():
    guard = StreamGuard()
    assert guard.observe(quote("10"), sequence=10).accepted
    assert guard.observe(quote("10"), sequence=10).duplicate
    gap = guard.observe(quote("13", at=NOW + timedelta(seconds=1)), sequence=13)
    assert gap.accepted and gap.missing_sequence == (11, 12)
    assert guard.observe(quote("12", at=NOW + timedelta(seconds=2)), sequence=12).out_of_order


def test_guard_uses_timestamp_when_venue_has_no_sequence():
    guard = StreamGuard()
    assert guard.observe(quote("a"), sequence=None).accepted
    assert guard.observe(quote("b", at=NOW - timedelta(seconds=1)), sequence=None).out_of_order


def test_stream_and_recovery_use_normalized_tick_path(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(VenueMarket(venue="polymarket", venue_key="P1", sport="football", market_type="match_winner", raw_title="A v B", mapping_status="unmapped", status="open", first_seen=NOW, last_seen=NOW))
    db.commit()
    store = FileRawPayloadStore(tmp_path)
    assert persist_stream_quote(db, store, quote(), sequence=1)
    assert not persist_stream_quote(db, store, quote(), sequence=1)
    assert db.query(VenuePriceTick).one().transport == "streaming"


def test_supervisor_reconnect_backfill_and_polling_fallback():
    polls = []
    supervisor = StreamSupervisor(retry_limit=2, fallback_poll=lambda venue: polls.append(venue) or "ok")
    assert supervisor.after_disconnect("polymarket", 1)["action"] == "reconnect"
    assert supervisor.after_disconnect("polymarket", 3)["action"] == "polling_fallback"
    assert polls == ["polymarket"]
    result = supervisor.recover("polymarket", [("P1", 11, 12)])
    assert result["permanent_gaps"][0]["cause"] == "venue history endpoint unavailable"
