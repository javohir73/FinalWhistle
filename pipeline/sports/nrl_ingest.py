"""NRL fixture/result ingest from fixturedownload.com (task-2-brief.md).

fixturedownload publishes a free, per-season JSON feed of the full NRL draw —
fixture, venue, and (once played) full-time score — at
https://fixturedownload.com/feed/json/nrl-{year}. This is the first non-football
sport vertical: it fills the sport_* tables (app.models) added by Task 1,
scoped by sport="nrl".

Mirrors pipeline.ingest.injuries's best-effort idiom: fetch_season NEVER raises
(any HTTP/timeout/JSON error is logged and answered with []), parse_row is pure
(None for malformed rows), and upsert_season never overwrites a stored finished
match — a result, once recorded, is not clobbered by a stale re-fetch.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from app.models import SportMatch, SportTeam

log = logging.getLogger(__name__)

FEED_URL = "https://fixturedownload.com/feed/json/nrl-{year}"
SPORT = "nrl"


def fetch_season(year: int, timeout: float = 20.0) -> list[dict]:
    """Return the raw fixture list for one NRL season. NEVER raises.

    Any HTTP error, timeout, or malformed JSON is logged and answered with []
    so a missing/unpublished season (e.g. one the feed doesn't go back to)
    can't abort a multi-season backfill.
    """
    url = FEED_URL.format(year=year)
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - a feed hiccup must never abort the backfill
        log.warning("nrl fetch_season(%s) failed: %s", year, exc)
        return []
    if not isinstance(data, list):
        log.warning("nrl fetch_season(%s) returned non-list payload: %r", year, type(data))
        return []
    return data


def parse_row(row: dict) -> dict | None:
    """One feed row -> a normalized dict, or None if malformed. Pure.

    Malformed = missing either team name or an unparseable DateUtc. Scores
    are only trusted as a pair: if either is null the match is "scheduled"
    with both scores None, otherwise "finished" with both scores set.
    """
    home_team = row.get("HomeTeam")
    away_team = row.get("AwayTeam")
    if not home_team or not away_team:
        return None

    date_str = row.get("DateUtc")
    try:
        # fixturedownload's DateUtc: "2026-03-01 02:15:00Z".
        kickoff_utc = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None

    score_home = row.get("HomeTeamScore")
    score_away = row.get("AwayTeamScore")
    if score_home is None or score_away is None:
        score_home = None
        score_away = None
        status = "scheduled"
    else:
        status = "finished"

    return {
        "match_no": row.get("MatchNumber"),
        "round": row.get("RoundNumber"),
        "kickoff_utc": kickoff_utc,
        "venue": row.get("Location"),
        "home_team": home_team,
        "away_team": away_team,
        "score_home": score_home,
        "score_away": score_away,
        "status": status,
    }


def _get_or_create_team(db: Session, cache: dict[str, SportTeam], name: str) -> SportTeam:
    team = cache.get(name)
    if team is not None:
        return team
    team = db.query(SportTeam).filter_by(sport=SPORT, name=name).one_or_none()
    if team is None:
        team = SportTeam(sport=SPORT, name=name)
        db.add(team)
        db.flush()
    cache[name] = team
    return team


def upsert_season(db: Session, year: int, rows: list[dict]) -> dict:
    """Parse+store one season's rows. Idempotent on (sport, season, match_no).

    Creates SportTeams on first sight by (sport, name). NEVER overwrites a
    stored finished match (freshness-guard spirit) — a scheduled row gaining
    scores flips to finished, but a finished match is immutable once written.
    Malformed rows are skipped silently (parse_row already logs nothing; the
    caller sees them simply absent from the counts).
    """
    created = 0
    updated = 0
    team_cache: dict[str, SportTeam] = {}

    for raw in rows:
        parsed = parse_row(raw)
        if parsed is None:
            log.warning("nrl upsert_season(%s): skipping malformed row %r", year, raw)
            continue

        home = _get_or_create_team(db, team_cache, parsed["home_team"])
        away = _get_or_create_team(db, team_cache, parsed["away_team"])

        match = (
            db.query(SportMatch)
            .filter_by(sport=SPORT, season=year, match_no=parsed["match_no"])
            .one_or_none()
        )
        if match is None:
            db.add(SportMatch(
                sport=SPORT, season=year, round=parsed["round"], match_no=parsed["match_no"],
                kickoff_utc=parsed["kickoff_utc"], venue=parsed["venue"],
                home_team_id=home.id, away_team_id=away.id,
                score_home=parsed["score_home"], score_away=parsed["score_away"],
                status=parsed["status"],
            ))
            created += 1
            continue

        if match.status == "finished":
            continue  # freshness guard: a recorded result is never clobbered

        if parsed["status"] == "finished" or (
            match.round != parsed["round"]
            or match.kickoff_utc != parsed["kickoff_utc"]
            or match.venue != parsed["venue"]
            or match.home_team_id != home.id
            or match.away_team_id != away.id
        ):
            match.round = parsed["round"]
            match.kickoff_utc = parsed["kickoff_utc"]
            match.venue = parsed["venue"]
            match.home_team_id = home.id
            match.away_team_id = away.id
            match.score_home = parsed["score_home"]
            match.score_away = parsed["score_away"]
            match.status = parsed["status"]
            updated += 1

    db.commit()
    return {"created": created, "updated": updated}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--seasons", nargs=2, type=int, required=True, metavar=("START", "END"),
        help="inclusive year range to backfill, e.g. --seasons 2016 2026",
    )
    args = ap.parse_args()
    start, end = args.seasons

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        for year in range(start, end + 1):
            rows = fetch_season(year)
            if not rows:
                log.info("%s: no data (feed empty or unavailable)", year)
                continue
            counts = upsert_season(db, year, rows)
            log.info(
                "%s: %d rows fetched, created=%d updated=%d",
                year, len(rows), counts["created"], counts["updated"],
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
