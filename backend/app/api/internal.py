"""Internal recompute endpoint — triggered by the scheduled job (PRD §11).

Protected by a shared secret. Regenerates predictions from the current DB state
and clears the read cache. The FULL data refresh (download results, recompute
Elo) is the pipeline orchestrator wired in task 7; this endpoint is the hook the
cron calls.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _require_token(provided: str | None) -> None:
    """Authorize an internal call. Fails closed: if no token is configured the
    endpoint is disabled (503) instead of falling back to a guessable default.
    Uses a constant-time compare to avoid leaking the secret via timing."""
    expected = settings.recompute_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured",
                    "message": "Internal endpoints are disabled (RECOMPUTE_TOKEN unset)."},
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail={"code": "unauthorized",
                                                     "message": "Invalid recompute token"})


@router.post("/recompute")
def recompute(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    _require_token(x_recompute_token)
    # Lazy import: the model packages aren't needed for normal read traffic.
    from pipeline.generate_predictions import generate_predictions

    summary = generate_predictions(db, model_version=settings.model_version)
    cache.clear()
    return {"status": "ok", "recomputed": summary}


@router.post("/refresh-live")
def refresh_live(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Pull live in-game scores and update fixtures. Safe to call every minute
    (an external cron does this during match windows). No-op without an API key."""
    _require_token(x_recompute_token)
    from pipeline.ingest.live_scores import refresh_live as run_live

    summary = run_live(db)
    cache.clear()
    return {"status": "ok", "live": summary}


@router.post("/recompute-scores")
def recompute_scores_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Recompute every bracket's leaderboard score + rank from current results.
    Backend-owned scoring; run after results update."""
    _require_token(x_recompute_token)
    from app.scoring import recompute_scores

    scored = recompute_scores(db)
    cache.clear()
    return {"status": "ok", "brackets_scored": scored}
