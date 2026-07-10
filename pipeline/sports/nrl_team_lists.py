"""NRL team-list ingest (Wave 3).

Weekly pipeline step: pulls each round's announced team lists via
StatsProvider.fetch_team_list and upserts them into nrl_team_lists,
flagging is_late_change when a jersey slot's named player differs from the
last-ingested list for that match (never on the first-ever announcement).

The real TeamListEntry (pipeline.sports.nrl_stats) carries no match_id — a
provider can't know our DB ids — so ingest_round resolves each entry to a
match by matching entry.team against the home/away team NAMES of that
round's SportMatch rows (sport="nrl", season, round_no), then hands
upsert_team_list entries already grouped by match id.

CLI: python -m pipeline.sports.nrl_team_lists --season 2026 [--round 1]
     (omit --round to auto-detect rounds with a scheduled match in the next
     10 days — the rounds a fresh announcement would cover)
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import NrlTeamList, SportMatch, SportTeam
from pipeline.sports.nrl_stats import NrlComStatsProvider, StatsProvider, TeamListEntry

log = logging.getLogger(__name__)

SPORT = "nrl"
_EMPTY = {"matches": 0, "players": 0, "late_changes": 0}


def upsert_team_list(db: Session, entries_by_match: dict[int, list[TeamListEntry]]) -> dict:
    """Replace the stored team list for every match_id in `entries_by_match`.

    Idempotent per match: read the existing (team, jersey) -> player mapping,
    delete-then-insert the replacement. is_late_change=True only when a prior
    list already existed for that match AND the (team, jersey) slot's player
    changed -- never on a match's first-ever announcement, and never for an
    unchanged player re-ingested.

    Returns {"matches": n, "players": n, "late_changes": n}.
    """
    matches = players = late_changes = 0
    for match_id, match_entries in entries_by_match.items():
        if not match_entries:
            continue
        existing = {
            (row.team, row.jersey): row.player
            for row in db.query(NrlTeamList).filter_by(match_id=match_id).all()
        }
        had_prior_list = bool(existing)
        db.query(NrlTeamList).filter_by(match_id=match_id).delete()

        for e in match_entries:
            prior_player = existing.get((e.team, e.jersey))
            is_late = had_prior_list and prior_player is not None and prior_player != e.player
            db.add(NrlTeamList(
                match_id=match_id, team=e.team, jersey=e.jersey,
                player=e.player, position=e.position, is_late_change=is_late,
            ))
            players += 1
            if is_late:
                late_changes += 1
        matches += 1

    db.commit()
    return {"matches": matches, "players": players, "late_changes": late_changes}


def _round_team_name_lookup(db: Session, season: int, round_no: int) -> dict[str, int]:
    """{team_name: match_id} for every home/away team in this round's
    SportMatch rows -- the round-wide analogue of nrl_stats._db_team_names,
    which resolves per-match rather than for a whole round."""
    rows = (
        db.query(SportMatch.id, SportMatch.home_team_id, SportMatch.away_team_id)
        .filter(SportMatch.sport == SPORT, SportMatch.season == season, SportMatch.round == round_no)
        .all()
    )
    team_ids = {tid for _, home_id, away_id in rows for tid in (home_id, away_id) if tid is not None}
    names: dict[int, str] = {}
    if team_ids:
        names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.id.in_(team_ids)).all())

    lookup: dict[str, int] = {}
    for match_id, home_id, away_id in rows:
        home_name = names.get(home_id)
        away_name = names.get(away_id)
        if home_name is not None:
            lookup[home_name] = match_id
        if away_name is not None:
            lookup[away_name] = match_id
    return lookup


def ingest_round(db: Session, season: int, round_no: int, provider: StatsProvider) -> dict:
    """Fetch + upsert one round's team lists. Never raises -- a feed hiccup
    logs and returns a zeroed summary, matching nrl_ingest's best-effort
    idiom. Entries whose team name doesn't resolve to any match in this
    round are logged and ignored."""
    try:
        entries = provider.fetch_team_list(season, round_no)
    except Exception as exc:  # noqa: BLE001 - a feed hiccup must never abort a run
        log.warning("nrl team-list fetch(%s, round %s) failed: %s", season, round_no, exc)
        return dict(_EMPTY)
    if not entries:
        return dict(_EMPTY)

    team_to_match = _round_team_name_lookup(db, season, round_no)
    entries_by_match: dict[int, list[TeamListEntry]] = {}
    for e in entries:
        match_id = team_to_match.get(e.team)
        if match_id is None:
            log.warning("nrl team-list: no match for team %r in %s round %s", e.team, season, round_no)
            continue
        entries_by_match.setdefault(match_id, []).append(e)

    if not entries_by_match:
        return dict(_EMPTY)
    return upsert_team_list(db, entries_by_match)


def rounds_needing_team_lists(db: Session, season: int, days_ahead: int = 10) -> list[int]:
    """Distinct round numbers with a scheduled match kicking off within the
    next `days_ahead` days -- the rounds a team-list announcement covers."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)
    rows = (
        db.query(SportMatch.round)
        .filter(
            SportMatch.sport == SPORT, SportMatch.season == season,
            SportMatch.status == "scheduled",
            SportMatch.kickoff_utc.isnot(None),
            SportMatch.kickoff_utc >= now - timedelta(days=1),
            SportMatch.kickoff_utc <= cutoff,
        )
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0] is not None})


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--round", type=int, dest="round_no", default=None,
                     help="ingest one specific round; omit to auto-detect upcoming rounds")
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        # NrlComStatsProvider.fetch_team_list is an honest empty ([]) until a
        # real team-list source is implemented (see pipeline/sports/nrl_stats.py)
        # -- until then this cron step safely no-ops (zeroed summary).
        provider = NrlComStatsProvider()
        rounds = [args.round_no] if args.round_no is not None else rounds_needing_team_lists(db, args.season)
        totals = dict(_EMPTY)
        for r in rounds:
            summary = ingest_round(db, args.season, r, provider)
            for k in totals:
                totals[k] += summary[k]
        log.info("nrl team-list ingest: season=%s rounds=%s totals=%s", args.season, rounds, totals)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
