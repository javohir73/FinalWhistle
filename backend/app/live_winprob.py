"""In-play (live) win probability — how W/D/L shifts with the score and time left.

This lives in the app (serving) layer ON PURPOSE. Unlike the pre-match engine in
ml/, the live probability must be recomputed per request from the CURRENT score
and minute, so it cannot be precomputed and frozen. It is a small, deterministic
transform of values already stored on the prediction (the pre-match
expected-goals rates) plus the live match state.

The pre-match model gives each team an expected-goals rate over 90 minutes
(lambda_home, lambda_away). Once a match is under way, only goals in the time
REMAINING can change the result. So we model each team's remaining goals as
Poisson with mean scaled to the minutes left, add them to the current score, and
read off the live W/D/L. As the clock runs down with the score level, the draw
probability climbs and the win probabilities fall — collapsing to the actual
result at full time. Standard, explainable in-play model (no betting data).

The live scoreline grid itself is built by the shared model-layer helper
``ml.models.live_grid.build_live_final_grid`` (the SAME grid the live derived
markets in ``ml.models.live_markets`` marginalize), so the bar and those markets
agree by construction. This bar just reads the W/D/L off that grid. The card
constants and ``_card_factors`` are re-exported from ``live_grid`` for backward
compatibility (older callers/tests import them from here).

Probability triples are (home, draw, away), matching the rest of the codebase.
"""
from __future__ import annotations

from ml.models.live_grid import (  # noqa: F401  (re-exported for compatibility)
    MAX_REDS_COUNTED,
    MAX_YELLOWS_COUNTED,
    RED_FACTORS,
    SECOND_YELLOW_HAZARD,
    _card_factors,
    _score_state,
    build_live_final_grid,
)
from ml.models.poisson import outcome_probabilities

Probs = tuple[float, float, float]

REGULATION_MINUTES = 90.0
_HALF_TIME = "half_time"
#: Extra time / shootouts are knockout-only (group matches never reach them) and
#: aren't modelled — callers fall back to the pre-match probabilities.
_UNMODELLED_PERIODS = ("extra_time", "penalty_shootout")


def regulation_remaining(
    minute: int | None, period: str | None, regulation: float = REGULATION_MINUTES
) -> float | None:
    """Best estimate of regulation minutes remaining, or None if not estimable.

    Uses the live clock when present; at half time falls back to a clean 45.
    Extra time and shootouts return None. A match with no clock and no usable
    period also returns None so the caller keeps the pre-match bar.
    """
    if period in _UNMODELLED_PERIODS:
        return None
    if period == _HALF_TIME:
        return regulation / 2.0
    if minute is not None:
        return max(0.0, regulation - float(minute))
    return None


def live_win_probabilities(
    score_home: int,
    score_away: int,
    lam_home: float,
    lam_away: float,
    minutes_remaining: float,
    rho: float = 0.0,
    regulation: float = REGULATION_MINUTES,
    max_extra_goals: int = 10,
    red_home: int = 0,
    red_away: int = 0,
    yellow_home: int = 0,
    yellow_away: int = 0,
) -> Probs:
    """Live W/D/L given the current score, the pre-match 90-minute goal rates,
    and the minutes left. Remaining goals per team ~ Poisson(rate * left/90).

    `rho` applies the same Dixon-Coles low-score correction the pre-match engine
    uses, on the REMAINING-goals grid. At kickoff (0-0, full time left) this makes
    the live triple identical to the pre-match prediction — no twitch.

    Card counts scale the remaining-time rates — see `_card_factors`.

    The W/D/L is read straight off the shared live final-score grid
    (`ml.models.live_grid.build_live_final_grid`) via `outcome_probabilities`, so
    it is identical (bit-for-bit) to what the live derived markets marginalize.
    """
    grid = build_live_final_grid(
        score_home, score_away, lam_home, lam_away, minutes_remaining,
        rho=rho, regulation=regulation, max_goals=max_extra_goals,
        red_home=red_home, red_away=red_away,
        yellow_home=yellow_home, yellow_away=yellow_away,
    )
    if grid is None:  # numerically impossible, but never divide by zero
        if score_home > score_away:
            return (1.0, 0.0, 0.0)
        if score_home < score_away:
            return (0.0, 0.0, 1.0)
        return (0.0, 1.0, 0.0)
    return outcome_probabilities(grid)


def live_probabilities_for_match(
    status: str | None,
    score_home: int | None,
    score_away: int | None,
    minute: int | None,
    period: str | None,
    lam_home: float | None,
    lam_away: float | None,
    rho: float | None = 0.0,
    red_home: int = 0,
    red_away: int = 0,
    yellow_home: int = 0,
    yellow_away: int = 0,
) -> Probs | None:
    """Live W/D/L for a match row, or None when it can't/shouldn't be computed.

    Returns None unless the match is in play with a known score, a modellable
    clock, and stored pre-match goal rates — in which case the caller keeps the
    frozen pre-match probabilities.

    Card counts scale the remaining-time rates — see `_card_factors`.
    """
    if status != "in_play":
        return None
    if score_home is None or score_away is None:
        return None
    if lam_home is None or lam_away is None:
        return None
    remaining = regulation_remaining(minute, period)
    if remaining is None:
        return None
    return live_win_probabilities(
        score_home, score_away, lam_home, lam_away, remaining, rho=rho or 0.0,
        red_home=red_home, red_away=red_away,
        yellow_home=yellow_home, yellow_away=yellow_away,
    )
