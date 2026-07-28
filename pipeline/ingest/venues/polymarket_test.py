"""Network-free Polymarket soccer catalogue discovery tests."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from pipeline.ingest.venues.polymarket import PolymarketAdapter
from pipeline.ingest.venues.types import VenuePayloadError

FIXTURES = Path(__file__).parents[1] / "testdata"
NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)


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
        return FakeResponse(self.responses.pop(0))


def _adapter(*responses):
    session = FakeSession(responses)
    return PolymarketAdapter(session=session, now=lambda: NOW), session


def test_discovery_resolves_soccer_tag_and_keyset_paginates_all_active_events():
    adapter, session = _adapter(
        _fixture("polymarket_soccer_tag.json"),
        _fixture("polymarket_active_events_page_1.json"),
        _fixture("polymarket_active_events_page_2.json"),
    )

    markets = adapter.discover_markets("football")

    assert [market.venue_key for market in markets] == ["0xaaa", "0xbbb", "0xccc"]
    assert [market.market_type for market in markets] == [
        "moneyline",
        "unknown",
        "award_winner",
    ]
    assert [market.status for market in markets] == ["active", "inactive", "closed"]
    assert all(market.venue == "polymarket" for market in markets)
    assert all(market.discovered_at == NOW for market in markets)
    assert markets[0].event_key == "event-101"
    assert markets[0].opened_at == datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)
    assert markets[0].closed_at == datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)
    assert markets[1].raw_title == "Will Arsenal vs Chelsea end in a draw?"
    assert markets[2].raw_payload["market"]["clobTokenIds"]

    assert session.calls[0] == (
        "https://gamma-api.polymarket.com/tags/slug/soccer",
        {},
        15.0,
    )
    assert session.calls[1][1] == {
        "tag_id": 100350,
        "active": "true",
        "closed": "false",
        "limit": 100,
    }
    assert session.calls[2][1]["after_cursor"] == "page-2"


def test_discovery_deduplicates_market_repeated_across_pages():
    adapter, _session = _adapter(
        _fixture("polymarket_soccer_tag.json"),
        _fixture("polymarket_active_events_page_1.json"),
        _fixture("polymarket_active_events_page_2.json"),
    )

    keys = [market.identity_key for market in adapter.discover_markets("football")]

    assert len(keys) == len(set(keys)) == 3


def test_unsupported_sport_is_a_network_free_empty_result():
    adapter, session = _adapter()

    assert adapter.discover_markets("nrl") == []
    assert session.calls == []


def test_repeated_event_cursor_is_rejected():
    repeated = {"events": [], "next_cursor": "again"}
    adapter, _session = _adapter(
        _fixture("polymarket_soccer_tag.json"), repeated, repeated
    )

    with pytest.raises(VenuePayloadError, match="repeated a cursor"):
        adapter.discover_markets("football")


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ({"id": "bad", "slug": "soccer"}, "numeric id"),
        ({"id": "100350", "slug": "not-soccer"}, "inconsistent"),
    ],
)
def test_malformed_soccer_tag_fails_loudly(tag, message):
    adapter, _session = _adapter(tag)

    with pytest.raises(VenuePayloadError, match=message):
        adapter.discover_markets("football")


def test_malformed_page_shape_fails_loudly():
    adapter, _session = _adapter(
        _fixture("polymarket_soccer_tag.json"), {"events": "not-a-list"}
    )

    with pytest.raises(VenuePayloadError, match="events list"):
        adapter.discover_markets("football")


def test_malformed_market_is_logged_without_aborting_valid_siblings(caplog):
    adapter, _session = _adapter(
        _fixture("polymarket_soccer_tag.json"),
        _fixture("polymarket_active_events_page_1.json"),
        _fixture("polymarket_active_events_page_2.json"),
    )

    markets = adapter.discover_markets("football")

    assert [market.venue_key for market in markets] == ["0xaaa", "0xbbb", "0xccc"]
    assert "market 'market-without-condition' rejected" in caplog.text
    assert "event 'event-malformed' has malformed markets" in caplog.text


def test_fetch_quote_returns_complete_yes_token_book_and_provenance():
    market = _fixture("polymarket_clob_market.json")
    book = _fixture("polymarket_orderbook_full.json")
    adapter, session = _adapter(market, book)

    quote = adapter.fetch_quote("0xaaa")

    assert quote.venue == "polymarket"
    assert quote.venue_key == "0xaaa"
    assert quote.observed_at == NOW
    assert quote.source_ts == datetime(2026, 7, 27, 3, 59, 30, tzinfo=timezone.utc)
    assert quote.source_event_id == "book-hash-42"
    assert quote.last == 0.4301
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
    assert quote.midpoint == pytest.approx(0.43025)
    assert quote.raw_payload == {"market": market, "book": book}
    assert session.calls == [
        ("https://clob.polymarket.com/clob-markets/0xaaa", {}, 15.0),
        (
            "https://clob.polymarket.com/book",
            {"token_id": "yes-token-aaa"},
            15.0,
        ),
    ]


def test_fetch_quote_preserves_empty_and_one_sided_books():
    market = _fixture("polymarket_clob_market.json")
    adapter, _session = _adapter(
        market,
        {"market": "0xaaa", "bids": [], "asks": []},
        market,
        {
            "market": "0xaaa",
            "bids": [{"price": "0.3333", "size": "2.5"}],
        },
    )

    empty = adapter.fetch_quote("0xaaa")
    one_sided = adapter.fetch_quote("0xaaa")

    assert empty.book.yes_bids == empty.book.yes_asks == ()
    assert empty.midpoint is None
    assert one_sided.yes_bid == 0.3333
    assert one_sided.bid_size == 2.5
    assert one_sided.yes_ask is None


@pytest.mark.parametrize(
    ("book", "message"),
    [
        ({"market": "wrong"}, "condition id does not match"),
        ({"market": "0xaaa", "bids": "bad"}, "levels must be a list"),
        (
            {"market": "0xaaa", "bids": [{"price": "bad", "size": "1"}]},
            "is not numeric",
        ),
        (
            {"market": "0xaaa", "asks": [{"price": "1.1", "size": "1"}]},
            "between 0 and 1",
        ),
        (
            {"market": "0xaaa", "asks": [{"price": "0.5", "size": "0"}]},
            "greater than 0",
        ),
        (
            {
                "market": "0xaaa",
                "bids": [{"price": "0.6", "size": "1"}],
                "asks": [{"price": "0.5", "size": "1"}],
            },
            "crossed",
        ),
        (
            {"market": "0xaaa", "timestamp": "1785124860000"},
            "in the future",
        ),
    ],
)
def test_fetch_quote_rejects_bad_books_and_retains_raw_payload(book, message):
    market = _fixture("polymarket_clob_market.json")
    adapter, _session = _adapter(market, book)

    with pytest.raises(VenuePayloadError, match=message) as caught:
        adapter.fetch_quote("0xaaa")

    assert caught.value.raw_payload is not None


def test_fetch_quote_rejects_market_without_exactly_one_yes_token():
    adapter, _session = _adapter({"t": [{"t": "no", "o": "No"}]})

    with pytest.raises(VenuePayloadError, match="exactly one Yes token"):
        adapter.fetch_quote("0xaaa")


def test_fetch_settlement_returns_resolved_winner_and_provenance():
    rows = _fixture("polymarket_settled_market.json")
    adapter, session = _adapter(rows)

    settlement = adapter.fetch_settlement("0xaaa")

    assert settlement is not None
    assert settlement.status == "settled"
    assert settlement.outcome == "Yes"
    assert settlement.settled_at == datetime(
        2026, 7, 27, 3, 30, tzinfo=timezone.utc
    )
    assert settlement.source_event_id == "2026-07-27T03:35:00Z"
    assert session.calls[0][1] == {
        "condition_ids": "0xaaa",
        "closed": "true",
        "limit": 2,
    }


@pytest.mark.parametrize(
    ("row", "expected_status"),
    [
        (
            {
                "conditionId": "0xaaa",
                "umaResolutionStatus": "cancelled",
                "closedTime": "2026-07-27T03:30:00Z",
            },
            "cancelled",
        ),
        (
            {
                "conditionId": "0xaaa",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.5", "0.5"]',
                "closedTime": "2026-07-27T03:30:00Z",
            },
            "void",
        ),
    ],
)
def test_fetch_settlement_preserves_cancelled_and_void_states(row, expected_status):
    adapter, _session = _adapter([row])

    settlement = adapter.fetch_settlement("0xaaa")

    assert settlement is not None
    assert settlement.status == expected_status
    assert settlement.outcome is None


def test_fetch_settlement_returns_none_while_outcome_is_not_determined():
    adapter, _session = _adapter(
        [
            {
                "conditionId": "0xaaa",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.4", "0.6"]',
                "closedTime": "2026-07-27T03:30:00Z",
            }
        ]
    )

    assert adapter.fetch_settlement("0xaaa") is None


def test_fetch_settlement_exposes_corrected_outcome_as_new_provenance_event():
    initial = _fixture("polymarket_settled_market.json")[0]
    corrected = {
        **initial,
        "outcomePrices": '["0", "1"]',
        "updatedAt": "2026-07-27T05:00:00Z",
    }
    adapter, _session = _adapter([initial], [corrected])

    before = adapter.fetch_settlement("0xaaa")
    after = adapter.fetch_settlement("0xaaa")

    assert before is not None and after is not None
    assert (before.outcome, after.outcome) == ("Yes", "No")
    assert before.source_event_id != after.source_event_id
