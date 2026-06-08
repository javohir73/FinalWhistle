"""FastAPI application entrypoint.

Registers CORS and the API routers. For task 1.x this exposes only a health
check that proves the frontend can reach the backend end-to-end. Data/prediction
routers are added in task 5.0.
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import groups, internal, knockout, matches, predictions, teams
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
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def cache_control(request: Request, call_next):
    """Explicit cache headers on read endpoints. Predictions change only on the
    daily refresh, so a short shared-cache TTL + SWR lets any CDN/proxy serve
    repeats cheaply (and is harmless behind the app's no-store fetches)."""
    response = await call_next(request)
    path = request.url.path
    if (
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


app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(teams.router)
app.include_router(groups.router)
app.include_router(knockout.router)
app.include_router(internal.router)
