"""Load the Premier League 2026-27 structure (teams, one group, fixtures).

League pivot D1/D2 (docs/LEAGUE-PIVOT-PLAN.md): unlike WC2026's fixed
wc26_schedule.json, league fixtures move (TV picks, postponements), so teams
seed once from a small checked-in JSON but the 380 fixtures come from the
provider every refresh. Produces:
  - 20 teams (from teams_file)
  - 1 group ("Premier League") containing all 20
  - 380 stage="group" matches upserted from API-Football fixtures

Idempotent: safe to run repeatedly (upserts by provider fixture id; never
duplicates, never touches WC26 rows — those are a different tournament_id and
were seeded without a provider_fixture_id in the first place).

Also writes matches.matchweek (League Score Predictions design doc,
c8d9e0f1a2b3_add_match_matchweek migration) from the fixture payload's
`league.round` (e.g. "Regular Season - 5" -> 5, see _parse_matchweek) — the
matchweek-scoped tipsheet/leaderboards' read side (app/api/
league_score_predictions.py) query this column; this is that column's only
writer. Set unconditionally on every upsert, like kickoff_utc/status/score_*,
so a broadcaster reshuffle that moves a fixture's round corrects it on the
next ingestion.

Parameterized (tournament_name/group_name/league_id/season) so
pipeline/leagues.py's registry + pipeline/run_pipeline.py's league branch can
drive this loader for any configured league, not just EPL — every parameter
defaults to this module's own EPL constant below, so nothing here changes
behavior for a bare load_league_structure(db) call.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Group, GroupTeam, Match, Team, Tournament
from pipeline.ingest.api_football import fetch_fixtures
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)

DEFAULT_TEAMS_FILE = "pipeline/data/epl2627_teams.json"

TOURNAMENT_NAME = "Premier League 2026-27"
TOURNAMENT_YEAR = 2026
GROUP_NAME = "Premier League"

# API-Football league/season for this competition (a league loader is
# competition-specific, same as wc26_structure.py hardcoding its own
# TOURNAMENT_NAME/YEAR — the provider-facing values live here, not in
# app.config, which stays the single "whichever competition is currently
# live" switch used by odds/live-scores/injuries).
LEAGUE_ID = 39
SEASON = 2026

# api-sports fixture.status.short -> our internal Match.status. Mirrors
# pipeline/ingest/api_football._STATUS + live_scores._STATUS_MAP's combined
# effect, restated here in our own vocabulary since this module writes Match
# rows directly rather than going through update_live_scores.
_STATUS = {
    "TBD": "scheduled", "NS": "scheduled",
    "1H": "in_play", "2H": "in_play", "ET": "in_play", "P": "in_play", "LIVE": "in_play",
    "HT": "in_play", "BT": "in_play",
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "AWD": "finished", "WO": "finished",
    "SUSP": "scheduled", "INT": "scheduled",
    "PST": "scheduled",
    "CANC": "scheduled", "ABD": "scheduled",
}


def _load_teams_file(teams_file: str) -> list[dict]:
    return json.loads(Path(teams_file).read_text(encoding="utf-8"))["teams"]


def _get_or_create_tournament(db: Session, tournament_name: str = TOURNAMENT_NAME) -> Tournament:
    t = db.query(Tournament).filter_by(name=tournament_name).one_or_none()
    if t is None:
        t = Tournament(
            name=tournament_name,
            # Every registered league (pipeline/leagues.py) is a 2026-27
            # season, same as EPL's -- not worth its own parameter until
            # Phase 2 actually needs a different value.
            year=TOURNAMENT_YEAR,
            host_countries="",
            # D4: a league has a real home side, not a host-nation bonus.
            home_advantage_mode="home",
        )
        db.add(t)
        db.flush()
    return t


def _upsert_team(db: Session, name: str, code: str, api_football_id: int) -> Team:
    canon = normalize_team_name(name)
    team = db.query(Team).filter_by(name=canon).one_or_none()
    if team is None:
        team = Team(
            name=canon, country_code=code, is_host=False,
            provider_team_id=api_football_id,
        )
        db.add(team)
        db.flush()
    else:
        team.country_code = code
        team.provider_team_id = api_football_id
    return team


def _get_or_create_group(db: Session, tournament: Tournament, group_name: str = GROUP_NAME) -> Group:
    group = db.query(Group).filter_by(
        tournament_id=tournament.id, name=group_name
    ).one_or_none()
    if group is None:
        group = Group(tournament_id=tournament.id, name=group_name)
        db.add(group)
        db.flush()
    return group


# API-Football's fixture.league.round is free text, e.g. "Regular Season - 5"
# (knockout-style rounds like "Quarter-finals" carry no trailing number and
# never occur in a league fixture list anyway) -- pull the trailing integer.
_ROUND_NUMBER_RE = re.compile(r"(\d+)\s*$")


def _parse_matchweek(round_str: str | None) -> int | None:
    """"Regular Season - 5" -> 5; None for anything that doesn't end in a
    number, or no round at all (matches.matchweek migration docstring)."""
    if not round_str:
        return None
    m = _ROUND_NUMBER_RE.search(round_str)
    return int(m.group(1)) if m else None


def _fixture_fields(
    fx: dict,
) -> tuple[int, str, str, datetime, str, int | None, int | None, int | None] | None:
    """Extract (fixture_id, home_name, away_name, kickoff_utc, status,
    score_home, score_away, matchweek) from one raw api-sports /fixtures
    response item, or None if malformed."""
    fixture = fx.get("fixture") or {}
    fid = fixture.get("id")
    date = fixture.get("date")
    status = (fixture.get("status") or {}).get("short")
    teams = fx.get("teams") or {}
    home = (teams.get("home") or {}).get("name")
    away = (teams.get("away") or {}).get("name")
    if fid is None or not date or not home or not away:
        return None
    kickoff = datetime.fromisoformat(date.replace("Z", "+00:00"))
    goals = fx.get("goals") or {}
    # Same league.round lookup + fallback as api_football.py's _to_item
    # (the football-data-v4-shaping layer for the live-scores path).
    league = fx.get("league") or fixture.get("league") or {}
    matchweek = _parse_matchweek(league.get("round"))
    return (
        int(fid), home, away, kickoff,
        _STATUS.get(status, "scheduled"),
        goals.get("home"), goals.get("away"),
        matchweek,
    )


def load_league_structure(
    db: Session,
    teams_file: str = DEFAULT_TEAMS_FILE,
    api_key: str | None = None,
    *,
    tournament_name: str = TOURNAMENT_NAME,
    group_name: str = GROUP_NAME,
    league_id: int = LEAGUE_ID,
    season: int = SEASON,
) -> dict:
    """Load one league's structure (default: EPL 2026-27). The keyword-only
    tournament_name/group_name/league_id/season let pipeline/run_pipeline.py's
    league branch drive this for any league in pipeline.leagues.LEAGUES --
    every default is this module's own EPL constant, so a bare
    load_league_structure(db) call keeps behaving exactly as it did before
    this became parameterized. Returns a summary dict for logging/tests."""
    if api_key is None:
        from app.config import settings

        api_key = settings.api_football_api_key

    teams_data = _load_teams_file(teams_file)
    tournament = _get_or_create_tournament(db, tournament_name)
    group = _get_or_create_group(db, tournament, group_name)

    team_by_name: dict[str, Team] = {}
    for t in teams_data:
        team = _upsert_team(db, t["name"], t["code"], t["api_football_id"])
        team_by_name[team.name] = team
        exists = db.query(GroupTeam).filter_by(
            group_id=group.id, team_id=team.id
        ).one_or_none()
        if exists is None:
            db.add(GroupTeam(group_id=group.id, team_id=team.id))

    raw_fixtures = fetch_fixtures(api_key, league=league_id, season=season)

    existing_by_fixture: dict[int, Match] = {
        m.provider_fixture_id: m
        for m in db.query(Match)
        .filter(
            Match.tournament_id == tournament.id,
            Match.provider_fixture_id.isnot(None),
        )
        .all()
    }

    created = updated = skipped = 0
    for fx in raw_fixtures:
        parsed = _fixture_fields(fx)
        if parsed is None:
            skipped += 1
            continue
        fid, home_name, away_name, kickoff, status, score_home, score_away, matchweek = parsed
        home = team_by_name.get(normalize_team_name(home_name))
        away = team_by_name.get(normalize_team_name(away_name))
        if home is None or away is None:
            log.warning("league fixture %s: unknown team(s) %r/%r", fid, home_name, away_name)
            skipped += 1
            continue

        match = existing_by_fixture.get(fid)
        if match is None:
            match = Match(
                tournament_id=tournament.id,
                group_id=group.id,
                stage="group",
                provider_fixture_id=fid,
                team_home_id=home.id,
                team_away_id=away.id,
                is_neutral=False,
            )
            db.add(match)
            created += 1
        else:
            updated += 1
        match.kickoff_utc = kickoff
        match.status = status
        match.score_home = score_home
        match.score_away = score_away
        # Unconditional, same as the fields above -- a fixture correction
        # (round moved by broadcaster reshuffle) must re-land on every
        # subsequent ingestion, not just the first time this row is created.
        match.matchweek = matchweek

    db.commit()

    # Best-effort: only matters if this ever runs inside the web process
    # itself (a separate CLI run — the daily/cutover case — has its own cache
    # instance, so this line is a no-op there; GET /api/tournaments/active's
    # short ttl_seconds is what actually bounds staleness across that
    # boundary — see backend/app/cache.py and backend/app/api/tournaments.py).
    try:
        from app.cache import cache

        cache.invalidate("tournaments:active")
    except Exception:  # noqa: BLE001 - never let cache housekeeping fail the load
        log.warning("could not invalidate tournaments:active cache", exc_info=True)

    total_matches = db.query(Match).filter_by(tournament_id=tournament.id).count()
    return {
        "tournament_id": tournament.id,
        "teams": len(team_by_name),
        "group_id": group.id,
        "fixtures_created": created,
        "fixtures_updated": updated,
        "fixtures_skipped": skipped,
        "total_matches": total_matches,
    }
