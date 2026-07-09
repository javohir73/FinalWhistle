"""Kalshi public-API adapter for the intel panel (spec 2026-07-10).

Market data GETs need no auth. parse_markets() is pure and fixture-tested;
output rows share the polymarket adapter's shape so the orchestrator treats
both sources identically. Prices are integer cents: the implied price is the
bid/ask mid when both sides are quoted, else last_price; zero/unquoted
markets are dropped rather than guessed.
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
#: Series tickers (verified live at rollout — Task 5 manual step).
WC_MATCH_SERIES = "KXWCGAME"
WC_TITLE_SERIES = "KXWC"

_VS = re.compile(r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)(?::.*)?$", re.IGNORECASE)


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


def parse_markets(markets: list[dict], kind: str) -> list[dict]:
    rows: list[dict] = []
    for market in markets:
        if market.get("status") not in ("active", "open"):
            continue
        price = _mid_price(market)
        team = (market.get("yes_sub_title") or "").strip()
        if price is None or not team:
            continue
        if kind == "match":
            vs = _VS.match((market.get("title") or "").strip())
            if not vs:
                log.info("kalshi: unmapped match market %r", market.get("title"))
                continue
            home, away = vs["home"].strip(), vs["away"].strip()
            if team.lower() in ("tie", "draw"):
                outcome, team_name = "draw", None
            elif team == home:
                outcome, team_name = "home", home
            elif team == away:
                outcome, team_name = "away", away
            else:
                log.info("kalshi: outcome %r not in title %r", team, market.get("title"))
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
                "outcome": "win", "team_name": team, "price": price,
            })
    return rows
