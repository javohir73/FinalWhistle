from datetime import datetime, timezone

import pytest

from ml.models.nrl_score import NrlScoreParams
from ml.sports.nrl.score_backtest import evaluate_score_model, promotion_gate


def test_promotion_gate_requires_five_percent_and_most_seasons():
    assert promotion_gate(
        model_mae=9.4,
        baseline_mae=10.0,
        seasons_improved=2,
        seasons_evaluated=3,
    )["passed"] is True
    assert promotion_gate(
        model_mae=9.6,
        baseline_mae=10.0,
        seasons_improved=3,
        seasons_evaluated=3,
    )["passed"] is False
    assert promotion_gate(
        model_mae=9.4,
        baseline_mae=10.0,
        seasons_improved=1,
        seasons_evaluated=3,
    )["passed"] is False
    assert promotion_gate(
        model_mae=9.4,
        baseline_mae=10.0,
        seasons_improved=2,
        seasons_evaluated=4,
    )["passed"] is False


def test_walk_forward_backtest_reports_each_held_out_season():
    rows = []
    match_id = 1
    for season in range(2017, 2026):
        for game in range(6):
            rows.append({
                "match_id": match_id,
                "season": season,
                "kickoff_utc": datetime(season, 3, game + 1, tzinfo=timezone.utc),
                "home_team_id": 1 if game % 2 == 0 else 2,
                "away_team_id": 2 if game % 2 == 0 else 1,
                "score_home": 30 if game % 2 == 0 else 12,
                "score_away": 12 if game % 2 == 0 else 30,
            })
            match_id += 1

    result = evaluate_score_model(rows)

    assert result["n"] == 18
    assert set(result["seasons"]) == {2023, 2024, 2025}
    assert all(result["seasons"][season]["n"] == 6 for season in result["seasons"])
    assert result["gate"]["minimum_improvement"] == 0.05


def test_archived_market_total_is_optional_and_must_be_pre_match_row_data():
    rows = []
    for index in range(20):
        rows.append({
            "match_id": index + 1,
            "season": 2023,
            "kickoff_utc": datetime(2023, 3, index + 1, tzinfo=timezone.utc),
            "home_team_id": 1,
            "away_team_id": 2,
            "score_home": 30,
            "score_away": 20,
            "market_total": 50.0,
        })
    params = NrlScoreParams(market_weight=1.0)

    result = evaluate_score_model(rows, params, held_out_seasons=(2023,))

    assert result["total_mae"] == pytest.approx(0.0, abs=1e-12)
