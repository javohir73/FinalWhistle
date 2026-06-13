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

# football-data.org v4 status -> our internal status. These are the nine real
# match statuses. Extra time and the shootout are NOT statuses — they arrive as
# `score.duration` (EXTRA_TIME / PENALTY_SHOOTOUT) while status stays IN_PLAY or
# PAUSED — so they are handled via the score node, not this map.
_STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "in_play",
    "PAUSED": "in_play",   # a break (half-time / before-ET / ET-break) — still live
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

# Deliberate not-playing transitions: a match is genuinely pulled off the board.
# These must apply even from a lagging (older-stamped) snapshot — POSTPONED /
# CANCELLED have no later snapshot to self-heal, so the freshness guard must
# never suppress them (they would otherwise strand a match showing "in play").
_DELIBERATE_STOP = frozenset({"SUSPENDED", "POSTPONED", "CANCELLED"})


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


def _parse_last_updated(value: object) -> datetime | None:
    """Parse the feed's `lastUpdated` (RFC3339 UTC, whole seconds, trailing Z)
    into an aware datetime, or None if absent/malformed."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _score_pair(node: object) -> tuple[int | None, int | None]:
    """Read a v4 score sub-node {home, away} defensively. Tolerates the three
    absent-phase shapes the free tier may use: an omitted key, JSON null, or
    {home: null, away: null}."""
    if not isinstance(node, dict):
        return None, None
    return node.get("home"), node.get("away")


def _oriented(node: object, feed_home_is_our_home: bool) -> tuple[int | None, int | None]:
    """A score sub-node mapped into OUR home/away orientation."""
    home, away = _score_pair(node)
    return (home, away) if feed_home_is_our_home else (away, home)


def _derive_period(raw_status: str, duration: object, minute: int | None) -> str:
    """Phase of play for an in-play match. Extra time and the shootout come from
    `score.duration`; half-time from the PAUSED status; otherwise the half is
    read off the (real-or-estimated) minute."""
    if duration == "PENALTY_SHOOTOUT":
        return "penalty_shootout"
    if duration == "EXTRA_TIME":
        return "extra_time"
    if raw_status == "PAUSED" and (minute is None or minute <= 60):
        # PAUSED is generic. Near 45' it is half-time; a later PAUSED (the break
        # before extra time, or an ET interval, in a knockout) is not — fall
        # through to a minute-based phase rather than mislabelling it "HT".
        return "half_time"
    return "second_half" if (minute is not None and minute > 45) else "first_half"


# Periods whose clock is deliberately frozen (no ticking number is shown).
_FROZEN_PERIODS = frozenset({"half_time", "penalty_shootout"})


def _is_frozen_period(period: object) -> bool:
    return period in _FROZEN_PERIODS


def _pick_minute(feed_minute: object, kickoff: datetime | None) -> int | None:
    """Prefer the feed's real minute (paid tiers) over the kickoff estimate.
    An explicit None check (not truthiness) so a legitimate minute 0 is kept."""
    if isinstance(feed_minute, int):
        return feed_minute
    return estimate_minute(kickoff)


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
            # A status this code doesn't know (LIVE is filter-only; ET/PENS are
            # durations). Guessing "scheduled" once un-lived matches on every
            # refresh — leave the row untouched.
            log.warning("ignoring unknown feed status %r for %s vs %s",
                        raw_status, home_name, away_name)
            continue

        # Freshness guard: the feed is served by load-balanced caches that can
        # lag each other. `lastUpdated` is a per-match version stamp — never let
        # an older snapshot overwrite a newer record we already applied.
        incoming_lu = _parse_last_updated(am.get("lastUpdated"))
        stored_lu = match.provider_last_updated
        if stored_lu is not None and stored_lu.tzinfo is None:
            stored_lu = stored_lu.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo
        if (incoming_lu is not None and stored_lu is not None and incoming_lu < stored_lu
                and raw_status not in _DELIBERATE_STOP):
            continue

        # Belt-and-braces one-way lifecycle guard (covers equal/missing stamps):
        # a match's life is scheduled -> in_play -> finished. Don't un-finish a
        # final, and don't let a lagging "hasn't kicked off" knock back a live
        # match — keep it live and keep the clock ticking through the lag.
        if match.status == "finished" and status != "finished":
            # Terminal — but still advance the version high-water mark so a later
            # genuinely-stale correction can't slip past the freshness guard.
            if incoming_lu is not None and (stored_lu is None or incoming_lu > stored_lu):
                match.provider_last_updated = incoming_lu
            continue
        if match.status == "in_play" and raw_status in _NOT_STARTED:
            if not _is_frozen_period(match.period):  # don't un-freeze a HT/PENS row
                match.minute = _pick_minute(am.get("minute"), match.kickoff_utc)
            if incoming_lu is not None:
                match.provider_last_updated = incoming_lu
            updated += 1
            live += 1
            continue

        score = am.get("score") or {}
        duration = score.get("duration")
        our_home = db.get(Team, match.team_home_id)
        feed_home_is_our_home = bool(our_home and our_home.name == home_name)
        new_home, new_away = _oriented(score.get("fullTime"), feed_home_is_our_home)
        # Don't let a partial payload (score omitted / null / fullTime null) blank
        # a score we already know — that would flip the UI back to the predicted
        # score under a live badge. Keep the last known score until a real one comes.
        if new_home is not None or new_away is not None or (
                match.score_home is None and match.score_away is None):
            match.score_home, match.score_away = new_home, new_away

        match.status = status
        if status == "in_play":
            feed_minute = am.get("minute")
            period = _derive_period(raw_status, duration, _pick_minute(feed_minute, match.kickoff_utc))
            match.period = period
            # Half-time freezes the clock (the UI shows HT, never a number);
            # otherwise prefer the feed's real minute (paid tiers) and fall back
            # to a kickoff estimate (free tier omits the live minute).
            match.minute = None if period == "half_time" else _pick_minute(feed_minute, match.kickoff_utc)
            match.injury_time = am.get("injuryTime")
            live += 1
        else:
            match.period = None
            match.minute = None
            match.injury_time = None
            if status == "finished":
                finished += 1

        # Shootout tally — read from score.penalties (the {home,away} OBJECT),
        # never the unrelated top-level `penalties` kick ARRAY. A finished
        # shootout keeps its tally even if a later (lagging) FINISHED snapshot
        # omits the duration, so the scoreboard never loses "(4-2 pens)".
        if duration == "PENALTY_SHOOTOUT":
            match.penalty_home, match.penalty_away = _oriented(
                score.get("penalties"), feed_home_is_our_home)
        elif status != "finished":
            match.penalty_home = match.penalty_away = None

        if incoming_lu is not None:
            match.provider_last_updated = incoming_lu
        updated += 1

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
