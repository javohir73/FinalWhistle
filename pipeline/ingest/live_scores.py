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
from datetime import datetime, timezone

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
    "EXTRA_TIME": "in_play",
    "PENALTY_SHOOTOUT": "in_play",
    "FINISHED": "finished",
    "AWARDED": "finished",
    "SUSPENDED": "scheduled",
    "POSTPONED": "scheduled",
    "CANCELLED": "scheduled",
}

# Raw statuses that mean "hasn't kicked off yet" — unlike the deliberate
# not-playing states (SUSPENDED/POSTPONED/CANCELLED) that also map to
# "scheduled" but must always be applied.
_NOT_STARTED = frozenset({"SCHEDULED", "TIMED"})


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


def estimate_minute(kickoff: datetime | None, now: datetime | None = None) -> int | None:
    """Approximate the live minute from kickoff time. The free tier's match
    list carries no `minute` field, so without this every in-play match shows
    a bare "Live" badge. First half maps to 1–45, the break holds at 45 (HT),
    the second half maps to 46–90 assuming a 15-minute interval; capped at 90.
    A scoreboard clock, not an official one."""
    if kickoff is None:
        return None
    if kickoff.tzinfo is None:  # SQLite drops tzinfo; naive means UTC here
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    elapsed = (now - kickoff).total_seconds() / 60
    if elapsed < 0:
        return 1
    if elapsed <= 45:
        return max(1, int(elapsed) + 1)  # 0:00–0:59 is the 1st minute
    if elapsed <= 60:
        return 45  # first-half stoppage + half-time interval
    return min(int(elapsed) - 15 + 1, 90)


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

        raw_status = am.get("status", "")
        status = _STATUS_MAP.get(raw_status)
        if status is None:
            # A status this code doesn't know. Guessing "scheduled" here once
            # un-lived matches on every refresh — leave the row untouched.
            log.warning("ignoring unknown feed status %r for %s vs %s",
                        raw_status, home_name, away_name)
            continue

        # The feed is served by load-balanced caches that can lag a snapshot
        # behind each other, and a match's lifecycle is one-way (scheduled ->
        # in_play -> finished). A "hasn't kicked off" claim for a match we've
        # seen in play, or anything un-finishing a final, is stale data: keep
        # our state instead of seesawing the scoreboard (and keep the live
        # clock ticking through the lag).
        if match.status == "finished" and status != "finished":
            continue
        if match.status == "in_play" and raw_status in _NOT_STARTED:
            match.minute = am.get("minute") or estimate_minute(match.kickoff_utc)
            updated += 1
            live += 1
            continue

        full_time = (am.get("score") or {}).get("fullTime") or {}
        their_home, their_away = full_time.get("home"), full_time.get("away")

        our_home = db.get(Team, match.team_home_id)
        if our_home and our_home.name == home_name:
            match.score_home, match.score_away = their_home, their_away
        else:  # the feed's home/away is our away/home — swap to our orientation
            match.score_home, match.score_away = their_away, their_home

        match.status = status
        # The free tier omits `minute`, so fall back to a kickoff-based estimate.
        match.minute = (
            (am.get("minute") or estimate_minute(match.kickoff_utc))
            if status == "in_play"
            else None
        )
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
