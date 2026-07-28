"""Contract tests shared by every prediction-market venue adapter."""

from datetime import datetime, timedelta, timezone

import pytest

from pipeline.ingest.venues.types import (
    OrderBook,
    OrderBookLevel,
    Quote,
    Settlement,
    VenueAdapter,
    VenueMarket,
    VenuePayloadError,
    heartbeat_idempotency_key,
    tick_idempotency_key,
)

UTC_NOW = datetime(2026, 7, 26, 5, 0, tzinfo=timezone.utc)


def test_market_identity_is_venue_scoped_and_timestamps_normalize_to_utc():
    market = VenueMarket(
        venue="kalshi",
        venue_key="KX-1",
        sport="football",
        raw_title="A v B",
        status="open",
        discovered_at=UTC_NOW.astimezone(timezone(timedelta(hours=10))),
    )

    assert market.identity_key == ("kalshi", "KX-1")
    assert market.discovered_at == UTC_NOW
    assert market.market_type == "unknown"


@pytest.mark.parametrize("field", ["venue", "venue_key", "sport"])
def test_market_rejects_missing_identity_fields(field):
    values = {
        "venue": "kalshi",
        "venue_key": "KX-1",
        "sport": "football",
        "raw_title": "",
        "status": "open",
        "discovered_at": UTC_NOW,
    }
    values[field] = "  "

    with pytest.raises(VenuePayloadError, match=field):
        VenueMarket(**values)


def test_market_keeps_empty_raw_title_but_rejects_bad_lifecycle():
    with pytest.raises(VenuePayloadError, match="closed_at"):
        VenueMarket(
            venue="kalshi",
            venue_key="KX-1",
            sport="football",
            raw_title="",
            status="closed",
            discovered_at=UTC_NOW,
            opened_at=UTC_NOW,
            closed_at=UTC_NOW - timedelta(seconds=1),
        )


def test_market_preserves_a_new_nonempty_venue_status():
    market = VenueMarket(
        venue="kalshi",
        venue_key="KX-1",
        sport="football",
        raw_title="A v B",
        status="initialized",
        discovered_at=UTC_NOW,
    )

    assert market.status == "initialized"


def test_contract_rejects_naive_timestamps():
    with pytest.raises(VenuePayloadError, match="timezone-aware"):
        VenueMarket(
            venue="kalshi",
            venue_key="KX-1",
            sport="football",
            raw_title="A v B",
            status="open",
            discovered_at=datetime(2026, 7, 26, 5, 0),
        )


def test_book_is_sorted_best_first_and_exposes_top_of_book():
    book = OrderBook(
        yes_bids=(OrderBookLevel(0.42, 5), OrderBookLevel(0.44, 3)),
        yes_asks=(OrderBookLevel(0.49, 7), OrderBookLevel(0.47, 2)),
    )

    assert (book.yes_bid, book.bid_size) == (0.44, 3)
    assert (book.yes_ask, book.ask_size) == (0.47, 2)
    assert book.midpoint == pytest.approx(0.455)
    assert [level.price for level in book.yes_bids] == [0.44, 0.42]
    assert [level.price for level in book.yes_asks] == [0.47, 0.49]


def test_one_sided_and_empty_books_are_valid_without_an_invented_midpoint():
    one_sided = OrderBook(yes_bids=(OrderBookLevel(0.44, 3),))

    assert one_sided.yes_bid == 0.44
    assert one_sided.yes_ask is None
    assert one_sided.midpoint is None
    assert OrderBook().midpoint is None


@pytest.mark.parametrize(
    ("level", "message"),
    [
        (lambda: OrderBookLevel(-0.01, 1), "between 0 and 1"),
        (lambda: OrderBookLevel(1.01, 1), "between 0 and 1"),
        (lambda: OrderBookLevel(float("nan"), 1), "between 0 and 1"),
        (lambda: OrderBookLevel(0.5, 0), "greater than 0"),
        (lambda: OrderBookLevel(0.5, float("inf")), "finite"),
    ],
)
def test_book_level_rejects_invalid_probability_or_size(level, message):
    with pytest.raises(VenuePayloadError, match=message):
        level()


def test_crossed_normalized_book_is_rejected():
    with pytest.raises(VenuePayloadError, match="crossed"):
        OrderBook(
            yes_bids=(OrderBookLevel(0.51, 1),),
            yes_asks=(OrderBookLevel(0.50, 1),),
        )


def test_quote_keeps_full_book_raw_payload_and_normalized_values():
    raw = {"orderbook": {"yes": [["0.44", "3"]]}}
    quote = Quote(
        venue="kalshi",
        venue_key="KX-1",
        observed_at=UTC_NOW,
        transport="polling",
        book=OrderBook(
            yes_bids=(OrderBookLevel(0.44, 3),),
            yes_asks=(OrderBookLevel(0.48, 2),),
        ),
        last=0.46,
        raw_payload=raw,
    )

    assert quote.raw_payload is raw
    assert (quote.yes_bid, quote.yes_ask, quote.last) == (0.44, 0.48, 0.46)
    assert quote.midpoint == pytest.approx(0.46)


def test_polling_tick_key_uses_scheduled_cycle_not_completion_time():
    first = Quote("kalshi", "KX-1", UTC_NOW, "polling")
    retry = Quote("kalshi", "KX-1", UTC_NOW + timedelta(seconds=12), "polling")

    assert tick_idempotency_key(first, scheduled_cycle_at=UTC_NOW) == (
        "kalshi",
        "KX-1",
        "polling",
        "cycle:2026-07-26T05:00:00+00:00",
    )
    assert tick_idempotency_key(first, scheduled_cycle_at=UTC_NOW) == (
        tick_idempotency_key(retry, scheduled_cycle_at=UTC_NOW)
    )


def test_stream_tick_key_requires_and_uses_stable_source_event_id():
    quote = Quote(
        "polymarket",
        "pm-1",
        UTC_NOW,
        "streaming",
        source_event_id="sequence-42",
    )

    assert tick_idempotency_key(quote) == (
        "polymarket",
        "pm-1",
        "streaming",
        "event:sequence-42",
    )
    with pytest.raises(VenuePayloadError, match="source_event_id"):
        tick_idempotency_key(Quote("polymarket", "pm-1", UTC_NOW, "streaming"))


def test_heartbeat_key_uses_scheduled_utc_cycle():
    local_cycle = UTC_NOW.astimezone(timezone(timedelta(hours=10)))
    assert heartbeat_idempotency_key("worker-1", "kalshi", local_cycle) == (
        "worker-1",
        "kalshi",
        UTC_NOW,
    )


def test_settlement_requires_outcome_only_for_settled_markets():
    settled = Settlement(
        venue="kalshi",
        venue_key="KX-1",
        status="settled",
        outcome="yes",
        settled_at=UTC_NOW,
        source="markets/KX-1",
    )
    void = Settlement(
        venue="kalshi",
        venue_key="KX-2",
        status="void",
        settled_at=UTC_NOW,
        source="markets/KX-2",
    )

    assert settled.identity_key == ("kalshi", "KX-1")
    assert void.outcome is None
    with pytest.raises(VenuePayloadError, match="outcome is required"):
        Settlement("kalshi", "KX-3", "settled", UTC_NOW, "markets/KX-3")
    with pytest.raises(VenuePayloadError, match="must not have an outcome"):
        Settlement("kalshi", "KX-4", "cancelled", UTC_NOW, "markets/KX-4", "yes")


def test_adapter_protocol_is_structural():
    class FixtureAdapter:
        venue = "fixture"

        def discover_markets(self, sport):
            return []

        def fetch_quote(self, venue_key):
            return Quote(self.venue, venue_key, UTC_NOW, "polling")

        def fetch_settlement(self, venue_key):
            return None

    assert isinstance(FixtureAdapter(), VenueAdapter)
