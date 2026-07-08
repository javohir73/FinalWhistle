"""Walk-forward parameter tuning for the Poisson-Elo engine (model v0.2).

Fits the goals-model knobs (base, beta, home advantage, Dixon-Coles rho) and then
the calibration temperature by minimizing log-loss on a *validation window that
ends before* the data we will later score on — so nothing leaks from the test
set. Elo pre-match ratings in the rows are already leak-free (each reflects only
earlier matches), so tuning reuses them directly.

Search is coordinate descent over small grids: cheap, deterministic, and good
enough for four smooth parameters.
"""
from __future__ import annotations

from datetime import timedelta

from ml.evaluation.calibration import fit_temperature
from ml.models.baseline_logistic import result_label
from ml.models.params import ModelParams
from ml.models.poisson import expected_goals_from_elo, outcome_probabilities, score_matrix, _apply_temperature
from ml.ratings.form import FormConfig, form_offsets

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15

# A tuning/validation window below this many matches is underpowered — fitting on
# it returns grid-corner params shaped by noise, so we fail loudly instead.
MIN_VAL_MATCHES = 100

# Coordinate-descent grids.
_BASE_GRID = [1.20, 1.25, 1.30, 1.35, 1.40, 1.45, 1.50]
_BETA_GRID = [0.0012, 0.0015, 0.0017, 0.0019, 0.0021, 0.0023, 0.0026]
_HOME_GRID = [0.0, 30.0, 45.0, 60.0, 75.0, 90.0, 110.0]
_RHO_GRID = [-0.18, -0.14, -0.10, -0.06, -0.03, 0.0, 0.04]

# Second-stage grids for the split form channels (model v2 C1) — run AFTER
# the base/beta/home_adv/rho passes above, on a separately-requested call
# (tune_form), never inside tune_params itself.
_C_ATK_GRID = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
_C_DEF_GRID = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
_CAP_GRID = [0.05, 0.10, 0.15, 0.20, 0.25]
_HALF_LIFE_GRID = [2, 3, 5, 8]


def wdl_probs(pre_home, pre_away, is_neutral, base, beta, home_adv, rho, temperature=1.0):
    """W/D/L triple for one match under the given params."""
    adv = 0.0 if is_neutral else home_adv
    lam_h, lam_a = expected_goals_from_elo(pre_home, pre_away, adv, base, beta)
    probs = outcome_probabilities(score_matrix(lam_h, lam_a, rho=rho))
    if temperature != 1.0:
        probs = _apply_temperature(probs, temperature)
    return probs


def _logloss(rows, base, beta, home_adv, rho, temperature=1.0):
    import math
    n = len(rows) or 1
    total = 0.0
    for r in rows:
        idx = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
        p = wdl_probs(r["pre_home"], r["pre_away"], r["is_neutral"], base, beta, home_adv, rho, temperature)
        total -= math.log(max(_EPS, min(1 - _EPS, p[idx])))
    return total / n


def tune_params(val_rows: list[dict], version: str = "poisson-elo-v0.2", passes: int = 3) -> ModelParams:
    """Coordinate-descent the goals params on val_rows, then fit temperature."""
    if len(val_rows) < MIN_VAL_MATCHES:
        raise ValueError(
            f"validation window has {len(val_rows)} matches (< MIN_VAL_MATCHES="
            f"{MIN_VAL_MATCHES}); too underpowered to tune.")
    base, beta, home_adv, rho = 1.35, 0.0019, 60.0, 0.0

    def best_on(grid, setter):
        best_v, best_ll = grid[0], float("inf")
        for v in grid:
            ll = setter(v)
            if ll < best_ll:
                best_ll, best_v = ll, v
        return best_v

    for _ in range(passes):
        base = best_on(_BASE_GRID, lambda v: _logloss(val_rows, v, beta, home_adv, rho))
        beta = best_on(_BETA_GRID, lambda v: _logloss(val_rows, base, v, home_adv, rho))
        home_adv = best_on(_HOME_GRID, lambda v: _logloss(val_rows, base, beta, v, rho))
        rho = best_on(_RHO_GRID, lambda v: _logloss(val_rows, base, beta, home_adv, v))

    # Fit temperature on the uncalibrated probs from the chosen goals params.
    probs_list = [
        wdl_probs(r["pre_home"], r["pre_away"], r["is_neutral"], base, beta, home_adv, rho)
        for r in val_rows
    ]
    labels = [_LABEL_INDEX[result_label(r["score_home"], r["score_away"])] for r in val_rows]
    temperature = fit_temperature(probs_list, labels)

    return ModelParams(
        version=version,
        base=round(base, 4),
        beta=round(beta, 5),
        home_adv=round(home_adv, 1),
        rho=round(rho, 3),
        temperature=round(temperature, 3),
    )


def validation_window(rows: list[dict], before_date, days: int = 730) -> list[dict]:
    """Rows in [before_date - days, before_date) — the leak-free tuning window."""
    start = before_date - timedelta(days=days)
    return [r for r in rows if start <= r["date"] < before_date]


def _form_logloss(val_rows: list[dict], base_params: ModelParams, form_cfg: dict | None) -> float:
    """Walk-forward log loss with the split form channels applied (or not,
    when ``form_cfg`` is None — the same "off" comparison point tune_params'
    own coordinate descent implicitly uses for every OTHER knob).

    ``val_rows`` MUST carry ``ledger_home``/``ledger_away`` — the PRE-
    ATTACHED, already leak-free, already-capped ledgers
    pipeline/backtest_data.py's build_enriched_rows snapshots BEFORE each
    row's own match (same shape ml.evaluation.experiments._row_probs
    consumes for scoring/serving). This function used to maintain a SECOND,
    independently-rebuilt running ledger at base_params' scale, unbounded —
    a different scale and cap than scoring/serving ever see (model v2 review
    finding: ablation validity requires one ledger, one scale, one cap,
    everywhere). Reading the rows' own ledgers instead of rebuilding one also
    means row order here no longer matters for leakage — the walk-forward
    pre-match property already lives in how build_enriched_rows built the
    ledgers, not in the order this function iterates them.
    """
    import math

    cfg = FormConfig(**form_cfg) if form_cfg else None

    total = 0.0
    n = len(val_rows) or 1
    for r in val_rows:
        adv = 0.0 if r["is_neutral"] else base_params.home_adv

        atk_h = def_h = atk_a = def_a = 0.0
        if cfg is not None:
            atk_h, def_h = form_offsets(r.get("ledger_home") or [], cfg)
            atk_a, def_a = form_offsets(r.get("ledger_away") or [], cfg)

        lam_h, lam_a = expected_goals_from_elo(
            r["pre_home"], r["pre_away"], adv, base_params.base, base_params.beta,
            atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
        )
        probs = outcome_probabilities(score_matrix(lam_h, lam_a, rho=base_params.rho))
        if base_params.temperature != 1.0:
            probs = _apply_temperature(probs, base_params.temperature)

        idx = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
        total -= math.log(max(_EPS, min(1 - _EPS, probs[idx])))

    return total / n


def tune_form(
    val_rows: list[dict], base_params: ModelParams, passes: int = 2
) -> dict:
    """Coordinate-descent the split form-channel hyperparams (model v2 C1) on
    top of an already-tuned ``base_params`` (goals + calibration knobs stay
    fixed here — this is a SEPARATE, second-stage grid, run only when the
    caller explicitly asks for it; it never runs inside tune_params and never
    changes tune_params' signature).

    ``val_rows`` must carry ``ledger_home``/``ledger_away`` (see
    _form_logloss) — the pre-attached, leak-free, capped ledgers
    build_enriched_rows produces.
    Objective: validation log loss, identical metric to tune_params'.
    Returns a form_channels dict ({"c_atk", "c_def", "cap", "half_life"}) —
    the exact shape ModelParams.form_channels / model_params.json expects.
    """
    if len(val_rows) < MIN_VAL_MATCHES:
        raise ValueError(
            f"validation window has {len(val_rows)} matches (< MIN_VAL_MATCHES="
            f"{MIN_VAL_MATCHES}); too underpowered to tune.")

    c_atk, c_def, cap, half_life = _C_ATK_GRID[0], _C_DEF_GRID[0], _CAP_GRID[-1], _HALF_LIFE_GRID[1]

    def best_on(grid, setter):
        best_v, best_ll = grid[0], float("inf")
        for v in grid:
            ll = setter(v)
            if ll < best_ll:
                best_ll, best_v = ll, v
        return best_v

    def cfg_dict(c_atk, c_def, cap, half_life):
        return {"c_atk": c_atk, "c_def": c_def, "cap": cap, "half_life": half_life}

    for _ in range(passes):
        c_atk = best_on(
            _C_ATK_GRID,
            lambda v: _form_logloss(val_rows, base_params, cfg_dict(v, c_def, cap, half_life)),
        )
        c_def = best_on(
            _C_DEF_GRID,
            lambda v: _form_logloss(val_rows, base_params, cfg_dict(c_atk, v, cap, half_life)),
        )
        cap = best_on(
            _CAP_GRID,
            lambda v: _form_logloss(val_rows, base_params, cfg_dict(c_atk, c_def, v, half_life)),
        )
        half_life = best_on(
            _HALF_LIFE_GRID,
            lambda v: _form_logloss(val_rows, base_params, cfg_dict(c_atk, c_def, cap, v)),
        )

    return cfg_dict(c_atk, c_def, float(cap), float(half_life))
