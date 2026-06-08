"""Tests for the walk-forward tuner (synthetic data; no network)."""
from datetime import datetime

from ml.evaluation.tune import tune_params, validation_window, wdl_probs
from ml.models.params import ModelParams


def _rows(n: int) -> list[dict]:
    """Synthetic matches where the higher-Elo side usually wins, so tuning has a
    real signal to fit."""
    rows = []
    for i in range(n):
        strong_home = i % 2 == 0
        pre_home, pre_away = (1800, 1500) if strong_home else (1500, 1800)
        sh, sa = (2, 0) if strong_home else (0, 2)
        if i % 5 == 0:  # some draws so draw prob is non-degenerate
            sh, sa = 1, 1
        rows.append({
            "pre_home": pre_home, "pre_away": pre_away, "is_neutral": True,
            "score_home": sh, "score_away": sa,
            "date": datetime(2020, 1, 1 + (i % 27)), "competition": "Friendly",
        })
    return rows


def test_wdl_probs_normalized():
    p = wdl_probs(1800, 1500, True, 1.35, 0.0019, 60.0, -0.1, 1.1)
    assert abs(sum(p) - 1.0) < 1e-9
    assert all(0.0 <= x <= 1.0 for x in p)


def test_tune_params_returns_valid_params_in_grid():
    params = tune_params(_rows(120))
    assert isinstance(params, ModelParams)
    assert params.version == "poisson-elo-v0.2"
    assert 1.2 <= params.base <= 1.5
    assert 0.0012 <= params.beta <= 0.0026
    assert 0.0 <= params.home_adv <= 110.0
    assert -0.18 <= params.rho <= 0.04
    assert 0.5 <= params.temperature <= 3.0


def test_validation_window_filters_by_date():
    rows = _rows(120)
    before = datetime(2020, 1, 20)
    win = validation_window(rows, before, days=10)
    assert win  # non-empty
    assert all(r["date"] < before for r in win)
