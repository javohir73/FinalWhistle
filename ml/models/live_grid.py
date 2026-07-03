"""Shared in-play grid math — the ONE place the live scoreline distribution is
built (Phase 3, docs/ROADMAP-ENGINE.md).

The live 1X2 bar (``app.live_winprob``) and the live derived markets
(``ml.models.live_markets``) must agree BY CONSTRUCTION — the bar cannot say
55% home while the totals/handicap grid implies something else. They do, because
both read the SAME normalized final-score grid produced here.

Model (unchanged from the original ``live_winprob``): the pre-match engine gives
each team a 90-minute expected-goals rate. Once a match is under way only goals
in the time REMAINING can change the result, so each team's remaining goals are
Poisson with mean scaled by the fraction of regulation left, corrected for the
low-score dependence via the same Dixon-Coles ``rho`` the pre-match grid uses,
and scaled by the card multipliers below. ``score_matrix`` prices that
REMAINING-goals grid; we then OFFSET every cell by the current score
(final_home = current_home + remaining_home, likewise away) so the grid is over
FINAL scorelines. Totals, correct-score and handicaps read off it are therefore
on the final score automatically.

This is a stdlib-only transform (``score_matrix`` is pure Python) of values
already stored on the prediction plus the live state — no model run, no DB.
"""
from __future__ import annotations

from ml.models.poisson import MAX_GOALS, score_matrix

REGULATION_MINUTES = 90.0

# --- Card adjustments ----------------------------------------------------------
# A sending-off changes both teams' scoring rates for the minutes REMAINING.
# Factors are (own rate ×, opponent rate ×) per red card, chosen by the carded
# team's CURRENT score situation — the model is recomputed per request, so the
# state re-derives itself whenever the score changes. Values sit at the mild end
# of published 10v11 estimates: a leading team bunkers (its goals dry up but it
# concedes barely more, keeping the hold likely), a trailing team must chase
# into counter-attacks. The football_data provider has no card feed — counts
# stay 0 there and this whole block is a no-op.
RED_FACTORS: dict[str, tuple[float, float]] = {
    "leading": (0.60, 1.05),
    "level": (0.75, 1.10),
    "trailing": (0.75, 1.15),
}
#: Reds beyond this aren't counted (7 players = abandonment; 3 is already farce).
MAX_REDS_COUNTED = 3
#: Chance an ACTIVE booking becomes a second yellow over a full 90 remaining.
#: Deliberately small — a yellow only matters as future-red risk (weak evidence,
#: by design; see the 2026-07-02 card-aware spec).
SECOND_YELLOW_HAZARD = 0.04
MAX_YELLOWS_COUNTED = 5


def _score_state(own: int, opp: int) -> str:
    if own > opp:
        return "leading"
    if own < opp:
        return "trailing"
    return "level"


def _card_factors(
    score_home: int,
    score_away: int,
    red_home: int,
    red_away: int,
    yellow_home: int,
    yellow_away: int,
    frac: float,
) -> tuple[float, float]:
    """Multipliers (home, away) on the remaining-time goal rates for the current
    card situation. Reds apply their score-state factors in full and compound;
    each active yellow blends both rates toward those factors with weight
    p = hazard × fraction-of-90-left, so booking risk decays to zero at full
    time. No cards -> (1.0, 1.0) exactly."""
    f_home = f_away = 1.0
    p = SECOND_YELLOW_HAZARD * max(0.0, min(1.0, frac))

    own_f, opp_f = RED_FACTORS[_score_state(score_home, score_away)]
    n_red = min(max(red_home, 0), MAX_REDS_COUNTED)
    n_yel = min(max(yellow_home, 0), MAX_YELLOWS_COUNTED)
    f_home *= own_f ** n_red * ((1.0 - p) + p * own_f) ** n_yel
    f_away *= opp_f ** n_red * ((1.0 - p) + p * opp_f) ** n_yel

    own_f, opp_f = RED_FACTORS[_score_state(score_away, score_home)]
    n_red = min(max(red_away, 0), MAX_REDS_COUNTED)
    n_yel = min(max(yellow_away, 0), MAX_YELLOWS_COUNTED)
    f_away *= own_f ** n_red * ((1.0 - p) + p * own_f) ** n_yel
    f_home *= opp_f ** n_red * ((1.0 - p) + p * opp_f) ** n_yel

    return f_home, f_away


def build_live_final_grid(
    current_score_home: int | None,
    current_score_away: int | None,
    lam_home: float | None,
    lam_away: float | None,
    minutes_remaining: float | None,
    rho: float = 0.0,
    regulation: float = REGULATION_MINUTES,
    max_goals: int = MAX_GOALS,
    red_home: int = 0,
    red_away: int = 0,
    yellow_home: int = 0,
    yellow_away: int = 0,
) -> list[list[float]] | None:
    """Normalized FINAL-score grid for a live match, or ``None`` on bad input.

    Steps: decay each pre-match rate by the fraction of regulation left, apply
    the card multipliers, price the REMAINING-goals grid with ``score_matrix``
    (Dixon-Coles ``rho`` baked in), then OFFSET every remaining cell [i][j] into
    the final cell [current_home + i][current_away + j] and normalize.

    The returned grid is SQUARE, ``(max(current_home, current_away) + max_goals
    + 1)`` per side — big enough that ``grid[fh][fa]`` is the probability of the
    FINAL scoreline (fh, fa) for every reachable cell, and square so the
    ``markets.py`` marginalizers (which assume a square grid) can consume it
    directly. At kickoff (0-0, full regulation left) it collapses to the
    pre-match ``score_matrix`` grid; at ``minutes_remaining <= 0`` the remaining
    grid is a point mass at 0-0, so the final grid is a point mass at the current
    score.

    ``None`` when any required input is missing or non-finite, or the grid has no
    positive mass — callers keep the frozen pre-match numbers.
    """
    if current_score_home is None or current_score_away is None:
        return None
    if lam_home is None or lam_away is None:
        return None
    if minutes_remaining is None:
        return None
    if current_score_home < 0 or current_score_away < 0:
        return None
    if regulation <= 0:
        return None

    frac = max(0.0, min(1.0, minutes_remaining / regulation))
    lam_h_rem = max(0.0, lam_home) * frac
    lam_a_rem = max(0.0, lam_away) * frac

    f_home, f_away = _card_factors(
        current_score_home, current_score_away,
        red_home, red_away, yellow_home, yellow_away, frac,
    )
    lam_h_rem *= f_home
    lam_a_rem *= f_away

    # Remaining-goals grid, with the same Dixon-Coles low-score correction the
    # pre-match engine uses (score_matrix applies tau to the 0/1 corner and
    # clamps negatives; cells outside the corner are plain independent Poisson).
    remaining = score_matrix(lam_h_rem, lam_a_rem, max_goals=max_goals, rho=rho)

    total = 0.0
    for row in remaining:
        for c in row:
            if c > 0.0:
                total += c
    if total <= 0.0:
        return None

    # Square so the (square-assuming) markets.py marginalizers can consume it.
    dim = max(current_score_home, current_score_away) + max_goals + 1
    grid = [[0.0] * dim for _ in range(dim)]
    for i, row in enumerate(remaining):
        fh = current_score_home + i
        for j, c in enumerate(row):
            cell = c if c > 0.0 else 0.0
            grid[fh][current_score_away + j] = cell / total
    return grid
