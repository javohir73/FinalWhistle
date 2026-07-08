"""Contract tests for the split, decayed, boundary-free form channels (C1).

Root-cause fix under test: the legacy single scalar `form_adjustment` cancels
attack and defence residuals (Norway: +1.22 gf vs +1.23 ga netted to ~0 while
Brazil's mild broad overperformance compounded to +29). `form_offsets` keeps
attack and defence as two independent channels so a bad defensive match can
no longer erase a hot attacking run.
"""
import math

import pytest

from ml.ratings.form import FormConfig, form_offsets

CFG = FormConfig(c_atk=0.25, c_def=0.25, cap=0.15, half_life=3.0)


def test_empty_ledger_returns_zero_offsets():
    assert form_offsets([], CFG) == (0.0, 0.0)


def test_single_match_no_decay_needed():
    # One match at age 0: weight = 1, damp = sqrt(1/4) = 0.5.
    atk, deff = form_offsets([(1.0, -1.0)], CFG)
    # decayed_mean = 1.0 (only point) -> raw = 0.25 * 1.0 * 0.5 = 0.125
    assert atk == pytest.approx(0.125)
    assert deff == pytest.approx(0.25 * -1.0 * 0.5)


def test_sign_convention_atk_positive_scoring_above_expectation():
    # Positive gf residual (scored more than expected) -> positive atk_form.
    atk, _ = form_offsets([(2.0, 0.0)] * 4, CFG)
    assert atk > 0


def test_sign_convention_def_positive_conceding_above_expectation():
    # Positive ga residual (CONCEDED more than expected) -> positive def_form,
    # which boosts the OPPONENT's lambda (this team's defence is leaky).
    _, deff = form_offsets([(0.0, 2.0)] * 4, CFG)
    assert deff > 0


def test_sign_convention_def_negative_when_conceding_below_expectation():
    _, deff = form_offsets([(0.0, -2.0)] * 4, CFG)
    assert deff < 0


def test_clamp_caps_each_offset_independently():
    # Absurd overperformance in both channels must still clamp to +-cap.
    ledger = [(10.0, 10.0)] * 8
    atk, deff = form_offsets(ledger, CFG)
    assert atk == pytest.approx(CFG.cap)
    assert deff == pytest.approx(CFG.cap)

    ledger_neg = [(-10.0, -10.0)] * 8
    atk_n, deff_n = form_offsets(ledger_neg, CFG)
    assert atk_n == pytest.approx(-CFG.cap)
    assert deff_n == pytest.approx(-CFG.cap)


def test_small_sample_damp_matches_sqrt_n_over_4_convention():
    # Mirrors FORM_FULL_WEIGHT_MATCHES=4: one match carries half the
    # influence of four (with residuals small enough the clamp never binds).
    small_cfg = FormConfig(c_atk=0.01, c_def=0.01, cap=1.0, half_life=1e9)
    one_atk, _ = form_offsets([(1.0, 0.0)], small_cfg)
    four_atk, _ = form_offsets([(1.0, 0.0)] * 4, small_cfg)
    assert one_atk == pytest.approx(four_atk / 2, rel=1e-6)


def test_small_sample_damp_is_full_weight_at_four_matches():
    small_cfg = FormConfig(c_atk=0.01, c_def=0.01, cap=1.0, half_life=1e9)
    four_atk, _ = form_offsets([(1.0, 0.0)] * 4, small_cfg)
    eight_atk, _ = form_offsets([(1.0, 0.0)] * 8, small_cfg)
    # min(1, sqrt(n/4)) saturates at n=4, so 4 and 8 identical matches (no
    # decay distinguishing them because half_life is effectively infinite)
    # produce the SAME damp factor (both = 1.0) -> same offset.
    assert four_atk == pytest.approx(eight_atk, rel=1e-6)


def test_decayed_mean_weighs_recent_matches_more():
    # Most recent LAST. A hot recent match should pull the mean toward it
    # more than an equally-sized old outlier, when half_life is short.
    cfg = FormConfig(c_atk=1.0, c_def=1.0, cap=10.0, half_life=1.0)
    old_hot = [(5.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]  # hot match oldest
    recent_hot = [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (5.0, 0.0)]  # hot match newest
    atk_old, _ = form_offsets(old_hot, cfg)
    atk_recent, _ = form_offsets(recent_hot, cfg)
    assert atk_recent > atk_old


def test_decayed_mean_half_life_math_two_point_ledger():
    # age 0 (most recent) weight 1.0, age 1 weight 0.5**(1/half_life).
    half_life = 3.0
    cfg = FormConfig(c_atk=1.0, c_def=0.0, cap=100.0, half_life=half_life)
    ledger = [(4.0, 0.0), (0.0, 0.0)]  # oldest first, most recent last
    w_old = 0.5 ** (1.0 / half_life)
    w_new = 1.0
    expected_mean = (4.0 * w_old + 0.0 * w_new) / (w_old + w_new)
    n = len(ledger)
    damp = min(1.0, math.sqrt(n / 4))
    expected_atk = max(-cfg.cap, min(cfg.cap, cfg.c_atk * expected_mean * damp))
    atk, deff = form_offsets(ledger, cfg)
    assert atk == pytest.approx(expected_atk)
    assert deff == pytest.approx(0.0)


def test_atk_and_def_channels_are_independent_no_cancellation():
    # This is the direct regression for the cancellation bug: a team with
    # strong positive attack residuals AND positive defence residuals
    # (conceding above expectation) in the SAME matches must show a
    # positive atk_form AND a positive def_form -- neither cancels the
    # other, unlike the legacy scalar (gf_mean - ga_mean).
    ledger = [(1.5, 1.4)] * 6
    atk, deff = form_offsets(ledger, CFG)
    assert atk > 0
    assert deff > 0


def test_norway_shape_case_atk_survives_def_flags_the_outlier():
    # The exact regression shape from the design doc / task brief: three
    # tournament rows with strong positive gf residuals and one big ga
    # outlier (the France defensive collapse), most recent last.
    ledger = [(1.5, -0.3), (0.8, 0.1), (-0.5, 2.4)]
    cfg = FormConfig(c_atk=0.25, c_def=0.25, cap=0.15, half_life=3.0)
    atk, deff = form_offsets(ledger, cfg)

    # Attack stays clearly positive despite the one bad defensive match --
    # the split channels never let ga cancel gf.
    assert atk > 0.05
    assert atk < cfg.cap  # damped/decayed enough not to pin the ceiling

    # Defence shows the recent outlier's effect strongly -- it's the most
    # recent match (age 0, full decay weight) so it dominates and pins the
    # cap, correctly flagging the defensive concern.
    assert deff == pytest.approx(cfg.cap)

    # The key proof the cancellation bug is gone: the legacy scalar nets
    # gf_mean - ga_mean over this ledger to a NEGATIVE number (attack signal
    # erased, reads as pure defensive collapse). Split channels instead show
    # a clearly positive attack signal alongside the defensive flag --
    # exactly the two-sided picture the legacy scalar could not represent.
    legacy_like_net = sum(gf for gf, _ in ledger) / len(ledger) - sum(ga for _, ga in ledger) / len(ledger)
    assert legacy_like_net < 0   # legacy: net negative, attack signal vanishes
    assert atk > 0               # split: attack signal survives, clearly positive


def test_seed_prepended_matches_contribute_with_correct_age():
    # A seed ledger prepended before tournament matches should decay further
    # (older) than the tournament matches that follow it.
    cfg = FormConfig(c_atk=1.0, c_def=0.0, cap=100.0, half_life=2.0)
    seed = [(3.0, 0.0)]
    tournament = [(0.0, 0.0)]
    combined = seed + tournament
    atk_combined, _ = form_offsets(combined, cfg)
    atk_tournament_only, _ = form_offsets(tournament, cfg)
    # The seed's positive residual, even decayed, should pull the combined
    # mean above the tournament-only mean (which is flat 0).
    assert atk_combined > atk_tournament_only


def test_config_is_frozen_dataclass():
    with pytest.raises(Exception):
        CFG.cap = 99.0


def test_returns_floats_not_numpy_types():
    atk, deff = form_offsets([(1.0, 1.0)], CFG)
    assert isinstance(atk, float)
    assert isinstance(deff, float)
