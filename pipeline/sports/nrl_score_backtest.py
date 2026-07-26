"""Read-only promotion report for the shadow NRL scoreline model.

Usage:
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_score_backtest
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_score_backtest --require-pass
"""
from __future__ import annotations

import argparse
import json

from ml.sports.nrl.score_backtest import evaluate_score_model


def _load_matches(db) -> list[dict]:
    from app.models import SportMatch

    rows = db.query(SportMatch).filter_by(sport="nrl", status="finished").all()
    return [
        {
            "match_id": row.id,
            "season": row.season,
            "kickoff_utc": row.kickoff_utc,
            "home_team_id": row.home_team_id,
            "away_team_id": row.away_team_id,
            "score_home": row.score_home,
            "score_away": row.score_away,
        }
        for row in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit non-zero when the 5%% promotion gate fails",
    )
    args = parser.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        result = evaluate_score_model(_load_matches(db))
    finally:
        db.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.require_pass and not result["gate"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
