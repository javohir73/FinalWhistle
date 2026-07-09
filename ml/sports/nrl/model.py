"""NRL margin-Elo rating model (pure math, no I/O).

Same World-Football-style Elo convention as ml/ratings/elo.py (see that module's
docstring for the general shape), adapted for NRL/golden-point rugby league:
margins are logged rather than bucketed, off-season regression pulls teams back
toward the mean, and predictions carry a small fixed draw mass plus an expected
points margin. This module is self-contained — it imports nothing from
ml.ratings — so the NRL vertical can evolve its own K/home-advantage/margin
tuning independently of the football pipeline.

Formula (provenance: World Football Elo convention, as in ml/ratings/elo.py):
  expected_home = 1 / (1 + 10 ** (-((R_home + home_adv) - R_away) / 400))
  R_home' = R_home + K * mult * (W - expected_home)
where W is 1/0.5/0 for win/draw/loss and mult is the margin multiplier (or a
fixed 1.0 for draws — see `update`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class NrlParams:
    """Tunable constants for the NRL Elo + margin model."""

    version: str = "nrl-elo-v0.1"
    k: float = 36.0                 # per-match Elo K
    home_adv: float = 45.0          # Elo points
    margin_mult_cap: float = 2.2    # cap on the margin multiplier
    season_regress: float = 0.25    # off-season regression toward the mean
    margin_slope: float = 0.045     # expected points margin per Elo diff point
    margin_sigma: float = 15.0      # residual std dev of margins
    p_draw: float = 0.012           # empirical golden-point-era draw mass


def expected_home_prob(elo_home: float, elo_away: float, home_adv: float) -> float:
    """Probability-like expectation of the home side winning (0..1)."""
    return 1.0 / (1.0 + 10.0 ** (-((elo_home + home_adv) - elo_away) / 400.0))


def margin_multiplier(margin: float, cap: float) -> float:
    """Log-scaled reward for winning margin, capped so blowouts taper off.

    A zero margin (a draw) multiplies to 0.0 here — `update` special-cases
    draws with a fixed multiplier instead of calling this with margin=0.
    """
    return min(math.log(abs(margin) + 1.0), cap)


def update(
    elo_home: float,
    elo_away: float,
    score_home: int,
    score_away: int,
    p: NrlParams,
) -> tuple[float, float]:
    """Return updated (home, away) Elo ratings after one match. Pure, zero-sum."""
    expected = expected_home_prob(elo_home, elo_away, p.home_adv)
    margin = score_home - score_away

    if score_home > score_away:
        w_home = 1.0
        mult = margin_multiplier(margin, p.margin_mult_cap)
    elif score_home < score_away:
        w_home = 0.0
        mult = margin_multiplier(margin, p.margin_mult_cap)
    else:
        # Draws have zero margin, which would zero out margin_multiplier and
        # freeze ratings even when the draw is a surprise against a favourite.
        # Use a fixed multiplier of 1.0 so a draw against expectation still
        # moves ratings (e.g. home_adv > 0 at equal Elo -> expected > 0.5,
        # W = 0.5 -> home loses points, away gains them).
        w_home = 0.5
        mult = 1.0

    delta = p.k * mult * (w_home - expected)
    return elo_home + delta, elo_away - delta


def regress_season(
    elos: dict[int, float],
    p: NrlParams,
    mean: float = 1500.0,
) -> dict[int, float]:
    """Return a new dict with every team moved `season_regress` toward `mean`."""
    return {
        team_id: elo + p.season_regress * (mean - elo)
        for team_id, elo in elos.items()
    }


def predict(
    elo_home: float,
    elo_away: float,
    p: NrlParams,
    neutral: bool = False,
) -> dict:
    """Return {"p_home", "p_draw", "p_away", "expected_margin"} for a fixture."""
    adv = 0.0 if neutral else p.home_adv
    raw = expected_home_prob(elo_home, elo_away, adv)
    p_home = raw * (1.0 - p.p_draw)
    p_away = (1.0 - raw) * (1.0 - p.p_draw)
    expected_margin = ((elo_home + adv) - elo_away) * p.margin_slope
    return {
        "p_home": p_home,
        "p_draw": p.p_draw,
        "p_away": p_away,
        "expected_margin": expected_margin,
    }
