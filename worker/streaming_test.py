"""Stream guard, stream persistence, and reconnect control. No network."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import VenueMarket as VenueMarketRow, VenuePriceTick
from pipeline.ingest.venues.types import (
    OrderBook,
    OrderBookLevel,
    Quote,
    VenuePayloadError,
)
from worker.capture_test import MemoryRawStore
from worker.streaming import StreamGuard, StreamSupervisor, persist_stream_quote

NOW = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.add(VenueMarketRow(
        venue="kalshi", venue_key="KX-1", sport="football",
        market_type="match_winner", raw_title="Arsenal v Chelsea",
        mapping_status="unmapped", status="open", first_seen=NOW, last_seen=NOW))
    session.commit()
    yield session
    session.close()


def _quote(*, transport="streaming", event_id="seq-1", source_ts=NOW,
           observed_at=NOW, bid=0.44, key="KX-1"):
    return Quote(
        venue="kalshi", venue_key=key, observed_at=observed_at, transport=transport,
        book=OrderBook(yes_bids=(OrderBookLevel(bid, 10),),
                       yes_asks=(OrderBookLevel(0.48, 10),)),
        source_ts=source_ts, source_event_id=event_id,
        raw_payload={"e": event_id},
    )


# --- the guard --------------------------------------------------------------


def test_a_repeated_event_id_is_refused_before_persistence():
    guard = StreamGuard()
    assert guard.observe(_quote()).accepted is True

    decision = guard.observe(_quote())
    assert (decision.accepted, decision.duplicate) == (False, True)


def test_a_sequence_gap_is_reported_without_dropping_the_update():
    guard = StreamGuard()
    guard.observe(_quote(event_id="seq-1"), sequence=10)

    decision = guard.observe(_quote(event_id="seq-4"), sequence=14)

    assert decision.accepted is True
    assert decision.missing_sequence == (11, 13)


def test_a_replayed_sequence_is_out_of_order_not_a_new_observation():
    guard = StreamGuard()
    guard.observe(_quote(event_id="seq-2"), sequence=11)

    decision = guard.observe(_quote(event_id="seq-1"), sequence=10)

    assert (decision.accepted, decision.out_of_order) == (False, True)


def test_a_backwards_venue_timestamp_is_refused_when_there_is_no_sequence():
    guard = StreamGuard()
    guard.observe(_quote(event_id="seq-2", source_ts=NOW))

    decision = guard.observe(
        _quote(event_id="seq-1", source_ts=NOW - timedelta(seconds=5)))

    assert (decision.accepted, decision.out_of_order) == (False, True)


def test_each_market_keeps_its_own_cursor():
    guard = StreamGuard()
    guard.observe(_quote(event_id="seq-1"), sequence=10)

    decision = guard.observe(_quote(key="KX-2", event_id="seq-1"), sequence=1)

    assert decision.accepted is True


# --- persistence ------------------------------------------------------------


def test_a_stream_tick_lands_with_arrival_time_and_declared_state(db_session):
    arrived = NOW + timedelta(milliseconds=900)
    written = persist_stream_quote(
        db_session, MemoryRawStore(), _quote(observed_at=arrived))

    assert written is True
    tick = db_session.query(VenuePriceTick).one()
    assert tick.transport == "streaming"
    assert tick.observation_key == "event:seq-1"
    assert (tick.observed_at - tick.source_ts).total_seconds() == 0.9
    assert (tick.ts - tick.source_ts).total_seconds() == 0
    assert tick.in_play_state_supported is False
    assert tick.scheduled_cycle_at is None


def test_recovery_redelivery_of_a_streamed_event_is_discarded(db_session):
    """The cross-transport property. One venue event is one observation, and
    a gap-recovery fetch of something the stream already delivered must not
    become a second row."""
    store = MemoryRawStore()
    assert persist_stream_quote(db_session, store, _quote()) is True

    written = persist_stream_quote(
        db_session, store,
        _quote(transport="recovery", observed_at=NOW + timedelta(minutes=30),
               bid=0.46))

    assert written is False
    tick = db_session.query(VenuePriceTick).one()
    assert tick.transport == "streaming", "first delivery keeps the provenance"
    assert tick.yes_bid == pytest.approx(0.44), "the stored observation is untouched"


def test_a_recovery_only_event_is_stored_and_stays_labelled(db_session):
    """Rows reading `recovery` are exactly the events the stream missed."""
    persist_stream_quote(db_session, MemoryRawStore(),
                         _quote(transport="recovery", event_id="seq-9"))

    tick = db_session.query(VenuePriceTick).one()
    assert (tick.transport, tick.observation_key) == ("recovery", "event:seq-9")


def test_distinct_events_at_the_same_venue_timestamp_are_both_kept(db_session):
    store = MemoryRawStore()
    persist_stream_quote(db_session, store, _quote(event_id="seq-1"))
    persist_stream_quote(db_session, store, _quote(event_id="seq-2"))

    assert db_session.query(VenuePriceTick).count() == 2


@pytest.mark.parametrize("kwargs,message", [
    ({"event_id": None}, "source_event_id"),
    ({"source_ts": None}, "source_ts"),
])
def test_an_event_without_stable_identity_is_refused(db_session, kwargs, message):
    """Not hashed, not stamped with arrival time. Either would make the next
    redelivery look like a new observation."""
    with pytest.raises(VenuePayloadError, match=message):
        persist_stream_quote(db_session, MemoryRawStore(), _quote(**kwargs))

    assert db_session.query(VenuePriceTick).count() == 0


def test_polling_transport_is_refused_by_the_stream_path(db_session):
    with pytest.raises(ValueError, match="streaming or recovery"):
        persist_stream_quote(db_session, MemoryRawStore(),
                             _quote(transport="polling"))


def test_an_undiscovered_market_is_refused(db_session):
    with pytest.raises(ValueError, match="undiscovered venue market"):
        persist_stream_quote(db_session, MemoryRawStore(), _quote(key="KX-UNKNOWN"))


def test_the_raw_payload_is_stored_under_its_delivery_path(db_session):
    store = MemoryRawStore()
    persist_stream_quote(db_session, store, _quote())
    persist_stream_quote(db_session, store,
                         _quote(transport="recovery", event_id="seq-2"))

    assert [obj["kind"] for obj in store.objects] == ["stream", "stream-recovery"]


# --- supervisor -------------------------------------------------------------


def test_reconnect_until_the_limit_then_fall_back_to_polling():
    calls = []
    supervisor = StreamSupervisor(retry_limit=2, fallback_poll=lambda v: calls.append(v))

    assert supervisor.after_disconnect("kalshi", 1)["action"] == "reconnect"
    assert supervisor.after_disconnect("kalshi", 2)["action"] == "reconnect"
    assert supervisor.after_disconnect("kalshi", 3)["action"] == "polling_fallback"
    assert calls == ["kalshi"]


def test_a_gap_with_no_backfill_endpoint_is_reported_as_permanent():
    supervisor = StreamSupervisor(retry_limit=1, fallback_poll=lambda _v: None)

    result = supervisor.recover("kalshi", [("KX-1", 11, 13)])

    assert result["recovered"] == 0
    assert result["permanent_gaps"][0]["venue_key"] == "KX-1"


def test_a_backfilled_gap_reports_what_it_recovered():
    supervisor = StreamSupervisor(
        retry_limit=1, fallback_poll=lambda _v: None,
        backfill=lambda _venue, _key, start, end: end - start + 1)

    assert supervisor.recover("kalshi", [("KX-1", 11, 13)])["recovered"] == 3
