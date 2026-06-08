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

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15

# Coordinate-descent grids.
_BASE_GRID = [1.20, 1.25, 1.30, 1.35, 1.40, 1.45, 1.50]
_BETA_GRID = [0.0012, 0.0015, 0.0017, 0.0019, 0.0021, 0.0023, 0.0026]
_HOME_GRID = [0.0, 30.0, 45.0, 60.0, 75.0, 90.0, 110.0]
_RHO_GRID = [-0.18, -0.14, -0.10, -0.06, -0.03, 0.0, 0.04]


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
