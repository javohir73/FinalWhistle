"""Match endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.db import get_db
from app.models import Match

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("/upcoming", response_model=list[schemas.MatchSummaryOut])
def upcoming_matches(db: Session = Depends(get_db)):
    cached = cache.get("matches:upcoming")
    if cached is not None:
        return cached
    # All fixtures with known teams (scheduled, in-play, or finished) so the
    # board can show live and full-time scores, not just upcoming kickoffs.
    matches = (
        db.query(Match)
        .filter(Match.team_home_id.isnot(None))
        .order_by(Match.kickoff_utc.is_(None), Match.kickoff_utc.asc(), Match.id.asc())
        .all()
    )
    result = [serializers.match_to_summary(db, m) for m in matches]
    cache.set("matches:upcoming", result)
    return result


@router.get("/{match_id}", response_model=schemas.PredictionOut)
def match_detail(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    pred = serializers.latest_prediction(db, match_id)
    if pred is None:
        raise HTTPException(status_code=404, detail={"code": "no_prediction",
                                                     "message": "No prediction for this match yet"})
    return serializers.prediction_to_out(db, match, pred)
