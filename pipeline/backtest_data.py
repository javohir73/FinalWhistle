"""Build enriched backtest rows from the database.

Replays Elo over all historical matches and attaches each match's date and
competition, producing the leak-free rows the pure backtest harness consumes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HistoricalMatch
from ml.ratings.elo import MatchInput, replay_with_prematch


def build_enriched_rows(db: Session) -> list[dict]:
    ordered = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )
    inputs = [
        MatchInput(
            home_id=m.team_a_id,
            away_id=m.team_b_id,
            score_home=m.score_a,
            score_away=m.score_b,
            competition=m.competition,
            is_neutral=m.is_neutral,
        )
        for m in ordered
    ]
    rows, _ = replay_with_prematch(inputs)
    # Attach date + competition (same order as `ordered`).
    for row, orm in zip(rows, ordered):
        row["date"] = orm.date
        row["competition"] = orm.competition
    return rows
