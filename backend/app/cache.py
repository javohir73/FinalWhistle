"""Tiny in-memory cache with a Redis-ready interface (PRD §7, §4.4).

Read endpoints serve precomputed predictions from this cache so they never
trigger a model run. The pipeline/recompute step calls `clear()` after writing
fresh predictions. Swapping to Redis later means reimplementing get/set/clear
with the same signatures — callers don't change.
"""
from __future__ import annotations

from typing import Any


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def clear(self) -> None:
        self._store.clear()


# Module-level singleton used by the routers.
cache = InMemoryCache()
