"""Polymarket Gamma adapter for the intel panel (spec 2026-07-10).

fetch_events() pulls ACTIVE events for one tag from the public Gamma API
(read-only, no auth). parse_events() is pure and fixture-tested: it turns
Gamma's binary Yes/No markets into neutral rows the orchestrator can map.

Event shapes handled:
- Match events: title "A vs B" / "A vs. B"; one binary market per outcome,
  identified by the team name (or the word "draw") in the market question.
- Title events: the ONE championship event per tag, recognized by its full
  title against TITLE_PATTERNS; one binary market per team, question
  "Will <team> win the ...?".

Anything that doesn't fit is skipped — the intel panel would rather show
nothing than a wrong mapping.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from pipeline.ingest.market_names import normalize, normalize_text

log = logging.getLogger(__name__)

BASE_URL = "https://gamma-api.polymarket.com"
#: Gamma tag slugs (verified live at rollout — Task 5 manual step).
WC_TAG_SLUG = "fifa-world-cup"
NRL_TAG_SLUG = "nrl"

_VS = re.compile(r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)$", re.IGNORECASE)

#: Championship-event title per tag, matched against the normalized (lowercase,
#: punctuation-stripped) event title. "winner" alone is NOT enough: the
#: fifa-world-cup tag also lists group-winner, qualifying-group and award
#: events ("World Cup: Fair Play Award Winner", "World Cup Group A Winner"),
#: whose questions are also "Will <team> win ...?" — the Fair Play event put
#: Netherlands at 87.9% into title_winner on 2026-07-20. Tags without a
#: vetted pattern yield no title rows at all (skip rather than guess).
TITLE_PATTERNS: dict[str, re.Pattern[str]] = {
    WC_TAG_SLUG: re.compile(r"^(?:\d{4} )?(?:fifa )?world cup winner$"),
    # No live NRL title event yet (tag currently empty) — verify at rollout.
    NRL_TAG_SLUG: re.compile(r"^(?:\d{4} )?nrl (?:premiership |grand final )?winner$"),
}


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


def parse_events(events: list[dict], tag_slug: str) -> list[dict]:
    title_pattern = TITLE_PATTERNS.get(tag_slug)
    rows: list[dict] = []
    for event in events:
        if event.get("closed"):
            continue
        title = event.get("title") or ""
        vs = _VS.match(title.strip())
        if vs:
            rows.extend(_parse_match_event(event, vs["home"].strip(), vs["away"].strip()))
        elif title_pattern and title_pattern.match(normalize_text(title)):
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
        # normalize_text (not normalize): the question is free text the team
        # name sits inside, not a lone string, so alias expansion has to run
        # on the whole question too — else aliased teams (Korea, USA, Iran)
        # never match here even though normalize(home)/normalize(away) do.
        question = normalize_text(market.get("question") or "")
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
