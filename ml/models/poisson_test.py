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


def test_predicted_score_shows_draw_only_for_even_games():
    # Strong home favorite -> a home-win scoreline.
    assert _result(predict_match(2100, 1500)) == "home"

    # Genuine coin-flip (equal Elo) -> a draw scoreline (1-1), even though the
    # draw is never the single highest W/D/L bucket in football.
    even = predict_match(1700, 1700, home_adv=0)
    assert _result(even) == "draw"
    assert even.score_home == even.score_away
    assert even.prob_draw < max(even.prob_home_win, even.prob_away_win)

    # Moderate edge: 1-1 may be the single most-likely exact score, but one side
    # is clearly ahead in the bar, so the draw headline is SUPPRESSED (avoids the
    # odd "one side ~50% but predicted 1-1" case). Falls back to the favored score.
    edge = predict_match(1750, 1650, home_adv=0)
    assert abs(edge.prob_home_win - edge.prob_away_win) > 0.08
    assert _result(edge) == "home"


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


def test_dixon_coles_increases_draw_probability():
    """Negative rho lifts the low-score draw mass (1-0/0-1/1-1/0-0 region)."""
    even_lams = (1.3, 1.3)
    base_draw = outcome_probabilities(score_matrix(*even_lams, rho=0.0))[1]
    dc_draw = outcome_probabilities(score_matrix(*even_lams, rho=-0.12))[1]
    assert dc_draw > base_draw
    # Still a valid normalized distribution.
    p = outcome_probabilities(score_matrix(*even_lams, rho=-0.12))
    assert abs(sum(p) - 1.0) < 1e-9


def test_temperature_softens_confident_predictions():
    """T > 1 pulls the dominant probability toward the others (less confident)."""
    raw = predict_match(2100, 1500, temperature=1.0)
    soft = predict_match(2100, 1500, temperature=1.4)
    assert soft.prob_home_win < raw.prob_home_win
    # Temperature is monotone, so the predicted winner/scoreline are unchanged.
    assert (soft.score_home > soft.score_away) == (raw.score_home > raw.score_away)
    assert abs(soft.prob_home_win + soft.prob_draw + soft.prob_away_win - 1.0) < 1e-9


def test_predict_match_calibrator_lifts_draw():
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 1.0, 0.0]}
    base = predict_match(1700, 1700, home_adv=0)
    cal = predict_match(1700, 1700, home_adv=0, calibrator=blob)
    assert cal.prob_draw > base.prob_draw
    assert abs(cal.prob_home_win + cal.prob_draw + cal.prob_away_win - 1.0) < 1e-9


def test_predict_match_temperature_path_equals_apply_temperature():
    # With no calibrator, the W/D/L triple must equal scalar temperature applied
    # to the RAW (uncalibrated) outcome probabilities — proving the temperature
    # fallback routes through calibrate() correctly (not a self-comparison).
    from ml.evaluation.calibration import apply_temperature

    lam_h, lam_a = expected_goals_from_elo(2100, 1500, 0.0)
    raw = outcome_probabilities(score_matrix(lam_h, lam_a))
    expected = apply_temperature(raw, 1.4)
    pred = predict_match(2100, 1500, home_adv=0, temperature=1.4)
    assert abs(pred.prob_home_win - expected[0]) < 1e-12
    assert abs(pred.prob_draw - expected[1]) < 1e-12
    assert abs(pred.prob_away_win - expected[2]) < 1e-12
