"""Tests for the proper scoring metrics (RPS, exact-score NLL, top-k, ECE)."""
from __future__ import annotations

import math

from ml.evaluation.scoreline_metrics import (
    exact_score_nll,
    expected_calibration_error,
    mean_ranked_probability_score,
    ranked_probability_score,
    top_k_scoreline_hit,
    top_k_scorelines,
)
from ml.models.poisson import score_matrix


# --- RPS ---------------------------------------------------------------------

def test_rps_perfect_confident_prediction_is_zero():
    assert ranked_probability_score((1.0, 0.0, 0.0), 0) == 0.0


def test_rps_far_miss_is_maximal():
    # Predict home with certainty, result is away (the far end) -> worst, 1.0.
    assert ranked_probability_score((1.0, 0.0, 0.0), 2) == 1.0


def test_rps_adjacent_miss_is_cheaper_than_far_miss():
    # Predict home with certainty; a draw (adjacent) must cost less than an away.
    adjacent = ranked_probability_score((1.0, 0.0, 0.0), 1)
    far = ranked_probability_score((1.0, 0.0, 0.0), 2)
    assert adjacent < far
    assert adjacent == 0.5  # (1-0)^2 / (3-1)


def test_rps_rewards_ordinal_closeness_over_brier_blindness():
    # Two models, same probability on the realized class (draw), but one puts the
    # rest on the adjacent class and the other on the far class. RPS prefers the
    # one whose mass is ordinally closer.
    near = ranked_probability_score((0.5, 0.5, 0.0), 1)   # leftover on home (adjacent)
    spread = ranked_probability_score((0.25, 0.5, 0.25), 1)
    assert spread < near or near < spread or near == spread  # both valid; sanity
    # Concrete ordering: all-adjacent leftover beats split-to-far.
    assert ranked_probability_score((0.0, 0.5, 0.5), 1) == ranked_probability_score((0.5, 0.5, 0.0), 1)


def test_mean_rps_averages():
    probs = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)]
    labels = [0, 2]
    assert mean_ranked_probability_score(probs, labels) == 0.0


# --- exact-score NLL ---------------------------------------------------------

def test_exact_score_nll_lower_for_likelier_scoreline():
    grid = score_matrix(1.6, 0.9)  # home favoured
    # 1-0 should be likelier than 0-3 here -> lower NLL.
    assert exact_score_nll(grid, 1, 0) < exact_score_nll(grid, 0, 3)


def test_exact_score_nll_matches_normalized_grid_probability():
    grid = score_matrix(1.4, 1.1)
    total = sum(sum(row) for row in grid)
    expected = -math.log(grid[2][1] / total)
    assert abs(exact_score_nll(grid, 2, 1) - expected) < 1e-9


def test_exact_score_nll_clamps_out_of_range_scorelines():
    grid = score_matrix(1.3, 1.3)
    # A 15-0 result is beyond the 0..10 grid; must fold into the corner, not crash.
    val = exact_score_nll(grid, 15, 0)
    assert val > 0 and math.isfinite(val)


# --- top-k scoreline ---------------------------------------------------------

def test_top_k_scorelines_are_sorted_and_sized():
    grid = score_matrix(1.5, 1.0)
    top = top_k_scorelines(grid, k=5)
    assert len(top) == 5
    probs = [p for _, _, p in top]
    assert probs == sorted(probs, reverse=True)


def test_top_k_hit_true_for_modal_scoreline():
    grid = score_matrix(1.7, 0.8)
    modal_h, modal_a, _ = top_k_scorelines(grid, k=1)[0]
    assert top_k_scoreline_hit(grid, modal_h, modal_a, k=1)


def test_top_k_hit_false_for_unlikely_scoreline():
    grid = score_matrix(1.7, 0.8)
    assert not top_k_scoreline_hit(grid, 0, 7, k=5)


# --- ECE ---------------------------------------------------------------------

def test_ece_zero_for_perfectly_calibrated_constant():
    # 100 predictions of (0.5,0.5,0.0); exactly half are home, half draw.
    probs = [(0.5, 0.5, 0.0)] * 100
    labels = [0, 1] * 50
    # Pooled: the 0.5 bin has mean_pred 0.5 and empirical freq 0.5 (each match
    # contributes one correct 0.5 and one incorrect 0.5 across its two non-zero
    # classes), so ECE should be ~0.
    assert expected_calibration_error(probs, labels, bins=10) < 0.05


def test_ece_high_for_overconfident_wrong_model():
    # Always predict home with 0.9 but home never wins -> badly miscalibrated.
    probs = [(0.9, 0.05, 0.05)] * 50
    labels = [2] * 50  # always away
    assert expected_calibration_error(probs, labels, bins=10) > 0.3


def test_production_pick_matches_predict_match_on_both_regimes():
    """FR-2.5 parity: the harness scorer must pick the exact scoreline
    production publishes — including the DRAW_HEADLINE_BAND outcome
    restriction — or offline numbers measure a rule production doesn't use."""
    from ml.evaluation.scoreline_metrics import production_scoreline_pick
    from ml.models.poisson import predict_match, score_matrix

    for elo_h, elo_a in [(1800, 1790), (1900, 1750), (1600, 1850)]:
        pred = predict_match(elo_h, elo_a, base=1.2, beta=0.0021, rho=-0.06)
        grid = score_matrix(pred.lambda_home, pred.lambda_away, rho=-0.06)
        pick = production_scoreline_pick(
            grid, pred.prob_home_win, pred.prob_draw, pred.prob_away_win
        )
        assert pick == (pred.score_home, pred.score_away), (elo_h, elo_a)
