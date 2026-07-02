"""Durable heartbeat for the post-results chain (learning_chain_status row).

The chain runs opportunistically inside the web process after a final whistle;
on a small instance it can crash or be killed mid-run, and its trigger sites
swallow failures by design. This module gives every entry point a shared,
DB-backed record of the last attempt / success / failure, and a "pending"
signal — finished matches not yet covered by a COMPLETED chain — that later
refreshes (app/live_refresh.py) and the daily pipeline use to retry. No
finished match should ever depend on its single transition event being
processed successfully.

Deliberately imports only app.models: /api/health reads it without pulling the
ml/pipeline packages into the request path.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import LearningChainStatus, Match


def _now() -> datetime:
    return datetime.now(timezone.utc)


def finished_matches_query(db: Session):
    """Finished matches with known teams and scores — the single source of
    truth for chain eligibility, shared with the learning loop's sweep
    (pipeline/learning_loop._finished_matches) so the watermark counts exactly
    what the chain processes."""
    return db.query(Match).filter(
        Match.status == "finished",
        Match.score_home.isnot(None),
        Match.score_away.isnot(None),
        Match.team_home_id.isnot(None),
        Match.team_away_id.isnot(None),
    )


def finished_match_count(db: Session) -> int:
    return finished_matches_query(db).count()


def get_chain_status(db: Session) -> LearningChainStatus | None:
    return db.get(LearningChainStatus, 1)


def _get_or_create(db: Session) -> LearningChainStatus:
    row = get_chain_status(db)
    if row is None:
        row = LearningChainStatus(id=1, covered_finished=0)
        db.add(row)
    return row


def chain_pending(db: Session) -> bool:
    """True when matches have finished that no COMPLETED chain has covered.
    A match's finish is terminal, so the finished count only grows — a count
    above the success watermark always means owed work."""
    row = get_chain_status(db)
    covered = (row.covered_finished or 0) if row else 0
    return finished_match_count(db) > covered


def record_attempt(db: Session, trigger: str) -> None:
    """Stamp the attempt BEFORE the heavy chain runs and commit immediately:
    if the process is killed mid-simulation, the attempt (without a matching
    success) is still visible to /api/health and the backoff logic."""
    row = _get_or_create(db)
    row.last_attempt_at = _now()
    row.last_trigger = trigger
    db.commit()


def record_success(db: Session, covered_finished: int, trigger: str | None = None) -> dict:
    """Advance the success watermark — call ONLY after the full chain
    (evaluate -> ratings -> predictions -> brackets) completed."""
    row = _get_or_create(db)
    row.last_success_at = _now()
    row.covered_finished = covered_finished
    if trigger is not None:
        row.last_trigger = trigger
    db.commit()
    return {"covered_finished": covered_finished}


def record_failure(db: Session, exc: BaseException) -> None:
    row = _get_or_create(db)
    row.last_error_at = _now()
    row.last_error = f"{type(exc).__name__}: {exc}"[:500]
    db.commit()
