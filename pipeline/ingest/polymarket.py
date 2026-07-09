"""Polymarket Gamma adapter for the intel panel (spec 2026-07-10).

fetch_events() pulls ACTIVE events for one tag from the public Gamma API
(read-only, no auth). parse_events() is pure and fixture-tested: it turns
Gamma's binary Yes/No markets into neutral rows the orchestrator can map.

Event shapes handled:
- Match events: title "A vs B" / "A vs. B"; one binary market per outcome,
  identified by the team name (or the word "draw") in the market question.
- Title events: title containing "winner"; one binary market per team,
  question "Will <team> win the ...?".

Anything that doesn't fit is skipped — the intel panel would rather show
nothing than a wrong mapping.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from pipeline.ingest.market_names import normalize

log = logging.getLogger(__name__)

BASE_URL = "https://gamma-api.polymarket.com"
#: Gamma tag slugs (verified live at rollout — Task 5 manual step).
WC_TAG_SLUG = "fifa-world-cup"
NRL_TAG_SLUG = "nrl"

_VS = re.compile(r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)$", re.IGNORECASE)


def fetch_events(tag_slug: str, timeout: float = 15.0) -> list[dict]:
    """Raw ACTIVE events for one tag. Callers own error handling."""
    resp = requests.get(
        f"{BASE_URL}/events",
        params={"tag_slug": tag_slug, "closed": "false", "limit": 200},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _yes_price(market: dict) -> float | None:
    """Yes-outcome price, or None when malformed/out of range."""
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices = json.loads(market.get("outcomePrices") or "[]")
        yes = outcomes.index("Yes")
        price = float(prices[yes])
    except (ValueError, IndexError, TypeError):
        return None
    return price if 0.0 < price < 1.0 else None


def _is_active(market: dict) -> bool:
    return bool(market.get("active")) and not market.get("closed")


def parse_events(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        if event.get("closed"):
            continue
        title = event.get("title") or ""
        vs = _VS.match(title.strip())
        if vs:
            rows.extend(_parse_match_event(event, vs["home"].strip(), vs["away"].strip()))
        elif "winner" in title.lower():
            rows.extend(_parse_title_event(event))
        else:
            log.info("polymarket: skipping unrecognized event %r", title)
    return rows


def _parse_match_event(event: dict, home: str, away: str) -> list[dict]:
    rows = []
    for market in event.get("markets") or []:
        if not _is_active(market):
            continue
        price = _yes_price(market)
        if price is None:
            continue
        question = normalize(market.get("question") or "")
        if "draw" in question or "tie" in question:
            outcome, team = "draw", None
        elif normalize(home) and normalize(home) in question:
            outcome, team = "home", home
        elif normalize(away) and normalize(away) in question:
            outcome, team = "away", away
        else:
            log.info("polymarket: unmapped match market %r", market.get("question"))
            continue
        rows.append({
            "source": "polymarket", "external_id": market["slug"],
            "group": event["slug"], "kind": "match",
            "home_name": home, "away_name": away,
            "outcome": outcome, "team_name": team, "price": price,
        })
    return rows


_TITLE_Q = re.compile(r"^will\s+(?P<team>.+?)\s+win\b", re.IGNORECASE)


def _parse_title_event(event: dict) -> list[dict]:
    rows = []
    for market in event.get("markets") or []:
        if not _is_active(market):
            continue
        price = _yes_price(market)
        if price is None:
            continue
        m = _TITLE_Q.match((market.get("question") or "").strip())
        if not m:
            log.info("polymarket: unmapped title market %r", market.get("question"))
            continue
        rows.append({
            "source": "polymarket", "external_id": market["slug"],
            "group": event["slug"], "kind": "title",
            "home_name": None, "away_name": None,
            "outcome": "win", "team_name": m["team"].strip(), "price": price,
        })
    return rows
