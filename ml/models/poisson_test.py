"""Tests for the Poisson goals model (task 3.3)."""
from ml.models.poisson import (
    expected_goals_from_elo,
    most_likely_score,
    outcome_probabilities,
    poisson_pmf,
    predict_match,
    score_matrix,
)


def test_poisson_pmf_sums_to_one():
    total = sum(poisson_pmf(k, 1.4) for k in range(40))
    assert abs(total - 1.0) < 1e-9


def test_outcome_probabilities_sum_to_one():
    matrix = score_matrix(1.5, 1.1)
    p_home, p_draw, p_away = outcome_probabilities(matrix)
    assert abs(p_home + p_draw + p_away - 1.0) < 1e-9


def test_equal_teams_symmetric():
    pred = predict_match(1800, 1800)
    assert abs(pred.prob_home_win - pred.prob_away_win) < 1e-9


def _result(pred):
    if pred.score_home > pred.score_away:
        return "home"
    if pred.score_home < pred.score_away:
        return "away"
    return "draw"


def test_scoreline_consistent_with_predicted_winner():
    # Strong home favorite: argmax W/D/L is a home win and the scoreline agrees.
    pred = predict_match(2100, 1500)
    assert pred.prob_home_win == max(pred.prob_home_win, pred.prob_draw, pred.prob_away_win)
    assert _result(pred) == "home"
    # When a draw is the most likely outcome, the scoreline is a draw.
    even = predict_match(1700, 1700, home_adv=0)
    if even.prob_draw >= max(even.prob_home_win, even.prob_away_win):
        assert _result(even) == "draw"


def test_stronger_team_favored():
    pred = predict_match(2100, 1600)
    assert pred.prob_home_win > pred.prob_away_win
    assert pred.prob_home_win > pred.prob_draw
    assert pred.lambda_home > pred.lambda_away


def test_home_advantage_increases_home_win_prob():
    neutral = predict_match(1800, 1800, home_adv=0)
    hosted = predict_match(1800, 1800, home_adv=60)
    assert hosted.prob_home_win > neutral.prob_home_win


def test_expected_goals_direction():
    lam_h, lam_a = expected_goals_from_elo(2000, 1700)
    assert lam_h > lam_a


def test_most_likely_score_is_a_valid_cell():
    matrix = score_matrix(1.7, 0.9)
    h, a, p = most_likely_score(matrix)
    assert 0 <= h and 0 <= a
    assert 0 < p <= 1
