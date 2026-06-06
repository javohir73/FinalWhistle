"""Prediction endpoint with history for the trend chart (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.db import get_db
from app.models import Match, Prediction

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


class PredictionHistoryPoint(BaseModel):
    generated_at: str | None
    model_version: str
    home_win: float
    draw: float
    away_win: float


class PredictionWithHistory(BaseModel):
    current: schemas.PredictionOut
    history: list[PredictionHistoryPoint]


@router.get("/{match_id}", response_model=PredictionWithHistory)
def prediction_for_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    pred = serializers.latest_prediction(db, match_id)
    if pred is None:
        raise HTTPException(status_code=404, detail={"code": "no_prediction",
                                                     "message": "No prediction for this match yet"})

    history_rows = (
        db.query(Prediction)
        .filter_by(match_id=match_id)
        .order_by(Prediction.created_at.asc(), Prediction.id.asc())
        .all()
    )
    history = [
        PredictionHistoryPoint(
            generated_at=r.created_at.isoformat() if r.created_at else None,
            model_version=r.model_version,
            home_win=r.prob_home_win,
            draw=r.prob_draw,
            away_win=r.prob_away_win,
        )
        for r in history_rows
    ]
    return PredictionWithHistory(
        current=serializers.prediction_to_out(db, match, pred), history=history
    )
