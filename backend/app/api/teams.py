"""Team endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.competition_scope import competition_cache_key, tournament_for_competition
from app.db import get_db
from app.models import Group, GroupTeam, Team

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=list[schemas.TeamOut])
def list_teams(competition: str | None = None, db: Session = Depends(get_db)):
    """List teams, optionally isolated to one competition."""
    tournament = tournament_for_competition(db, competition)
    if competition is not None and tournament is None:
        return []

    cache_key = competition_cache_key("teams", competition)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    query = (
        db.query(Team)
        .join(GroupTeam, GroupTeam.team_id == Team.id)
        .join(Group, Group.id == GroupTeam.group_id)
    )
    if tournament is not None:
        query = query.filter(Group.tournament_id == tournament.id)
    teams = query.order_by(Team.elo_rating.is_(None), Team.elo_rating.desc()).all()
    result = [serializers.team_to_out(t) for t in teams]
    cache.set(cache_key, result)
    return result


@router.get("/{team_id}", response_model=schemas.TeamProfileOut)
def team_profile(
    team_id: int,
    competition: str | None = None,
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail={"code": "team_not_found",
                                                     "message": f"No team {team_id}"})
    tournament = tournament_for_competition(db, competition)
    if competition is not None:
        belongs = (
            tournament is not None
            and db.query(GroupTeam)
            .join(Group, Group.id == GroupTeam.group_id)
            .filter(
                GroupTeam.team_id == team_id,
                Group.tournament_id == tournament.id,
            )
            .first()
            is not None
        )
        if not belongs:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "team_not_found",
                    "message": f"No team {team_id} in {competition}",
                },
            )
    return serializers.team_profile(db, team)
