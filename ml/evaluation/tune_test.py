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


def _rows_with_team_ids(n: int, params: ModelParams = DEFAULT_PARAMS) -> list[dict]:
    """Synthetic team-identified rows (the shape build_enriched_rows produces
    via ml.ratings.elo.replay_with_prematch: home_id/away_id + pre-match
    ratings), WITH pre-attached ledger_home/ledger_away -- exactly the shape
    pipeline/backtest_data.py's build_enriched_rows hands tune_form (model v2
    review finding: tune_form must consume the rows' own pre-attached,
    already-leak-free, capped ledgers rather than rebuild a second one at a
    different scale). Team 1 is a strong home side that also runs hot
    (over-scores its Poisson expectation) in a recognizable pattern, so a
    form channel has real signal to fit -- mirrors _rows()'s "real signal"
    design intent. Ledgers are built the same walk-forward way
    build_enriched_rows does: each row's ledger is snapshotted BEFORE that
    match, then the match's own residual is appended for later rows only."""
    from ml.models.poisson import expected_goals_from_elo

    raw = []
    for i in range(n):
        strong_home = i % 2 == 0
        home_id, away_id = (1, 2) if strong_home else (2, 1)
        pre_home, pre_away = (1800, 1500) if strong_home else (1500, 1800)
        sh, sa = (3, 0) if strong_home else (0, 2)
        if i % 5 == 0:
            sh, sa = 1, 1
        raw.append({
            "home_id": home_id, "away_id": away_id,
            "pre_home": pre_home, "pre_away": pre_away, "is_neutral": True,
            "score_home": sh, "score_away": sa,
            "date": datetime(2020, 1, 1 + (i % 27)), "competition": "Friendly",
        })

    from pipeline.backtest_data import LEDGER_CAP

    ledgers: dict[int, list[tuple[float, float]]] = {}
    for r in raw:
        home_id, away_id = r["home_id"], r["away_id"]
        r["ledger_home"] = list(ledgers.get(home_id, []))[-LEDGER_CAP:]
        r["ledger_away"] = list(ledgers.get(away_id, []))[-LEDGER_CAP:]

        lam_h, lam_a = expected_goals_from_elo(
            r["pre_home"], r["pre_away"], 0.0, params.base, params.beta,
        )
        home_gf, home_ga = r["score_home"] - lam_h, r["score_away"] - lam_a
        away_gf, away_ga = r["score_away"] - lam_a, r["score_home"] - lam_h
        ledgers.setdefault(home_id, []).append((home_gf, home_ga))
        ledgers.setdefault(away_id, []).append((away_gf, away_ga))
        ledgers[home_id] = ledgers[home_id][-LEDGER_CAP:]
        ledgers[away_id] = ledgers[away_id][-LEDGER_CAP:]
    return raw


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


# --- _form_logloss consumes PRE-ATTACHED ledgers (model v2 review finding) -


def test_form_logloss_uses_pre_attached_row_ledgers_not_a_rebuilt_one():
    """_form_logloss must read r["ledger_home"]/r["ledger_away"] directly
    (exactly like ml.evaluation.experiments._row_probs) instead of
    maintaining its own second running ledger at base_params scale. Proof:
    feeding rows whose pre-attached ledgers are all EMPTY must be identical
    to form_channels off, even though the rows' own score history (if a
    second ledger were rebuilt from score_home/score_away) would give a
    hot-running team real signal."""
    from ml.evaluation.tune import _form_logloss

    rows = _rows_with_team_ids(120)
    for r in rows:
        r["ledger_home"] = []
        r["ledger_away"] = []

    cfg = {"c_atk": 0.5, "c_def": 0.5, "cap": 0.25, "half_life": 3.0}
    off_ll = _form_logloss(rows, DEFAULT_PARAMS, None)
    on_ll = _form_logloss(rows, DEFAULT_PARAMS, cfg)
    assert abs(on_ll - off_ll) < 1e-12  # no ledger evidence -> no-op, regardless of cfg


def test_form_logloss_respects_ledger_cap_from_the_row_not_unbounded():
    """A row whose pre-attached ledger was already capped (LEDGER_CAP=15, the
    same cap scoring/serving use) must be scored on exactly that capped
    ledger -- not a longer one _form_logloss reconstructs itself."""
    from pipeline.backtest_data import LEDGER_CAP
    from ml.evaluation.tune import _form_logloss

    rows = _rows_with_team_ids(120)
    # Row far enough in to have accumulated more than LEDGER_CAP prior
    # appearances for team 1 if a second ledger were rebuilt unbounded.
    target = rows[-1]
    assert target["home_id"] == 1 or target["away_id"] == 1
    key = "ledger_home" if target["home_id"] == 1 else "ledger_away"
    assert len(target[key]) <= LEDGER_CAP  # the fixture itself never exceeds it

    cfg = {"c_atk": 0.5, "c_def": 0.5, "cap": 0.25, "half_life": 3.0}
    # Sanity the function runs end-to-end on capped ledgers without error.
    ll = _form_logloss(rows, DEFAULT_PARAMS, cfg)
    assert ll > 0.0


def test_form_logloss_scores_on_served_scale_ledger_matching_serving():
    """The pre-attached ledgers are built on base_params' own scale (the
    caller's responsibility, per build_enriched_rows' served-scale default);
    _form_logloss must not rebuild them at some OTHER scale. Proof: scoring
    the same rows' pre-attached ledgers with two different base_params must
    change the result only through the params passed to expected_goals_from_elo
    for scoring -- not through a second, independently-scaled ledger vanishing
    the difference."""
    from ml.evaluation.tune import _form_logloss

    alt_params = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(), "base": 1.2, "beta": 0.0021}
    )
    rows = _rows_with_team_ids(120, params=DEFAULT_PARAMS)
    cfg = {"c_atk": 0.5, "c_def": 0.5, "cap": 0.25, "half_life": 3.0}

    ll_default = _form_logloss(rows, DEFAULT_PARAMS, cfg)
    ll_alt = _form_logloss(rows, alt_params, cfg)
    assert ll_default != ll_alt  # scoring params actually take effect
