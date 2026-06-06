"""Tests for the Elo model (task 3.1)."""
from ml.ratings.elo import (
    MatchInput,
    expected_score,
    goal_diff_multiplier,
    k_factor,
    run_elo,
    update_ratings,
)


def test_expected_score_symmetry_at_equal_ratings():
    assert abs(expected_score(1500, 1500, 0) - 0.5) < 1e-9
    # home advantage tilts the expectation above 0.5
    assert expected_score(1500, 1500, 60) > 0.5


def test_k_factor_classification():
    assert k_factor("FIFA World Cup") == 60.0
    assert k_factor("FIFA World Cup qualification") == 40.0
    assert k_factor("UEFA Euro") == 50.0
    assert k_factor("Friendly") == 20.0
    assert k_factor("Some Random Cup") == 30.0


def test_goal_diff_multiplier_increases_with_margin():
    assert goal_diff_multiplier(1) == 1.0
    assert goal_diff_multiplier(2) == 1.5
    assert goal_diff_multiplier(4) > goal_diff_multiplier(2)


def test_update_is_zero_sum_and_directionally_correct():
    new_h, new_a = update_ratings(1500, 1500, 2, 0, competition="Friendly", is_neutral=True)
    assert new_h > 1500  # winner gains
    assert new_a < 1500  # loser loses
    assert abs((new_h - 1500) + (new_a - 1500)) < 1e-9  # zero-sum


def test_bigger_win_moves_rating_more():
    small = update_ratings(1500, 1500, 1, 0, competition="Friendly", is_neutral=True)[0]
    big = update_ratings(1500, 1500, 5, 0, competition="Friendly", is_neutral=True)[0]
    assert big > small


def test_run_elo_orders_stronger_team_higher():
    # Team 1 consistently beats team 2.
    matches = [
        MatchInput(1, 2, 3, 0, "Friendly", True),
        MatchInput(2, 1, 0, 2, "Friendly", True),
        MatchInput(1, 2, 1, 0, "Friendly", True),
    ]
    ratings = run_elo(matches)
    assert ratings[1] > ratings[2]
    assert ratings[1] > 1500 > ratings[2]
