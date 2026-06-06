"""Tiny in-memory cache with a TTL and a Redis-ready interface (PRD §7, §4.4).

Read endpoints serve precomputed predictions from this cache so they never
trigger a model run. Entries expire after `ttl_seconds` so that a SEPARATE
process (e.g. the daily refresh cron) updating the database becomes visible to
the web process without cross-process invalidation. The recompute endpoint also
clears it explicitly. Swapping to Redis later means reimplementing get/set/clear
with the same signatures — callers don't change.
"""
from __future__ import annotations

import time
from typing import Any

from app.config import settings


class InMemoryCache:
    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.cache_ttl_seconds

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time() + self._ttl, value)

    def clear(self) -> None:
        self._store.clear()


# Module-level singleton used by the routers.
cache = InMemoryCache()
