"""Per-match metric math, pinned with the tournament's first two real results."""
import math

import pytest

from ml.evaluation.match_metrics import (
    AWAY,
    DRAW,
    HOME,
    MatchEvaluation,
    brier,
    evaluate_match,
    exact_score_correct,
    goal_error,
    log_loss,
    outcome_index,
    predicted_index,
    winner_correct,
)

# Matchday 1 fixtures (production data, 2026-06-12) — the marketing claims rest
# on exactly these numbers, so they are pinned here.
MEXICO_PROBS = (0.8104, 0.1258, 0.0638)  # Mexico 2-0 South Africa, predicted 2-0
KOREA_PROBS = (0.4623, 0.2512, 0.2865)  # South Korea 2-1 Czechia, predicted 1-0


def test_outcome_index():
    assert outcome_index(2, 0) == HOME
    assert outcome_index(1, 1) == DRAW
    assert outcome_index(0, 3) == AWAY


def test_mexico_exact_score_call():
    ev = evaluate_match(MEXICO_PROBS, 2, 0, 2, 0)
    assert ev.winner_correct is True
    assert ev.exact_score_correct is True
    assert ev.goal_error == 0
    assert ev.brier == pytest.approx(
        (1 - 0.8104) ** 2 + 0.1258**2 + 0.0638**2, abs=1e-9
    )
    assert ev.log_loss == pytest.approx(-math.log(0.8104), abs=1e-9)
    assert ev.outcome_idx == HOME
    assert ev.predicted_idx == HOME


def test_korea_winner_only_call():
    ev = evaluate_match(KOREA_PROBS, 1, 0, 2, 1)
    assert ev.winner_correct is True  # 46% lean, correct side
    assert ev.exact_score_correct is False  # 1-0 predicted, 2-1 actual
    assert ev.goal_error == 2  # |1-2| + |0-1|
    assert ev.log_loss == pytest.approx(-math.log(0.4623), abs=1e-9)


def test_upset_is_a_miss_not_an_error():
    # Favorite loses: winner wrong, metrics large but finite and well-defined.
    ev = evaluate_match(MEXICO_PROBS, 2, 0, 0, 1)
    assert ev.winner_correct is False
    assert ev.exact_score_correct is False
    assert ev.outcome_idx == AWAY
    assert 0 <= ev.brier <= 2.0
    assert ev.log_loss == pytest.approx(-math.log(0.0638), abs=1e-9)


def test_draw_outcome_scoring():
    probs = (0.30, 0.45, 0.25)
    ev = evaluate_match(probs, 1, 1, 0, 0)
    assert ev.winner_correct is True  # draw was the pick and the result
    assert ev.exact_score_correct is False  # 1-1 vs 0-0
    assert ev.goal_error == 2


def test_brier_bounds():
    assert brier((1.0, 0.0, 0.0), HOME) == 0.0
    assert brier((1.0, 0.0, 0.0), AWAY) == pytest.approx(2.0)


def test_log_loss_clamped_for_zero_probability():
    # A zero-probability outcome must not blow up to infinity.
    assert math.isfinite(log_loss((1.0, 0.0, 0.0), AWAY))


def test_predicted_index_tie_breaks_deterministically():
    assert predicted_index((0.4, 0.4, 0.2)) == HOME  # first max wins


def test_helpers_match_dataclass():
    assert winner_correct(KOREA_PROBS, 2, 1) is True
    assert exact_score_correct(1, 0, 2, 1) is False
    assert goal_error(1, 0, 2, 1) == 2
    assert isinstance(evaluate_match(KOREA_PROBS, 1, 0, 2, 1), MatchEvaluation)


def test_exact_score_uses_explicit_basis_when_given():
    """FR-2.2: the exact-score comparison can run on the 90-minute basis while
    winner/Brier keep the final-result basis (after-ET convention)."""
    from ml.evaluation.match_metrics import evaluate_match

    ev = evaluate_match(
        (0.2, 0.5, 0.3), 1, 1, 2, 1,  # final 2-1 (home win after ET)
        exact_home_goals=1, exact_away_goals=1,  # 90' score was 1-1
    )
    assert ev.exact_score_correct is True  # scored on the 90' basis
    assert ev.outcome_idx == 0  # winner basis unchanged: home won the tie
    assert ev.goal_error == 0  # goal distance follows the exact basis


def test_exact_basis_defaults_to_final_score():
    from ml.evaluation.match_metrics import evaluate_match

    ev = evaluate_match((0.2, 0.5, 0.3), 1, 1, 2, 1)
    assert ev.exact_score_correct is False
    assert ev.goal_error == 1
