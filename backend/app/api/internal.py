"""Internal recompute endpoint — triggered by the scheduled job (PRD §11).

Protected by a shared secret. Regenerates predictions from the current DB state
and clears the read cache. The FULL data refresh (download results, recompute
Elo) is the pipeline orchestrator wired in task 7; this endpoint is the hook the
cron calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.post("/recompute")
def recompute(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    if x_recompute_token != settings.recompute_token:
        raise HTTPException(status_code=401, detail={"code": "unauthorized",
                                                     "message": "Invalid recompute token"})
    # Lazy import: the model packages aren't needed for normal read traffic.
    from pipeline.generate_predictions import generate_predictions

    summary = generate_predictions(db, model_version=settings.model_version)
    cache.clear()
    return {"status": "ok", "recomputed": summary}
