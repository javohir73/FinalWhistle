"""Group / standings endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.db import get_db
from app.models import Group

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("", response_model=list[schemas.GroupOut])
def list_groups(db: Session = Depends(get_db)):
    cached = cache.get("groups:all")
    if cached is not None:
        return cached
    groups = db.query(Group).order_by(Group.name.asc()).all()
    result = [serializers.group_to_out(db, g) for g in groups]
    cache.set("groups:all", result)
    return result


@router.get("/{group_id}", response_model=schemas.GroupOut)
def group_detail(group_id: int, db: Session = Depends(get_db)):
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail={"code": "group_not_found",
                                                     "message": f"No group {group_id}"})
    return serializers.group_to_out(db, group)
