"""Goalscorer-data ingestion helpers (Phase 2). Stage 1a ships only the team-id
linker; squad + per-player stats ingestion arrive in Stage 1b."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Player, Team
from pipeline.ingest.api_football import fetch_squad
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)


_POSITION_MAP = {"Goalkeeper": "G", "Defender": "D", "Midfielder": "M", "Attacker": "F"}


def _squad_position(pos: str | None) -> str | None:
    """Map an api-sports squad position word to our G/D/M/F code (None if unknown)."""
    return _POSITION_MAP.get(pos or "")


def ingest_squad(db: Session, api_key: str, team: Team) -> int:
    """Upsert Player rows (identity + position) for one team's squad, keyed on
    provider_player_id. Returns the number of squad players seen. No stats here."""
    if team.provider_team_id is None:
        return 0
    response = fetch_squad(api_key, team.provider_team_id)
    squad_players = (response[0].get("players") if response else None) or []
    seen = 0
    for p in squad_players:
        pid = p.get("id")
        if pid is None:
            continue
        row = db.query(Player).filter_by(provider_player_id=pid).one_or_none()
        if row is None:
            row = Player(provider_player_id=pid)
            db.add(row)
        if p.get("name"):
            row.name = p["name"]
        row.team_id = team.id
        mapped = _squad_position(p.get("position"))
        if mapped is not None:
            row.position = mapped
        seen += 1
    db.commit()
    return seen


def link_team_ids(db: Session, teams_response: list[dict]) -> int:
    """Set Team.provider_team_id from an api-sports /teams response, matching on
    the normalized team name. Returns the number of Team rows linked. Unknown
    provider teams are ignored (never create a Team)."""
    by_norm = {normalize_team_name(t.name): t for t in db.query(Team).all()}
    linked = 0
    for entry in teams_response or []:
        team = entry.get("team") or {}
        pid, pname = team.get("id"), team.get("name")
        if pid is None or not pname:
            continue
        row = by_norm.get(normalize_team_name(pname))
        if row is not None and row.provider_team_id != pid:
            row.provider_team_id = pid
            linked += 1
    db.commit()
    return linked
