"""Leaderboard: public top-N (no auth) + join (auth).

Scores are computed server-side (app/scoring.py); this only reads them. Only
brackets the user explicitly made public appear — private is the default.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import schemas
from app.auth import get_current_user
from app.cache import cache
from app.db import get_db
from app.models import AppUser, Bracket, BracketScore, Team

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("", response_model=list[schemas.LeaderboardRowOut])
def leaderboard(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Public leaderboard, ranked by total points. No auth required (read-only)."""
    total_public = db.query(Bracket).filter(Bracket.visibility == "public").count()
    rows = (
        db.query(Bracket, BracketScore, Team)
        .outerjoin(BracketScore, BracketScore.bracket_id == Bracket.id)
        .outerjoin(Team, Team.id == Bracket.champion_team_id)
        .filter(Bracket.visibility == "public")
        .order_by(
            BracketScore.total_points.is_(None),
            BracketScore.total_points.desc(),
            Bracket.submitted_at.asc(),
        )
        .limit(limit)
        .all()
    )
    out = []
    for bracket, score, team in rows:
        rank = score.rank if score else None
        pct = (
            round(100.0 * (total_public - rank + 1) / total_public)
            if rank and total_public
            else None
        )
        out.append(
            schemas.LeaderboardRowOut(
                rank=rank,
                display_name=bracket.display_name or "Anonymous",
                champion=team.name if team else None,
                total_points=score.total_points if score else 0,
                percentile=pct,
                updated_at=bracket.updated_at.isoformat() if bracket.updated_at else None,
            )
        )
    return out


@router.post("/join", response_model=schemas.BracketOut)
def join_leaderboard(
    payload: schemas.JoinLeaderboardIn,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Publish the user's bracket to the leaderboard with a display name."""
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail={"code": "name_required",
                                                     "message": "A display name is required."})
    b = db.query(Bracket).filter_by(user_id=user.id).one_or_none()
    if b is None:
        raise HTTPException(status_code=404, detail={"code": "no_bracket",
                                                     "message": "Save a bracket before joining."})
    b.display_name = name[:60]
    b.visibility = "public" if payload.visibility != "private" else "private"
    b.submitted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(b)
    cache.clear()
    from app.api.brackets import to_bracket_out
    return to_bracket_out(b)
