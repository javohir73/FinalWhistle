"""Tests for the market-odds anchoring math (exact-score program FR-4.3).

Covers margin removal (proportional normalization), the OU-2.5 and 1X2
inversions into a market-implied lambda_total (round-trip against a known
Poisson grid), and the blend properties the PRD mandates: w=0 identity,
w=1 sum equals the market total, and the Elo split ratio invariant.
"""
import math

import pytest

from ml.models.odds_blend import (
    blend_lambda_total,
    lambda_total_from_1x2,
    lambda_total_from_over,
    market_lambda_total,
    remove_margin,
)
from ml.models.poisson import outcome_probabilities, poisson_pmf, score_matrix


# --- margin removal ----------------------------------------------------------

def test_remove_margin_normalizes_to_one():
    probs = remove_margin((2.10, 3.30, 3.60))
    assert abs(sum(probs) - 1.0) < 1e-12


def test_remove_margin_is_proportional():
    # Proportional normalization: probability RATIOS equal raw 1/odds ratios.
    odds = (1.50, 4.20, 6.00)
    p = remove_margin(odds)
    assert p[0] / p[1] == pytest.approx((1 / odds[0]) / (1 / odds[1]))
    assert p[1] / p[2] == pytest.approx((1 / odds[1]) / (1 / odds[2]))


def test_remove_margin_two_way_market():
    # Works for the two-way OU market as well as 1X2.
    over, under = remove_margin((1.90, 1.90))
    assert over == pytest.approx(0.5)
    assert under == pytest.approx(0.5)


def test_remove_margin_rejects_nonpositive_odds():
    with pytest.raises(ValueError):
        remove_margin((2.0, 0.0, 3.0))


# --- OU-2.5 inversion --------------------------------------------------------

def _p_over_25(lam_total: float) -> float:
    """P(total goals >= 3) under Poisson(lam_total)."""
    return 1.0 - sum(poisson_pmf(k, lam_total) for k in range(3))


def test_lambda_total_from_over_round_trips():
    for lam in (1.4, 2.2, 2.7, 3.5):
        p = _p_over_25(lam)
        assert lambda_total_from_over(p) == pytest.approx(lam, abs=1e-6)


def test_lambda_total_from_over_is_monotone():
    assert lambda_total_from_over(0.6) > lambda_total_from_over(0.4)


def test_lambda_total_from_over_rejects_degenerate_probs():
    for bad in (0.0, 1.0, -0.1, 1.1):
        with pytest.raises(ValueError):
            lambda_total_from_over(bad)


# --- 1X2 inversion (sanity channel) ------------------------------------------

def test_lambda_total_from_1x2_round_trips():
    # Build the exact W/D/L triple of a known lambda pair, invert, and expect
    # the total back (independent Poisson, no Dixon-Coles in the inversion).
    for lam_h, lam_a in ((1.5, 0.9), (1.1, 1.1), (2.0, 0.6)):
        wdl = outcome_probabilities(score_matrix(lam_h, lam_a))
        total = lambda_total_from_1x2(*wdl)
        assert total == pytest.approx(lam_h + lam_a, abs=0.02)


# --- market total selection ---------------------------------------------------

def test_market_lambda_total_prefers_ou_market():
    # OU prices implying a KNOWN total; 1X2 prices implying a different one.
    lam = 2.9
    p_over = _p_over_25(lam)
    over_odds, under_odds = 1.0 / p_over, 1.0 / (1.0 - p_over)
    wdl = outcome_probabilities(score_matrix(0.8, 0.8))  # total 1.6, far away
    total = market_lambda_total(
        odds_over25=over_odds, odds_under25=under_odds,
        odds_home=1 / wdl[0], odds_draw=1 / wdl[1], odds_away=1 / wdl[2],
    )
    assert total == pytest.approx(lam, abs=1e-6)


def test_market_lambda_total_falls_back_to_1x2():
    wdl = outcome_probabilities(score_matrix(1.5, 0.9))
    total = market_lambda_total(
        odds_home=1 / wdl[0], odds_draw=1 / wdl[1], odds_away=1 / wdl[2],
    )
    assert total == pytest.approx(2.4, abs=0.02)


def test_market_lambda_total_none_without_any_market():
    assert market_lambda_total() is None
    assert market_lambda_total(odds_over25=1.9) is None          # half an OU pair
    assert market_lambda_total(odds_home=2.0, odds_draw=3.3) is None  # partial 1X2


# --- blend properties (FR-4.3) -------------------------------------------------

def test_blend_w_zero_is_identity():
    assert blend_lambda_total(1.7, 1.1, market_total=2.2, w_odds=0.0) == (1.7, 1.1)


def test_blend_w_one_matches_market_sum():
    lam_h, lam_a = blend_lambda_total(1.7, 1.1, market_total=2.2, w_odds=1.0)
    assert lam_h + lam_a == pytest.approx(2.2)


def test_blend_preserves_elo_split_ratio():
    for w in (0.15, 0.5, 0.85):
        lam_h, lam_a = blend_lambda_total(1.7, 1.1, market_total=3.4, w_odds=w)
        assert lam_h / lam_a == pytest.approx(1.7 / 1.1)


def test_blend_sum_is_convex_combination():
    lam_h, lam_a = blend_lambda_total(1.7, 1.1, market_total=3.4, w_odds=0.25)
    assert lam_h + lam_a == pytest.approx(0.75 * 2.8 + 0.25 * 3.4)


def test_blend_ignores_missing_or_degenerate_market():
    assert blend_lambda_total(1.7, 1.1, market_total=None, w_odds=0.5) == (1.7, 1.1)
    assert blend_lambda_total(1.7, 1.1, market_total=0.0, w_odds=0.5) == (1.7, 1.1)
    assert blend_lambda_total(1.7, 1.1, market_total=-1.0, w_odds=0.5) == (1.7, 1.1)


def test_blend_ignores_nonsense_math_gracefully():
    # A zero engine total cannot be rescaled (split undefined) -> unchanged.
    assert blend_lambda_total(0.0, 0.0, market_total=2.5, w_odds=0.5) == (0.0, 0.0)
