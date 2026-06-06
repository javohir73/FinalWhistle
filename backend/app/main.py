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

from app.api import groups, internal, matches, predictions, teams
from app.config import settings

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    }


app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(teams.router)
app.include_router(groups.router)
app.include_router(internal.router)
