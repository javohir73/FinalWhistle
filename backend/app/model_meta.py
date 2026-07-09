"""Single source of truth for the model version REPORTED by monitoring and
analytics surfaces (health, Sentry tagging, the learning-loop's fallback tag,
the model-record API).

The version that actually TAGS prediction rows is
``ml.models.params.load_params().version`` — pipeline/generate_predictions.py
stamps ``params.version`` directly, and that path is untouched by this helper.
Everything else that needs to SAY what version is currently live should go
through ``current_model_version()`` instead of ``app.config.settings.model_version``,
so reporting can never drift from what's actually being served (the v0.1
code default / v0.4 render.yaml pin vs. the real v0.5 in model_params.json).
"""
from __future__ import annotations

from ml.models.params import load_params

_cached_version: str | None = None


def current_model_version() -> str:
    """The live model version, read from ml/models/model_params.json.

    Falls back to ``app.config.settings.model_version`` (the documented
    default) if the params file can't be read for any reason — this must
    never raise, since callers include health checks and Sentry init.

    Caches the first successful read: model_params.json doesn't change
    within a running process (a new version ships as a fresh deploy), and
    load_params() itself re-reads the file from disk on every call with no
    caching of its own.
    """
    global _cached_version
    if _cached_version is not None:
        return _cached_version
    try:
        version = load_params().version
    except Exception:  # noqa: BLE001 — must never raise; reporting paths need an answer
        from app.config import settings

        return settings.model_version
    _cached_version = version
    return version
