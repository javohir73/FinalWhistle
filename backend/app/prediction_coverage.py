"""Read-only prediction-coverage detector (FR-1.2/FR-1.3).

A scheduled match with both teams assigned but no prediction row would be
silently skipped by the learning loop at evaluation time (a guaranteed zero
in the model record), because evaluation scores only the frozen pre-kickoff
prediction. This query is the shared detector used by /api/health and the
daily pipeline's coverage step; the generating sweep lives in
pipeline/prediction_coverage.py.

Deliberately imports only app.models — /api/health reads it without pulling
the ml/pipeline packages into the request path (same policy as chain_status).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Match, Prediction


def matches_missing_prediction(
    db: Session, within_hours: float | None = None
) -> list[Match]:
    """Scheduled matches with both teams known and NO prediction row.

    ``within_hours`` narrows to kickoffs inside the window (an unknown kickoff
    cannot be proven far away, so it is treated as due — defensive).
    """
    has_prediction = (
        db.query(Prediction.id).filter(Prediction.match_id == Match.id).exists()
    )
    q = db.query(Match).filter(
        Match.status == "scheduled",
        Match.team_home_id.isnot(None),
        Match.team_away_id.isnot(None),
        ~has_prediction,
    )
    if within_hours is not None:
        horizon = datetime.now(timezone.utc) + timedelta(hours=within_hours)
        q = q.filter(or_(Match.kickoff_utc.is_(None), Match.kickoff_utc <= horizon))
    return q.order_by(Match.kickoff_utc.asc().nullsfirst(), Match.id.asc()).all()
