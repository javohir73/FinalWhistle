"""Knockout / tournament simulation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.cache import cache
from app.db import get_db
from app.models import Team, TournamentOdds

router = APIRouter(prefix="/api/knockout", tags=["knockout"])


@router.get("/odds", response_model=list[schemas.TournamentOddsOut])
def knockout_odds(db: Session = Depends(get_db)):
    """Every team's chance of reaching each knockout round and winning the title,
    from the full-tournament Monte-Carlo. Sorted by title probability."""
    cached = cache.get("knockout:odds")
    if cached is not None:
        return cached
    rows = db.query(TournamentOdds).all()
    out = []
    for r in rows:
        team = db.get(Team, r.team_id)
        out.append(
            schemas.TournamentOddsOut(
                team_id=r.team_id,
                team=team.name if team else "TBD",
                make_knockout=r.make_knockout,
                reach_r16=r.reach_r16,
                reach_qf=r.reach_qf,
                reach_sf=r.reach_sf,
                reach_final=r.reach_final,
                win_title=r.win_title,
            )
        )
    out.sort(key=lambda x: x.win_title or 0.0, reverse=True)
    cache.set("knockout:odds", out)
    return out
