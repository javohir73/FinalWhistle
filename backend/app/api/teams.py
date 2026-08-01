"""Team endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.competition_scope import competition_cache_key, tournament_for_competition
from app.db import get_db
from app.models import Group, GroupTeam, Match, Team
from pipeline.leagues import LEAGUES

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
    if tournament is not None:
        # Shared-table cups can have qualifying/knockout participants that do
        # not belong in GroupTeam (and therefore must not enter standings).
        # They still need to appear in the competition team list and have
        # working profile links from fixture cards.
        team_ids = {
            team_id
            for (team_id,) in (
                db.query(GroupTeam.team_id)
                .join(Group, Group.id == GroupTeam.group_id)
                .filter(Group.tournament_id == tournament.id)
                .all()
            )
        }
        for home_id, away_id in (
            db.query(Match.team_home_id, Match.team_away_id)
            .filter(Match.tournament_id == tournament.id)
            .all()
        ):
            if home_id is not None:
                team_ids.add(home_id)
            if away_id is not None:
                team_ids.add(away_id)
        query = db.query(Team).filter(Team.id.in_(team_ids))
    else:
        query = (
            db.query(Team)
            .join(GroupTeam, GroupTeam.team_id == Team.id)
            .join(Group, Group.id == GroupTeam.group_id)
        )
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
        belongs_to_group = (
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
        belongs_to_fixture = (
            tournament is not None
            and db.query(Match)
            .filter(
                Match.tournament_id == tournament.id,
                (Match.team_home_id == team_id) | (Match.team_away_id == team_id),
            )
            .first()
            is not None
        )
        if not belongs_to_group and not belongs_to_fixture:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "team_not_found",
                    "message": f"No team {team_id} in {competition}",
                },
            )
    history_competition = (
        LEAGUES[competition]["club_competition"]
        if competition in LEAGUES
        else None
    )
    return serializers.team_profile(
        db,
        team,
        tournament_id=tournament.id if tournament is not None else None,
        history_competition=history_competition,
    )
