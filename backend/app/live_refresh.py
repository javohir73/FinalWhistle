"""Opportunistic in-process live-score refresh.

The matches board polls /api/matches/upcoming every 30s while anyone is
watching, so that traffic itself can keep live scores fresh — no external
every-minute cron required. POST /api/internal/refresh-live still exists for
an optional belt-and-braces cron.

Guards, in order:
- live mode must be active (LIVE_MODE_ENABLED + an API key);
- at most one upstream attempt per MIN_INTERVAL_SECONDS (football-data.org's
  free tier allows 10 req/min — we use at most 1);
- only inside a live window (a match in play, or a kickoff within the last
  3 hours / next 5 minutes), so idle days cost zero API calls.

Runs as a FastAPI background task after the response is sent — readers never
wait on the upstream feed.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import settings
from app.models import Match

log = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 60.0
_WINDOW_BACK = timedelta(hours=3)  # kicked off recently → may be in play
_WINDOW_AHEAD = timedelta(minutes=5)  # kicking off imminently → flip promptly

_lock = threading.Lock()
_last_attempt = 0.0  # time.monotonic() of the last upstream attempt


def in_live_window(db: Session) -> bool:
    """True when live scores could plausibly be changing right now: a match is
    in play, or a scheduled match kicked off recently / kicks off imminently
    (covering the scheduled→in-play transition our DB hasn't seen yet)."""
    now = datetime.now(timezone.utc)
    return (
        db.query(Match.id)
        .filter(
            or_(
                Match.status == "in_play",
                and_(
                    Match.status == "scheduled",
                    Match.kickoff_utc.isnot(None),
                    Match.kickoff_utc >= now - _WINDOW_BACK,
                    Match.kickoff_utc <= now + _WINDOW_AHEAD,
                ),
            )
        )
        .first()
        is not None
    )


def maybe_refresh_live(session_factory=None) -> dict | None:
    """Refresh live scores if live mode is on, the rate limit allows it, and a
    live window is active. Never raises (background task). Returns the refresh
    summary, or None when skipped."""
    global _last_attempt
    if not settings.live_updates_active:
        return None
    if not _lock.acquire(blocking=False):
        return None  # another request's refresh is already running
    try:
        if time.monotonic() - _last_attempt < MIN_INTERVAL_SECONDS:
            return None
        if session_factory is None:
            from app.db import SessionLocal as session_factory  # late: avoid cycles
        db = session_factory()
        try:
            if not in_live_window(db):
                return None
            _last_attempt = time.monotonic()  # only real attempts hit the rate limit
            from pipeline.ingest.live_scores import refresh_live

            summary = refresh_live(db)
            if summary.get("updated"):
                cache.clear()  # evict the stale board so the next poll shows new scores
            return summary
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — a feed/DB hiccup must never propagate
        log.warning("opportunistic live refresh failed: %s", exc)
        return None
    finally:
        _lock.release()
