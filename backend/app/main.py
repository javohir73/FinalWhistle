"""FastAPI application entrypoint.

Registers CORS and the API routers. For task 1.x this exposes only a health
check that proves the frontend can reach the backend end-to-end. Data/prediction
routers are added in task 5.0.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

from app.api import (
    auth, brackets, groups, internal, knockout, leaderboard, match_picks, matches,
    model_record, predictions, teams,
)
from app.config import settings

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
    elif path == "/api/matches/upcoming" or (
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
def health() -> dict:
    """Liveness check. The frontend homepage calls this to prove connectivity."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "model_version": settings.model_version,
        "live_updates": "ready" if settings.live_updates_active else "inactive",
    }


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
