"""Split, decayed, boundary-free form channels (model v2 change C1).

Root cause this replaces: the legacy single scalar in ml/ratings/tournament.py
(``form_adjustment``) collapses attack and defence residuals into one number,
so a hot attacking run and a bad defensive match can arithmetically cancel
(the Norway–Brazil post-mortem: +1.22 gf vs +1.23 ga netted to ~0). It also
starts from zero at the tournament boundary, discarding pre-tournament form.

``form_offsets`` fixes both: attack and defence are independent log-lambda
offsets, and the residual ledger the caller passes in can be seeded with
pre-tournament matches (ml/ratings/tournament.py owns the ledger; this module
is pure math over it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Matches needed before the small-sample damp reaches full weight — the same
#: √(n/4) ramp as the legacy scalar's FORM_FULL_WEIGHT_MATCHES convention.
FULL_WEIGHT_MATCHES = 4


@dataclass(frozen=True)
class FormConfig:
    """Tuned knobs for the two form channels (fit by ml/evaluation/tune.py's
    tune_form, never hand-set for the served model)."""

    c_atk: float
    c_def: float
    cap: float        # clamp on each offset, log-lambda units
    half_life: float  # decay half-life in matches


def _decayed_mean(values: list[float], half_life: float) -> float:
    """Exponentially recency-weighted mean. ``values`` is oldest-first; the
    LAST element is age 0. w_i = 0.5 ** (age_i / half_life)."""
    n = len(values)
    if n == 0:
        return 0.0
    weight_sum = 0.0
    total = 0.0
    for i, v in enumerate(values):
        age = (n - 1) - i
        w = 0.5 ** (age / half_life)
        total += w * v
        weight_sum += w
    return total / weight_sum if weight_sum else 0.0


def form_offsets(
    residual_ledger: list[tuple[float, float]], cfg: FormConfig
) -> tuple[float, float]:
    """(atk_form, def_form) log-lambda offsets from a time-ordered ledger.

    ``residual_ledger``: list of (gf_residual, ga_residual) per match, most
    recent LAST (age 0). Empty ledger -> (0.0, 0.0).

    Sign conventions: positive atk_form = team scoring above expectation
    (boosts own lambda); positive def_form = team CONCEDING above
    expectation (boosts the OPPONENT's lambda) -- callers apply def_form as
    the opponent-side offset (see expected_goals_from_elo's def_home/def_away).

    A small-sample damp (min(1, sqrt(n / FULL_WEIGHT_MATCHES)), mirroring the
    legacy FORM_FULL_WEIGHT_MATCHES=4 convention) is applied before the clamp,
    so one hot/cold match cannot swing an offset to the cap on its own.
    """
    n = len(residual_ledger)
    if n == 0:
        return 0.0, 0.0

    gf_residuals = [gf for gf, _ in residual_ledger]
    ga_residuals = [ga for _, ga in residual_ledger]

    gf_mean = _decayed_mean(gf_residuals, cfg.half_life)
    ga_mean = _decayed_mean(ga_residuals, cfg.half_life)

    damp = min(1.0, math.sqrt(n / FULL_WEIGHT_MATCHES))

    atk_raw = cfg.c_atk * gf_mean * damp
    def_raw = cfg.c_def * ga_mean * damp

    atk_form = max(-cfg.cap, min(cfg.cap, atk_raw))
    def_form = max(-cfg.cap, min(cfg.cap, def_raw))
    return float(atk_form), float(def_form)
