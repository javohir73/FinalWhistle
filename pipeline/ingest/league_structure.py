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
"""
from __future__ import annotations

import json
import logging
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


def _get_or_create_tournament(db: Session) -> Tournament:
    t = db.query(Tournament).filter_by(name=TOURNAMENT_NAME).one_or_none()
    if t is None:
        t = Tournament(
            name=TOURNAMENT_NAME,
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


def _get_or_create_group(db: Session, tournament: Tournament) -> Group:
    group = db.query(Group).filter_by(
        tournament_id=tournament.id, name=GROUP_NAME
    ).one_or_none()
    if group is None:
        group = Group(tournament_id=tournament.id, name=GROUP_NAME)
        db.add(group)
        db.flush()
    return group


def _fixture_fields(fx: dict) -> tuple[int, str, str, datetime, str, int | None, int | None] | None:
    """Extract (fixture_id, home_name, away_name, kickoff_utc, status,
    score_home, score_away) from one raw api-sports /fixtures response item,
    or None if malformed."""
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
    return (
        int(fid), home, away, kickoff,
        _STATUS.get(status, "scheduled"),
        goals.get("home"), goals.get("away"),
    )


def load_league_structure(
    db: Session, teams_file: str = DEFAULT_TEAMS_FILE, api_key: str | None = None,
) -> dict:
    """Load the EPL 2026-27 structure. Returns a summary dict for logging/tests."""
    if api_key is None:
        from app.config import settings

        api_key = settings.api_football_api_key

    teams_data = _load_teams_file(teams_file)
    tournament = _get_or_create_tournament(db)
    group = _get_or_create_group(db, tournament)

    team_by_name: dict[str, Team] = {}
    for t in teams_data:
        team = _upsert_team(db, t["name"], t["code"], t["api_football_id"])
        team_by_name[team.name] = team
        exists = db.query(GroupTeam).filter_by(
            group_id=group.id, team_id=team.id
        ).one_or_none()
        if exists is None:
            db.add(GroupTeam(group_id=group.id, team_id=team.id))

    raw_fixtures = fetch_fixtures(api_key, league=LEAGUE_ID, season=SEASON)

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
        fid, home_name, away_name, kickoff, status, score_home, score_away = parsed
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

    db.commit()

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
