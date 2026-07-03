"""Parse football-data.co.uk club-match CSVs (docs/ROADMAP-ENGINE.md, Phase 1).

football-data.co.uk publishes free, per-league CSVs for the major club
divisions (E0 = Premier League, etc.). Each row is one match with full-time
goals/result plus a wide block of bookmaker odds columns.

Phase 1 generalises the WC26 engine to club football and asks the same
commercial question as Phase 0: does the model beat the CLOSING line? So this
parser prefers the CLOSING-odds columns and, per row, keeps only clean data —
present integer scores and three decimal odds each > 1.0. Malformed rows are
logged and skipped, never fatal.

Pure module — no DB, no network, no app imports. Orchestration lives in
pipeline/run_club_benchmark.py.

Column reference (football-data.co.uk notes):
  FTHG/FTAG  full-time home/away goals        FTR  full-time result (H/D/A)
  AvgC*      market-average CLOSING odds      PSC* Pinnacle CLOSING odds
  B365C*     Bet365 CLOSING odds              MaxC* market-maximum CLOSING odds
  Avg*/B365* the same books' OPENING odds (non-closing fallback)
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

# Ordered preference of (home, draw, away) odds-column triples. CLOSING columns
# come first (the roadmap benchmarks vs the closing line); opening columns are a
# last-resort fallback. The key is the shared prefix recorded as odds_source.
_ODDS_CHAIN: list[tuple[str, tuple[str, str, str]]] = [
    ("AvgC", ("AvgCH", "AvgCD", "AvgCA")),  # market-average closing
    ("PSC", ("PSCH", "PSCD", "PSCA")),      # Pinnacle closing
    ("B365C", ("B365CH", "B365CD", "B365CA")),  # Bet365 closing
    ("MaxC", ("MaxCH", "MaxCD", "MaxCA")),  # market-maximum closing
    ("Avg", ("AvgH", "AvgD", "AvgA")),      # market-average opening (fallback)
    ("B365", ("B365H", "B365D", "B365A")),  # Bet365 opening (fallback)
]


def _select_odds_columns(columns) -> tuple[str, tuple[str, str, str]]:
    """Pick the first fully-present odds triple from the preference chain."""
    present = set(columns)
    for source, triple in _ODDS_CHAIN:
        if all(col in present for col in triple):
            return source, triple
    raise ValueError(
        "no recognised odds columns in CSV header; expected one of "
        + ", ".join(t[0] for t in _ODDS_CHAIN)
    )


def load_football_data_csv(path: str, normalize=str.strip) -> list[dict]:
    """Load a football-data.co.uk CSV into join-ready match records.

    Chooses the closing-odds column-triple highest in ``_ODDS_CHAIN`` that is
    present in the header (raising if none are), parses the Date column
    day-first, and keeps only rows with present integer scores and three decimal
    odds each > 1.0. Team names pass through ``normalize`` (default ``str.strip``
    — club names must NOT go through the national-team mapper, which could mangle
    them). Rows are returned in file order; sorting is the caller's job.

    Returns a list of dicts with keys: date (datetime.date), home_team,
    away_team, home_score (int), away_score (int), odds_home, odds_draw,
    odds_away (float), odds_source (str, e.g. "AvgC").
    """
    df = pd.read_csv(path)
    odds_source, (home_col, draw_col, away_col) = _select_odds_columns(df.columns)

    # Day-first covers DD/MM/YY and DD/MM/YYYY; to_datetime also accepts ISO.
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")

    records: list[dict] = []
    for i, row in df.iterrows():
        line = i + 2  # +1 for 0-index, +1 for the header row
        parsed_date = dates.iloc[i]
        if pd.isna(parsed_date):
            log.warning("skipping row %d: unparseable date %r", line, row.get("Date"))
            continue
        try:
            home_score = int(row["FTHG"])
            away_score = int(row["FTAG"])
        except (KeyError, TypeError, ValueError):
            log.warning("skipping row %d: missing/invalid score", line)
            continue

        try:
            odds_home = float(row[home_col])
            odds_draw = float(row[draw_col])
            odds_away = float(row[away_col])
        except (KeyError, TypeError, ValueError):
            log.warning("skipping row %d: missing/invalid %s odds", line, odds_source)
            continue
        if min(odds_home, odds_draw, odds_away) <= 1.0:
            log.warning("skipping row %d: %s odds not all > 1.0", line, odds_source)
            continue

        records.append(
            {
                "date": parsed_date.date(),
                "home_team": normalize(str(row["HomeTeam"])),
                "away_team": normalize(str(row["AwayTeam"])),
                "home_score": home_score,
                "away_score": away_score,
                "odds_home": odds_home,
                "odds_draw": odds_draw,
                "odds_away": odds_away,
                "odds_source": odds_source,
            }
        )
    return records
