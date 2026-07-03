"""FastAPI application entrypoint.

Registers CORS and the API routers. For task 1.x this exposes only a health
check that proves the frontend can reach the backend end-to-end. Data/prediction
routers are added in task 5.0.
"""
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

from app.api import (
    auth, brackets, groups, internal, knockout, leaderboard, markets, match_picks, matches,
    model_record, predictions, teams,
)
from app.config import settings
from app.cache import cache
from app.db import get_db
from app.live_refresh import maybe_refresh_live

# Error tracking — only active when SENTRY_DSN is set (safe no-op otherwise).
if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.0,  # errors only; no perf tracing on the free tier
        send_default_pii=False,
    )
    sentry_sdk.set_tag("model_version", settings.model_version)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    # Single source of truth (shared with require_same_origin): configured origins
    # + their www/apex siblings, plus an optional anchored preview regex.
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Misconfig guard: once real email is on, the reset/verification links must point
# at an allowed origin or the page's same-origin POST 403s. (No-op in console mode.)
if settings.email_provider.strip().lower() not in ("", "console") and not settings.public_base_url_allowed:
    logger.warning(
        "PUBLIC_BASE_URL %r is not an allowed origin %s — reset/verification email "
        "links will 403 on submit. Add it to CORS_ORIGINS.",
        settings.public_base_url, settings.allowed_origins,
    )


@app.middleware("http")
async def cache_control(request: Request, call_next):
    """Explicit cache headers on read endpoints. Predictions change only on the
    daily refresh, so a short shared-cache TTL + SWR lets any CDN/proxy serve
    repeats cheaply (and is harmless behind the app's no-store fetches).

    Auth, bracket, and match-pick responses are user-specific and MUST never be
    shared-cached — a CDN keying on the (user-less) URL could otherwise serve one
    user's session/bracket/picks to another. Force `no-store` on those regardless
    of method."""
    response = await call_next(request)
    path = request.url.path
    if (
        path.startswith("/api/auth")
        or path.startswith("/api/brackets")
        or path.startswith("/api/match-picks")
    ):
        response.headers["Cache-Control"] = "no-store"
    elif path.startswith("/api/knockout/bracket") or path == "/api/matches/upcoming" or (
        path.startswith("/api/matches/") and path.endswith("/summary")
    ):
        # Live scoreboard feeds: the frontend polls these every 30s through
        # Vercel's same-origin /backend-api/* rewrite, and the edge honors
        # origin Cache-Control — a shared max-age let PoPs answer those polls
        # with minutes-old "scheduled" payloads after kickoff. A poll that
        # never reaches the origin also can't drive the opportunistic live
        # refresh (live_refresh.py). The in-process cache absorbs the load.
        response.headers["Cache-Control"] = "no-store"
    elif (
        request.method == "GET"
        and path.startswith("/api/")
        and path != "/api/health"
        and not path.startswith("/api/internal")
    ):
        response.headers.setdefault(
            "Cache-Control", "public, max-age=60, stale-while-revalidate=300"
        )
    elif request.method == "GET" and path.startswith("/v1/"):
        # Versioned public API (markets, Phase 2): shared-cacheable — the same
        # slow-moving read policy as /api/ reads. Frozen predictions change only
        # on the daily refresh, so a short shared TTL + SWR serves repeats cheaply.
        response.headers.setdefault(
            "Cache-Control", "public, max-age=60, stale-while-revalidate=300"
        )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Normalize all errors to {"error": {"code", "message"}} (PRD §11)."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"error": detail}
    else:
        body = {"error": {"code": f"http_{exc.status_code}", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": str(exc.errors())}},
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness check. The frontend homepage calls this to prove connectivity.

    Also surfaces the post-results chain heartbeat: chain failures are
    swallowed at the trigger sites by design, so this is where a silently
    dying chain (crash / instance kill mid-simulation) becomes visible to
    monitors. Guarded — liveness never depends on the DB being reachable."""
    out = {
        "status": "ok",
        "app": settings.app_name,
        "model_version": settings.model_version,
        "live_updates": "ready" if settings.live_updates_active else "inactive",
        "email": settings.email_status,
    }
    try:
        from app.chain_status import chain_pending, get_chain_status

        row = get_chain_status(db)

        def _iso(dt):
            return dt.isoformat() if dt else None

        out["learning_chain"] = {
            "pending": chain_pending(db),  # finished matches no completed chain covers
            "last_attempt_at": _iso(row.last_attempt_at if row else None),
            "last_success_at": _iso(row.last_success_at if row else None),
            "last_error_at": _iso(row.last_error_at if row else None),
            "last_error": row.last_error if row else None,
            "last_trigger": row.last_trigger if row else None,
        }
    except Exception:  # noqa: BLE001 — health must answer even without a DB
        out["learning_chain"] = {"status": "unavailable"}
    try:
        from app.prediction_coverage import matches_missing_prediction

        # Matches kicking off within 48h whose frozen prediction is missing —
        # each would be a guaranteed zero in the model record (FR-1.3).
        due = matches_missing_prediction(db, within_hours=48)
        out["prediction_coverage"] = {
            "missing": len(due),
            "match_ids": [m.id for m in due][:20],
        }
    except Exception:  # noqa: BLE001 — health must answer even without a DB
        out["prediction_coverage"] = {"status": "unavailable"}
    try:
        from app.models import PredictionResult

        # Shadow-mode progress only (task 4.9): the pair count tells monitors
        # the comparison sample is growing; the accuracy comparison itself
        # stays behind /api/internal/shadow-record's token (FR-4.6/FR-4.8).
        out["shadow_progress"] = {
            "pairs": db.query(PredictionResult)
            .filter(PredictionResult.is_shadow.is_(True))
            .count(),
        }
    except Exception:  # noqa: BLE001 — health must answer even without a DB
        out["shadow_progress"] = {"status": "unavailable"}
    return out


@app.get("/api/live/ping")
def live_ping(background_tasks: BackgroundTasks) -> dict:
    """Minimal keep-alive + live-refresh trigger for the every-minute cron.

    Schedules the SAME rate-limited, live-window-guarded refresh that board
    traffic triggers (maybe_refresh_live) — but returns a ~13-byte body so a
    response-size-limited cron service (cron-job.org caps response size and
    fails "output too large" on the full /api/matches/upcoming payload, which
    can auto-disable the job) never fails on it. No token: it exposes nothing
    a page load doesn't already trigger."""
    background_tasks.add_task(maybe_refresh_live)
    return {"ok": True}


@app.get("/api/health/provider")
def provider_health() -> dict:
    """On-demand diagnostic (cached): is the live provider's key reaching
    current-season PLAYER data — the prerequisite for goalscorer predictions?
    Returns the plan + reachability; never exposes the key."""
    if settings.live_provider != "api_football" or not settings.api_football_api_key:
        return {
            "provider": settings.live_provider,
            "player_data_reachable": None,
            "note": "api_football is not the active provider, or no key is set",
        }
    cached = cache.get("provider:player-probe")
    if cached is not None:
        return cached
    from pipeline.ingest.api_football import probe_player_access

    out = {"provider": "api_football", **probe_player_access(
        settings.api_football_api_key,
        settings.api_football_league,
        settings.api_football_season,
    )}
    cache.set("provider:player-probe", out)
    return out


@app.get("/api/health/provider-sample")
def provider_sample() -> dict:
    """One-off shape capture (cached): trimmed live samples of /teams,
    /players/squads and /players?id= so the goalscorer ingester is written
    against real field names. No secrets in the output."""
    if settings.live_provider != "api_football" or not settings.api_football_api_key:
        return {"provider": settings.live_provider, "note": "api_football not active or no key"}
    cached = cache.get("provider:sample")
    if cached is not None:
        return cached
    from pipeline.ingest.api_football import probe_player_sample

    out = probe_player_sample(
        settings.api_football_api_key,
        settings.api_football_league,
        settings.api_football_season,
        2025,
    )
    cache.set("provider:sample", out)
    return out


app.include_router(auth.router)
app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(teams.router)
app.include_router(groups.router)
app.include_router(knockout.router)
app.include_router(brackets.router)
app.include_router(match_picks.router)
app.include_router(leaderboard.router)
app.include_router(model_record.router)
app.include_router(internal.router)
app.include_router(markets.router)
