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


#: Minimum wait before RETRYING a chain that failed (or was killed) — the
#: 30s board polls must not hammer a chain that keeps dying on a small
#: instance. A brand-new final whistle always runs immediately.
CHAIN_RETRY_SECONDS = 600.0

_chain_lock = threading.Lock()  # chains never overlap within this process


def _chain_retry_due(db: Session) -> bool:
    """A chain is owed (finished matches no COMPLETED chain covers — it
    crashed, was killed mid-run, or the finish was ingested while nothing
    could react) and the retry backoff has elapsed since the last attempt."""
    from app.chain_status import chain_pending, get_chain_status

    if not chain_pending(db):
        return False
    row = get_chain_status(db)
    last = row.last_attempt_at if row else None
    if last is None:
        return True
    if last.tzinfo is None:  # SQLite drops tzinfo; naive means UTC here
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() >= CHAIN_RETRY_SECONDS


def maybe_run_post_results_chain(db: Session, summary: dict, trigger: str = "live_refresh") -> None:
    """Run the post-results learning chain when a refresh just finished a
    match, OR when a previous chain is still owed (retry with backoff) —
    recording the outcome under ``summary["post_results"]``.

    Shared by every live-ingestion entry point — the traffic-driven refresh
    below and POST /api/internal/refresh-live — so evaluation, rating updates,
    prediction regeneration and bracket rescoring never depend on one path
    catching one transition event. Never raises: scores are already committed,
    and the next trigger or the daily pipeline retries the chain.
    """
    try:
        if not summary.get("newly_finished") and not _chain_retry_due(db):
            return
        if not _chain_lock.acquire(blocking=False):
            return  # a chain is already running; the watermark covers stragglers
        try:
            from pipeline.learning_loop import run_tracked_post_results_chain

            chain = run_tracked_post_results_chain(
                db,
                settings.model_version,
                trigger=trigger,
                n_sims=settings.chain_n_sims,
                tournament_sims=settings.chain_tournament_sims,
            )
            summary["post_results"] = chain
            log.info("post-results chain (%s): %s", trigger, chain)
        finally:
            _chain_lock.release()
    except Exception:  # noqa: BLE001 — recorded in chain status; retried later
        log.exception("post-results chain failed; data remains consistent")


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
                # No live scores to fetch — but a chain may still be owed (it
                # crashed after the day's LAST final whistle, when the window
                # closes behind it). Board traffic retries it here, backoff-
                # limited, so the record heals before the 06:00 pipeline.
                summary = {}
                maybe_run_post_results_chain(db, summary)
                if summary.get("post_results"):
                    cache.clear()
                    return summary
                return None
            _last_attempt = time.monotonic()  # only real attempts hit the rate limit
            from pipeline.ingest.live_scores import refresh_live

            summary = refresh_live(db)
            # Final whistle just blew (or a chain is owed): run the learning
            # chain. Rare by nature — a handful of finals per day at most.
            maybe_run_post_results_chain(db, summary)
            if summary.get("updated") or summary.get("post_results"):
                cache.clear()  # evict stale board/odds so the next poll is fresh
            return summary
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — a feed/DB hiccup must never propagate
        log.warning("opportunistic live refresh failed: %s", exc)
        return None
    finally:
        _lock.release()
