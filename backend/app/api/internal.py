"""Internal recompute endpoint — triggered by the scheduled job (PRD §11).

Protected by a shared secret. Regenerates predictions from the current DB state
and clears the read cache. The FULL data refresh (download results, recompute
Elo) is the pipeline orchestrator wired in task 7; this endpoint is the hook the
cron calls.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func
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
    # Full chain: evaluate finished predictions + update tournament ratings
    # (conservative Elo delta + capped form), THEN regenerate predictions and
    # simulations from the adjusted ratings, THEN rescore brackets.
    from pipeline.learning_loop import run_post_results_chain

    summary = run_post_results_chain(
        db, settings.model_version, n_sims=5000, tournament_sims=2000
    )
    cache.clear()
    return {"status": "ok", "recomputed": summary}


def _run_refresh_players(db, api_key: str, league: int) -> dict:
    """Indirection point (patchable in tests) for the player-stats ingestion pass."""
    from pipeline.ingest.players import refresh_players
    return refresh_players(db, api_key, league)


@router.post("/refresh-players")
def refresh_players_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
) -> dict:
    """Run one bounded player-stats ingestion pass (squads + club/WC scoring).
    Token-guarded; the heavy api-football calls run here, where the key lives."""
    _require_token(x_recompute_token)
    if settings.live_provider != "api_football" or not settings.api_football_api_key:
        return {"skipped": "api_football not active or no key",
                "teams_linked": 0, "squads_ingested": 0, "players_refreshed": 0}
    return _run_refresh_players(db, settings.api_football_api_key, settings.api_football_league)


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


@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Lightweight ops counts (signups, brackets). Token-guarded — same secret as
    the other internal endpoints. Use to check signups without DB access:
    `curl -H "X-Recompute-Token: <token>" <api>/api/internal/stats`."""
    _require_token(x_recompute_token)
    from app.models import AppUser, Bracket

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    latest = db.query(func.max(AppUser.created_at)).scalar()

    by_country = [
        {"country": c or "??", "count": n}
        for c, n in db.query(AppUser.signup_country, func.count(AppUser.id))
        .group_by(AppUser.signup_country)
        .order_by(func.count(AppUser.id).desc())
        .all()
    ]
    by_city = [
        {"city": city, "country": country or "??", "count": n}
        for city, country, n in db.query(
            AppUser.signup_city, AppUser.signup_country, func.count(AppUser.id)
        )
        .filter(AppUser.signup_city.isnot(None))
        .group_by(AppUser.signup_city, AppUser.signup_country)
        .order_by(func.count(AppUser.id).desc())
        .limit(20)
        .all()
    ]
    return {
        "users": db.query(AppUser).count(),
        "signups_last_24h": db.query(AppUser).filter(AppUser.created_at >= since).count(),
        "brackets": db.query(Bracket).count(),
        "public_brackets": db.query(Bracket).filter(Bracket.visibility == "public").count(),
        "latest_signup": latest.isoformat() if latest else None,
        "by_country": by_country,
        "by_city": by_city,
    }


@router.post("/recompute-scores")
def recompute_scores_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Recompute every bracket's leaderboard score + rank from current results.
    Backend-owned scoring; run after results update."""
    _require_token(x_recompute_token)
    from app.scoring import recompute_scores, knockout_results_from_db

    scored = recompute_scores(db, knockout_results=knockout_results_from_db(db))
    cache.clear()
    return {"status": "ok", "brackets_scored": scored}
