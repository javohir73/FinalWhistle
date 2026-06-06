"""Historical bookmaker odds — CALIBRATION USE ONLY (PRD Decision #1).

These odds are never shown to users in the MVP. They convert to implied
probabilities so the calibration backtest (task 4) can compare the model against
the market. Source: football-data.co.uk-style CSVs, which expose bookmaker odds
columns (e.g. B365H/B365D/B365A = bet365 home/draw/away) and FTR (full-time
result: H/D/A). Free, weekly, reliable (PRD §8.1).
"""
from __future__ import annotations

import pandas as pd


def implied_probabilities(
    odds_home: float, odds_draw: float, odds_away: float
) -> tuple[float, float, float]:
    """Convert decimal odds to normalized implied probabilities.

    Raw implied prob = 1/odds, but the three sum to >1 (the bookmaker's
    "overround"/margin). We normalize so they sum to 1.
    """
    if min(odds_home, odds_draw, odds_away) <= 0:
        raise ValueError("decimal odds must be positive")
    raw = (1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away)
    total = sum(raw)
    return (raw[0] / total, raw[1] / total, raw[2] / total)


def prepare_calibration_frame(
    df: pd.DataFrame,
    home_col: str = "B365H",
    draw_col: str = "B365D",
    away_col: str = "B365A",
    result_col: str = "FTR",
) -> pd.DataFrame:
    """Build a tidy calibration frame: implied probs + actual outcome.

    Returns columns [p_home, p_draw, p_away, result] where result is H/D/A.
    Pure (no DB / no network) so it is unit-testable on a small sample.
    """
    needed = {home_col, draw_col, away_col, result_col}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"odds data missing columns: {sorted(missing)}")

    df = df.dropna(subset=list(needed)).copy()
    probs = df.apply(
        lambda r: implied_probabilities(r[home_col], r[draw_col], r[away_col]),
        axis=1,
        result_type="expand",
    )
    probs.columns = ["p_home", "p_draw", "p_away"]
    probs["result"] = df[result_col].values
    return probs.reset_index(drop=True)
