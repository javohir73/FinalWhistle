"""Versioned public markets API — GET /v1/markets/{match_id} (Phase 2,
docs/ROADMAP-ENGINE.md).

Additive, read-only surface for B2B consumers: it reads the FROZEN Prediction
row and returns derived betting markets with model version, calibration metadata
and the explanation payload. It never runs the model (serializers depend only on
app.models); it only marginalizes the stored distribution.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.db import get_db
from app.models import Match

router = APIRouter(prefix="/v1/markets", tags=["markets-v1"])


@router.get("/{match_id}", response_model=schemas.MarketsOut)
def markets_for_match(
    match_id: int,
    live: int = Query(0, description="1 to re-price from the in-play state when the match is live"),
    db: Session = Depends(get_db),
):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "not_found",
                                                     "message": f"No match {match_id}"})
    pred = serializers.latest_prediction(db, match_id)
    if pred is None:
        raise HTTPException(status_code=404, detail={"code": "no_prediction",
                                                     "message": "No prediction for this match yet"})
    if pred.lambda_home is None or pred.lambda_away is None:
        # A prediction without engine params can't price the scoreline grid.
        raise HTTPException(status_code=404, detail={"code": "markets_unavailable",
                                                     "message": "No scoreline model for this match"})
    # ?live=1 on a live match re-prices from the current score/clock; the live
    # serializer itself falls back to the frozen markets when the state isn't
    # usable. Any other case (no ?live, or not in play) is the Phase-2 payload
    # unchanged — the default is byte-identical to before.
    if live == 1 and match.status == "in_play":
        return serializers.prediction_to_live_markets_out(db, match, pred)
    return serializers.prediction_to_markets_out(db, match, pred)
