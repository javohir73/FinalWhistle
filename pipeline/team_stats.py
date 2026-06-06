"""Compute basic team_stats snapshots from historical_matches.

For each team, summarizes their most recent `window` matches: matches played,
goals for/against, clean sheets, and form points (3 win / 1 draw / 0 loss).
These feed the team profile pages and the model's form features. Idempotent per
(team_id, as_of_date).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import HistoricalMatch, TeamStats


def compute_team_stats(
    db: Session, as_of: datetime | None = None, window: int = 10
) -> dict:
    """Build a TeamStats row per team from their last `window` matches."""
    as_of = as_of or datetime.now(timezone.utc)

    matches = (
        db.query(HistoricalMatch)
        .filter(HistoricalMatch.date <= as_of)
        .order_by(HistoricalMatch.date.desc())
        .all()
    )

    # team_id -> list of (goals_for, goals_against) most-recent-first
    recent: dict[int, list[tuple[int, int]]] = {}
    for m in matches:
        for team_id, gf, ga in (
            (m.team_a_id, m.score_a, m.score_b),
            (m.team_b_id, m.score_b, m.score_a),
        ):
            bucket = recent.setdefault(team_id, [])
            if len(bucket) < window:
                bucket.append((gf, ga))

    written = 0
    for team_id, results in recent.items():
        gf = sum(r[0] for r in results)
        ga = sum(r[1] for r in results)
        clean = sum(1 for r in results if r[1] == 0)
        points = sum(3 if r[0] > r[1] else 1 if r[0] == r[1] else 0 for r in results)

        row = (
            db.query(TeamStats)
            .filter_by(team_id=team_id, as_of_date=as_of)
            .one_or_none()
        )
        if row is None:
            row = TeamStats(team_id=team_id, as_of_date=as_of)
            db.add(row)
        row.matches_played = len(results)
        row.goals_for = gf
        row.goals_against = ga
        row.clean_sheets = clean
        row.form_points_last10 = float(points)
        written += 1

    db.commit()
    return {"teams_with_stats": written, "window": window}
