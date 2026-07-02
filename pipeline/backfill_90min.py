"""Backfill score_home_90/score_away_90 for already-finished matches (FR-2.3).

The live capture (pipeline/ingest/live_scores.py) freezes the regulation score
going forward; this fills history — and self-heals matches whose extra-time
polls were all missed (cron gaps on the free tier):

- group-stage matches never have extra time: the final IS the 90' score;
- knockout matches derive the 90' score from goal-event minutes, but ONLY
  when the events reconcile exactly with the stored final score — missing or
  contaminated event lists (e.g. shootout kicks recorded as goals) fail the
  reconciliation and the match keeps a NULL 90' score, so evaluation falls
  back to the after-ET final rather than trusting a bad reconstruction.

Idempotent: rows with a captured 90' score are never touched. Runs as a cheap
daily-pipeline step (only NULL rows are examined).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Match

log = logging.getLogger(__name__)


def _derive_from_events(m: Match) -> tuple[int, int] | None:
    """Regulation score from goal-event minutes; None when unreconcilable.

    Event minutes are the provider's ``time.elapsed`` — 90 for stoppage-time
    goals (90+x), 91-120 for extra time — so ``minute <= 90`` is exactly the
    regulation set.
    """
    events = m.goal_events or []
    if not events:
        return None
    if any(not isinstance(e, dict) or e.get("minute") is None or e.get("side") not in ("home", "away")
           for e in events):
        return None
    h_all = sum(1 for e in events if e["side"] == "home")
    a_all = sum(1 for e in events if e["side"] == "away")
    if (h_all, a_all) != (m.score_home, m.score_away):
        return None  # incomplete or contaminated — never guess
    h90 = sum(1 for e in events if e["side"] == "home" and e["minute"] <= 90)
    a90 = sum(1 for e in events if e["side"] == "away" and e["minute"] <= 90)
    return h90, a90


def backfill_90min_scores(db: Session) -> int:
    """Fill NULL 90-minute scores where derivable; returns rows updated."""
    rows = (
        db.query(Match)
        .filter(
            Match.status == "finished",
            Match.score_home.isnot(None),
            Match.score_away.isnot(None),
            Match.score_home_90.is_(None),
        )
        .all()
    )
    updated = 0
    for m in rows:
        if m.stage == "group":
            m.score_home_90, m.score_away_90 = m.score_home, m.score_away
            updated += 1
            continue
        derived = _derive_from_events(m)
        if derived is not None:
            m.score_home_90, m.score_away_90 = derived
            updated += 1
    if updated:
        db.commit()
    log.info("90-minute backfill: %d row(s) filled, %d left NULL",
             updated, len(rows) - updated)
    return updated
