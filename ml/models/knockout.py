"""Knockout-tie resolution — extra time and penalties (model v0.5).

The match engine (ml/models/poisson.py) predicts regulation only: its W/D/L
triple and scoreline stop at the 90th minute. A knockout tie level after 90
continues — 30 minutes of extra time, then a shootout — so "who goes through"
needs everything past the 90th minute. This module owns that:

- ``shootout_p`` / ``fit_pk_beta``: the capped Elo-logistic penalty model
  (moved here from ml/simulate/bracket.py, which re-imports them — penalties
  are a match-model concern, not a simulation concern).
- ``ko_advance``: the analytic decomposition of the advance probability,

    P(home advances) = P(home in 90)
                     + P(draw at 90) * ( P(home in ET)
                                       + P(level after ET) * P(home on pens) )

  Extra time reuses the same Dixon-Coles machinery at 30-minute rates:
  ``lam_et = lam * (30/90) * et_tempo``. ``et_tempo`` is the ET
  goals-per-minute rate relative to regulation — prior 1.0 (same tempo),
  tunable in model_params.json and fittable later with shrinkage, exactly the
  ``pk_beta`` restraint pattern. Everything is computed on the closed-form
  grid; no sampling, so the block is deterministic and cheap.

The regulation triple passed in is the CALIBRATED, served triple — the
decomposition must sit on top of the numbers the product already shows, so
P(advance) always reconciles with the visible W/D/L bar. The ET grid itself
is NOT calibrated (the calibrator was fit on 90-minute outcomes only).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ml.models.poisson import outcome_probabilities, score_matrix

# Penalty shootout: near coin-flip. Strength enters via a small, capped logistic
# (pk_beta loaded from model_params.json; default 0.0 = pure coin-flip). The win
# probability is clamped to PK_BAND so no parameter drift can re-introduce a
# large skill bias (shootouts are empirically close to random).
PK_BAND = (0.45, 0.55)
PK_PRIOR_WEIGHT = 200  # shrinkage strength for fit_pk_beta (samples are thin)

# Extra time is a third of a match; et_tempo scales the per-minute goal rate
# relative to regulation (1.0 = same tempo).
ET_FRACTION = 30.0 / 90.0
ET_TEMPO_DEFAULT = 1.0


def shootout_p(elo_h: float, elo_a: float, pk_beta: float) -> float:
    """P(home wins the shootout), clamped to PK_BAND."""
    p = 1.0 / (1.0 + math.exp(-pk_beta * (elo_h - elo_a)))
    lo, hi = PK_BAND
    return min(hi, max(lo, p))


def fit_pk_beta(samples: list[tuple[float, bool]]) -> float:
    """Fit a tiny logistic slope from historical penalty-decided knockouts, then
    SHRINK toward 0 by n/(n+PK_PRIOR_WEIGHT). `samples` = (elo_gap favorite-minus-
    underdog, favorite_won). Returns 0.0 when data is empty/thin (-> coin-flip)."""
    n = len(samples)
    if n == 0:
        return 0.0
    num = den = 0.0
    for gap, won in samples:
        p = 0.5  # logistic at beta=0
        num += gap * ((1.0 if won else 0.0) - p)
        den += (gap * gap) * p * (1.0 - p)
    raw = (num / den) if den > 0 else 0.0
    return raw * (n / (n + PK_PRIOR_WEIGHT))


@dataclass
class KnockoutAdvance:
    """How a knockout tie resolves, decomposed by path.

    ``win_90/win_et/win_pens`` are UNCONDITIONAL probabilities (they already
    include the chance of reaching that stage), so each side's three paths sum
    to its advance probability, and the two advance probabilities sum to 1.
    """
    p_advance_home: float
    p_advance_away: float
    p_extra_time: float  # tie level after 90 — the regulation draw probability
    p_shootout: float    # tie still level after 120
    home_win_90: float
    home_win_et: float
    home_win_pens: float
    away_win_90: float
    away_win_et: float
    away_win_pens: float

    def to_payload(self) -> dict:
        """JSON-ready block for the predictions store / API (4 dp, matching the
        probability rounding used elsewhere in the payload)."""
        r = lambda x: round(x, 4)  # noqa: E731
        return {
            "p_advance_home": r(self.p_advance_home),
            "p_advance_away": r(self.p_advance_away),
            "p_extra_time": r(self.p_extra_time),
            "p_shootout": r(self.p_shootout),
            "paths": {
                "home": {"win_90": r(self.home_win_90), "win_et": r(self.home_win_et),
                         "win_pens": r(self.home_win_pens)},
                "away": {"win_90": r(self.away_win_90), "win_et": r(self.away_win_et),
                         "win_pens": r(self.away_win_pens)},
            },
        }


def ko_advance(
    p_home: float,
    p_draw: float,
    p_away: float,
    lam_home: float,
    lam_away: float,
    elo_home: float,
    elo_away: float,
    rho: float = 0.0,
    pk_beta: float = 0.0,
    et_tempo: float = ET_TEMPO_DEFAULT,
) -> KnockoutAdvance:
    """Resolve a knockout tie past the 90th minute.

    ``p_home/p_draw/p_away`` is the served (calibrated) regulation triple;
    ``lam_home/lam_away`` are the same per-90 rates that built it. Extra time
    is the Dixon-Coles grid at ``lam * ET_FRACTION * et_tempo`` (rho kept: the
    low-score cells it corrects are exactly where a 30-minute segment lives),
    penalties the capped Elo logistic. The input triple is normalized so the
    two advance probabilities always sum to exactly 1.
    """
    total = p_home + p_draw + p_away
    if total <= 0.0:
        raise ValueError("degenerate regulation triple: non-positive total mass")
    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    et_scale = ET_FRACTION * et_tempo
    et_h, et_d, et_a = outcome_probabilities(
        score_matrix(lam_home * et_scale, lam_away * et_scale, rho=rho)
    )
    pk_h = shootout_p(elo_home, elo_away, pk_beta)

    p_shootout = p_draw * et_d
    home_win_et = p_draw * et_h
    away_win_et = p_draw * et_a
    home_win_pens = p_shootout * pk_h
    away_win_pens = p_shootout * (1.0 - pk_h)
    return KnockoutAdvance(
        p_advance_home=p_home + home_win_et + home_win_pens,
        p_advance_away=p_away + away_win_et + away_win_pens,
        p_extra_time=p_draw,
        p_shootout=p_shootout,
        home_win_90=p_home,
        home_win_et=home_win_et,
        home_win_pens=home_win_pens,
        away_win_90=p_away,
        away_win_et=away_win_et,
        away_win_pens=away_win_pens,
    )
