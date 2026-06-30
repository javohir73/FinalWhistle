"""Goalscorer-data ingestion helpers (Phase 2). Stage 1a ships only the team-id
linker; squad + per-player stats ingestion arrive in Stage 1b."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Team
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)


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
