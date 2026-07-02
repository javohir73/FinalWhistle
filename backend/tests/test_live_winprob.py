"""Tests for the in-play (live) win probability model (app serving layer)."""
from __future__ import annotations

from app.live_winprob import (
    live_probabilities_for_match,
    live_win_probabilities,
    regulation_remaining,
)
# ml import is fine in a TEST (the boundary is about the runtime read path).
from ml.models.poisson import outcome_probabilities, score_matrix


# --- regulation_remaining ----------------------------------------------------

def test_remaining_uses_live_clock():
    assert regulation_remaining(79, "second_half") == 11.0


def test_remaining_half_time_is_45():
    assert regulation_remaining(None, "half_time") == 45.0


def test_remaining_none_without_clock():
    assert regulation_remaining(None, None) is None


def test_remaining_none_for_extra_time_and_shootout():
    assert regulation_remaining(100, "extra_time") is None
    assert regulation_remaining(None, "penalty_shootout") is None


def test_remaining_clamps_past_90():
    assert regulation_remaining(94, "second_half") == 0.0


# --- live_win_probabilities --------------------------------------------------

def test_at_kickoff_matches_pregame_poisson():
    lam_h, lam_a = 1.6, 1.0
    live = live_win_probabilities(0, 0, lam_h, lam_a, 90.0)
    pre = outcome_probabilities(score_matrix(lam_h, lam_a, rho=0.0))
    for a, b in zip(live, pre):
        assert abs(a - b) < 0.02


def test_at_kickoff_with_rho_matches_dixon_coles_pregame_exactly():
    # With the production rho, the live triple must reduce to the SAME pre-match
    # Dixon-Coles prediction at kickoff — no twitch when the match goes live.
    lam_h, lam_a, rho = 1.6, 1.0, -0.06
    live = live_win_probabilities(0, 0, lam_h, lam_a, 90.0, rho=rho)
    pre = outcome_probabilities(score_matrix(lam_h, lam_a, rho=rho))
    for a, b in zip(live, pre):
        assert abs(a - b) < 1e-9


def test_rho_lifts_draw_vs_independent_at_kickoff():
    lam_h, lam_a = 1.4, 1.4
    indep = live_win_probabilities(0, 0, lam_h, lam_a, 90.0, rho=0.0)
    dc = live_win_probabilities(0, 0, lam_h, lam_a, 90.0, rho=-0.06)
    assert dc[1] > indep[1]  # negative rho boosts the draw


def test_leader_late_is_near_certain():
    ph, _, pa = live_win_probabilities(2, 1, 1.5, 1.2, 1.0)
    assert ph > 0.9
    assert pa < 0.05


def test_level_late_lifts_draw_probability():
    _, draw_late, _ = live_win_probabilities(2, 2, 1.5, 1.5, 5.0)
    _, draw_start, _ = live_win_probabilities(0, 0, 1.5, 1.5, 90.0)
    assert draw_late > draw_start
    assert draw_late > 0.6


def test_no_time_left_collapses_to_current_result():
    assert live_win_probabilities(2, 1, 1.5, 1.5, 0.0) == (1.0, 0.0, 0.0)
    assert live_win_probabilities(1, 1, 1.5, 1.5, 0.0) == (0.0, 1.0, 0.0)
    assert live_win_probabilities(0, 2, 1.5, 1.5, 0.0) == (0.0, 0.0, 1.0)


def test_probs_sum_to_one():
    ph, pd, pa = live_win_probabilities(1, 0, 1.4, 1.1, 40.0)
    assert abs(ph + pd + pa - 1.0) < 1e-9


def test_trailing_team_comeback_shrinks_with_time():
    _, _, away_early = live_win_probabilities(0, 1, 1.4, 1.4, 70.0)
    _, _, away_late = live_win_probabilities(0, 1, 1.4, 1.4, 10.0)
    assert away_late > away_early


# --- live_probabilities_for_match (the serving guard) ------------------------

def test_for_match_computes_when_in_play():
    out = live_probabilities_for_match(
        status="in_play", score_home=2, score_away=2, minute=79,
        period="second_half", lam_home=1.5, lam_away=1.1, rho=-0.06,
    )
    assert out is not None
    assert abs(sum(out) - 1.0) < 1e-9
    assert out[1] > 0.5


def test_for_match_none_when_not_in_play():
    assert live_probabilities_for_match("scheduled", None, None, None, None, 1.5, 1.1) is None
    assert live_probabilities_for_match("finished", 2, 1, 90, None, 1.5, 1.1) is None


def test_for_match_none_without_lambdas():
    assert live_probabilities_for_match("in_play", 1, 1, 60, "second_half", None, None) is None


def test_for_match_none_without_clock():
    assert live_probabilities_for_match("in_play", 1, 1, None, None, 1.5, 1.1) is None


# --- card adjustments ---------------------------------------------------------

from app.live_winprob import _card_factors


def test_zero_cards_is_bit_identical_to_unadjusted():
    base = live_win_probabilities(1, 0, 1.6, 1.0, 30.0, rho=-0.06)
    carded = live_win_probabilities(1, 0, 1.6, 1.0, 30.0, rho=-0.06,
                                    red_home=0, red_away=0,
                                    yellow_home=0, yellow_away=0)
    assert carded == base


def test_red_card_lowers_carded_team_and_lifts_opponent():
    base = live_win_probabilities(0, 0, 1.4, 1.2, 60.0)
    carded = live_win_probabilities(0, 0, 1.4, 1.2, 60.0, red_home=1)
    assert carded[0] < base[0]
    assert carded[2] > base[2]
    assert abs(sum(carded) - 1.0) < 1e-9


def test_away_red_mirrors_home():
    base = live_win_probabilities(0, 0, 1.4, 1.2, 60.0)
    carded = live_win_probabilities(0, 0, 1.4, 1.2, 60.0, red_away=1)
    assert carded[2] < base[2]
    assert carded[0] > base[0]


def test_card_factors_by_score_state():
    # Home leading: bunker — own rate cut hard, opponent boost small.
    assert _card_factors(1, 0, 1, 0, 0, 0, 1.0) == (0.60, 1.05)
    # Home trailing: must chase — opponent counter boost is largest.
    assert _card_factors(0, 1, 1, 0, 0, 0, 1.0) == (0.75, 1.15)
    # Level: standard mild effect.
    assert _card_factors(0, 0, 1, 0, 0, 0, 1.0) == (0.75, 1.10)
    # Away-side red at level mirrors onto the other factor.
    assert _card_factors(0, 0, 0, 1, 0, 0, 1.0) == (1.10, 0.75)


def test_reds_compound_and_cap_at_three():
    fh, fa = _card_factors(0, 0, 2, 0, 0, 0, 1.0)
    assert abs(fh - 0.75 ** 2) < 1e-12 and abs(fa - 1.10 ** 2) < 1e-12
    fh5, _ = _card_factors(0, 0, 5, 0, 0, 0, 1.0)
    fh3, _ = _card_factors(0, 0, 3, 0, 0, 0, 1.0)
    assert fh5 == fh3  # counted reds cap at 3


def test_yellow_effect_small_and_decays_with_clock():
    fh_half, fa_half = _card_factors(0, 0, 0, 0, 2, 0, 0.5)  # 2 bookings, 45' left
    assert 0.98 < fh_half < 1.0     # about a 1% shift — negligible by design
    assert 1.0 < fa_half < 1.01
    assert _card_factors(0, 0, 0, 0, 2, 0, 0.0) == (1.0, 1.0)  # gone at FT


def test_for_match_threads_card_counts():
    without = live_probabilities_for_match(
        status="in_play", score_home=0, score_away=0, minute=30,
        period="first_half", lam_home=1.4, lam_away=1.2, rho=0.0)
    with_red = live_probabilities_for_match(
        status="in_play", score_home=0, score_away=0, minute=30,
        period="first_half", lam_home=1.4, lam_away=1.2, rho=0.0, red_home=1)
    assert with_red[0] < without[0]
