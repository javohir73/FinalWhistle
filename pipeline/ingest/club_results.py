"""Ingest EPL club historical results (league pivot D3).

Source: football-data.co.uk mmz4281/{season}/E0.csv (E0 = English Premier
League), one CSV per season, free and auth-free. Ten seasons (2016-17
through 2025-26) give the club Elo replay (pipeline/compute_club_elo.py)
enough history to converge before the 2026-27 season kicks off.

Mirrors pipeline/ingest/historical_results.py's shape (download -> clean ->
load) but writes into the SAME historical_matches table with a distinct
`competition` discriminator (CLUB_COMPETITION = "Premier League"), per D3's
minimal-migration path: HistoricalMatch already carries a nullable
`competition` column, so no schema change is needed here. International and
club ingest must never mix — CLUB_COMPETITION is the one value both this
module and pipeline/compute_elo.py's scoping filter share.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team
from pipeline.team_mapping import normalize_team_name

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/E0.csv"

# Ten seasons, oldest first: 2016-17 .. 2025-26 (E0 = English Premier League).
SEASON_CODES = [
    "1617", "1718", "1819", "1920", "2021",
    "2122", "2223", "2324", "2425", "2526",
]

# The LAST season, held out for the home-advantage fit (pipeline/compute_club_elo.py).
HOLDOUT_SEASON_CODE = "2526"

# Discriminator stored on historical_matches.competition for every row this
# module writes. Never collides with an international tournament name from
# the martj42 dataset (e.g. "FIFA World Cup", "Friendly") — the ONE value
# pipeline/compute_elo.py excludes from its international replay, and
# pipeline/compute_club_elo.py includes exclusively.
CLUB_COMPETITION = "Premier League"

EXPECTED_COLUMNS = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}


def download_club_results_df(season_codes: list[str] = SEASON_CODES) -> pd.DataFrame:
    """Download and concatenate every season's E0 CSV (network)."""
    frames = []
    for code in season_codes:
        df = pd.read_csv(BASE_URL.format(season=code))
        df["season_code"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def clean_club_results_df(df: pd.DataFrame) -> pd.DataFrame:
    """Validate columns, drop rows missing scores, normalize team names.

    Pure (no DB / no network) so it is unit-testable on a small sample. Dates
    are day-first (football-data.co.uk's DD/MM/YY(YY) convention). Club names
    DO go through team_mapping (unlike run_club_benchmark.py's str.strip-only
    parser) — this ingest writes into the DB and must land on the same
    canonical Team rows the league structure loader seeds from
    pipeline/data/epl2627_teams.json.
    """
    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"club results data missing columns: {sorted(missing)}")

    df = df.dropna(subset=["FTHG", "FTAG", "Date", "HomeTeam", "AwayTeam"])
    df = df.copy()
    df["HomeTeam"] = df["HomeTeam"].map(normalize_team_name)
    df["AwayTeam"] = df["AwayTeam"].map(normalize_team_name)
    df["FTHG"] = df["FTHG"].astype(int)
    df["FTAG"] = df["FTAG"].astype(int)
    df["match_date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["match_date"])
    df = df[(df["HomeTeam"] != "") & (df["AwayTeam"] != "")]
    df = df[df["HomeTeam"] != df["AwayTeam"]]
    return df


def _team_id_cache(db: Session) -> dict[str, int]:
    return {t.name: t.id for t in db.query(Team).all()}


def load_club_results(db: Session, df: pd.DataFrame, limit: int | None = None) -> dict:
    """Load cleaned club results into historical_matches. Idempotent.

    Club matches are never at a neutral venue (is_neutral=False — unlike the
    international ingest, which reads a per-row `neutral` column). Every row
    is tagged competition=CLUB_COMPETITION.
    """
    df = clean_club_results_df(df)
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

    # existing (date, a, b) keys for idempotency — scoped to club rows only,
    # so a same-day international fixture between two like-named teams (none
    # exist in practice, but the scoping is the point) can never collide.
    existing: set[tuple] = {
        (m.date.date().isoformat(), m.team_a_id, m.team_b_id)
        for m in db.query(HistoricalMatch).filter_by(competition=CLUB_COMPETITION).all()
    }
    seen_in_file: set[tuple] = set()

    inserted = 0
    skipped = 0
    for row in df.itertuples(index=False):
        a_id = team_id(row.HomeTeam)
        b_id = team_id(row.AwayTeam)
        date_str = row.match_date.date().isoformat()
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
                score_a=int(row.FTHG),
                score_b=int(row.FTAG),
                competition=CLUB_COMPETITION,
                is_neutral=False,
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
