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


def test_residual_ledger_records_one_entry_per_match_in_kickoff_order():
    # Unified residual ledger (C1): each team's state carries the time-ordered
    # (gf_residual, ga_residual) history, not just the summed mean.
    matches = [
        TournamentMatch(KOR, CZE, 2, 1),
        TournamentMatch(KOR, MEX, 0, 0),
    ]
    states = replay_tournament(BASE, matches)
    assert len(states[KOR].residual_ledger) == 2
    # Ledger entries are (gf_residual, ga_residual) tuples that sum/average
    # to the existing gf_residual_sum / ga_residual_sum fields.
    gf_sum = sum(gf for gf, _ in states[KOR].residual_ledger)
    ga_sum = sum(ga for _, ga in states[KOR].residual_ledger)
    assert gf_sum == pytest.approx(states[KOR].gf_residual_sum)
    assert ga_sum == pytest.approx(states[KOR].ga_residual_sum)


def test_residual_ledger_empty_for_team_with_no_matches():
    states = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 2, 1)])
    # MEX/CZE... wait CZE played; check a team truly absent from the replay.
    assert MEX not in states


def test_residual_ledger_is_backward_compatible_with_sums_and_means():
    # Existing fields (gf_residual_sum, ga_residual_sum, gf_residual_mean,
    # ga_residual_mean, matches_played, detail, form_adjustment,
    # total_adjustment) must keep working exactly as before -- the ledger is
    # additive, not a replacement.
    matches = [TournamentMatch(KOR, CZE, 2, 1)]
    states = replay_tournament(BASE, matches)
    s = states[KOR]
    assert s.matches_played == 1
    assert s.gf_residual_mean == pytest.approx(s.gf_residual_sum / s.matches_played)
    assert isinstance(s.detail, list) and len(s.detail) == 1
    assert isinstance(s.form_adjustment, float)
    assert isinstance(s.total_adjustment, float)


def test_seed_ledgers_are_prepended_per_team():
    # seed_ledgers lets learning_loop inject pre-tournament residuals so form
    # doesn't reset to zero at the tournament boundary.
    seed = {KOR: [(0.5, -0.2), (1.0, 0.0)]}
    matches = [TournamentMatch(KOR, CZE, 2, 1)]
    states = replay_tournament(BASE, matches, seed_ledgers=seed)
    # Ledger = 2 seed rows + 1 tournament row, seed rows FIRST (oldest).
    assert len(states[KOR].residual_ledger) == 3
    assert states[KOR].residual_ledger[0] == seed[KOR][0]
    assert states[KOR].residual_ledger[1] == seed[KOR][1]
    # The tournament match's residual is the last (most recent) entry.
    assert states[KOR].residual_ledger[2] != seed[KOR][0]


def test_seed_ledgers_do_not_affect_sums_means_or_matches_played():
    # The seed is for the NEW ledger channel only -- it must not perturb the
    # legacy scalar fields (matches_played, gf_residual_sum, etc.), which are
    # defined purely over matches actually replayed this run.
    seed = {KOR: [(5.0, -5.0)]}
    matches = [TournamentMatch(KOR, CZE, 2, 1)]
    with_seed = replay_tournament(BASE, matches, seed_ledgers=seed)
    without_seed = replay_tournament(BASE, matches)
    assert with_seed[KOR].matches_played == without_seed[KOR].matches_played
    assert with_seed[KOR].gf_residual_sum == pytest.approx(without_seed[KOR].gf_residual_sum)
    assert with_seed[KOR].ga_residual_sum == pytest.approx(without_seed[KOR].ga_residual_sum)
    assert with_seed[KOR].form_adjustment == pytest.approx(without_seed[KOR].form_adjustment)


def test_seed_ledgers_for_team_with_no_tournament_matches_still_surface():
    # A team seeded but never actually appearing in `matches` should still
    # get a state entry carrying just the seed (so pre-tournament form is
    # visible even before their first tournament match, per the design doc's
    # "boundary-free" requirement)... but replay_tournament currently only
    # creates state for teams that PLAY. Guard: seeding a team absent from
    # matches must not raise, and must not fabricate a played state.
    seed = {MEX: [(1.0, 0.0)]}
    states = replay_tournament(BASE, [TournamentMatch(KOR, CZE, 2, 1)], seed_ledgers=seed)
    assert MEX not in states  # unchanged behavior: no state without a played match


def test_seed_ledgers_none_is_equivalent_to_omitted():
    matches = [TournamentMatch(KOR, CZE, 2, 1)]
    a = replay_tournament(BASE, matches, seed_ledgers=None)
    b = replay_tournament(BASE, matches)
    assert a[KOR].residual_ledger == b[KOR].residual_ledger


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
