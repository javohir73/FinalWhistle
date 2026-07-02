"""Market-odds anchoring math for the shadow model (exact-score program FR-4.3).

Bookmaker totals capture information Elo cannot see (dead rubbers, rotation,
weather), and market consensus is the best-evidenced upgrade for goal
expectations in the literature. This module turns stored prices into a
market-implied expected-goals TOTAL and nudges the Poisson engine's lambda
pair toward it — moving only the SUM while keeping the Elo-based SPLIT, so
the market informs "how many goals" and Elo keeps owning "who scores them".

Method (documented per FR-4.3):
  * Margin removal — proportional normalization: raw implied probabilities
    1/odds are divided by their sum (the bookmaker overround), for both the
    three-way 1X2 and the two-way over/under market.
  * OU-2.5 inversion (primary) — with total goals N ~ Poisson(lambda_T),
    P(over 2.5) = P(N >= 3) = 1 - e^-λ(1 + λ + λ²/2) is strictly increasing
    in λ, so a bisection root-find recovers lambda_T from the market's
    margin-free over probability.
  * 1X2 inversion (sanity/fallback) — a two-parameter root-find on the
    independent-Poisson grid: the home share of the total is matched to the
    market's home/away skew (inner bisection), then the total is matched to
    the market's draw probability (outer bisection; draws thin out as totals
    rise). Used when no OU-2.5 market is stored, and as a cross-check.

All functions are pure; the Odds table lookup lives in the pipeline.
"""
from __future__ import annotations

from collections.abc import Sequence

from ml.models.poisson import outcome_probabilities, poisson_pmf, score_matrix

#: lambda_total search bracket — generous for international football (a market
#: implying <0.1 or >12 expected goals is noise, not information).
_LAM_LO, _LAM_HI = 0.05, 12.0
_BISECT_STEPS = 60  # halves the bracket to ~3e-18 — far below any market tick


def remove_margin(prices: Sequence[float]) -> tuple[float, ...]:
    """Decimal odds -> margin-free implied probabilities (sum to 1).

    Proportional normalization: each raw 1/odds is divided by the market's
    total booked probability (the overround). Works for any n-way market
    (1X2, over/under). Raises on non-positive prices — those are data errors,
    not a margin.
    """
    if not prices or min(prices) <= 0:
        raise ValueError("decimal odds must be positive")
    raw = [1.0 / p for p in prices]
    total = sum(raw)
    return tuple(r / total for r in raw)


def _p_over(lam_total: float, threshold: int) -> float:
    """P(total goals >= threshold) under Poisson(lam_total)."""
    return 1.0 - sum(poisson_pmf(k, lam_total) for k in range(threshold))


def lambda_total_from_over(p_over: float, line: float = 2.5) -> float:
    """Invert a margin-free P(over `line` goals) into the Poisson total.

    The survival function P(N >= ceil(line)) is strictly increasing in the
    mean, so bisection on the bracket converges unconditionally. p_over must
    be strictly inside (0, 1) — a market at 0 or 1 carries no invertible
    information.
    """
    if not 0.0 < p_over < 1.0:
        raise ValueError("over-probability must be strictly between 0 and 1")
    threshold = int(line) + 1  # over 2.5 goals <=> at least 3
    lo, hi = _LAM_LO, _LAM_HI
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2.0
        if _p_over(mid, threshold) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _grid_wdl(lam_total: float, home_share: float) -> tuple[float, float, float]:
    """W/D/L triple of an independent-Poisson grid at (total, home share)."""
    lam_h = lam_total * home_share
    lam_a = lam_total * (1.0 - home_share)
    return outcome_probabilities(score_matrix(lam_h, lam_a))


def _share_for_skew(lam_total: float, skew: float) -> float:
    """The home share reproducing the market's home-away probability skew at a
    fixed total (P(home) - P(away) is increasing in the share -> bisection)."""
    lo, hi = 0.01, 0.99
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2.0
        p_h, _, p_a = _grid_wdl(lam_total, mid)
        if (p_h - p_a) < skew:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def lambda_total_from_1x2(p_home: float, p_draw: float, p_away: float) -> float:
    """Invert a margin-free 1X2 triple into the Poisson total (sanity channel).

    For each candidate total, the home share is first solved to match the
    market's home-away skew; the draw probability of that grid then decreases
    monotonically as the total grows (more goals = fewer level scorelines),
    so an outer bisection on the draw probability pins the total.
    """
    skew = p_home - p_away
    lo, hi = _LAM_LO, _LAM_HI
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2.0
        _, grid_draw, _ = _grid_wdl(mid, _share_for_skew(mid, skew))
        if grid_draw > p_draw:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def market_lambda_total(
    odds_over25: float | None = None,
    odds_under25: float | None = None,
    odds_home: float | None = None,
    odds_draw: float | None = None,
    odds_away: float | None = None,
) -> float | None:
    """Market-implied expected-goals total from stored prices, or None.

    The OU-2.5 market is the primary source (it prices the total directly);
    the 1X2 triple is the fallback when no complete OU pair is stored.
    Malformed prices yield None rather than raising — a broken odds row must
    degrade to "no market", never break prediction generation (FR-4.2).
    """
    if odds_over25 is not None and odds_under25 is not None:
        try:
            p_over, _ = remove_margin((odds_over25, odds_under25))
            return lambda_total_from_over(p_over)
        except ValueError:
            return None
    if odds_home is not None and odds_draw is not None and odds_away is not None:
        try:
            return lambda_total_from_1x2(*remove_margin((odds_home, odds_draw, odds_away)))
        except ValueError:
            return None
    return None


def blend_lambda_total(
    lam_home: float, lam_away: float, market_total: float | None, w_odds: float
) -> tuple[float, float]:
    """Move the lambda SUM toward the market total; keep the Elo-based split.

    blended_total = (1 - w_odds) * (lam_home + lam_away) + w_odds * market_total,
    then both lambdas are scaled by the same factor so lam_home/lam_away is
    unchanged. w_odds=0 (the shipped default, FR-4.8) or a missing/degenerate
    market returns the pair untouched — the safe identity.
    """
    total = lam_home + lam_away
    if w_odds <= 0.0 or market_total is None or market_total <= 0.0 or total <= 0.0:
        return lam_home, lam_away
    blended = (1.0 - w_odds) * total + w_odds * market_total
    scale = blended / total
    return lam_home * scale, lam_away * scale
