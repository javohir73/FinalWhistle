"""Tests for the additive, leak-safe vNext replay harness."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from ml.evaluation.vnext_replay import VNextReplayConfig, replay_vnext, world_cup_year
from ml.ratings.dynamic_strength import DynamicModelConfig


T0 = datetime(2025, 6, 1, 12, tzinfo=timezone.utc)


def _row(
    index: int,
    home: int,
    away: int,
    score_home: int,
    score_away: int,
    *,
    target: bool = False,
) -> dict:
    return {
        "id": index,
        "home_id": home,
        "away_id": away,
        "pre_home": 1500.0 + 8.0 * index,
        "pre_away": 1500.0 - 5.0 * index,
        "score_home": score_home,
        "score_away": score_away,
        "is_neutral": True,
        "date": T0 + timedelta(days=index),
        "competition": "Test Cup",
        "target": target,
    }


def _config() -> VNextReplayConfig:
    return VNextReplayConfig(
        dynamic=DynamicModelConfig(base_log_total=math.log(2.4)),
        bootstrap_samples=100,
        bootstrap_seed=7,
    )


def test_replay_returns_all_three_models_and_requested_metrics():
    rows = [
        _row(0, 1, 2, 1, 0),
        _row(1, 2, 3, 1, 1, target=True),
        _row(2, 1, 3, 2, 0, target=True),
    ]
    result = replay_vnext(rows, target_selector=lambda row: row["target"], config=_config())

    assert result["n_matches"] == 2
    assert set(result["models"]) == {
        "legacy",
        "coherent_legacy",
        "orthogonal_elo_dynamic_tempo",
        "dynamic_strength_tempo",
    }
    for metrics in result["models"].values():
        assert metrics["n"] == 2
        assert metrics["log_loss"] > 0.0
        assert metrics["brier"] >= 0.0
        assert 0.0 <= metrics["accuracy"] <= 1.0
        assert metrics["exact_score_nll"] > 0.0
        assert metrics["over_under_2_5_brier"] >= 0.0


def test_target_result_is_not_used_before_its_forecast():
    history = _row(0, 1, 2, 2, 0)
    target = _row(1, 1, 3, 0, 0, target=True)
    changed_target = {**target, "score_home": 6, "score_away": 1}

    original = replay_vnext(
        [history, target], target_selector=lambda row: row["target"], config=_config()
    )["receipts"][0]
    changed = replay_vnext(
        [history, changed_target],
        target_selector=lambda row: row["target"],
        config=_config(),
    )["receipts"][0]

    for model in original["forecasts"]:
        assert (
            original["forecasts"][model]["wdl"]
            == changed["forecasts"][model]["wdl"]
        )
        assert (
            original["forecasts"][model]["expected_goals"]
            == changed["forecasts"][model]["expected_goals"]
        )
        assert (
            original["forecasts"][model]["over_2_5_probability"]
            == changed["forecasts"][model]["over_2_5_probability"]
        )


def test_every_metric_is_coherent_with_the_same_forecast_receipt():
    result = replay_vnext(
        [_row(0, 1, 2, 2, 1, target=True)],
        target_selector=lambda row: row["target"],
        config=_config(),
    )
    receipt = result["receipts"][0]

    for model, forecast in receipt["forecasts"].items():
        p_home, p_draw, p_away = forecast["wdl"]
        assert p_home + p_draw + p_away == pytest.approx(1.0)
        assert result["models"][model]["log_loss"] == pytest.approx(-math.log(p_home))
        expected_brier = (p_home - 1.0) ** 2 + p_draw**2 + p_away**2
        assert result["models"][model]["brier"] == pytest.approx(expected_brier)
        assert result["models"][model]["exact_score_nll"] == pytest.approx(
            -math.log(forecast["exact_score_probability"])
        )
        assert result["models"][model]["over_under_2_5_brier"] == pytest.approx(
            (forecast["over_2_5_probability"] - 1.0) ** 2
        )


def test_zero_tempo_change_preserves_served_wdl_calibration_parity():
    calibrator = {
        "method": "vector_scaling",
        "t": 1.0,
        "b": [0.0, 0.25, -0.15],
    }
    config = VNextReplayConfig(
        base=1.35,
        calibrator=calibrator,
        calibrator_artifact_id="test-calibrator-v1",
        dynamic=DynamicModelConfig(base_log_total=math.log(2.7)),
        bootstrap_samples=0,
    )
    row = _row(0, 1, 2, 1, 1, target=True)
    row["pre_home"] = row["pre_away"] = 1500.0

    receipt = replay_vnext(
        [row], target_selector=lambda source: source["target"], config=config
    )["receipts"][0]

    assert receipt["forecasts"]["orthogonal_elo_dynamic_tempo"]["wdl"] == pytest.approx(
        receipt["forecasts"]["legacy"]["wdl"]
    )
    tempo = receipt["forecasts"]["orthogonal_elo_dynamic_tempo"]
    coherent = receipt["forecasts"]["coherent_legacy"]
    assert tempo["wdl"] == pytest.approx(coherent["wdl"])
    assert tempo["expected_goals"] == pytest.approx(coherent["expected_goals"])
    assert tempo["exact_score_probability"] == pytest.approx(
        coherent["exact_score_probability"]
    )
    assert tempo["over_2_5_probability"] == pytest.approx(
        coherent["over_2_5_probability"]
    )


def test_dynamic_replay_learns_only_after_each_row_forecast():
    rows = [
        _row(0, 1, 2, 3, 0, target=True),
        _row(1, 1, 3, 2, 0, target=True),
    ]
    receipts = replay_vnext(
        rows, target_selector=lambda row: row["target"], config=_config()
    )["receipts"]

    assert receipts[0]["dynamic_evidence_before"] == 0
    assert receipts[1]["dynamic_evidence_before"] == 1
    first_share = receipts[0]["forecasts"]["dynamic_strength_tempo"]["wdl"][0]
    second_share = receipts[1]["forecasts"]["dynamic_strength_tempo"]["wdl"][0]
    assert second_share > first_share


def test_same_timestamp_batch_is_forecast_before_any_same_time_result():
    first = _row(0, 1, 2, 3, 0, target=True)
    second = _row(1, 1, 3, 1, 0, target=True)
    second["date"] = first["date"]
    changed_first = {**first, "score_home": 0, "score_away": 5}

    original = replay_vnext(
        [first, second], target_selector=lambda row: row["target"], config=_config()
    )["receipts"][1]
    changed = replay_vnext(
        [changed_first, second],
        target_selector=lambda row: row["target"],
        config=_config(),
    )["receipts"][1]

    assert (
        original["forecasts"]["dynamic_strength_tempo"]
        == changed["forecasts"]["dynamic_strength_tempo"]
    )
    assert original["dynamic_evidence_before"] == 0


def test_out_of_grid_exact_score_is_epsilon_not_edge_cell_probability():
    config = VNextReplayConfig(
        max_goals=2,
        dynamic=DynamicModelConfig(max_goals=10),
        bootstrap_samples=0,
    )
    result = replay_vnext(
        [_row(0, 1, 2, 3, 0, target=True)],
        target_selector=lambda row: row["target"],
        config=config,
    )

    for forecast in result["receipts"][0]["forecasts"].values():
        assert forecast["exact_score_in_grid"] is False
        assert forecast["exact_score_probability"] == 1e-15
        assert forecast["values"]["exact_score_nll"] == pytest.approx(-math.log(1e-15))


def test_paired_deltas_and_confidence_intervals_are_returned():
    rows = [
        _row(0, 1, 2, 1, 0, target=True),
        _row(1, 2, 3, 0, 1, target=True),
        _row(2, 3, 1, 2, 2, target=True),
    ]
    result = replay_vnext(
        rows, target_selector=lambda row: row["target"], config=_config()
    )

    for comparison in result["paired_vs_legacy"].values():
        assert comparison["log_loss"]["n"] == 3
        assert len(comparison["log_loss"]["ci95"]) == 2
        assert comparison["log_loss"]["better_when"] == "negative"
        assert comparison["accuracy"]["better_when"] == "positive"
    assert set(result["paired_component_vs_coherent_legacy"]) == {
        "orthogonal_elo_dynamic_tempo",
        "dynamic_strength_tempo",
    }


def test_world_cup_selector_uses_year_and_excludes_qualifiers():
    selector = world_cup_year(2026)
    base = _row(0, 1, 2, 1, 0)
    assert selector({**base, "date": date(2026, 6, 11), "competition": "FIFA World Cup"})
    assert not selector(
        {**base, "date": "2026-06-11", "competition": "FIFA World Cup qualification"}
    )


def test_invalid_or_non_chronological_dates_are_rejected():
    naive = _row(0, 1, 2, 1, 0, target=True)
    naive["date"] = datetime(2025, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        replay_vnext([naive], target_selector=lambda row: True, config=_config())

    later = _row(0, 1, 2, 1, 0, target=True)
    earlier = _row(1, 2, 3, 1, 0, target=True)
    later["date"] = T0 + timedelta(days=2)
    earlier["date"] = T0 + timedelta(days=1)
    with pytest.raises(ValueError, match="chronological"):
        replay_vnext(
            [later, earlier], target_selector=lambda row: True, config=_config()
        )


def test_empty_target_and_invalid_rows_are_rejected():
    row = _row(0, 1, 2, 1, 0)
    with pytest.raises(ValueError, match="matched no rows"):
        replay_vnext([row], target_selector=lambda source: False, config=_config())
    with pytest.raises(ValueError, match="missing required"):
        replay_vnext([{}], target_selector=lambda source: True, config=_config())
