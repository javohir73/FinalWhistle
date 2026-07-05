"""Public model-vs-market endpoint: the live comparison against the final
pre-kickoff consensus we captured.

Compute-on-read over the captured Odds + pre-kickoff Prediction rows, mirroring
GET /api/model/record. Lazy-imports the pipeline so the app package does not
depend on pipeline at import time (same pattern as
/api/internal/availability-record).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.cache import cache
from app.db import get_db

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/market-record")
def market_record_endpoint(db: Session = Depends(get_db)):
    cached = cache.get("model:market-record")
    if cached is not None:
        return cached
    from pipeline.run_market_benchmark import market_record

    out = market_record(db)
    cache.set("model:market-record", out)
    return out
