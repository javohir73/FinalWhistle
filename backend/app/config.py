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

    # Alternative live provider: API-Football (api-sports.io). Richer feed whose
    # fixtures carry the real live minute (status.elapsed), so the scoreboard clock
    # is the official one rather than a kickoff estimate. Empty => unused.
    api_football_api_key: str = ""
    api_football_league: int = 1   # API-Football league id for the FIFA World Cup
    api_football_season: int = 2026

    # Which provider serves /api/internal/refresh-live: "football_data" (default,
    # free tier → estimated minute) or "api_football" (real live minute).
    live_provider: str = "football_data"

    # Master switch for live mode (activate near kickoff). Live updates are only
    # active when BOTH this is on and the active provider's key is set — else a
    # safe no-op.
    live_mode_enabled: bool = False

    @property
    def active_live_api_key(self) -> str:
        """API key for the currently selected live provider ("" => unconfigured)."""
        if self.live_provider == "api_football":
            return self.api_football_api_key
        return self.football_data_api_key

    @property
    def live_updates_active(self) -> bool:
        return bool(self.live_mode_enabled and self.active_live_api_key)

    # Error tracking (Sentry). Empty => disabled (safe no-op).
    sentry_dsn: str = ""
    environment: str = "production"

    # Auth — first-party email+password accounts on opaque session cookies.
    # COOKIE_SECURE must be "false" in local dev (http://localhost), "true" in prod
    # (the Secure flag stops a cookie from being sent over plain http otherwise).
    cookie_secure: bool = True

    # CORS / allowed browser origins. Also used for the Origin check on
    # state-changing requests (CSRF defense-in-depth). Comma-separated.
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
