"""Application settings, loaded from environment variables.

Centralizes config so nothing is hard-coded. The app name lives here as a single
constant (PRD Resolved Decision #5 — name finalized as "FinalWhistle").
"""
import re
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# A bare IPv4 host has no www/apex sibling to expand.
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


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

    # League pivot (docs/LEAGUE-PIVOT-PLAN.md D7): which competition
    # pipeline.run_pipeline.run_pipeline targets. "wc26" (default — every
    # existing step, byte-identical) or "league" (Premier League 2026-27:
    # league_structure + club Elo + club-model predictions/learning-loop;
    # WC-only steps like KO venues/bracket sim are skipped). Flipping this in
    # prod is the WS-C cutover (stop-gated) — config stays single-competition,
    # not a toggle for running both at once.
    pipeline_target: str = "wc26"

    # In-play events refetch cadence (seconds). Cards can arrive without a goal,
    # so live fixtures refetch /fixtures/events when the last fetch is older
    # than this. ~20 calls per live match hour on the default; the goal-count
    # trigger still fires immediately on any goal.
    events_refetch_seconds: int = 180

    # Master switch for live mode (activate near kickoff). Live updates are only
    # active when BOTH this is on and the active provider's key is set — else a
    # safe no-op.
    live_mode_enabled: bool = False

    # Post-results chain (runs opportunistically inside the web process after a
    # final whistle): slimmer Monte-Carlo than the daily pipeline — freshness
    # beats the last decimal there, and a long chain risks being killed on a
    # small instance mid-run. The 06:00 UTC pipeline re-simulates at full depth.
    chain_n_sims: int = 1000
    chain_tournament_sims: int = 500

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
    # state-changing requests (CSRF defense-in-depth). Comma-separated. The
    # www/apex sibling of each entry is auto-allowed (see allowed_origins).
    cors_origins: str = "http://localhost:3000"

    # OPTIONAL anchored regex admitting extra origins (e.g. this project's Vercel
    # preview deploys: ^https://fifa-wc26-prediction-[a-z0-9-]+\.vercel\.app$).
    # Empty => disabled (the safe default; a loose *.vercel.app pattern would be a
    # CSRF hole since anyone can deploy there). Feeds BOTH CORS and the Origin
    # guard; a malformed pattern fails closed (treated as disabled).
    cors_preview_regex: str = ""

    # Transactional email (password reset, email verification). Provider-agnostic:
    # EMAIL_PROVIDER="console" (default — logs the link, makes no network call) or
    # "resend". EMAIL_API_KEY is the provider secret; empty => safe console
    # fallback so a missing key never 500s the auth flow.
    email_provider: str = "console"
    email_api_key: str = ""
    email_from: str = "FinalWhistle <noreply@finalwhistle.app>"

    # Base URL for user-facing links embedded in emails (reset/verify). Must be an
    # allowed origin (see allowed_origins) so the page's same-origin POST passes
    # the Origin guard. Defaults to the canonical URL; never hardcode in routes.
    public_base_url: str = "https://fifa-wc26-prediction.vercel.app"

    # Read-cache lifetime. Lets a separate refresh process's DB writes appear in
    # the web process without cross-process cache invalidation.
    cache_ttl_seconds: int = 600

    # SANDBOX API keys gating the versioned public API (/v1, ROADMAP Phase 4).
    # Comma-separated allow-list. Empty (the shipped default) => the gate is OFF
    # and /v1 stays public exactly as Phase 2/3 shipped. Set API_KEYS_ALLOWED to a
    # comma-separated list of sandbox keys to require an X-API-Key header.
    api_keys_allowed: str = ""

    @property
    def allowed_api_keys(self) -> set[str]:
        """Sandbox API keys admitted to /v1 (empty => gate disabled, /v1 public)."""
        return {k.strip() for k in self.api_keys_allowed.split(",") if k.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @staticmethod
    def _sibling_origin(origin: str) -> str | None:
        """The www<->apex sibling of an origin, preserving scheme + port.
        Returns None for localhost, bare IPs, or anything without a registrable
        host (nothing meaningful to expand)."""
        parts = urlsplit(origin)
        if not parts.scheme or not parts.netloc:
            return None
        netloc = parts.netloc
        host, _, port = netloc.partition(":")
        if host == "localhost" or _IPV4_RE.match(host):
            return None
        if host.startswith("www."):
            sib_host = host[4:]
        elif "." in host:
            sib_host = "www." + host
        else:
            return None
        sib_netloc = f"{sib_host}:{port}" if port else sib_host
        return f"{parts.scheme}://{sib_netloc}"

    @property
    def allowed_origins(self) -> list[str]:
        """The configured origins plus each one's www/apex sibling (deduped,
        order-preserving). The single source of truth for both CORSMiddleware and
        the require_same_origin CSRF guard, so the two never drift."""
        out: list[str] = []
        for origin in self.cors_origin_list:
            if origin not in out:
                out.append(origin)
            sibling = self._sibling_origin(origin)
            if sibling and sibling not in out:
                out.append(sibling)
        return out

    @property
    def public_base_url_allowed(self) -> bool:
        """The reset/verification email links point at public_base_url, and those
        pages POST same-origin — so public_base_url MUST be an allowed origin or
        the submit 403s. (Only matters once real email sending is on.)"""
        return self.public_base_url in self.allowed_origins

    @property
    def email_status(self) -> str:
        """Diagnostic for /api/health — does prod actually SEND email?
          - "console"      : no real provider/key → links are only logged, never sent
                             (reset/verify will silently not arrive).
          - "misconfigured": a provider+key are set, but PUBLIC_BASE_URL isn't an
                             allowed origin, so the emailed link 403s on submit.
          - "ready"        : a real provider + key + a usable link base.
        Never exposes the key itself."""
        provider = (self.email_provider or "").strip().lower()
        if provider in ("", "console") or not self.email_api_key:
            return "console"
        if not self.public_base_url_allowed:
            return "misconfigured"
        return "ready"

    @property
    def cors_origin_regex(self) -> str | None:
        """The validated preview-origin pattern, or None when unset/invalid.
        Fails closed: a malformed regex admits nothing rather than crashing every
        request or accidentally allowing all."""
        pattern = self.cors_preview_regex.strip()
        if not pattern:
            return None
        try:
            re.compile(pattern)
        except re.error:
            return None
        return pattern

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
