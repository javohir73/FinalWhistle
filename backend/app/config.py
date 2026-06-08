"""Application settings, loaded from environment variables.

Centralizes config so nothing is hard-coded. The app name lives here as a single
constant (PRD Resolved Decision #5 — name finalized as "FinalWhistle").
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Product
    app_name: str = "FinalWhistle"
    model_version: str = "poisson-elo-v0.1"

    # Database — defaults to the local docker-compose Postgres.
    database_url: str = "postgresql+psycopg2://wc26:wc26@localhost:5432/wc26"

    # Secret token guarding POST /api/internal/recompute and /refresh-live.
    # No production default on purpose: if RECOMPUTE_TOKEN is unset the endpoints
    # refuse all calls (see api/internal.py) rather than accepting a known secret.
    recompute_token: str = ""

    # Live in-game scores (football-data.org). Empty => live updates disabled.
    football_data_api_key: str = ""
    football_data_competition: str = "WC"  # FIFA World Cup competition code

    # CORS: comma-separated list of allowed frontend origins.
    cors_origins: str = "http://localhost:3000"

    # Read-cache lifetime. Lets a separate refresh process's DB writes appear in
    # the web process without cross-process cache invalidation.
    cache_ttl_seconds: int = 600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """Normalize provider URLs (e.g. Render's 'postgres://') to a SQLAlchemy
        driver URL so deploys work without manual editing."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url


settings = Settings()
