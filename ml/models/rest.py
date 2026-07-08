"""Rest-days signal: schedule (in)equality as a bounded lambda offset.

Teams on short rest underperform; the marginal value of a rest day flattens
past a week. The signal is the DIFFERENTIAL — equal rest cancels exactly,
whatever the absolute numbers — mapped to a symmetric pair of log-lambda
offsets and clamped so a scheduling anomaly (postponement, data glitch) can
never wreck a forecast. Pure functions, no I/O; the caller supplies each
team's days since their last finished match.

Ships as a param-gated no-op (model_params.json "rest_days": null) with a
shadow twin graded like every other signal; DEFAULT_REST is the twin's
configuration and the starting point for a future fit.
"""
from __future__ import annotations

# Marginal rest only matters inside this window: below 2 days everyone is
# wrecked, past 8 everyone is fresh. Values outside are clipped in.
REST_WINDOW = (2.0, 8.0)

#: Twin configuration and promotion default: ~2% expected-goals swing per net
#: rest day, capped at ~8% total — deliberately small, like every prior.
DEFAULT_REST = {"coef": 0.02, "cap": 0.08}


def rest_offsets(
    rest_home_days: float | None,
    rest_away_days: float | None,
    coef: float,
    cap: float,
) -> tuple[float, float] | None:
    """Symmetric (off_home, off_away) log-lambda pair from a rest differential,
    or None when either side has no prior match (tournament openers). The full
    capped effect is split half onto each side so the TOTAL goals level is
    preserved — the signal moves the balance, not the scoreline tempo."""
    if rest_home_days is None or rest_away_days is None:
        return None
    lo, hi = REST_WINDOW
    clip = lambda d: max(lo, min(hi, d))  # noqa: E731
    x = coef * (clip(rest_home_days) - clip(rest_away_days))
    x = max(-cap, min(cap, x))
    return x / 2.0, -x / 2.0
