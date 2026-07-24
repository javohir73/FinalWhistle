"""Ingest club historical results (league pivot D3; multi-division as of
League Score Predictions Phase 2).

Source: football-data.co.uk mmz4281/{season}/{division}.csv, one CSV per
season, free and auth-free -- E0 = English Premier League, SP1 = La Liga,
D1 = Bundesliga. Ten seasons (2016-17 through 2025-26) give the club Elo
replay (pipeline/compute_club_elo.py) enough history to converge before a
league's covered season kicks off. The division code and competition
discriminator are the only per-league parameters; download/clean/load are
otherwise division-agnostic.

Mirrors pipeline/ingest/historical_results.py's shape (download -> clean ->
load) but writes into the SAME historical_matches table with a distinct
`competition` discriminator per league (CLUB_COMPETITION = "Premier League"
is EPL's, the module default so every existing caller of this file's
functions is unaffected), per D3's minimal-migration path: HistoricalMatch
already carries a nullable `competition` column, so no schema change is
needed here. International and club ingest must never mix, and as of Phase 2
neither may two leagues' club rows -- every historical_matches row's
`competition` is one of pipeline.leagues.LEAGUES[...]["club_competition"],
the set pipeline/compute_elo.py's international-replay scoping filter
excludes in full (see club_competitions() there).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Match, Team, Tournament
from pipeline.team_mapping import normalize_team_name

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"

# football-data.co.uk's division code for EPL, the module default so a bare
# download_club_results_df() call is unaffected by Phase 2's new parameter.
DEFAULT_DIVISION = "E0"

# Ten seasons, oldest first: 2016-17 .. 2025-26. Same window/format for every
# division -- football-data.co.uk uses the same {season}/{division}.csv shape
# and season-code convention across leagues.
SEASON_CODES = [
    "1617", "1718", "1819", "1920", "2021",
    "2122", "2223", "2324", "2425", "2526",
]

# The LAST season, held out for the home-advantage fit (pipeline/compute_club_elo.py).
HOLDOUT_SEASON_CODE = "2526"

# EPL's discriminator, stored on historical_matches.competition -- the module
# default for load_club_results/sync_finished_matches_to_history so every
# existing (EPL) caller is unaffected. Never collides with an international
# tournament name from the martj42 dataset (e.g. "FIFA World Cup", "Friendly").
# La Liga/Bundesliga get their own values (pipeline/leagues.py's
# "club_competition" field, e.g. "La Liga"/"Bundesliga") -- see this module's
# own docstring on why the exclusion in compute_elo.py must track the full set.
CLUB_COMPETITION = "Premier League"

EXPECTED_COLUMNS = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}


def download_club_results_df(
    season_codes: list[str] = SEASON_CODES, division: str = DEFAULT_DIVISION
) -> pd.DataFrame:
    """Download and concatenate every season's CSV for one division (network)."""
    frames = []
    for code in season_codes:
        df = pd.read_csv(BASE_URL.format(season=code, division=division))
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


def load_club_results(
    db: Session, df: pd.DataFrame, limit: int | None = None, *, competition: str = CLUB_COMPETITION
) -> dict:
    """Load cleaned club results into historical_matches. Idempotent.

    Club matches are never at a neutral venue (is_neutral=False — unlike the
    international ingest, which reads a per-row `neutral` column). Every row
    is tagged competition=``competition`` (default CLUB_COMPETITION, i.e. EPL
    -- every existing caller is unaffected; Phase 2 leagues pass their own
    pipeline.leagues.LEAGUES[...]["club_competition"]).
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

    # existing (date, a, b) keys for idempotency — scoped to THIS competition
    # only, so a same-day fixture in a different league (or the international
    # ingest) between like-named teams can never collide.
    existing: set[tuple] = {
        (m.date.date().isoformat(), m.team_a_id, m.team_b_id)
        for m in db.query(HistoricalMatch).filter_by(competition=competition).all()
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
                competition=competition,
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


def sync_finished_matches_to_history(
    db: Session, tournament: Tournament, *, competition: str = CLUB_COMPETITION
) -> dict:
    """Mirror this tournament's finished Match rows into historical_matches
    (competition=``competition``, default CLUB_COMPETITION i.e. EPL --
    every existing caller is unaffected), idempotently.

    In-season, results only exist as Match rows (from
    pipeline.ingest.league_structure's fixture upsert) — the football-data.co.uk
    season CSV isn't published until the season ends. This keeps
    pipeline/compute_club_elo.py's replay current every pipeline run without
    waiting for next season's CSV dump. Idempotent on the same (date, home,
    away) key load_club_results uses, so re-running never duplicates.
    """
    existing: set[tuple] = {
        (m.date.date().isoformat(), m.team_a_id, m.team_b_id)
        for m in db.query(HistoricalMatch).filter_by(competition=competition).all()
    }
    finished = (
        db.query(Match)
        .filter(
            Match.tournament_id == tournament.id,
            Match.status == "finished",
            Match.score_home.isnot(None),
            Match.score_away.isnot(None),
            Match.kickoff_utc.isnot(None),
        )
        .all()
    )
    inserted = 0
    for m in finished:
        date_str = m.kickoff_utc.date().isoformat()
        key = (date_str, m.team_home_id, m.team_away_id)
        if key in existing:
            continue
        db.add(
            HistoricalMatch(
                date=m.kickoff_utc,
                team_a_id=m.team_home_id,
                team_b_id=m.team_away_id,
                score_a=m.score_home,
                score_b=m.score_away,
                competition=competition,
                is_neutral=False,
            )
        )
        existing.add(key)
        inserted += 1
    db.commit()
    return {"matches_inserted": inserted}
