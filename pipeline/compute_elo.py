"""Compute Elo ratings from historical_matches and store on teams.elo_rating.

Replays the full match history oldest-first (Elo is path-dependent) and writes
each team's final rating. Run after historical_results ingestion.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team
from ml.ratings.elo import MatchInput, run_elo


def compute_and_store_elo(db: Session) -> dict:
    rows = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )
    matches = [
        MatchInput(
            home_id=r.team_a_id,
            away_id=r.team_b_id,
            score_home=r.score_a,
            score_away=r.score_b,
            competition=r.competition,
            is_neutral=r.is_neutral,
        )
        for r in rows
    ]
    ratings = run_elo(matches)

    updated = 0
    for team_id, rating in ratings.items():
        team = db.get(Team, team_id)
        if team is not None:
            team.elo_rating = round(rating, 1)
            updated += 1
    db.commit()

    return {"matches_replayed": len(matches), "teams_rated": updated}
