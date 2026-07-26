"""Chronological MAE gate for the shadow NRL scoreline model."""
from __future__ import annotations

import math

from ml.models.nrl_score import (
    NrlExternalScoreSignals,
    NrlScoreParams,
    NrlScoreState,
    predict_scoreline,
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def promotion_gate(
    *,
    model_mae: float,
    baseline_mae: float,
    seasons_improved: int,
    seasons_evaluated: int,
    minimum_improvement: float = 0.05,
) -> dict:
    improvement = (
        (baseline_mae - model_mae) / baseline_mae
        if baseline_mae > 0 and math.isfinite(model_mae)
        else float("-inf")
    )
    required_seasons = seasons_evaluated // 2 + 1 if seasons_evaluated else 1
    passed = improvement >= minimum_improvement and seasons_improved >= required_seasons
    return {
        "passed": passed,
        "improvement": improvement,
        "minimum_improvement": minimum_improvement,
        "seasons_improved": seasons_improved,
        "required_seasons": required_seasons,
    }


def evaluate_score_model(
    matches: list[dict],
    params: NrlScoreParams | None = None,
    held_out_seasons: tuple[int, ...] = (2023, 2024, 2025),
) -> dict:
    """Walk forward match by match, always updating after prediction.

    Optional ``market_total``/``market_margin`` and point-adjustment fields are
    consumed only from the row being predicted. A caller loading archived
    external signals is responsible for ensuring they were captured before
    kickoff; absent signals cleanly fall back to the independent model.
    """
    p = params or NrlScoreParams()
    state = NrlScoreState(params=p)
    ordered = sorted(
        matches,
        key=lambda row: (
            row.get("kickoff_utc") is None,
            row.get("kickoff_utc"),
            row.get("match_id", 0),
        ),
    )
    by_season: dict[int, dict[str, list[float]]] = {
        season: {"model": [], "baseline": [], "team": []}
        for season in held_out_seasons
    }

    for row in ordered:
        home_id = row.get("home_team_id")
        away_id = row.get("away_team_id")
        score_home = row.get("score_home")
        score_away = row.get("score_away")
        if None in (home_id, away_id, score_home, score_away):
            continue
        signals = NrlExternalScoreSignals(
            market_total=row.get("market_total"),
            market_margin=row.get("market_margin"),
            home_points_adjustment=row.get("home_points_adjustment", 0.0),
            away_points_adjustment=row.get("away_points_adjustment", 0.0),
            total_adjustment=row.get("total_adjustment", 0.0),
        )
        prediction = predict_scoreline(state, home_id, away_id, signals)
        season = row.get("season")
        if season in by_season:
            actual_total = score_home + score_away
            by_season[season]["model"].append(
                abs(prediction.expected_total - actual_total)
            )
            by_season[season]["baseline"].append(
                abs(p.baseline_total - actual_total)
            )
            by_season[season]["team"].extend([
                abs(prediction.expected_home - score_home),
                abs(prediction.expected_away - score_away),
            ])
        state.update(home_id, away_id, score_home, score_away)

    seasons: dict[int, dict] = {}
    all_model: list[float] = []
    all_baseline: list[float] = []
    all_team: list[float] = []
    seasons_improved = 0
    for season in held_out_seasons:
        values = by_season[season]
        model_mae = _mean(values["model"])
        baseline_mae = _mean(values["baseline"])
        if values["model"] and model_mae < baseline_mae:
            seasons_improved += 1
        seasons[season] = {
            "n": len(values["model"]),
            "total_mae": model_mae,
            "baseline_mae": baseline_mae,
            "team_score_mae": _mean(values["team"]),
        }
        all_model.extend(values["model"])
        all_baseline.extend(values["baseline"])
        all_team.extend(values["team"])

    model_mae = _mean(all_model)
    baseline_mae = _mean(all_baseline)
    gate = promotion_gate(
        model_mae=model_mae,
        baseline_mae=baseline_mae,
        seasons_improved=seasons_improved,
        seasons_evaluated=sum(bool(by_season[s]["model"]) for s in held_out_seasons),
        minimum_improvement=p.promotion_improvement,
    )
    return {
        "model_version": p.version,
        "n": len(all_model),
        "total_mae": model_mae,
        "baseline_mae": baseline_mae,
        "team_score_mae": _mean(all_team),
        "seasons": seasons,
        "gate": gate,
    }
