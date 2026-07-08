"""Tests for the knockout advance decomposition (extra time + penalties)."""
import pytest

from ml.models.knockout import (
    ET_FRACTION,
    PK_BAND,
    KnockoutAdvance,
    fit_pk_beta,
    ko_advance,
    shootout_p,
)
from ml.models.poisson import outcome_probabilities, score_matrix


def _adv(**overrides) -> KnockoutAdvance:
    """A representative favorite-vs-underdog tie; overridable per test."""
    kwargs = dict(
        p_home=0.46, p_draw=0.29, p_away=0.25,
        lam_home=1.4, lam_away=1.0,
        elo_home=1900, elo_away=1800,
        rho=-0.06, pk_beta=0.0,
    )
    kwargs.update(overrides)
    return ko_advance(**kwargs)


def test_advance_probabilities_sum_to_one():
    adv = _adv()
    assert abs(adv.p_advance_home + adv.p_advance_away - 1.0) < 1e-9


def test_paths_sum_to_advance_probability():
    adv = _adv()
    assert abs(adv.home_win_90 + adv.home_win_et + adv.home_win_pens - adv.p_advance_home) < 1e-9
    assert abs(adv.away_win_90 + adv.away_win_et + adv.away_win_pens - adv.p_advance_away) < 1e-9


def test_no_draw_means_advance_equals_regulation():
    adv = _adv(p_home=0.7, p_draw=0.0, p_away=0.3)
    assert abs(adv.p_advance_home - 0.7) < 1e-9
    assert adv.p_extra_time == 0.0
    assert adv.p_shootout == 0.0
    assert adv.home_win_et == adv.home_win_pens == 0.0


def test_parity_is_a_coin_flip():
    adv = _adv(p_home=0.355, p_draw=0.29, p_away=0.355,
               lam_home=1.2, lam_away=1.2, elo_home=1800, elo_away=1800)
    assert abs(adv.p_advance_home - 0.5) < 1e-9
    assert abs(adv.home_win_et - adv.away_win_et) < 1e-9
    assert abs(adv.home_win_pens - adv.away_win_pens) < 1e-9


def test_shootout_share_respects_pk_band():
    # Even an absurd pk_beta cannot push the pens split past the clamp.
    adv = _adv(pk_beta=10.0)
    assert adv.home_win_pens <= adv.p_shootout * PK_BAND[1] + 1e-12
    assert adv.away_win_pens >= adv.p_shootout * PK_BAND[0] - 1e-12


def test_et_stage_matches_direct_grid():
    # The ET split must be exactly the Dixon-Coles grid at 30-minute rates.
    lam_h, lam_a, rho, p_draw = 1.4, 1.0, -0.06, 0.29
    et_h, et_d, et_a = outcome_probabilities(
        score_matrix(lam_h * ET_FRACTION, lam_a * ET_FRACTION, rho=rho)
    )
    adv = _adv(lam_home=lam_h, lam_away=lam_a, rho=rho, p_draw=p_draw)
    assert abs(adv.home_win_et - p_draw * et_h) < 1e-9
    assert abs(adv.p_shootout - p_draw * et_d) < 1e-9


def test_et_tempo_zero_sends_every_draw_to_penalties():
    # lam_et = 0 -> ET is always 0-0, so the whole draw mass reaches the shootout.
    adv = _adv(et_tempo=0.0)
    assert adv.home_win_et == 0.0
    assert abs(adv.p_shootout - adv.p_extra_time) < 1e-9


def test_input_triple_is_normalized():
    # 4-dp rounded triples don't sum to exactly 1; advance probs still must.
    adv = _adv(p_home=0.4599, p_draw=0.2902, p_away=0.2497)
    assert abs(adv.p_advance_home + adv.p_advance_away - 1.0) < 1e-9


def test_degenerate_triple_raises():
    with pytest.raises(ValueError):
        _adv(p_home=0.0, p_draw=0.0, p_away=0.0)


def test_payload_shape_and_consistency():
    payload = _adv().to_payload()
    assert set(payload) == {"p_advance_home", "p_advance_away", "p_extra_time",
                            "p_shootout", "paths"}
    for side in ("home", "away"):
        paths = payload["paths"][side]
        total = paths["win_90"] + paths["win_et"] + paths["win_pens"]
        assert abs(total - payload[f"p_advance_{side}"]) < 5e-4  # rounding slack


def test_shootout_helpers_still_importable_from_bracket():
    # bracket.py re-exports the penalty model; the tuner and tests rely on it.
    from ml.simulate.bracket import fit_pk_beta as bracket_fit, shootout_p as bracket_p
    assert bracket_p is shootout_p
    assert bracket_fit is fit_pk_beta


def test_pk_shift_moves_the_pens_split_within_the_band():
    base = _adv()
    shifted = _adv(pk_shift=0.03)
    # Away keeper out (+shift toward home): home pens share rises, ET untouched.
    assert shifted.home_win_pens > base.home_win_pens
    assert shifted.home_win_et == base.home_win_et
    # Advance probabilities still sum to 1.
    assert abs(shifted.p_advance_home + shifted.p_advance_away - 1.0) < 1e-9
    # No shift can escape the clamp.
    extreme = _adv(pk_shift=5.0)
    assert extreme.home_win_pens <= extreme.p_shootout * PK_BAND[1] + 1e-12


def test_shootout_p_shift_clamps_to_band():
    assert shootout_p(1800, 1800, 0.0, shift=0.2) == PK_BAND[1]
    assert shootout_p(1800, 1800, 0.0, shift=-0.2) == PK_BAND[0]
    assert shootout_p(1800, 1800, 0.0, shift=0.0) == 0.5
