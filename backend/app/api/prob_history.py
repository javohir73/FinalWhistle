"""Per-match public prediction history — feeds match-card sparklines."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Match, Prediction

router = APIRouter(prefix="/api/matches", tags=["matches"])

_MAX_POINTS = 7


@router.get("/{match_id}/prob-history")
def prob_history(match_id: int, db: Session = Depends(get_db)):
    if db.get(Match, match_id) is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    rows = (
        db.query(Prediction)
        .filter(Prediction.match_id == match_id, Prediction.is_shadow.is_(False))
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(_MAX_POINTS)
        .all()
    )
    rows.reverse()
    return {
        "match_id": match_id,
        "points": [
            {
                "date": p.created_at.isoformat() if p.created_at else None,
                "p_home": p.prob_home_win,
                "p_draw": p.prob_draw,
                "p_away": p.prob_away_win,
            }
            for p in rows
        ],
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
