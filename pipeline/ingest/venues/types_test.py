"""Contract tests for the venue value objects. Hermetic: no network, no DB."""

from datetime import datetime, timedelta, timezone

import pytest

from pipeline.ingest.venues import (
    UNSUPPORTED_IN_PLAY,
    InPlayState,
    OrderBook,
    OrderBookLevel,
    Quote,
    Settlement,
    VenueMarket,
    VenuePayloadError,
    heartbeat_identity,
    tick_identity,
)

NOW = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)


def _quote(**overrides) -> Quote:
    values = {
        "venue": "kalshi",
        "venue_key": "KX-BUN-BAY-BVB",
        "observed_at": NOW,
        "transport": "polling",
    }
    values.update(overrides)
    return Quote(**values)


# --- identity: polling ------------------------------------------------------


def test_polling_identity_uses_the_scheduled_cycle_not_completion_time():
    first = tick_identity(_quote(observed_at=NOW + timedelta(seconds=2)),
                          scheduled_cycle_at=NOW)
    retry = tick_identity(_quote(observed_at=NOW + timedelta(seconds=47)),
                          scheduled_cycle_at=NOW)

    assert first == retry
    assert first.ts == NOW
    assert first.observation_key == "cycle:2026-10-03T14:30:00+00:00"


def test_polling_identity_ignores_a_venue_event_id():
    """Transport decides the key shape; field presence does not.

    A venue that mints a fresh event id on every poll would otherwise turn one
    retried cycle into two rows.
    """
    first = tick_identity(
        _quote(source_event_id="evt-1", source_ts=NOW), scheduled_cycle_at=NOW)
    retry = tick_identity(
        _quote(source_event_id="evt-2", source_ts=NOW), scheduled_cycle_at=NOW)

    assert first == retry
    assert first.observation_key.startswith("cycle:")


def test_polling_identity_requires_a_scheduled_cycle():
    with pytest.raises(VenuePayloadError, match="scheduled_cycle_at"):
        tick_identity(_quote())


def test_polling_identity_normalizes_the_cycle_to_utc():
    berlin = timezone(timedelta(hours=2))
    identity = tick_identity(
        _quote(), scheduled_cycle_at=NOW.astimezone(berlin))

    assert identity.ts == NOW
    assert identity.observation_key == "cycle:2026-10-03T14:30:00+00:00"


def test_polling_identity_rejects_a_naive_cycle():
    with pytest.raises(VenuePayloadError, match="timezone-aware"):
        tick_identity(_quote(), scheduled_cycle_at=NOW.replace(tzinfo=None))


# --- identity: streaming ----------------------------------------------------


@pytest.mark.parametrize("transport", ["streaming", "recovery"])
def test_stream_identity_is_stable_across_arrival_times(transport):
    """The blocker this contract exists for.

    A redelivered event is the same observation. Keying on arrival time gives
    the second copy a fresh primary key, so the uniqueness constraint never
    fires and the duplicate is invisible.
    """
    delivered = _quote(transport=transport, observed_at=NOW,
                       source_ts=NOW, source_event_id="seq-9001")
    redelivered = _quote(transport=transport,
                         observed_at=NOW + timedelta(minutes=4),
                         source_ts=NOW, source_event_id="seq-9001")

    assert tick_identity(delivered) == tick_identity(redelivered)
    assert tick_identity(delivered).ts == NOW
    assert tick_identity(delivered).observation_key == "event:seq-9001"


def test_stream_identity_rejects_a_quote_without_a_venue_event_id():
    with pytest.raises(VenuePayloadError, match="source_event_id"):
        tick_identity(_quote(transport="streaming", source_ts=NOW))


def test_stream_identity_rejects_a_quote_without_a_venue_timestamp():
    with pytest.raises(VenuePayloadError, match="source_ts"):
        tick_identity(_quote(transport="streaming", source_event_id="seq-1"))


def test_stream_identity_ignores_a_scheduled_cycle():
    identity = tick_identity(
        _quote(transport="recovery", source_ts=NOW, source_event_id="seq-3"),
        scheduled_cycle_at=NOW + timedelta(hours=5))

    assert identity.ts == NOW
    assert identity.observation_key == "event:seq-3"


def test_distinct_stream_events_keep_distinct_identities():
    one = tick_identity(_quote(transport="streaming", source_ts=NOW,
                               source_event_id="seq-1"))
    two = tick_identity(_quote(transport="streaming", source_ts=NOW,
                               source_event_id="seq-2"))

    assert one != two


# --- heartbeat identity -----------------------------------------------------


def test_heartbeat_identity_normalizes_and_requires_its_parts():
    identity = heartbeat_identity("worker-a", "kalshi", NOW)
    assert (identity.worker, identity.venue, identity.scheduled_cycle_at) == (
        "worker-a", "kalshi", NOW)

    with pytest.raises(VenuePayloadError):
        heartbeat_identity("  ", "kalshi", NOW)
    with pytest.raises(VenuePayloadError):
        heartbeat_identity("worker-a", "kalshi", NOW.replace(tzinfo=None))


# --- in-play state ----------------------------------------------------------


def test_quote_defaults_to_unsupported_in_play_state():
    """Fail closed: silence from an adapter is not a claim about the match."""
    assert _quote().in_play == UNSUPPORTED_IN_PLAY
    assert _quote().in_play.supported is False


def test_unsupported_state_may_not_carry_match_detail():
    with pytest.raises(VenuePayloadError, match="live match detail"):
        InPlayState(supported=False, score=(1, 0))
    with pytest.raises(VenuePayloadError, match="live match detail"):
        InPlayState(supported=False, is_in_play=True)


def test_supported_but_unreported_is_distinct_from_unsupported():
    """The three cases a single nullable column collapses into one."""
    unsupported = InPlayState(supported=False)
    reported_nothing = InPlayState(supported=True)
    reported = InPlayState(supported=True, score=(2, 1), cards=(1, 0))

    assert unsupported != reported_nothing
    assert unsupported.as_columns()["in_play_state_supported"] is False
    assert reported_nothing.as_columns()["in_play_state_supported"] is True
    assert reported_nothing.as_columns()["home_score"] is None
    assert reported.as_columns()["home_score"] == 2
    assert reported.as_columns()["away_cards"] == 0


def test_as_columns_covers_every_in_play_column_exactly():
    assert set(InPlayState(supported=True).as_columns()) == {
        "in_play_state_supported", "is_in_play", "clock_state", "period",
        "minute", "home_score", "away_score", "home_cards", "away_cards",
    }


@pytest.mark.parametrize("kwargs", [
    {"score": (-1, 0)},
    {"cards": (0, -2)},
    {"score": (1,)},
    {"score": (1, "0")},
    {"minute": -1.0},
    {"minute": float("nan")},
    {"period": "   "},
])
def test_in_play_state_rejects_impossible_detail(kwargs):
    with pytest.raises(VenuePayloadError):
        InPlayState(supported=True, **kwargs)


def test_in_play_state_accepts_a_full_reading():
    state = InPlayState(supported=True, is_in_play=True, clock_label="63'",
                        period="second_half", minute=63, score=(1, 1),
                        cards=(2, 0))

    assert _quote(in_play=state).in_play.score == (1, 1)
    assert state.as_columns()["clock_state"] == "63'"
    assert state.as_columns()["period"] == "second_half"


def test_quote_rejects_a_non_state_in_play_value():
    with pytest.raises(VenuePayloadError, match="InPlayState"):
        _quote(in_play={"score": (1, 0)})


# --- books and prices -------------------------------------------------------


def test_order_book_canonicalizes_sides_and_exposes_the_top():
    book = OrderBook(
        yes_bids=(OrderBookLevel(0.41, 100), OrderBookLevel(0.44, 50)),
        yes_asks=(OrderBookLevel(0.49, 20), OrderBookLevel(0.46, 75)),
    )

    assert (book.yes_bid, book.bid_size) == (0.44, 50)
    assert (book.yes_ask, book.ask_size) == (0.46, 75)
    assert book.midpoint == pytest.approx(0.45)


def test_one_sided_and_empty_books_have_no_invented_midpoint():
    assert OrderBook().midpoint is None
    assert OrderBook(yes_bids=(OrderBookLevel(0.44, 50),)).midpoint is None


def test_crossed_book_is_rejected():
    with pytest.raises(VenuePayloadError, match="crossed"):
        OrderBook(yes_bids=(OrderBookLevel(0.60, 10),),
                  yes_asks=(OrderBookLevel(0.55, 10),))


@pytest.mark.parametrize("price,size", [
    (1.01, 10), (-0.01, 10), (float("nan"), 10), (float("inf"), 10),
    (0.5, 0), (0.5, -1), (0.5, float("inf")),
])
def test_order_book_level_rejects_out_of_domain_values(price, size):
    with pytest.raises(VenuePayloadError):
        OrderBookLevel(price, size)


@pytest.mark.parametrize("last", [1.01, -0.01, float("nan"), float("inf")])
def test_quote_rejects_an_out_of_domain_last_price(last):
    with pytest.raises(VenuePayloadError, match="last"):
        _quote(last=last)


def test_quote_normalizes_timestamps_and_rejects_naive_ones():
    tokyo = timezone(timedelta(hours=9))
    quote = _quote(observed_at=NOW.astimezone(tokyo), source_ts=NOW.astimezone(tokyo))

    assert quote.observed_at == NOW
    assert quote.source_ts == NOW
    with pytest.raises(VenuePayloadError, match="timezone-aware"):
        _quote(observed_at=NOW.replace(tzinfo=None))


def test_quote_rejects_an_unknown_transport():
    with pytest.raises(VenuePayloadError, match="transport"):
        _quote(transport="carrier-pigeon")


# --- market and settlement --------------------------------------------------


def test_venue_market_requires_identity_fields_and_orders_its_lifecycle():
    market = VenueMarket(venue="kalshi", venue_key="KX-1", sport="football",
                         raw_title="", status="open", discovered_at=NOW)

    assert market.identity_key == ("kalshi", "KX-1")
    assert market.raw_title == ""  # unmapped markets are first-class data

    with pytest.raises(VenuePayloadError, match="venue_key"):
        VenueMarket(venue="kalshi", venue_key=" ", sport="football",
                    raw_title="", status="open", discovered_at=NOW)
    with pytest.raises(VenuePayloadError, match="closed_at"):
        VenueMarket(venue="kalshi", venue_key="KX-1", sport="football",
                    raw_title="", status="closed", discovered_at=NOW,
                    opened_at=NOW, closed_at=NOW - timedelta(hours=1))


def test_settlement_requires_an_outcome_only_when_settled():
    settled = Settlement(venue="kalshi", venue_key="KX-1", status="settled",
                         settled_at=NOW, source="venue", outcome="home")
    assert settled.outcome == "home"

    assert Settlement(venue="kalshi", venue_key="KX-1", status="void",
                      settled_at=NOW, source="venue").outcome is None

    with pytest.raises(VenuePayloadError, match="settled outcome"):
        Settlement(venue="kalshi", venue_key="KX-1", status="settled",
                   settled_at=NOW, source="venue")
    with pytest.raises(VenuePayloadError, match="must not have an outcome"):
        Settlement(venue="kalshi", venue_key="KX-1", status="cancelled",
                   settled_at=NOW, source="venue", outcome="home")


# --- the package boundary ---------------------------------------------------


def test_contracts_package_performs_no_io():
    """Phase 1 is inert. An adapter or DB import here would make it not so."""
    import pipeline.ingest.venues.types as module

    source = module.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for forbidden in ("import requests", "from app.", "import sqlalchemy",
                      "from sqlalchemy", "import httpx", "urllib"):
        assert forbidden not in text, f"contracts must not reach {forbidden}"
