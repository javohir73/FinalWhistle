"""FastAPI application entrypoint.

Registers CORS and the API routers. For task 1.x this exposes only a health
check that proves the frontend can reach the backend end-to-end. Data/prediction
routers are added in task 5.0.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    """Liveness check. The frontend homepage calls this to prove connectivity."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "model_version": settings.model_version,
    }
