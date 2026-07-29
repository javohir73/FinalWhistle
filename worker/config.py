"""Validated, environment-driven capture-worker settings.

Two defaults are deliberate and load-bearing:

* ``enabled`` is False. Importing this module, constructing settings, or
  starting the process without an explicit opt-in captures nothing and opens
  no socket.
* ``market_key_allowlist`` is empty, and empty means **capture nothing**. An
  absent allowlist is a missing decision, not permission to poll every market
  a venue happens to list.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def _positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    #: Master switch. Nothing polls, connects or writes without this.
    enabled: bool = False
    enabled_venues: tuple[str, ...] = ("kalshi", "polymarket")
    worker_id: str = "market-capture-local"
    discovery_seconds: int = 21_600
    prematch_seconds: int = 300
    inplay_seconds: int = 30
    #: Exact `venue:venue_key` entries. EMPTY MEANS CAPTURE NOTHING.
    market_key_allowlist: tuple[str, ...] = ()
    max_markets_per_venue: int = 5
    registry_scope: str = "eligible"
    request_timeout_seconds: float = 15.0
    retry_limit: int = 3
    backoff_initial_seconds: float = 0.5
    backoff_max_seconds: float = 8.0
    order_book_top_n: int = 10
    stale_quote_seconds: int = 300
    unsettled_warning_seconds: int = 86_400
    raw_store_backend: str = "local"
    raw_store_path: Path = Path("var/market-intel-raw")
    raw_store_bucket: str = ""
    raw_store_endpoint: str = ""
    raw_store_region: str = "auto"
    #: Bounded raw retention. A venue that starts returning multi-megabyte
    #: garbage must not be able to fill the disk one poll at a time.
    max_raw_payload_bytes: int = 2_000_000
    max_rejected_payloads_per_cycle: int = 5

    def __post_init__(self) -> None:
        venues = tuple(dict.fromkeys(v.strip().casefold() for v in self.enabled_venues if v.strip()))
        if not venues:
            raise ValueError("enabled_venues must not be empty")
        if not self.worker_id.strip():
            raise ValueError("worker_id must not be empty")
        object.__setattr__(self, "enabled_venues", venues)
        object.__setattr__(self, "worker_id", self.worker_id.strip())
        allowlist = tuple(
            dict.fromkeys(value.strip() for value in self.market_key_allowlist if value.strip())
        )
        for value in allowlist:
            if ":" not in value or not all(part.strip() for part in value.split(":", 1)):
                raise ValueError(
                    "market_key_allowlist entries must be qualified as venue:venue_key"
                )
        object.__setattr__(self, "market_key_allowlist", allowlist)
        registry_scope = self.registry_scope.strip().casefold()
        if registry_scope not in {"eligible", "all"}:
            raise ValueError("registry_scope must be eligible or all")
        object.__setattr__(self, "registry_scope", registry_scope)
        object.__setattr__(self, "raw_store_path", Path(self.raw_store_path))
        backend = self.raw_store_backend.strip().casefold()
        if backend not in {"local", "s3"}:
            raise ValueError("raw_store_backend must be local or s3")
        if backend == "s3" and (
            not self.raw_store_bucket.strip() or not self.raw_store_endpoint.strip()
        ):
            raise ValueError("s3 raw store requires bucket and endpoint")
        object.__setattr__(self, "raw_store_backend", backend)
        for name in (
            "discovery_seconds",
            "prematch_seconds",
            "inplay_seconds",
            "max_markets_per_venue",
            "request_timeout_seconds",
            "backoff_initial_seconds",
            "backoff_max_seconds",
            "order_book_top_n",
            "stale_quote_seconds",
            "unsettled_warning_seconds",
            "max_raw_payload_bytes",
        ):
            _positive(name, getattr(self, name))
        if self.retry_limit < 0:
            raise ValueError("retry_limit must be at least 0")
        if self.max_rejected_payloads_per_cycle < 0:
            raise ValueError("max_rejected_payloads_per_cycle must be at least 0")
        if self.backoff_max_seconds < self.backoff_initial_seconds:
            raise ValueError("backoff_max_seconds must be >= backoff_initial_seconds")

    def refuse_reason(self) -> str | None:
        """Why this configuration must not capture, or None if it may.

        Checked before the process does anything. A worker started without an
        opt-in, or without an explicit market list, stops with this message
        rather than quietly polling a whole venue catalogue.
        """
        if not self.enabled:
            return (
                "capture is disabled: set MARKET_CAPTURE_ENABLED=true to opt in. "
                "Nothing was fetched and nothing was written."
            )
        if not self.market_key_allowlist:
            return (
                "MARKET_CAPTURE_MARKET_KEYS is empty. An absent allowlist captures "
                "nothing -- it is never read as 'capture every market'. Set exact "
                "venue:venue_key entries."
            )
        return None

    @classmethod
    def from_env(cls) -> "CaptureSettings":
        def integer(name: str, default: int) -> int:
            return int(os.getenv(name, str(default)))

        def number(name: str, default: float) -> float:
            return float(os.getenv(name, str(default)))

        def flag(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            value = raw.strip().casefold()
            if value in _TRUE:
                return True
            if value in _FALSE:
                return False
            raise ValueError(f"{name} must be a boolean, got {raw!r}")

        defaults = cls()
        return cls(
            enabled=flag("MARKET_CAPTURE_ENABLED", defaults.enabled),
            enabled_venues=tuple(
                value.strip()
                for value in os.getenv(
                    "MARKET_CAPTURE_VENUES", ",".join(defaults.enabled_venues)
                ).split(",")
                if value.strip()
            ),
            worker_id=os.getenv("MARKET_CAPTURE_WORKER_ID", defaults.worker_id),
            market_key_allowlist=tuple(
                value.strip()
                for value in os.getenv("MARKET_CAPTURE_MARKET_KEYS", "").split(",")
                if value.strip()
            ),
            max_markets_per_venue=integer(
                "MARKET_CAPTURE_MAX_MARKETS_PER_VENUE", defaults.max_markets_per_venue
            ),
            registry_scope=os.getenv(
                "MARKET_CAPTURE_REGISTRY_SCOPE", defaults.registry_scope
            ),
            discovery_seconds=integer(
                "MARKET_CAPTURE_DISCOVERY_SECONDS", defaults.discovery_seconds
            ),
            prematch_seconds=integer(
                "MARKET_CAPTURE_PREMATCH_SECONDS", defaults.prematch_seconds
            ),
            inplay_seconds=integer(
                "MARKET_CAPTURE_INPLAY_SECONDS", defaults.inplay_seconds
            ),
            request_timeout_seconds=number(
                "MARKET_CAPTURE_TIMEOUT_SECONDS", defaults.request_timeout_seconds
            ),
            retry_limit=integer("MARKET_CAPTURE_RETRY_LIMIT", defaults.retry_limit),
            backoff_initial_seconds=number(
                "MARKET_CAPTURE_BACKOFF_INITIAL_SECONDS",
                defaults.backoff_initial_seconds,
            ),
            backoff_max_seconds=number(
                "MARKET_CAPTURE_BACKOFF_MAX_SECONDS", defaults.backoff_max_seconds
            ),
            order_book_top_n=integer(
                "MARKET_CAPTURE_BOOK_TOP_N", defaults.order_book_top_n
            ),
            stale_quote_seconds=integer(
                "MARKET_CAPTURE_STALE_SECONDS", defaults.stale_quote_seconds
            ),
            unsettled_warning_seconds=integer(
                "MARKET_CAPTURE_UNSETTLED_WARNING_SECONDS",
                defaults.unsettled_warning_seconds,
            ),
            raw_store_path=Path(
                os.getenv("MARKET_CAPTURE_RAW_STORE_PATH", str(defaults.raw_store_path))
            ),
            raw_store_backend=os.getenv(
                "MARKET_CAPTURE_RAW_STORE_BACKEND", defaults.raw_store_backend
            ),
            raw_store_bucket=os.getenv("MARKET_CAPTURE_RAW_STORE_BUCKET", ""),
            raw_store_endpoint=os.getenv("MARKET_CAPTURE_RAW_STORE_ENDPOINT", ""),
            raw_store_region=os.getenv(
                "MARKET_CAPTURE_RAW_STORE_REGION", defaults.raw_store_region
            ),
            max_raw_payload_bytes=integer(
                "MARKET_CAPTURE_MAX_RAW_PAYLOAD_BYTES", defaults.max_raw_payload_bytes
            ),
            max_rejected_payloads_per_cycle=integer(
                "MARKET_CAPTURE_MAX_REJECTED_PER_CYCLE",
                defaults.max_rejected_payloads_per_cycle,
            ),
        )
