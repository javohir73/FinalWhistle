"""Load the WC2026 structure (teams, groups, fixtures) into the database.

Reads the verified seed files in pipeline/data/ and produces:
  - 48 teams
  - 12 groups + group memberships
  - 72 group-stage matches (round-robin per group)
  - 32 knockout placeholder matches (R32/R16/QF/SF/third/final), teams TBD
  = 104 matches total

Idempotent: safe to run repeatedly (upserts by natural key; never duplicates).
Host nations play their group games at home, so any group match involving a host
sets host_team_id / venue_country / is_neutral=False (PRD Decision #2).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Group, GroupTeam, Match, Team, Tournament
from pipeline.team_mapping import normalize_team_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_KO_SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "data" / "wc26_ko_schedule.json"


def _ko_kickoffs() -> dict[int, datetime]:
    raw = json.loads(_KO_SCHEDULE_PATH.read_text())["kickoffs"]
    return {int(k): datetime.fromisoformat(v.replace("Z", "+00:00")) for k, v in raw.items()}
TOURNAMENT_NAME = "FIFA World Cup 2026"
TOURNAMENT_YEAR = 2026

# Standard 4-team round-robin matchday order (0-indexed positions).
ROUND_ROBIN = [
    (0, 1), (2, 3),   # matchday 1
    (0, 2), (3, 1),   # matchday 2
    (3, 0), (1, 2),   # matchday 3
]

# Knockout placeholder structure -> count per stage (sums to 32).
KNOCKOUT_STAGES = [
    ("R32", 16),
    ("R16", 8),
    ("QF", 4),
    ("SF", 2),
    ("third_place", 1),
    ("final", 1),
]


def _load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _load_schedule() -> dict[tuple[str, frozenset[str]], dict]:
    """Build a lookup of confirmed group-stage kickoff/venue data, keyed by
    (group name, unordered pair of team names). Optional: returns {} if the
    schedule file is absent so structure loading still works."""
    path = DATA_DIR / "wc26_schedule.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    lookup: dict[tuple[str, frozenset[str]], dict] = {}
    for m in data.get("matches", []):
        home = normalize_team_name(m["home"])
        away = normalize_team_name(m["away"])
        lookup[(m["group"], frozenset({home, away}))] = m
    return lookup


def _get_or_create_tournament(db: Session) -> Tournament:
    t = db.query(Tournament).filter_by(name=TOURNAMENT_NAME).one_or_none()
    if t is None:
        t = Tournament(
            name=TOURNAMENT_NAME,
            year=TOURNAMENT_YEAR,
            host_countries="Canada, Mexico, United States",
        )
        db.add(t)
        db.flush()
    return t


def _upsert_team(db: Session, name: str, code: str, conf: str, is_host: bool) -> Team:
    canon = normalize_team_name(name)
    team = db.query(Team).filter_by(name=canon).one_or_none()
    if team is None:
        team = Team(name=canon, country_code=code, confederation=conf, is_host=is_host)
        db.add(team)
        db.flush()
    else:
        team.country_code = code
        team.confederation = conf
        team.is_host = is_host
    return team


def load_structure(db: Session) -> dict:
    """Load all WC2026 structure. Returns a small summary dict for logging/tests."""
    teams_data = _load_json("wc26_teams.json")
    groups_data = _load_json("wc26_groups.json")
    host_country_by_team = groups_data.get("host_country_by_team", {})
    schedule = _load_schedule()

    tournament = _get_or_create_tournament(db)

    # 1. Teams
    team_by_name: dict[str, Team] = {}
    for t in teams_data["teams"]:
        team = _upsert_team(db, t["name"], t["code"], t["confederation"], t["is_host"])
        team_by_name[team.name] = team

    # 2. Groups + memberships + group-stage fixtures
    group_match_count = 0
    for g in groups_data["groups"]:
        group = db.query(Group).filter_by(
            tournament_id=tournament.id, name=g["name"]
        ).one_or_none()
        if group is None:
            group = Group(tournament_id=tournament.id, name=g["name"])
            db.add(group)
            db.flush()

        members = [team_by_name[normalize_team_name(n)] for n in g["teams"]]
        for team in members:
            exists = db.query(GroupTeam).filter_by(
                group_id=group.id, team_id=team.id
            ).one_or_none()
            if exists is None:
                db.add(GroupTeam(group_id=group.id, team_id=team.id))

        # round-robin fixtures
        for hi, ai in ROUND_ROBIN:
            home, away = members[hi], members[ai]

            host_team_id = None
            is_neutral = True
            for team in (home, away):
                if team.name in host_country_by_team:
                    host_team_id = team.id
                    is_neutral = False
                    break

            # Confirmed schedule (kickoff/venue), matched on the unordered pair.
            sched = schedule.get((g["name"], frozenset({home.name, away.name})))
            kickoff_utc = venue = venue_city = venue_country = None
            if sched:
                if sched.get("kickoff_utc"):
                    kickoff_utc = datetime.fromisoformat(sched["kickoff_utc"])
                venue = sched.get("stadium")
                venue_city = sched.get("city")
                venue_country = sched.get("country")
            elif not is_neutral:
                # Fallback for host matches when no schedule row is present.
                venue_country = host_country_by_team[home.name if home.name in host_country_by_team else away.name]

            existing = db.query(Match).filter_by(
                tournament_id=tournament.id,
                group_id=group.id,
                team_home_id=home.id,
                team_away_id=away.id,
            ).one_or_none()
            if existing is not None:
                # Backfill schedule data on idempotent re-runs.
                existing.kickoff_utc = kickoff_utc
                existing.venue = venue
                existing.venue_city = venue_city
                existing.venue_country = venue_country
                existing.host_team_id = host_team_id
                existing.is_neutral = is_neutral
                continue

            db.add(
                Match(
                    tournament_id=tournament.id,
                    group_id=group.id,
                    stage="group",
                    team_home_id=home.id,
                    team_away_id=away.id,
                    is_neutral=is_neutral,
                    host_team_id=host_team_id,
                    kickoff_utc=kickoff_utc,
                    venue=venue,
                    venue_city=venue_city,
                    venue_country=venue_country,
                    status="scheduled",
                )
            )
            group_match_count += 1

    # 3. Knockout placeholders + idempotent match_no/kickoff stamping.
    #    Stamps newly-created AND pre-existing teamless rows; safe to re-run.
    kickoffs = _ko_kickoffs()
    match_no = 73
    ko_created = ko_stamped = 0
    for stage, count in KNOCKOUT_STAGES:
        rows = (
            db.query(Match)
            .filter(
                Match.tournament_id == tournament.id,
                Match.group_id.is_(None),
                Match.stage == stage,
            )
            .order_by(Match.id)
            .all()
        )
        for i in range(count):
            if i < len(rows):
                row = rows[i]
            else:
                row = Match(
                    tournament_id=tournament.id,
                    group_id=None,
                    stage=stage,
                    is_neutral=True,
                    status="scheduled",
                )
                db.add(row)
                ko_created += 1
            row.match_no = match_no
            if row.kickoff_utc is None:
                row.kickoff_utc = kickoffs.get(match_no)
            ko_stamped += 1
            match_no += 1

    db.commit()

    total_matches = db.query(Match).filter_by(tournament_id=tournament.id).count()
    return {
        "tournament_id": tournament.id,
        "teams": len(team_by_name),
        "groups": len(groups_data["groups"]),
        "group_matches_created": group_match_count,
        "knockout_created": ko_created,
        "ko_stamped": ko_stamped,
        "total_matches": total_matches,
    }
