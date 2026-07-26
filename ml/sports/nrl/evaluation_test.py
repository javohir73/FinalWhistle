from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from ml.sports.nrl.evaluation import (
    EvaluationConfig,
    LeakageError,
    _margin_summary,
    _scoreline_summary,
    _total_summary,
    _winner_summary,
    cluster_bootstrap_ci,
    evaluate,
)
from ml.sports.nrl.model import NrlParams


def _row(
    match_id: int,
    season: int,
    round_: int,
    day: int,
    home: int,
    away: int,
    score_home: int,
    score_away: int,
    *,
    kickoff: datetime | None = None,
    market: dict | None = None,
) -> dict:
    return {
        "match_id": match_id,
        "season": season,
        "round": round_,
        "kickoff_utc": kickoff or datetime(season, 3, day, 8, tzinfo=timezone.utc),
        "venue": "Test Ground",
        "home_team_id": home,
        "away_team_id": away,
        "score_home": score_home,
        "score_away": score_away,
        "market": market,
    }


def _history() -> list[dict]:
    return [
        _row(1, 2021, 1, 1, 1, 2, 24, 12),
        _row(2, 2021, 1, 2, 3, 4, 10, 22),
        _row(3, 2022, 1, 1, 2, 3, 18, 18),
        _row(4, 2022, 2, 8, 4, 1, 20, 21),
        _row(5, 2023, 1, 1, 1, 3, 21, 20),
        _row(6, 2023, 1, 2, 2, 4, 16, 16),
    ]


def _config(**changes) -> EvaluationConfig:
    values = {
        "from_season": 2023,
        "to_season": 2023,
        "model_version": "test-model",
        "bootstrap_samples": 50,
        "seed": 2026,
    }
    values.update(changes)
    return EvaluationConfig(**values)


def _evaluate(rows: list[dict], **config_changes) -> dict:
    return evaluate(
        rows,
        _config(**config_changes),
        winner_params=NrlParams(),
    )


def test_same_kickoff_matches_are_all_predicted_before_any_result_update():
    rows = _history()
    shared_kickoff = datetime(2023, 3, 1, 8, tzinfo=timezone.utc)
    rows[-2]["kickoff_utc"] = shared_kickoff
    rows[-1]["kickoff_utc"] = shared_kickoff

    original = _evaluate(rows)
    changed_rows = deepcopy(rows)
    changed_rows[-2]["score_home"] = 60
    changed_rows[-2]["score_away"] = 0
    changed = _evaluate(changed_rows)

    original_second = original["predictions"][1]
    changed_second = changed["predictions"][1]
    assert original_second["winner"] == changed_second["winner"]
    assert original_second["margin"] == changed_second["margin"]
    assert original_second["total"] == changed_second["total"]
    assert original_second["scoreline"] == changed_second["scoreline"]
    assert original["leakage_audit"]["strictly_prior_state"] is True


def test_future_results_do_not_change_historical_run_or_fingerprint():
    original = _evaluate(_history())
    with_future = _evaluate(_history() + [_row(99, 2024, 1, 1, 1, 4, 70, 0)])

    assert with_future["dataset_fingerprint"] == original["dataset_fingerprint"]
    assert with_future["predictions"] == original["predictions"]
    assert with_future["results"] == original["results"]


def test_post_kickoff_external_signal_is_rejected():
    rows = _history()
    kickoff = rows[-1]["kickoff_utc"]
    rows[-1]["market"] = {
        "licensed": True,
        "captured_at": kickoff,
        "moneyline": [0.5, 0.02, 0.48],
    }

    with pytest.raises(LeakageError, match="captured_at must be before kickoff"):
        _evaluate(rows)


def test_golden_point_and_rare_draw_are_graded_consistently():
    result = _evaluate(_history())

    assert [row["actual_outcome"] for row in result["predictions"]] == [
        "home",
        "draw",
    ]
    uniform = result["results"]["winner"]["uniform"]
    assert uniform["log_loss"] == pytest.approx(math.log(3))
    assert uniform["brier"] == pytest.approx(2 / 3)
    assert result["results"]["margin"]["zero"]["winner_sign_accuracy"] == 0.0


def test_incomplete_markets_are_reported_but_do_not_change_internal_gates():
    without_markets = _evaluate(_history())
    rows = _history()
    rows[-1]["market"] = {
        "licensed": True,
        "captured_at": rows[-1]["kickoff_utc"] - timedelta(hours=1),
        "moneyline": [0.45, 0.05, 0.5],
        "margin": -1.5,
        "total": 44.5,
    }
    partial_markets = _evaluate(rows)

    assert partial_markets["results"]["gates"] == without_markets["results"]["gates"]
    for report in partial_markets["results"]["market_benchmarks"].values():
        assert report["status"] == "unavailable"
        assert report["metrics"] is None


def test_market_metrics_enable_only_after_every_season_reaches_coverage_gate():
    rows = _history()
    for row in rows[-2:]:
        row["market"] = {
            "licensed": True,
            "captured_at": row["kickoff_utc"] - timedelta(hours=1),
            "moneyline": [0.6, 0.02, 0.38],
            "margin": 4.0,
            "total": 42.0,
        }
    result = _evaluate(rows)

    for report in result["results"]["market_benchmarks"].values():
        assert report["status"] == "available"
        assert report["metrics"]["n"] == 2


def test_clustered_bootstrap_is_deterministic_and_resamples_round_blocks():
    values = [-1.0, -1.0, 2.0, 2.0]
    clusters = [(2023, 1), (2023, 1), (2023, 2), (2023, 2)]

    first = cluster_bootstrap_ci(values, clusters, samples=500, seed=2026)
    second = cluster_bootstrap_ci(values, clusters, samples=500, seed=2026)

    assert first == second
    assert first[0] <= -1.0
    assert first[1] >= 2.0


def test_every_prediction_has_one_shared_fixture_row_for_all_benchmarks():
    result = _evaluate(_history())

    assert [row["match_id"] for row in result["predictions"]] == [5, 6]
    for row in result["predictions"]:
        assert set(row["winner"]) == {
            "model",
            "uniform",
            "base_rate",
            "always_home",
            "elo_favorite",
            "market",
        }
        assert set(row["margin"]) == {
            "model",
            "zero",
            "rolling_home",
            "elo",
            "market",
        }
        assert set(row["total"]) == {
            "model",
            "rolling",
            "legacy_constant",
            "market",
        }


def test_metric_functions_match_hand_calculated_fixture_values():
    records = [
        {
            "actual_home": 20,
            "actual_away": 10,
            "actual_outcome": "home",
            "winner": {"test": [0.5, 0.2, 0.3]},
            "margin": {"test": 8.0, "zero": 0.0},
            "total": {"test": 32.0},
            "scoreline": {
                "expected_home": 19.0,
                "expected_away": 11.0,
                "predicted_home": 20,
                "predicted_away": 10,
                "baseline_home": 18.0,
                "baseline_away": 12.0,
            },
        },
        {
            "actual_home": 12,
            "actual_away": 18,
            "actual_outcome": "away",
            "winner": {"test": [0.2, 0.1, 0.7]},
            "margin": {"test": -4.0, "zero": 0.0},
            "total": {"test": 28.0},
            "scoreline": {
                "expected_home": 14.0,
                "expected_away": 16.0,
                "predicted_home": 14,
                "predicted_away": 16,
                "baseline_home": 18.0,
                "baseline_away": 12.0,
            },
        },
    ]

    winner = _winner_summary(records, "test")
    assert winner["log_loss"] == pytest.approx((-math.log(0.5) - math.log(0.7)) / 2)
    assert winner["brier"] == pytest.approx(0.26)
    assert winner["rps"] == pytest.approx(0.1175)
    assert winner["accuracy"] == 1.0
    assert winner["ece"] == pytest.approx(1.6 / 6)

    margin = _margin_summary(records, "test")
    assert margin == {
        "n": 2,
        "mae": 2.0,
        "rmse": 2.0,
        "bias": 0.0,
        "within_6": 1.0,
        "within_12": 1.0,
        "winner_sign_accuracy": 1.0,
    }
    assert _margin_summary(records, "zero")["winner_sign_accuracy"] == 0.0

    total = _total_summary(records, "test")
    assert total == {
        "n": 2,
        "mae": 2.0,
        "rmse": 2.0,
        "bias": 0.0,
        "within_6": 1.0,
        "within_12": 1.0,
    }

    scoreline = _scoreline_summary(records, True)
    assert scoreline == {
        "n": 2,
        "home_mae": 1.5,
        "away_mae": 1.5,
        "combined_team_mae": 1.5,
        "exact_hit_rate": 0.5,
        "both_within_6": 1.0,
    }
    rolling = _scoreline_summary(records, False)
    assert rolling["combined_team_mae"] == 4.0
    assert rolling["exact_hit_rate"] == 0.0
    assert rolling["both_within_6"] == 1.0
