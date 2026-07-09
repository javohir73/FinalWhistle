"""Kalshi public-API adapter for the intel panel (spec 2026-07-10; live-shape
fix Task 5 2026-07-10).

Market data GETs need no auth. parse_markets() is pure and fixture-tested;
output rows share the polymarket adapter's shape so the orchestrator treats
both sources identically. Live WC markets ship null yes_bid/yes_ask/
last_price (the bid/ask/last path is kept for if the exchange ever
populates it, but never fires today), a "Reg Time: " prefix on
yes_sub_title, and titles with no colon ("A vs B Winner?"). Real prices
come from the public per-market orderbook endpoint via an injected
price_lookup — kept out of parse_markets itself so parsing stays pure and
network-free for tests; the orchestrator wires price_lookup=orderbook_mid.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

import requests

from pipeline.ingest.market_names import normalize

log = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
#: Series tickers (verified live 2026-07-10 — Task 5).
WC_MATCH_SERIES = "KXWCGAME"
#: "Men's World Cup winner" futures. Zero open markets as of Task 5 — that's
#: fine, fetch_markets just returns [] and the title leg contributes 0 rows
#: harmlessly, unlike the guessed "KXWC" ticker it replaces (which 404s).
WC_TITLE_SERIES = "KXMWORLDCUP"

#: Live titles carry no colon ("Argentina vs Switzerland Winner?"); strip
#: the trailing "Winner?" (with an optional leading colon, for any market
#: that does use one) before matching "home vs away".
_TRAILING_WINNER = re.compile(r"\s*:?\s*winner\??\s*$", re.IGNORECASE)
_VS = re.compile(r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)(?::.*)?$", re.IGNORECASE)
#: yes_sub_title on match markets is "Reg Time: <team|Tie>", not a bare name.
_REG_TIME = re.compile(r"^\s*reg\s*time\s*:\s*", re.IGNORECASE)


def fetch_markets(series_ticker: str, timeout: float = 15.0) -> list[dict]:
    """Raw OPEN markets for one series. Callers own error handling."""
    resp = requests.get(
        f"{BASE_URL}/markets",
        params={"series_ticker": series_ticker, "status": "open", "limit": 500},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("markets", [])


def _mid_price(market: dict) -> float | None:
    bid, ask = market.get("yes_bid") or 0, market.get("yes_ask") or 0
    cents = (bid + ask) / 2 if bid and ask else (market.get("last_price") or 0)
    return cents / 100 if 0 < cents < 100 else None


def _mid_from_orderbook(data: dict) -> float | None:
    """Implied yes mid from a /orderbook response: (best yes bid + (1 - best
    no bid)) / 2. Pure math, no I/O, so it's unit-testable without the
    network. Requires both sides non-empty and a mid strictly between 0 and
    1, else None — never guess a price off a one-sided or empty book."""
    book = data.get("orderbook_fp") or {}
    yes_side, no_side = book.get("yes_dollars") or [], book.get("no_dollars") or []
    if not yes_side or not no_side:
        return None
    best_yes_bid = max(float(level[0]) for level in yes_side)
    best_no_bid = max(float(level[0]) for level in no_side)
    mid = (best_yes_bid + (1 - best_no_bid)) / 2
    return mid if 0 < mid < 1 else None


def orderbook_mid(ticker: str, timeout: float = 15.0) -> float | None:
    """Best-effort implied price for one market from the public orderbook
    endpoint — the field live WC markets actually populate, unlike
    yes_bid/yes_ask/last_price. Per-market boundary: any failure (network,
    HTTP status, bad JSON, empty book) is swallowed and logged, never
    raised, so one bad ticker can't sink a batch of otherwise-good rows."""
    try:
        resp = requests.get(f"{BASE_URL}/markets/{ticker}/orderbook", timeout=timeout)
        resp.raise_for_status()
        return _mid_from_orderbook(resp.json())
    except Exception:
        log.warning("kalshi: orderbook lookup failed for %s", ticker, exc_info=True)
        return None


def parse_markets(markets: list[dict], kind: str,
                   price_lookup: Callable[[str], float | None] | None = None) -> list[dict]:
    rows: list[dict] = []
    for market in markets:
        if market.get("status") not in ("active", "open"):
            continue
        price = _mid_price(market)
        if price is None and price_lookup is not None:
            price = price_lookup(market["ticker"])
        sub = _REG_TIME.sub("", (market.get("yes_sub_title") or "").strip()).strip()
        if price is None or not sub:
            continue
        if kind == "match":
            title = _TRAILING_WINNER.sub("", (market.get("title") or "").strip()).strip()
            vs = _VS.match(title)
            if not vs:
                log.info("kalshi: unmapped match market %r", market.get("title"))
                continue
            home, away = vs["home"].strip(), vs["away"].strip()
            if sub.lower() in ("tie", "draw"):
                outcome, team_name = "draw", None
            elif normalize(sub) == normalize(home):
                outcome, team_name = "home", home
            elif normalize(sub) == normalize(away):
                outcome, team_name = "away", away
            else:
                log.info("kalshi: outcome %r not in title %r", sub, market.get("title"))
                continue
            rows.append({
                "source": "kalshi", "external_id": market["ticker"],
                "group": market["event_ticker"], "kind": "match",
                "home_name": home, "away_name": away,
                "outcome": outcome, "team_name": team_name, "price": price,
            })
        else:  # title
            rows.append({
                "source": "kalshi", "external_id": market["ticker"],
                "group": market["event_ticker"], "kind": "title",
                "home_name": None, "away_name": None,
                "outcome": "win", "team_name": sub, "price": price,
            })
    return rows
