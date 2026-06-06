"""Ingest FIFA rankings and apply them to teams.fifa_rank.

FIFA rank is a secondary / cold-start feature (Elo is the primary strength
signal, PRD §8/§9). This module is source-agnostic: `apply_rankings` takes a
DataFrame with columns [team, rank] (optional [points, date]) so it works with
any free source — a Kaggle CSV, a GitHub mirror, or a hand-maintained file in
pipeline/data/fifa_rankings.csv. Names pass through team_mapping.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Team
from pipeline.team_mapping import normalize_team_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_RANKINGS_CSV = DATA_DIR / "fifa_rankings.csv"


def load_rankings_df() -> pd.DataFrame:
    """Load rankings from the local seed CSV if present.

    The pipeline can replace this with a live download; kept simple and
    auth-free for the MVP. Raises if no source is available so failures are loud.
    """
    if LOCAL_RANKINGS_CSV.exists():
        return pd.read_csv(LOCAL_RANKINGS_CSV)
    raise FileNotFoundError(
        f"No rankings source found at {LOCAL_RANKINGS_CSV}. "
        "Provide a CSV with columns [team, rank] or pass a DataFrame to apply_rankings()."
    )


def apply_rankings(db: Session, df: pd.DataFrame) -> dict:
    """Update teams.fifa_rank from a rankings DataFrame. Pure of network.

    Only updates teams that already exist (created by structure/historical ingest);
    unknown teams are reported, not created.
    """
    required = {"team", "rank"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"rankings data missing columns: {sorted(missing)}")

    updated = 0
    unmatched: list[str] = []
    for row in df.itertuples(index=False):
        name = normalize_team_name(str(row.team))
        team = db.query(Team).filter_by(name=name).one_or_none()
        if team is None:
            unmatched.append(name)
            continue
        team.fifa_rank = int(row.rank)
        updated += 1

    db.commit()
    return {"rows_in": int(len(df)), "updated": updated, "unmatched": unmatched}
