"""Tests for the in-play (live) scoreline markets (Phase 3, docs/ROADMAP-ENGINE.md).

The live derived markets are pure grid math on the SHARED live final-score grid
(``ml.models.live_grid.build_live_final_grid``) — the same grid the live 1X2 bar
(``app.live_winprob``) reads. So they must (a) reduce to the pre-match markets at
kickoff, (b) collapse onto the current score at full time, and (c) carry a
one_x_two that matches the live bar bit-for-bit at every state.
"""
import math

import pytest

from ml.models.live_grid import build_live_final_grid
from ml.models.live_markets import live_markets
from ml.models.markets import _correct_score_from_grid, _over_under_from_grid
from ml.models.poisson import outcome_probabilities, score_matrix

# The live bar — the consistency test asserts live_markets["one_x_two"] equals
# this at several states (importing the app serving layer; fine in a TEST, the
# ml/ boundary is about the runtime read path, not test wiring).
from app.live_winprob import live_probabilities_for_match, live_win_probabilities


LH, LA = 1.7, 1.1  # a representative uneven fixture


# --- build_live_final_grid ----------------------------------------------------

def test_grid_at_kickoff_equals_prematch_score_matrix():
    # 0-0, full 90 left, no cards => the final grid IS the pre-match grid.
    grid = build_live_final_grid(0, 0, LH, LA, 90.0, rho=-0.06)
    pre = score_matrix(LH, LA, rho=-0.06)
    total = sum(sum(r) for r in pre)
    pre_norm = [[c / total for c in row] for row in pre]
    assert len(grid) == len(pre_norm)
    for gr, pr in zip(grid, pre_norm):
        assert len(gr) == len(pr)
        for g, p in zip(gr, pr):
            assert abs(g - p) < 1e-12


def test_grid_sums_to_one():
    grid = build_live_final_grid(1, 0, LH, LA, 30.0, rho=-0.06)
    assert abs(sum(sum(row) for row in grid) - 1.0) < 1e-12


def test_grid_offset_by_current_score():
    # At t=0 (no time left) all remaining mass is at 0-0, so the ONLY populated
    # final cell is the current score.
    grid = build_live_final_grid(2, 1, LH, LA, 0.0)
    assert abs(grid[2][1] - 1.0) < 1e-12
    others = sum(grid[h][a] for h in range(len(grid)) for a in range(len(grid[0]))
                 if not (h == 2 and a == 1))
    assert others < 1e-12


def test_grid_none_on_missing_or_invalid_inputs():
    assert build_live_final_grid(None, 0, LH, LA, 45.0) is None
    assert build_live_final_grid(0, None, LH, LA, 45.0) is None
    assert build_live_final_grid(0, 0, None, LA, 45.0) is None
    assert build_live_final_grid(0, 0, LH, None, 45.0) is None
    assert build_live_final_grid(0, 0, LH, LA, None) is None
    assert build_live_final_grid(-1, 0, LH, LA, 45.0) is None
    assert build_live_final_grid(0, 0, LH, LA, 45.0, regulation=0.0) is None


# --- live_markets: kickoff reduces to pre-match ------------------------------

def test_live_markets_none_on_missing_inputs():
    assert live_markets(None, 0, LH, LA, 45.0) is None
    assert live_markets(0, 0, None, None, 45.0) is None
    assert live_markets(0, 0, LH, LA, None) is None


def test_one_x_two_at_kickoff_matches_prematch_poisson():
    m = live_markets(0, 0, LH, LA, 90.0, rho=-0.06)
    pre = outcome_probabilities(score_matrix(LH, LA, rho=-0.06))
    for a, b in zip(m["one_x_two"], pre):
        assert abs(a - b) < 1e-12


def test_markets_at_kickoff_reduce_to_prematch_grid_markets():
    # Totals / correct-score at kickoff equal the pre-match grid marginals (to
    # floating-point tolerance — summation order differs by a few ULPs).
    m = live_markets(0, 0, LH, LA, 90.0, rho=-0.06)
    pre = score_matrix(LH, LA, rho=-0.06)
    tot = sum(sum(r) for r in pre)
    pre_norm = [[c / tot for c in row] for row in pre]
    exp_tot = _over_under_from_grid(pre_norm, (0.5, 1.5, 2.5, 3.5, 4.5))
    for got, exp in zip(m["totals"], exp_tot):
        assert got["line"] == exp["line"]
        assert got["over"] == pytest.approx(exp["over"], abs=1e-12)
        assert got["under"] == pytest.approx(exp["under"], abs=1e-12)
    exp_cs = _correct_score_from_grid(pre_norm, top_n=12)
    for got, exp in zip(m["correct_score"], exp_cs):
        assert (got["home"], got["away"]) == (exp["home"], exp["away"])
        assert got["prob"] == pytest.approx(exp["prob"], abs=1e-12)


# --- live_markets: full-time collapse ----------------------------------------

def test_one_x_two_collapses_to_one_hot_at_full_time():
    # Home leads at t=0 -> one-hot home.
    assert live_markets(2, 1, LH, LA, 0.0)["one_x_two"] == pytest.approx((1.0, 0.0, 0.0))
    # Level -> one-hot draw.
    assert live_markets(1, 1, LH, LA, 0.0)["one_x_two"] == pytest.approx((0.0, 1.0, 0.0))
    # Away leads -> one-hot away.
    assert live_markets(0, 2, LH, LA, 0.0)["one_x_two"] == pytest.approx((0.0, 0.0, 1.0))


def test_correct_score_top_entry_is_current_score_at_full_time():
    m = live_markets(3, 1, LH, LA, 0.0)
    top = m["correct_score"][0]
    assert (top["home"], top["away"]) == (3, 1)
    assert top["prob"] == pytest.approx(1.0)


# --- live_markets: dynamics ---------------------------------------------------

def test_blowout_away_win_near_zero_but_positive():
    m = live_markets(3, 0, LH, LA, 10.0, rho=-0.06)
    p_away = m["one_x_two"][2]
    assert 0.0 < p_away < 0.02


def test_red_card_on_leader_shifts_toward_opponent():
    base = live_markets(1, 0, LH, LA, 40.0, rho=-0.06)
    # Home is leading and gets a red -> home win drops, away win rises.
    carded = live_markets(1, 0, LH, LA, 40.0, rho=-0.06, red_home=1)
    assert carded["one_x_two"][0] < base["one_x_two"][0]
    assert carded["one_x_two"][2] > base["one_x_two"][2]


def test_double_chance_matches_one_x_two_pairs():
    m = live_markets(1, 0, LH, LA, 40.0, rho=-0.06)
    ph, pd, pa = m["one_x_two"]
    dc = m["double_chance"]
    assert dc["home_or_draw"] == pytest.approx(ph + pd)
    assert dc["home_or_away"] == pytest.approx(ph + pa)
    assert dc["draw_or_away"] == pytest.approx(pd + pa)


# --- live_markets: internal consistency of each shape ------------------------

def test_totals_over_plus_under_is_one_per_line():
    m = live_markets(1, 1, LH, LA, 25.0, rho=-0.06)
    assert [r["line"] for r in m["totals"]] == [0.5, 1.5, 2.5, 3.5, 4.5]
    for row in m["totals"]:
        assert abs(row["over"] + row["under"] - 1.0) < 1e-12


def test_btts_yes_plus_no_is_one():
    m = live_markets(1, 0, LH, LA, 30.0, rho=-0.06)
    assert abs(m["btts"]["yes"] + m["btts"]["no"] - 1.0) < 1e-12


def test_correct_score_sums_to_one_and_truncated():
    m = live_markets(0, 0, LH, LA, 55.0, rho=-0.06)
    assert len(m["correct_score"]) == 12
    # Truncated top-12, but the FULL grid still sums to ~1 (assert via a full
    # rebuild off the shared grid).
    grid = build_live_final_grid(0, 0, LH, LA, 55.0, rho=-0.06)
    full = _correct_score_from_grid(grid)
    assert abs(sum(c["prob"] for c in full) - 1.0) < 1e-9
    probs = [c["prob"] for c in m["correct_score"]]
    assert probs == sorted(probs, reverse=True)


def test_asian_handicap_rows_per_line_sum_to_one():
    m = live_markets(1, 0, LH, LA, 40.0, rho=-0.06)
    assert [r["line"] for r in m["asian_handicap"]] == [-1.0, -0.5, 0.0, 0.5, 1.0]
    for r in m["asian_handicap"]:
        assert abs(r["home"] + r["push"] + r["away"] - 1.0) < 1e-12


def test_returns_expected_keys():
    m = live_markets(1, 0, LH, LA, 40.0, rho=-0.06)
    assert set(m) == {
        "one_x_two", "double_chance", "totals", "btts",
        "correct_score", "asian_handicap",
    }


# --- CONSISTENCY: live_markets one_x_two == the live bar (by construction) ----

@pytest.mark.parametrize(
    "sh,sa,mins,rho,rh,ra,yh,ya",
    [
        (0, 0, 90.0, -0.06, 0, 0, 0, 0),   # kickoff
        (0, 0, 90.0, 0.0, 0, 0, 0, 0),     # kickoff, independent
        (1, 0, 30.0, -0.06, 0, 0, 0, 0),   # home lead, mid
        (2, 2, 5.0, -0.06, 0, 0, 0, 0),    # level, late
        (0, 1, 10.0, -0.06, 0, 0, 0, 0),   # away lead, late
        (3, 0, 10.0, -0.08, 0, 0, 0, 0),   # blowout
        (1, 0, 40.0, -0.06, 1, 0, 0, 0),   # home red
        (0, 0, 60.0, 0.0, 0, 1, 0, 0),     # away red
        (0, 1, 25.0, -0.06, 0, 1, 2, 1),   # mixed cards
        (2, 1, 1.0, 0.0, 0, 0, 0, 0),      # near full time
    ],
)
def test_one_x_two_equals_live_bar(sh, sa, mins, rho, rh, ra, yh, ya):
    bar = live_win_probabilities(
        sh, sa, LH, LA, mins, rho=rho,
        red_home=rh, red_away=ra, yellow_home=yh, yellow_away=ya,
    )
    m = live_markets(
        sh, sa, LH, LA, mins, rho=rho,
        red_home=rh, red_away=ra, yellow_home=yh, yellow_away=ya,
    )
    for a, b in zip(m["one_x_two"], bar):
        assert abs(a - b) < 1e-9


def test_one_x_two_equals_serving_bar_via_for_match():
    # The public serving entry point (status/period guards) must also agree with
    # live_markets computed from the same decoded state.
    bar = live_probabilities_for_match(
        status="in_play", score_home=1, score_away=0, minute=50,
        period="second_half", lam_home=LH, lam_away=LA, rho=-0.06, red_home=1,
    )
    # minute=50 in second_half -> 40 minutes remaining.
    m = live_markets(1, 0, LH, LA, 40.0, rho=-0.06, red_home=1)
    assert bar is not None
    for a, b in zip(m["one_x_two"], bar):
        assert abs(a - b) < 1e-9
