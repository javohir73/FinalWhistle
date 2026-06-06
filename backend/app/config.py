"""Application settings, loaded from environment variables.

Centralizes config so nothing is hard-coded. The app name lives here as a single
constant (PRD Resolved Decision #5 — "PitchProphet" is a placeholder name).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Product
    app_name: str = "PitchProphet"
    model_version: str = "poisson-elo-v0.1"

    # Database — defaults to the local docker-compose Postgres.
    database_url: str = "postgresql+psycopg2://wc26:wc26@localhost:5432/wc26"

    # Secret token guarding POST /api/internal/recompute.
    recompute_token: str = "dev-recompute-token"

    # CORS: comma-separated list of allowed frontend origins.
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
