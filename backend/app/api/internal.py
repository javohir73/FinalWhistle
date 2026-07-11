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
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import settings
from app.db import get_db
from app.model_meta import current_model_version

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
    # simulations from the adjusted ratings, THEN rescore brackets. Tracked:
    # success advances the chain watermark, failure is recorded for /api/health.
    from pipeline.learning_loop import run_tracked_post_results_chain

    summary = run_tracked_post_results_chain(
        db, current_model_version(), trigger="recompute", n_sims=5000, tournament_sims=2000
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
    (an external cron does this during match windows). No-op without an API key.
    A match finishing in this pass triggers the post-results chain, exactly as
    the traffic-driven refresh does — the cron path must not depend on board
    traffic to evaluate predictions and rescore brackets."""
    _require_token(x_recompute_token)
    from app.live_refresh import maybe_run_post_results_chain
    from pipeline.ingest.live_scores import refresh_live as run_live

    summary = run_live(db)
    maybe_run_post_results_chain(db, summary, trigger="internal")  # never raises
    cache.clear()
    return {"status": "ok", "live": summary}


@router.post("/nrl-refresh-live")
def nrl_refresh_live(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Poll every in-window NRL match's live state via StatsProvider.fetch_live
    and update nrl_live_state/nrl_live_events. Safe to call every minute; a
    scheduled workflow does so during NRL match windows (Thu-Sun AEST, plus
    the occasional Monday game -- see .github/workflows/nrl-live-refresh.yml)."""
    _require_token(x_recompute_token)
    from pipeline.sports.nrl_live_poll import poll_live_matches
    from pipeline.sports.nrl_stats import NrlComStatsProvider

    # NrlComStatsProvider.fetch_live is an honest None-stub until a real live
    # feed lands, so this endpoint currently reports polled=0 and is safe to
    # call any time.
    summary = poll_live_matches(db, NrlComStatsProvider())
    if summary["polled"]:
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


class FlagInternalUserIn(BaseModel):
    email: str | None = None
    display_name: str | None = None  # bracket display name shown on the board
    internal: bool = True


@router.post("/flag-internal-user")
def flag_internal_user(
    payload: FlagInternalUserIn,
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Mark an account as internal (smoke tests, ops) so it never appears on the
    public leaderboard, or unmark it with `"internal": false`. Select the account
    by email or by its (unique) leaderboard display name. Token-guarded:
    `curl -H "X-Recompute-Token: <token>" -H "Content-Type: application/json"
    -d '{"email": "..."}' <api>/api/internal/flag-internal-user`."""
    _require_token(x_recompute_token)
    from app.models import AppUser, Bracket
    from app.scoring import knockout_results_from_db, recompute_scores

    if (payload.email is None) == (payload.display_name is None):
        raise HTTPException(status_code=422, detail={
            "code": "one_selector_required",
            "message": "Provide exactly one of email or display_name."})
    if payload.email is not None:
        email = payload.email.strip().lower()
        user = db.query(AppUser).filter(func.lower(AppUser.email) == email).one_or_none()
    else:
        name = payload.display_name.strip().lower()
        matches = (
            db.query(AppUser)
            .join(Bracket, Bracket.user_id == AppUser.id)
            .filter(func.lower(Bracket.display_name) == name)
            .all()
        )
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail={
                "code": "ambiguous_display_name",
                "message": "Multiple accounts use that display name; flag by email."})
        user = matches[0] if matches else None
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "not_found",
                                                     "message": "No matching account."})
    user.is_internal = payload.internal
    db.commit()
    # Re-rank so leaderboard ranks stay contiguous without the flagged account.
    recompute_scores(db, knockout_results=knockout_results_from_db(db))
    cache.clear()
    return {"status": "ok", "email": user.email, "is_internal": user.is_internal}


@router.get("/shadow-record")
def shadow_record(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Production vs shadow model record, side by side (FR-4.6) — the input to
    the MANUAL promotion decision (FR-4.8; nothing here auto-promotes).
    Token-guarded: shadow numbers are internal until the owner says otherwise.

    Like-for-like: "production" is restricted to matches that ALSO have a
    shadow result, so both comparison columns aggregate the same match set.
    Matches evaluated before Phase 4 deployed have no shadow twin; letting
    them into the comparison would skew it by sample composition alone (e.g.
    an easy pre-deploy group-stage stretch the shadow never predicted). The
    unrestricted record ships separately as "production_full_record"."""
    _require_token(x_recompute_token)
    from app.models import PredictionResult

    def aggregate(rows: list) -> dict:
        n = len(rows)
        return {
            "n": n,
            "exact_hits": sum(1 for r in rows if r.exact_score_correct),
            "winner_acc": round(sum(1 for r in rows if r.winner_correct) / n, 4) if n else None,
            "avg_brier": round(sum(r.brier for r in rows) / n, 4) if n else None,
            # The runbook's promotion gate criterion is avg LOG LOSS (>=30
            # pairs AND the twin ahead) — Brier alone can't answer it. Old
            # rows may predate the column; average over the non-null values.
            "avg_log_loss": (
                round(sum(lls) / len(lls), 4)
                if (lls := [r.log_loss for r in rows if r.log_loss is not None])
                else None
            ),
            "model_versions": sorted({r.model_version for r in rows}),
        }

    shadow_rows = (
        db.query(PredictionResult).filter(PredictionResult.is_shadow.is_(True)).all()
    )
    production_rows = (
        db.query(PredictionResult).filter(PredictionResult.is_shadow.is_(False)).all()
    )
    shadow_match_ids = {r.match_id for r in shadow_rows}
    paired_production = [r for r in production_rows if r.match_id in shadow_match_ids]
    return {
        "production": aggregate(paired_production),
        "shadow": aggregate(shadow_rows),
        "production_full_record": aggregate(production_rows),
    }


@router.get("/availability-record")
def availability_record_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Availability twin vs published forecast, paired on finished matches — the
    availability signal's ONLY evidence path (it is live-only; no backtest gate).
    Token-guarded and internal: the input to the MANUAL promotion decision
    (FR-4.8), nothing here auto-promotes. Compute-on-read over frozen Prediction
    rows — no persistence, no prediction_results row (that stays odds-only)."""
    _require_token(x_recompute_token)
    # Lazy import (call-time) mirrors this module's other pipeline imports and
    # avoids the app->pipeline cycle at load.
    from pipeline.run_availability_benchmark import availability_record

    return availability_record(db)


@router.get("/offsets-record")
def offsets_record_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """xG-offsets twin vs published forecast, paired on finished matches — the
    StatsBomb xG-nudged team-offsets signal's evidence path
    (docs/superpowers/plans/2026-07-04-statsbomb-xg-team-offsets.md).
    Token-guarded and internal: the input to the MANUAL promotion decision,
    nothing here auto-promotes. Compute-on-read over frozen Prediction rows —
    no persistence, no prediction_results row (that stays odds-only)."""
    _require_token(x_recompute_token)
    # Lazy import (call-time) mirrors this module's other pipeline imports and
    # avoids the app->pipeline cycle at load.
    from pipeline.run_offsets_benchmark import offsets_record

    return offsets_record(db)


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
