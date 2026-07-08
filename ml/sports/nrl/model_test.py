"""Tests for the NRL margin-Elo model (task 3)."""
import math

from ml.sports.nrl.model import (
    NrlParams,
    expected_home_prob,
    margin_multiplier,
    predict,
    regress_season,
    update,
)


def test_expected_home_prob_symmetric_at_zero_adv():
    assert abs(expected_home_prob(1500, 1500, 0) - 0.5) < 1e-9


def test_expected_home_prob_home_adv_tilts_above_half():
    assert expected_home_prob(1500, 1500, 45) > 0.5


def test_expected_home_prob_no_overflow_on_large_gap():
    # A large-but-plausible Elo gap must stay a valid, finite probability
    # strictly inside (0, 1) — no OverflowError, no saturation to 0/1.
    p_big = expected_home_prob(1500, 700, 45)
    p_small = expected_home_prob(700, 1500, 45)
    assert 0.0 < p_big < 1.0
    assert 0.0 < p_small < 1.0
    assert p_big > 0.99
    assert p_small < 0.02


def test_expected_home_prob_extreme_gap_does_not_raise():
    # An extreme gap saturates to 0.0/1.0 (float underflow), which is a valid
    # probability, not a crash — the important thing is it never raises.
    p_big = expected_home_prob(1500, -100000, 45)
    p_small = expected_home_prob(-100000, 1500, 45)
    assert math.isfinite(p_big)
    assert math.isfinite(p_small)
    assert 0.0 <= p_small <= p_big <= 1.0


def test_margin_multiplier_zero_at_zero_margin():
    assert margin_multiplier(0, 2.2) == 0.0


def test_margin_multiplier_matches_log_formula():
    assert abs(margin_multiplier(4, 2.2) - math.log(5)) < 1e-9


def test_margin_multiplier_respects_cap():
    huge = margin_multiplier(1000, 2.2)
    assert huge == 2.2


def test_margin_multiplier_uses_absolute_margin():
    assert margin_multiplier(-10, 2.2) == margin_multiplier(10, 2.2)


# --- update() ---

def test_update_is_zero_sum():
    p = NrlParams()
    new_h, new_a = update(1500, 1500, 24, 10, p)
    assert abs((new_h - 1500) + (new_a - 1500)) < 1e-9


def test_update_winner_gains_loser_loses():
    p = NrlParams()
    new_h, new_a = update(1500, 1500, 24, 10, p)
    assert new_h > 1500
    assert new_a < 1500


def test_update_blowout_moves_more_than_narrow_win_but_respects_cap():
    p = NrlParams()
    narrow_h, _ = update(1500, 1500, 19, 18, p)
    blowout_h, _ = update(1500, 1500, 60, 4, p)
    massive_h, _ = update(1500, 1500, 600, 4, p)
    assert (blowout_h - 1500) > (narrow_h - 1500)
    # cap bounds the multiplier, so the massive blowout can't exceed k * cap * (1 - expected)
    away_adv_expected = expected_home_prob(1500, 1500, p.home_adv)
    max_delta = p.k * p.margin_mult_cap * (1.0 - away_adv_expected)
    assert massive_h - 1500 <= max_delta + 1e-9


def test_update_draw_at_equal_elo_moves_home_down_away_up():
    # With home_adv > 0, expected_home_prob(equal elos) > 0.5. A draw (W=0.5)
    # underperforms that expectation, so the home side loses rating and the
    # away side gains it — even though nobody won.
    p = NrlParams()
    new_h, new_a = update(1500, 1500, 10, 10, p)
    assert new_h < 1500
    assert new_a > 1500
    assert abs((new_h - 1500) + (new_a - 1500)) < 1e-9


def test_update_draw_uses_full_multiplier_not_zero():
    # Draws must still move ratings: the margin is 0 so margin_multiplier(0, cap)
    # would be 0.0, but a draw uses a fixed multiplier of 1.0 instead, otherwise
    # a draw against expectation would incorrectly leave ratings untouched.
    p = NrlParams()
    new_h, _ = update(1500, 1500, 10, 10, p)
    expected = expected_home_prob(1500, 1500, p.home_adv)
    want_delta = p.k * 1.0 * (0.5 - expected)
    assert abs((new_h - 1500) - want_delta) < 1e-9


def test_update_home_win_delta_formula():
    p = NrlParams()
    new_h, new_a = update(1500, 1500, 24, 10, p)
    expected = expected_home_prob(1500, 1500, p.home_adv)
    mult = margin_multiplier(14, p.margin_mult_cap)
    want_delta = p.k * mult * (1.0 - expected)
    assert abs((new_h - 1500) - want_delta) < 1e-9
    assert abs((new_a - 1500) + want_delta) < 1e-9


# --- regress_season() ---

def test_regress_season_moves_fraction_toward_mean():
    p = NrlParams()
    elos = {1: 1600.0, 2: 1400.0, 3: 1500.0}
    regressed = regress_season(elos, p)
    assert abs(regressed[1] - (1600.0 - p.season_regress * (1600.0 - 1500.0))) < 1e-9
    assert abs(regressed[2] - (1400.0 + p.season_regress * (1500.0 - 1400.0))) < 1e-9
    assert regressed[3] == 1500.0


def test_regress_season_does_not_mutate_input():
    p = NrlParams()
    elos = {1: 1600.0}
    regress_season(elos, p)
    assert elos[1] == 1600.0


def test_regress_season_custom_mean():
    p = NrlParams()
    elos = {1: 2000.0}
    regressed = regress_season(elos, p, mean=1000.0)
    assert abs(regressed[1] - (2000.0 - p.season_regress * 1000.0)) < 1e-9


# --- predict() ---

def test_predict_neutral_symmetry():
    p = NrlParams()
    a, b = 1550.0, 1480.0
    home_view = predict(a, b, p, neutral=True)
    away_view = predict(b, a, p, neutral=True)
    assert abs(home_view["p_home"] - away_view["p_away"]) < 1e-9
    assert abs(home_view["p_away"] - away_view["p_home"]) < 1e-9
    assert abs(home_view["p_draw"] - away_view["p_draw"]) < 1e-9
    assert abs(home_view["expected_margin"] + away_view["expected_margin"]) < 1e-9


def test_predict_probabilities_sum_to_one():
    p = NrlParams()
    for elo_home, elo_away in [(1500, 1500), (1650, 1400), (1300, 1700)]:
        out = predict(elo_home, elo_away, p)
        total = out["p_home"] + out["p_draw"] + out["p_away"]
        assert abs(total - 1.0) < 1e-9


def test_predict_p_draw_matches_params():
    p = NrlParams()
    out = predict(1500, 1500, p)
    assert out["p_draw"] == p.p_draw


def test_predict_home_edge_positive_at_equal_elo_non_neutral():
    p = NrlParams()
    out = predict(1500, 1500, p, neutral=False)
    assert out["p_home"] > out["p_away"]


def test_predict_home_edge_vanishes_at_equal_elo_neutral():
    p = NrlParams()
    out = predict(1500, 1500, p, neutral=True)
    assert abs(out["p_home"] - out["p_away"]) < 1e-9


def test_predict_expected_margin_sign_follows_favourite():
    p = NrlParams()
    home_favoured = predict(1600, 1400, p, neutral=True)
    away_favoured = predict(1400, 1600, p, neutral=True)
    assert home_favoured["expected_margin"] > 0
    assert away_favoured["expected_margin"] < 0


def test_predict_expected_margin_includes_home_adv_when_not_neutral():
    p = NrlParams()
    out = predict(1500, 1500, p, neutral=False)
    assert abs(out["expected_margin"] - p.home_adv * p.margin_slope) < 1e-9


def test_predict_float_hygiene_large_gap():
    p = NrlParams()
    out = predict(3000, -3000, p)
    assert 0.0 < out["p_home"] < 1.0
    assert 0.0 < out["p_away"] < 1.0
    assert 0.0 <= out["p_draw"] < 1.0
    total = out["p_home"] + out["p_draw"] + out["p_away"]
    assert abs(total - 1.0) < 1e-9
    assert math.isfinite(out["expected_margin"])


def test_nrl_params_defaults():
    p = NrlParams()
    assert p.version == "nrl-elo-v0.1"
    assert p.k == 36.0
    assert p.home_adv == 45.0
    assert p.margin_mult_cap == 2.2
    assert p.season_regress == 0.25
    assert p.margin_slope == 0.045
    assert p.margin_sigma == 15.0
    assert p.p_draw == 0.012
