"""Network-free Kalshi catalogue discovery tests."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from pipeline.ingest.venues.kalshi import KalshiAdapter
from pipeline.ingest.venues.types import VenuePayloadError

FIXTURES = Path(__file__).parents[1] / "testdata"
NOW = datetime(2026, 7, 26, 5, 0, tzinfo=timezone.utc)


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params, timeout))
        if "/markets/" in url and not url.endswith("/orderbook"):
            if self.responses and isinstance(self.responses[0], dict) and "market" in self.responses[0]:
                return FakeResponse(self.responses.pop(0))
            return FakeResponse(
                {"market": {"last_price_dollars": "0.4300"}}
            )
        return FakeResponse(self.responses.pop(0))


def _adapter(*responses):
    session = FakeSession(responses)
    return KalshiAdapter(session=session, now=lambda: NOW), session


def test_discovery_filters_exact_soccer_series_and_paginates_all_open_events():
    adapter, session = _adapter(
        _fixture("kalshi_soccer_series.json"),
        _fixture("kalshi_open_events_page_1.json"),
        _fixture("kalshi_open_events_page_2.json"),
    )

    markets = adapter.discover_markets("football")

    assert [market.venue_key for market in markets] == [
        "KXEPLGAME-26AUG01ARSCHE-ARS",
        "KXEPLGAME-26AUG01ARSCHE-DRAW",
        "KXLIGAMXBTTS-26AUG02AMEPAC-YES",
    ]
    assert [market.market_type for market in markets] == ["game", "game", "btts"]
    assert [market.status for market in markets] == ["open", "paused", "open"]
    assert all(market.venue == "kalshi" for market in markets)
    assert all(market.discovered_at == NOW for market in markets)
    assert markets[2].opened_at == datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    assert markets[0].raw_payload["market"]["ticker"] == markets[0].venue_key

    assert session.calls[0][1] == {
        "category": "Sports",
        "tags": "Soccer",
        "include_product_metadata": "true",
    }
    assert "cursor" not in session.calls[1][1]
    assert session.calls[2][1]["cursor"] == "page-2"
    assert session.calls[1][1]["with_nested_markets"] == "true"


def test_discovery_deduplicates_market_repeated_across_pages():
    adapter, _session = _adapter(
        _fixture("kalshi_soccer_series.json"),
        _fixture("kalshi_open_events_page_1.json"),
        _fixture("kalshi_open_events_page_2.json"),
    )

    keys = [market.identity_key for market in adapter.discover_markets("football")]

    assert len(keys) == len(set(keys)) == 3


def test_unsupported_sport_is_a_network_free_empty_result():
    adapter, session = _adapter()

    assert adapter.discover_markets("nrl") == []
    assert session.calls == []


def test_repeated_event_cursor_is_rejected():
    repeated = {"events": [], "cursor": "again"}
    adapter, _session = _adapter(
        _fixture("kalshi_soccer_series.json"), repeated, repeated
    )

    with pytest.raises(VenuePayloadError, match="repeated a cursor"):
        adapter.discover_markets("football")


def test_malformed_market_is_logged_and_does_not_drop_siblings(caplog):
    events = {
        "events": [
            {
                "event_ticker": "KXEPLGAME-1",
                "series_ticker": "KXEPLGAME",
                "title": "A vs B",
                "markets": [
                    {"status": "open"},
                    {"ticker": "GOOD", "status": "open", "title": "A vs B"},
                ],
            }
        ],
        "cursor": "",
    }
    adapter, _session = _adapter(_fixture("kalshi_soccer_series.json"), events)

    markets = adapter.discover_markets("football")

    assert [market.venue_key for market in markets] == ["GOOD"]
    assert "market None rejected" in caplog.text


def test_malformed_page_shape_fails_loudly():
    adapter, _session = _adapter({"series": "not-a-list"})

    with pytest.raises(VenuePayloadError, match="series response"):
        adapter.discover_markets("football")


def test_fetch_quote_requests_complete_fixed_point_book_and_normalizes_yes_side():
    payload = _fixture("kalshi_orderbook_full.json")
    adapter, session = _adapter(payload)

    quote = adapter.fetch_quote("KXEPLGAME-26AUG01ARSCHE-ARS")

    assert quote.venue == "kalshi"
    assert quote.venue_key == "KXEPLGAME-26AUG01ARSCHE-ARS"
    assert quote.observed_at == NOW
    assert quote.transport == "polling"
    assert quote.raw_payload["orderbook"] is payload
    assert quote.last == 0.43
    assert [(level.price, level.size) for level in quote.book.yes_bids] == [
        (0.4205, 13.25),
        (0.41, 10.0),
        (0.15, 100.0),
    ]
    assert [(level.price, level.size) for level in quote.book.yes_asks] == [
        (0.44, 17.5),
        (0.55, 20.0),
        (0.99, 100.0),
    ]
    assert quote.yes_bid == 0.4205
    assert quote.yes_ask == 0.44
    assert quote.midpoint == pytest.approx(0.43025)
    assert session.calls == [
        (
            "https://external-api.kalshi.com/trade-api/v2/markets/"
            "KXEPLGAME-26AUG01ARSCHE-ARS/orderbook",
            {"depth": 0},
            15.0,
        ),
        (
            "https://external-api.kalshi.com/trade-api/v2/markets/"
            "KXEPLGAME-26AUG01ARSCHE-ARS",
            {},
            15.0,
        ),
    ]


def test_fetch_quote_preserves_empty_and_one_sided_books():
    adapter, _session = _adapter(
        _fixture("kalshi_orderbook_empty.json"),
        {"orderbook_fp": {"yes_dollars": [["0.3333", "2.50"]]}},
    )

    empty = adapter.fetch_quote("EMPTY")
    one_sided = adapter.fetch_quote("ONE-SIDED")

    assert empty.book.yes_bids == ()
    assert empty.book.yes_asks == ()
    assert empty.midpoint is None
    assert one_sided.yes_bid == 0.3333
    assert one_sided.bid_size == 2.5
    assert one_sided.yes_ask is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "orderbook_fp object"),
        ({"orderbook_fp": {"yes_dollars": "bad"}}, "levels must be a list"),
        (
            {"orderbook_fp": {"yes_dollars": [["0.5"]]}},
            "must be \\[price, size\\]",
        ),
        (
            {"orderbook_fp": {"yes_dollars": [["not-a-price", "1"]]}},
            "is not numeric",
        ),
        (
            {"orderbook_fp": {"yes_dollars": [["1.001", "1"]]}},
            "price must be between 0 and 1",
        ),
        (
            {"orderbook_fp": {"no_dollars": [["0.5", "0"]]}},
            "size must be greater than 0",
        ),
    ],
)
def test_fetch_quote_rejects_malformed_fixed_point_books(payload, message):
    adapter, _session = _adapter(payload)

    with pytest.raises(VenuePayloadError, match=message):
        adapter.fetch_quote("MARKET")


def test_fetch_quote_rejects_crossed_normalized_book():
    adapter, _session = _adapter(
        {
            "orderbook_fp": {
                "yes_dollars": [["0.6000", "4.00"]],
                "no_dollars": [["0.5000", "3.00"]],
            }
        }
    )

    with pytest.raises(VenuePayloadError, match="order book is crossed"):
        adapter.fetch_quote("CROSSED")


def test_fetch_quote_rejects_empty_key_without_network_call():
    adapter, session = _adapter()

    with pytest.raises(VenuePayloadError, match="venue_key must not be empty"):
        adapter.fetch_quote("  ")

    assert session.calls == []


def test_fetch_quote_error_retains_rejected_raw_payload():
    payload = {"orderbook_fp": {"yes_dollars": [["bad", "1"]]}}
    adapter, _session = _adapter(payload)

    with pytest.raises(VenuePayloadError) as caught:
        adapter.fetch_quote("MARKET")

    assert caught.value.raw_payload is payload


def test_fetch_settlement_returns_finalized_outcome_with_provenance():
    payload = {
        "market": {
            "ticker": "MARKET",
            "status": "finalized",
            "result": "yes",
            "settlement_ts": "2026-07-27T03:30:00Z",
            "updated_time": "2026-07-27T03:31:00Z",
        }
    }
    adapter, session = _adapter(payload)

    settlement = adapter.fetch_settlement("MARKET")

    assert settlement is not None
    assert settlement.status == "settled"
    assert settlement.outcome == "yes"
    assert settlement.settled_at == datetime(
        2026, 7, 27, 3, 30, tzinfo=timezone.utc
    )
    assert settlement.source_event_id == "2026-07-27T03:31:00Z"
    assert settlement.raw_payload is payload
    assert session.calls[0][0].endswith("/markets/MARKET")


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [("void", "void"), ("cancelled", "cancelled")],
)
def test_fetch_settlement_preserves_terminal_non_outcome_states(
    result, expected_status
):
    adapter, _session = _adapter(
        {
            "market": {
                "status": "finalized",
                "result": result,
                "settlement_ts": "2026-07-27T03:30:00Z",
            }
        }
    )

    settlement = adapter.fetch_settlement("MARKET")

    assert settlement is not None
    assert settlement.status == expected_status
    assert settlement.outcome is None


@pytest.mark.parametrize("status", ["closed", "determined", "disputed", "amended"])
def test_fetch_settlement_revisits_non_finalized_markets(status):
    adapter, _session = _adapter(
        {"market": {"status": status, "result": "yes"}}
    )

    assert adapter.fetch_settlement("MARKET") is None


def test_fetch_settlement_rejects_incomplete_finalized_market_with_raw_payload():
    payload = {"market": {"status": "finalized", "result": "yes"}}
    adapter, _session = _adapter(payload)

    with pytest.raises(VenuePayloadError, match="settlement_ts") as caught:
        adapter.fetch_settlement("MARKET")

    assert caught.value.raw_payload is payload


def test_quotes_declare_live_match_state_unsupported():
    """Kalshi publishes no clock, score or cards anywhere capture reads.

    Saying so explicitly is the point: a downstream state-matched comparison
    can then exclude these ticks and name the venue, instead of counting a
    disagreement between a real model state and a score that never existed.
    """
    adapter, _session = _adapter(
        _fixture("kalshi_orderbook_full.json"),
        {"market": {"last_price_dollars": "0.4300"}},
    )

    quote = adapter.fetch_quote("KXEPLGAME-26AUG01ARSCHE-ARS")

    assert KalshiAdapter.in_play_state_fields == frozenset()
    assert quote.in_play.supported is False
    assert quote.in_play.as_columns() == {
        "in_play_state_supported": False, "is_in_play": None, "clock_state": None,
        "period": None, "minute": None, "home_score": None, "away_score": None,
        "home_cards": None, "away_cards": None,
    }
