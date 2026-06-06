"""Tests for the backtest harness incl. the beat-the-baseline gate (task 4.7)."""
from datetime import datetime, timezone

from ml.evaluation.backtest import backtest, compute_metrics, model_probs


def test_compute_metrics_perfect_predictions():
    m = compute_metrics([(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)], ["H", "A"])
    assert m["accuracy"] == 1.0
    assert m["log_loss"] < 0.001
    assert m["brier"] < 0.001


def test_compute_metrics_handles_empty():
    m = compute_metrics([], [])
    assert m["n"] == 0


def test_model_probs_sum_to_one():
    p = model_probs(1900, 1600, is_neutral=True)
    assert abs(sum(p) - 1.0) < 1e-9


def _synthetic_rows():
    """Strong, learnable signal: high pre_home almost always wins.

    Training history (pre-2018) is balanced enough that a base-rate baseline is
    uninformative, so the Elo-aware model must beat it.
    """
    rows = []
    # Training rows: a mix so base-rate ~ even-ish.
    for i in range(200):
        strong_home = i % 2 == 0
        rows.append({
            "pre_home": 1900 if strong_home else 1500,
            "pre_away": 1500 if strong_home else 1900,
            "is_neutral": True,
            "score_home": 3 if strong_home else 0,
            "score_away": 0 if strong_home else 3,
            "date": datetime(2000 + i % 15, 1, 1, tzinfo=timezone.utc),
            "competition": "Friendly",
        })
    # Target: WC2018, strong home favorites that win (model should be confident+right).
    for j in range(20):
        rows.append({
            "pre_home": 1950, "pre_away": 1450, "is_neutral": True,
            "score_home": 2, "score_away": 0,
            "date": datetime(2018, 6, 15, tzinfo=timezone.utc),
            "competition": "FIFA World Cup",
        })
    return rows


def test_model_beats_base_rate_on_log_loss_gate():
    """PRD Goal #3, encoded as a test: the model must beat the naive baseline."""
    result = backtest(_synthetic_rows(), 2018)
    assert result["n_matches"] == 20
    assert result["model"]["log_loss"] < result["base_rate_baseline"]["log_loss"]


def test_backtest_raises_for_missing_year():
    import pytest

    with pytest.raises(ValueError):
        backtest(_synthetic_rows(), 1990)
