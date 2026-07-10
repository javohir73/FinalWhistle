"""Fit the NRL margin+total model (Wave 1): expected margin as elo_diff +
home advantage via ordinary least squares over every completed 2017-2025
nrl match, expected total as a recency-weighted (2:1) league scoring mean
over the two most recent seasons present. Writes the result to
ml/models/nrl_model_params.json via ml.models.nrl_margin_total.save_margin_total_params.

Independent of ml/sports/nrl/model.py's own margin_slope (the win-probability
Elo model's built-in margin estimate, used for the existing `expected_margin`
field) -- this is a separate, explicitly-fit model (version "nrl-elo-v0.2")
stamped onto SportPrediction.predicted_margin/predicted_total by
pipeline/sports/nrl_predict.py's generate().

CLI: PYTHONPATH=backend:. python -m pipeline.sports.nrl_margin_total_fit
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models import SportMatch
from ml.models.nrl_margin_total import NrlMarginTotalParams, save_margin_total_params
from ml.sports.nrl.model import regress_season, update
from ml.sports.nrl.params import load_nrl_params

log = logging.getLogger(__name__)

SPORT = "nrl"
MIN_SEASON = 2017
MAX_SEASON = 2025


def _kickoff_key(m: SportMatch) -> tuple:
    return (m.kickoff_utc is None, m.kickoff_utc or datetime.min, m.id)


def collect_training_rows(matches: list[SportMatch]) -> list[tuple[float, float]]:
    """Replay Elo chronologically (mirrors pipeline.sports.nrl_predict._current_elos)
    and return (pre_match_elo_diff, actual_margin) pairs for every match in
    [MIN_SEASON, MAX_SEASON] -- pre-match state only, never post-match, so the
    regression never leaks the outcome it's predicting."""
    params = load_nrl_params()
    ordered = sorted(matches, key=_kickoff_key)
    elos: dict[int, float] = {}
    current_season: int | None = None
    rows: list[tuple[float, float]] = []

    for m in ordered:
        if current_season is not None and m.season != current_season:
            elos = regress_season(elos, params)
        current_season = m.season

        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        if MIN_SEASON <= m.season <= MAX_SEASON:
            rows.append((elo_home - elo_away, float(m.score_home - m.score_away)))

        new_home, new_away = update(elo_home, elo_away, m.score_home, m.score_away, params)
        elos[m.home_team_id] = new_home
        elos[m.away_team_id] = new_away

    return rows


def fit_margin(rows: list[tuple[float, float]]) -> tuple[float, float]:
    """Least squares margin ~ elo_diff + home_advantage. Returns
    (margin_coef_elo_diff, margin_intercept); the intercept is the fitted
    home-advantage in POINTS. Design matrix X = [elo_diff, 1]."""
    if not rows:
        return 0.0, 0.0
    elo_diffs = np.array([r[0] for r in rows], dtype=float)
    margins = np.array([r[1] for r in rows], dtype=float)
    X = np.column_stack([elo_diffs, np.ones_like(elo_diffs)])
    coef, *_ = np.linalg.lstsq(X, margins, rcond=None)
    return float(coef[0]), float(coef[1])


def fit_expected_total(matches_by_season: dict) -> float:
    """Recency-weighted league scoring mean: the two most recent seasons
    present, most-recent weighted 2:1 over the second-most-recent. Falls back
    to a single season's mean (weight 1) if only one is present, or the
    NrlMarginTotalParams default if none."""
    seasons = sorted(matches_by_season)
    if not seasons:
        return NrlMarginTotalParams().expected_total

    def season_mean(season) -> float | None:
        totals = [
            m.score_home + m.score_away for m in matches_by_season[season]
            if m.score_home is not None and m.score_away is not None
        ]
        return sum(totals) / len(totals) if totals else None

    latest = season_mean(seasons[-1])
    if latest is None:
        return NrlMarginTotalParams().expected_total
    if len(seasons) < 2:
        return latest
    prev = season_mean(seasons[-2])
    if prev is None:
        return latest
    return (2 * latest + prev) / 3


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal

    db: Session = SessionLocal()
    try:
        finished = (
            db.query(SportMatch)
            .filter(SportMatch.sport == SPORT, SportMatch.status == "finished")
            .all()
        )
        if not finished:
            log.warning("no finished nrl matches in the DB -- nothing to fit")
            return 1

        rows = collect_training_rows(finished)
        coef, intercept = fit_margin(rows)

        by_season: dict[int, list[SportMatch]] = {}
        for m in finished:
            by_season.setdefault(m.season, []).append(m)
        expected_total = fit_expected_total(by_season)

        params = NrlMarginTotalParams(
            version="nrl-elo-v0.2",
            margin_coef_elo_diff=coef,
            margin_intercept=intercept,
            expected_total=expected_total,
        )
        save_margin_total_params(params)
        log.info(
            "fit %d matches: margin_coef_elo_diff=%.5f margin_intercept=%.2f expected_total=%.2f",
            len(rows), coef, intercept, expected_total,
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
