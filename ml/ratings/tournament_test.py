"""Anti-overfitting contract for in-tournament rating updates.

These tests pin the safety properties the brief demands: conservative deltas,
a hard cap on the form layer, idempotent replay, and no update without a
played match.
"""
import math

import pytest

from ml.ratings.tournament import (
    FORM_CAP_ELO,
    LIVE_DAMPING,
    TeamState,
    TournamentMatch,
    form_adjustment,
    replay_tournament,
    stage_weight,
)

MEX, RSA, KOR, CZE = 1, 2, 3, 4
BASE = {MEX: 1800.0, RSA: 1600.0, KOR: 1750.0, CZE: 1740.0}


def test_no_matches_no_update():
    assert replay_tournament(BASE, []) == {}


def test_unknown_team_skipped_defensively():
    states = replay_tournament(BASE, [TournamentMatch(99, MEX, 1, 0)])
    assert states == {}


def test_expected_win_moves_ratings_conservatively():
    # Mexico (favorite, +60 host adv) beats South Africa 2-0: small delta.
    states = replay_tournament(
        BASE, [TournamentMatch(MEX, RSA, 2, 0, home_adv=60.0)]
    )
    assert 0 < states[MEX].elo_delta < 15  # expected result barely moves it
    assert states[RSA].elo_delta == pytest.approx(-states[MEX].elo_delta)  # zero-sum


def test_single_upset_cannot_overreact():
    # Massive upset: heavy favorite loses 0-2. The whole point of damping —
    # the delta stays well under what a bracket flip would need.
    states = replay_tournament(
        BASE, [TournamentMatch(MEX, RSA, 0, 2, home_adv=60.0)]
    )
    upset_delta = abs(states[MEX].elo_delta)
    # K_wc(60) × damping(0.5) × G(1.5) × |0 − E≈0.81| ≈ 36 points ≈ ~5 pp.
    assert upset_delta < 40
    # And it is HALF what the historical convention would have applied.
    assert LIVE_DAMPING == 0.5


def test_blowout_is_sublinear():
    s2 = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 2, 0)])
    s5 = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 5, 0)])
    assert s5[KOR].elo_delta > s2[KOR].elo_delta  # bigger win, bigger delta
    # ...but nowhere near 2.5x — the goal-diff curve flattens.
    assert s5[KOR].elo_delta / s2[KOR].elo_delta < 1.5


def test_knockout_stage_weighs_more_than_group():
    g = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 2, 1, stage="group")])
    f = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 2, 1, stage="final")])
    assert f[KOR].elo_delta > g[KOR].elo_delta
    assert stage_weight("final") == pytest.approx(1.2)
    assert stage_weight("unknown-stage") == 1.0


def test_replay_is_idempotent():
    matches = [
        TournamentMatch(MEX, RSA, 2, 0, home_adv=60.0),
        TournamentMatch(KOR, CZE, 2, 1),
        TournamentMatch(MEX, KOR, 1, 1),
    ]
    a = replay_tournament(BASE, matches)
    b = replay_tournament(BASE, matches)
    for tid in a:
        assert a[tid].elo_delta == pytest.approx(b[tid].elo_delta)
        assert a[tid].form_adjustment == pytest.approx(b[tid].form_adjustment)


def test_form_adjustment_hard_cap():
    # Absurd overperformance (winning every match 6-0 vs expectation ~1.5)
    # must still be clamped to the ceiling — the anti-overfitting guarantee.
    assert form_adjustment(4.5, -1.5, 4) == FORM_CAP_ELO
    assert form_adjustment(-4.5, 1.5, 4) == -FORM_CAP_ELO
    # The cap maps to ~5 pp win probability for an even match: ln10/1600/pt.
    assert FORM_CAP_ELO * (math.log(10) / 1600) <= 0.08  # within ±5-8% ceiling


def test_form_ramps_with_matches_played():
    # Residuals small enough that the cap doesn't bind — isolates the ramp.
    one = abs(form_adjustment(0.3, -0.3, 1))
    four = abs(form_adjustment(0.3, -0.3, 4))
    assert one == pytest.approx(four / 2)  # √(1/4) = 0.5
    assert form_adjustment(0.3, -0.3, 0) == 0.0


def test_residuals_track_model_expectation():
    # Korea 2-1 Czechia with near-equal ratings: lambdas ≈ 1.35 each, so the
    # winner overperformed attack (+0.65-ish) and the loser underperformed.
    states = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 2, 1)])
    assert states[KOR].gf_residual_mean > 0
    assert states[CZE].gf_residual_mean < 0
    assert states[KOR].matches_played == 1
    # Detail trail exists for explainability.
    assert states[KOR].detail[0]["score"] == "2-1"
    assert "lambda_home" in states[KOR].detail[0]


def test_total_adjustment_composes_delta_and_form():
    s = TeamState(elo_delta=10.0, matches_played=4, gf_residual_sum=2.0, ga_residual_sum=-2.0)
    assert s.total_adjustment == pytest.approx(10.0 + s.form_adjustment)
    assert abs(s.form_adjustment) <= FORM_CAP_ELO


def test_replay_residuals_use_served_goal_params():
    """FR-2.4 regression: residuals must be measured against the SERVED model's
    expected goals (base/beta from model_params.json), not the v0.1 defaults —
    otherwise every stored residual carries a systematic bias."""
    from ml.models.poisson import expected_goals_from_elo
    from ml.ratings.tournament import TournamentMatch, replay_tournament

    base, beta = 1.2, 0.0021
    states = replay_tournament(
        BASE, [TournamentMatch(MEX, RSA, 2, 0)], goals_base=base, goals_beta=beta
    )
    lam_h, lam_a = expected_goals_from_elo(BASE[MEX], BASE[RSA], 0.0, base=base, beta=beta)
    assert states[MEX].gf_residual_sum == pytest.approx(2 - lam_h)
    assert states[MEX].ga_residual_sum == pytest.approx(0 - lam_a)
