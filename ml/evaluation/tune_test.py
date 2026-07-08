"""Tests for the walk-forward tuner (synthetic data; no network)."""
from datetime import datetime

from ml.evaluation.tune import tune_form, tune_params, validation_window, wdl_probs
from ml.models.params import DEFAULT_PARAMS, ModelParams


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


# --- tune_form: second-stage grid for the split form channels (C1) ---------


def _rows_with_team_ids(n: int) -> list[dict]:
    """Synthetic team-identified rows (the shape build_enriched_rows produces
    via ml.ratings.elo.replay_with_prematch: home_id/away_id + pre-match
    ratings). Team 1 is a strong home side that also runs hot (over-scores
    its Poisson expectation) in a recognizable pattern, so a form channel has
    real signal to fit -- mirrors _rows()'s "real signal" design intent."""
    rows = []
    for i in range(n):
        strong_home = i % 2 == 0
        home_id, away_id = (1, 2) if strong_home else (2, 1)
        pre_home, pre_away = (1800, 1500) if strong_home else (1500, 1800)
        sh, sa = (3, 0) if strong_home else (0, 2)
        if i % 5 == 0:
            sh, sa = 1, 1
        rows.append({
            "home_id": home_id, "away_id": away_id,
            "pre_home": pre_home, "pre_away": pre_away, "is_neutral": True,
            "score_home": sh, "score_away": sa,
            "date": datetime(2020, 1, 1 + (i % 27)), "competition": "Friendly",
        })
    return rows


def test_tune_form_returns_form_channels_dict_in_grid():
    result = tune_form(_rows_with_team_ids(120), DEFAULT_PARAMS)
    assert isinstance(result, dict)
    for key in ("c_atk", "c_def", "cap", "half_life"):
        assert key in result

    from ml.evaluation.tune import _C_ATK_GRID, _C_DEF_GRID, _CAP_GRID, _HALF_LIFE_GRID
    assert result["c_atk"] in _C_ATK_GRID
    assert result["c_def"] in _C_DEF_GRID
    assert result["cap"] in _CAP_GRID
    assert result["half_life"] in _HALF_LIFE_GRID


def test_tune_form_does_not_mutate_base_params():
    base = DEFAULT_PARAMS
    tune_form(_rows_with_team_ids(120), base)
    assert base.form_channels is None  # tune_form must not touch the input


def test_tune_form_does_not_change_tune_params_signature():
    # Explicit guard per the brief: tune_params' signature must be untouched.
    import inspect
    sig = inspect.signature(tune_params)
    assert list(sig.parameters) == ["val_rows", "version", "passes"]


def test_tune_form_improves_or_matches_log_loss_vs_form_off():
    """The chosen grid point must not make validation log loss WORSE than
    leaving form channels off entirely (same objective tune_params uses)."""
    from ml.evaluation.tune import _form_logloss

    rows = _rows_with_team_ids(200)
    off_ll = _form_logloss(rows, DEFAULT_PARAMS, None)
    best = tune_form(rows, DEFAULT_PARAMS)
    on_ll = _form_logloss(rows, DEFAULT_PARAMS, best)
    assert on_ll <= off_ll + 1e-9


def test_tune_form_underpowered_window_raises():
    from ml.evaluation.tune import MIN_VAL_MATCHES
    import pytest
    with pytest.raises(ValueError):
        tune_form(_rows_with_team_ids(MIN_VAL_MATCHES - 1), DEFAULT_PARAMS)
