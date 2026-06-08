"""Live in-game score ingestion from football-data.org (free tier).

Fetches the tournament's matches, maps each to our fixture by the (normalized)
team pair, and updates status / score / live minute. Designed to be called every
~minute during match windows by an external cron hitting POST
/api/internal/refresh-live. A no-op (never raises) when no API key is set.

football-data.org v4: GET /v4/competitions/{code}/matches, auth via the
`X-Auth-Token` header. Free tier covers the World Cup (code "WC").
"""
from __future__ import annotations

import logging

import requests
from sqlalchemy.orm import Session

from app.models import Match, Team
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"

# football-data.org status -> our internal status.
_STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "in_play",
    "PAUSED": "in_play",
    "FINISHED": "finished",
    "AWARDED": "finished",
    "SUSPENDED": "scheduled",
    "POSTPONED": "scheduled",
    "CANCELLED": "scheduled",
}


def fetch_matches(api_key: str, competition: str = "WC", timeout: float = 15.0) -> list[dict]:
    """Return the raw match list for a competition from football-data.org."""
    resp = requests.get(
        f"{BASE_URL}/competitions/{competition}/matches",
        headers={"X-Auth-Token": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("matches", [])


def _index_by_pair(db: Session) -> dict[frozenset, Match]:
    """Map {normalized {home,away} pair -> Match} for fixtures with known teams.
    Group pairings are unique, so the unordered pair is an unambiguous key."""
    index: dict[frozenset, Match] = {}
    for m in db.query(Match).filter(Match.team_home_id.isnot(None)).all():
        home = db.get(Team, m.team_home_id)
        away = db.get(Team, m.team_away_id)
        if home and away and home.name != away.name:
            index[frozenset((home.name, away.name))] = m
    return index


def update_live_scores(db: Session, api_matches: list[dict]) -> dict:
    """Apply fetched match states to our DB. Returns a small summary."""
    index = _index_by_pair(db)
    updated = live = finished = 0

    for am in api_matches:
        try:
            home_name = normalize_team_name(am["homeTeam"]["name"])
            away_name = normalize_team_name(am["awayTeam"]["name"])
        except (KeyError, TypeError):
            continue

        match = index.get(frozenset((home_name, away_name)))
        if match is None or home_name == away_name:
            continue

        status = _STATUS_MAP.get(am.get("status", ""), "scheduled")
        full_time = (am.get("score") or {}).get("fullTime") or {}
        their_home, their_away = full_time.get("home"), full_time.get("away")

        our_home = db.get(Team, match.team_home_id)
        if our_home and our_home.name == home_name:
            match.score_home, match.score_away = their_home, their_away
        else:  # the feed's home/away is our away/home — swap to our orientation
            match.score_home, match.score_away = their_away, their_home

        match.status = status
        match.minute = am.get("minute") if status == "in_play" else None
        updated += 1
        if status == "in_play":
            live += 1
        elif status == "finished":
            finished += 1

    db.commit()
    return {"updated": updated, "live": live, "finished": finished}


def refresh_live(db: Session, api_key: str | None = None, competition: str | None = None) -> dict:
    """Fetch + apply live scores. No-op (never raises) when no key is configured."""
    from app.config import settings

    key = api_key if api_key is not None else settings.football_data_api_key
    comp = competition or settings.football_data_competition
    if not key:
        log.info("live scores skipped: no FOOTBALL_DATA_API_KEY configured")
        return {"skipped": "no_api_key", "updated": 0, "live": 0, "finished": 0}

    try:
        api_matches = fetch_matches(key, comp)
    except Exception as exc:  # noqa: BLE001 - never break the cron on a feed hiccup
        log.warning("live scores fetch failed: %s", exc)
        return {"error": str(exc), "updated": 0, "live": 0, "finished": 0}

    return update_live_scores(db, api_matches)
