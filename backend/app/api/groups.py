"""Group / standings endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.competition_scope import competition_cache_key, tournament_for_competition
from app.db import get_db
from app.models import Group

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("", response_model=list[schemas.GroupOut])
def list_groups(competition: str | None = None, db: Session = Depends(get_db)):
    tournament = tournament_for_competition(db, competition)
    if competition is not None and tournament is None:
        return []

    cache_key = competition_cache_key("groups", competition)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    query = db.query(Group)
    if tournament is not None:
        query = query.filter(Group.tournament_id == tournament.id)
    groups = query.order_by(Group.name.asc()).all()
    result = [serializers.group_to_out(db, g) for g in groups]
    cache.set(cache_key, result)
    return result


@router.get("/{group_id}", response_model=schemas.GroupOut)
def group_detail(
    group_id: int,
    competition: str | None = None,
    db: Session = Depends(get_db),
):
    group = db.get(Group, group_id)
    tournament = tournament_for_competition(db, competition)
    if (
        group is None
        or (
            competition is not None
            and (tournament is None or group.tournament_id != tournament.id)
        )
    ):
        raise HTTPException(status_code=404, detail={"code": "group_not_found",
                                                     "message": f"No group {group_id}"})
    return serializers.group_to_out(db, group)
