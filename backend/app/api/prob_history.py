"""Per-match public prediction history — feeds match-card sparklines."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Match, Prediction

router = APIRouter(prefix="/api/matches", tags=["matches"])

_MAX_POINTS = 7
# Every pipeline run appends a Prediction row, so a single calendar day can
# hold several. Fetch enough recent rows to comfortably cover _MAX_POINTS
# distinct days even at a handful of runs/day, then collapse in Python.
_FETCH_LIMIT = 60


@router.get("/{match_id}/prob-history")
def prob_history(match_id: int, db: Session = Depends(get_db)):
    if db.get(Match, match_id) is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    rows = (
        db.query(Prediction)
        .filter(Prediction.match_id == match_id, Prediction.is_shadow.is_(False))
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(_FETCH_LIMIT)
        .all()
    )
    # Collapse to at most one point per calendar day (the latest run of that
    # day) — rows are already ordered desc by (created_at, id), so the first
    # row seen for a given date is its latest. Keep the most recent
    # _MAX_POINTS distinct days, then restore ascending order.
    daily: list[Prediction] = []
    seen_dates: set = set()
    for p in rows:
        day = p.created_at.date() if p.created_at else None
        if day in seen_dates:
            continue
        seen_dates.add(day)
        daily.append(p)
        if len(daily) == _MAX_POINTS:
            break
    daily.reverse()
    return {
        "match_id": match_id,
        "points": [
            {
                "date": p.created_at.isoformat() if p.created_at else None,
                "p_home": p.prob_home_win,
                "p_draw": p.prob_draw,
                "p_away": p.prob_away_win,
            }
            for p in daily
        ],
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
