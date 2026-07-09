"""Kalshi parsing: live payload shapes -> neutral rows.

Live WC match markets ship null yes_bid/yes_ask/last_price (Task 5
finding); price falls back to an injected price_lookup (the orderbook mid
in production). yes_sub_title carries a "Reg Time: " prefix and titles
have no colon ("A vs B Winner?", not "A vs B: Winner?") — both stripped
before matching. Outcome matching runs team names through
market_names.normalize() so it lines up with the title's home/away.
"""
import json
from pathlib import Path

import pytest

from pipeline.ingest.kalshi import _mid_from_orderbook, parse_markets

FIXTURE = Path(__file__).parent / "testdata" / "kalshi_markets.json"


def _markets():
    return json.loads(FIXTURE.read_text())["markets"]


def test_match_markets_use_orderbook_fallback_when_quotes_null():
    markets = [m for m in _markets() if m["ticker"].startswith("KXWCGAME-26JUL09FRAMAR")]
    prices = {
        "KXWCGAME-26JUL09FRAMAR-FRA": 0.615,
        "KXWCGAME-26JUL09FRAMAR-MAR": 0.17,
        "KXWCGAME-26JUL09FRAMAR-TIE": 0.215,
    }
    rows = parse_markets(markets, kind="match", price_lookup=lambda t: prices[t])
    by = {r["outcome"]: r for r in rows}
    assert by["home"]["team_name"] == "France" and by["home"]["price"] == 0.615
    assert by["away"]["team_name"] == "Morocco" and by["away"]["price"] == 0.17
    assert by["draw"]["team_name"] is None and by["draw"]["price"] == 0.215
    assert by["home"]["home_name"] == "France" and by["home"]["away_name"] == "Morocco"
    assert by["home"]["group"] == "KXWCGAME-26JUL09FRAMAR"
    assert by["home"]["source"] == "kalshi"


def test_match_market_direct_bid_ask_used_when_populated():
    markets = [m for m in _markets() if m["ticker"] == "KXWCGAME-26JUL10ESPBEL-ESP"]
    rows = parse_markets(markets, kind="match")  # no price_lookup needed
    assert rows[0]["team_name"] == "Spain" and rows[0]["price"] == 0.6


def test_null_price_without_lookup_is_skipped_not_crashed():
    markets = [m for m in _markets() if m["ticker"].startswith("KXWCGAME-26JUL09FRAMAR")]
    assert parse_markets(markets, kind="match") == []


def test_reg_time_tie_is_draw_with_no_team_name():
    markets = [m for m in _markets() if m["ticker"] == "KXWCGAME-26JUL09FRAMAR-TIE"]
    rows = parse_markets(markets, kind="match", price_lookup=lambda t: 0.215)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "draw" and rows[0]["team_name"] is None


def test_title_markets_and_zero_quotes_dropped():
    markets = [m for m in _markets() if m["ticker"].startswith("KXMWORLDCUP")]
    rows = parse_markets(markets, kind="title")
    assert [(r["team_name"], r["price"], r["outcome"]) for r in rows] == [
        ("France", 0.31, "win"),
    ]


def test_mid_from_orderbook_uses_best_bid_each_side():
    # Verified live for KXWCGAME-26JUL09FRAMAR-FRA: best yes bid 0.61, best
    # no bid 0.38 -> mid = (0.61 + (1 - 0.38)) / 2 = 0.615.
    data = {"orderbook_fp": {
        "yes_dollars": [["0.0100", "4041470.52"], ["0.6100", "180505.45"]],
        "no_dollars": [["0.0100", "4597033.06"], ["0.3800", "617219.72"]],
    }}
    assert _mid_from_orderbook(data) == pytest.approx(0.615)


def test_mid_from_orderbook_empty_side_returns_none():
    assert _mid_from_orderbook(
        {"orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.5", "1"]]}}) is None
    assert _mid_from_orderbook({}) is None


def test_colon_title_form_still_parses():
    # Older ": Winner?" style must keep working alongside the live no-colon form.
    market = {
        "ticker": "KXWCGAME-OLDSTYLE-FRA", "event_ticker": "KXWCGAME-OLDSTYLE",
        "title": "France vs Morocco: Winner?", "yes_sub_title": "Reg Time: France",
        "status": "active", "yes_bid": 61, "yes_ask": 65, "last_price": 63,
    }
    rows = parse_markets([market], kind="match")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "home"
    assert rows[0]["home_name"] == "France" and rows[0]["away_name"] == "Morocco"


def test_mid_from_orderbook_unsorted_levels_and_range_guard():
    # best bid is the max price on each side, not the last listed level
    data = {"orderbook_fp": {
        "yes_dollars": [["0.6100", "10"], ["0.0100", "99"]],
        "no_dollars": [["0.3800", "10"], ["0.0100", "99"]],
    }}
    assert _mid_from_orderbook(data) == pytest.approx(0.615)
    # degenerate book computing to mid == 0 fails the 0 < mid < 1 guard
    degenerate = {"orderbook_fp": {
        "yes_dollars": [["0.0000", "1"]], "no_dollars": [["1.0000", "1"]],
    }}
    assert _mid_from_orderbook(degenerate) is None


def test_orderbook_mid_swallows_all_failures(monkeypatch):
    from pipeline.ingest import kalshi

    def network_down(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(kalshi.requests, "get", network_down)
    assert kalshi.orderbook_mid("ANY") is None

    class MalformedResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"orderbook_fp": {"yes_dollars": [["not-a-price", "1"]],
                                     "no_dollars": [["0.5", "1"]]}}

    monkeypatch.setattr(kalshi.requests, "get", lambda *a, **k: MalformedResp())
    assert kalshi.orderbook_mid("ANY") is None
