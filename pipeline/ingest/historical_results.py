"""Ingest historical international match results.

Source: martj42/international_results (the canonical, auth-free mirror of the
Kaggle "International football results from 1872 to present" dataset). Free,
community-maintained, high reliability (PRD §8.1).

Pipeline: download CSV -> normalize team names -> auto-create teams -> dedupe ->
insert into historical_matches. Teams not in the WC2026 set are still created
(Elo needs the full match history, not just games between WC teams).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team
from pipeline.team_mapping import normalize_team_name

RESULTS_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)

EXPECTED_COLUMNS = {
    "date", "home_team", "away_team", "home_score", "away_score",
    "tournament", "city", "country", "neutral",
}


def download_results_df() -> pd.DataFrame:
    """Download the full results CSV into a DataFrame (network)."""
    return pd.read_csv(RESULTS_URL)


def clean_results_df(df: pd.DataFrame) -> pd.DataFrame:
    """Validate columns, drop rows missing scores, and normalize team names.

    Pure (no DB / no network) so it is unit-testable on a small sample.
    """
    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"results data missing columns: {sorted(missing)}")

    df = df.dropna(subset=["home_score", "away_score", "date", "home_team", "away_team"])
    df = df.copy()
    df["home_team"] = df["home_team"].map(normalize_team_name)
    df["away_team"] = df["away_team"].map(normalize_team_name)
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    # neutral may be "TRUE"/"FALSE" strings or booleans.
    df["neutral"] = df["neutral"].map(
        lambda v: str(v).strip().lower() in ("true", "1", "yes")
    )
    # drop self-matches / blanks
    df = df[(df["home_team"] != "") & (df["away_team"] != "")]
    df = df[df["home_team"] != df["away_team"]]
    return df


def _team_id_cache(db: Session) -> dict[str, int]:
    return {t.name: t.id for t in db.query(Team).all()}


def load_historical(db: Session, df: pd.DataFrame, limit: int | None = None) -> dict:
    """Load cleaned results into historical_matches. Idempotent.

    Returns a summary dict (rows_in, teams_created, matches_inserted, skipped_dupes).
    """
    df = clean_results_df(df)
    if limit is not None:
        df = df.head(limit)

    cache = _team_id_cache(db)
    teams_created = 0

    def team_id(name: str) -> int:
        nonlocal teams_created
        if name not in cache:
            team = Team(name=name, is_host=False)
            db.add(team)
            db.flush()
            cache[name] = team.id
            teams_created += 1
        return cache[name]

    # existing (date, a, b) keys for idempotency
    existing: set[tuple] = {
        (m.date.date().isoformat(), m.team_a_id, m.team_b_id)
        for m in db.query(HistoricalMatch).all()
    }
    seen_in_file: set[tuple] = set()

    inserted = 0
    skipped = 0
    for row in df.itertuples(index=False):
        a_id = team_id(row.home_team)
        b_id = team_id(row.away_team)
        date_str = str(row.date)[:10]
        key = (date_str, a_id, b_id)
        if key in existing or key in seen_in_file:
            skipped += 1
            continue
        seen_in_file.add(key)
        db.add(
            HistoricalMatch(
                date=datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc),
                team_a_id=a_id,
                team_b_id=b_id,
                score_a=int(row.home_score),
                score_b=int(row.away_score),
                competition=str(row.tournament),
                is_neutral=bool(row.neutral),
                venue=str(row.city) if pd.notna(row.city) else None,
            )
        )
        inserted += 1

    db.commit()
    return {
        "rows_in": int(len(df)),
        "teams_created": teams_created,
        "matches_inserted": inserted,
        "skipped_dupes": skipped,
    }
