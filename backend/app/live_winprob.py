"""In-play (live) win probability — how W/D/L shifts with the score and time left.

This lives in the app (serving) layer ON PURPOSE. Unlike the pre-match engine in
ml/, the live probability must be recomputed per request from the CURRENT score
and minute, so it cannot be precomputed and frozen. It is a small, deterministic,
stdlib-only transform of values already stored on the prediction (the pre-match
expected-goals rates) plus the live match state — it never runs the ml/ model, so
the read path stays independent of ml/ (PRD §7).

The pre-match model gives each team an expected-goals rate over 90 minutes
(lambda_home, lambda_away). Once a match is under way, only goals in the time
REMAINING can change the result. So we model each team's remaining goals as
Poisson with mean scaled to the minutes left, add them to the current score, and
read off the live W/D/L. As the clock runs down with the score level, the draw
probability climbs and the win probabilities fall — collapsing to the actual
result at full time. Standard, explainable in-play model (no betting data).

Probability triples are (home, draw, away), matching the rest of the codebase.
"""
from __future__ import annotations

import math

Probs = tuple[float, float, float]

REGULATION_MINUTES = 90.0
_HALF_TIME = "half_time"
#: Extra time / shootouts are knockout-only (group matches never reach them) and
#: aren't modelled — callers fall back to the pre-match probabilities.
_UNMODELLED_PERIODS = ("extra_time", "penalty_shootout")


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _dixon_coles_tau(h: int, a: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles low-score dependence factor for the four cells independent
    Poisson misprices. rho = 0 recovers plain Poisson. Mirrors the pre-match
    engine (ml.models.poisson) so the live bar reduces to the pre-match bar at
    kickoff instead of twitching."""
    if h == 0 and a == 0:
        return 1.0 - lam * mu * rho
    if h == 0 and a == 1:
        return 1.0 + lam * rho
    if h == 1 and a == 0:
        return 1.0 + mu * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


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
) -> Probs:
    """Live W/D/L given the current score, the pre-match 90-minute goal rates,
    and the minutes left. Remaining goals per team ~ Poisson(rate * left/90).

    `rho` applies the same Dixon-Coles low-score correction the pre-match engine
    uses, on the REMAINING-goals grid. At kickoff (0-0, full time left) this makes
    the live triple identical to the pre-match prediction — no twitch.
    """
    frac = max(0.0, min(1.0, minutes_remaining / regulation)) if regulation > 0 else 0.0
    lam_h_rem = max(0.0, lam_home) * frac
    lam_a_rem = max(0.0, lam_away) * frac

    p_home = p_draw = p_away = 0.0
    home_pmf = [_poisson_pmf(i, lam_h_rem) for i in range(max_extra_goals + 1)]
    away_pmf = [_poisson_pmf(j, lam_a_rem) for j in range(max_extra_goals + 1)]
    for i, pi in enumerate(home_pmf):
        fh = score_home + i
        for j, pj in enumerate(away_pmf):
            p = pi * pj
            if rho:
                p *= _dixon_coles_tau(i, j, lam_h_rem, lam_a_rem, rho)
            fa = score_away + j
            if fh > fa:
                p_home += p
            elif fh < fa:
                p_away += p
            else:
                p_draw += p

    total = p_home + p_draw + p_away
    if total <= 0:  # numerically impossible, but never divide by zero
        if score_home > score_away:
            return (1.0, 0.0, 0.0)
        if score_home < score_away:
            return (0.0, 0.0, 1.0)
        return (0.0, 1.0, 0.0)
    return (p_home / total, p_draw / total, p_away / total)


def live_probabilities_for_match(
    status: str | None,
    score_home: int | None,
    score_away: int | None,
    minute: int | None,
    period: str | None,
    lam_home: float | None,
    lam_away: float | None,
    rho: float | None = 0.0,
) -> Probs | None:
    """Live W/D/L for a match row, or None when it can't/shouldn't be computed.

    Returns None unless the match is in play with a known score, a modellable
    clock, and stored pre-match goal rates — in which case the caller keeps the
    frozen pre-match probabilities.
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
        score_home, score_away, lam_home, lam_away, remaining, rho=rho or 0.0
    )
