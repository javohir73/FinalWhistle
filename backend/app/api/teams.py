"""Team endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.db import get_db
from app.models import GroupTeam, Team

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=list[schemas.TeamOut])
def list_teams(db: Session = Depends(get_db)):
    """List the 48 WC2026 teams (those assigned to a group)."""
    cached = cache.get("teams:all")
    if cached is not None:
        return cached
    teams = (
        db.query(Team)
        .join(GroupTeam, GroupTeam.team_id == Team.id)
        .order_by(Team.elo_rating.is_(None), Team.elo_rating.desc())
        .all()
    )
    result = [serializers.team_to_out(t) for t in teams]
    cache.set("teams:all", result)
    return result


@router.get("/{team_id}", response_model=schemas.TeamProfileOut)
def team_profile(team_id: int, db: Session = Depends(get_db)):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail={"code": "team_not_found",
                                                     "message": f"No team {team_id}"})
    return serializers.team_profile(db, team)
