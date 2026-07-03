"""Tests for scoreline-derived betting markets (Phase 2, docs/ROADMAP-ENGINE.md).

Pure grid math on top of the Dixon-Coles Poisson scoreline grid — no model,
no training, no DB. Every probability shape must stay internally consistent
with the same normalized grid the engine already prices.
"""
import math

import pytest

from ml.models.markets import (
    _normalized_grid,
    asian_handicap,
    asian_handicap_lines,
    both_teams_to_score,
    correct_score,
    derive_scoreline_markets,
    double_chance_from_triple,
    over_under,
)
from ml.models.poisson import goal_markets


LH, LA = 1.7, 1.1  # a representative uneven fixture


def test_normalized_grid_sums_to_one_and_is_square():
    grid = _normalized_grid(LH, LA, rho=-0.08)
    assert len(grid) == 11 and all(len(row) == 11 for row in grid)
    total = sum(sum(row) for row in grid)
    assert abs(total - 1.0) < 1e-12
    assert all(cell >= 0.0 for row in grid for cell in row)


def test_normalized_grid_raises_on_degenerate_zero_grid():
    # NaN rates make every cell non-finite -> clamped to 0 -> zero total mass.
    # (lam=0 is NOT degenerate: it is a valid point mass at 0-0.)
    with pytest.raises(ValueError):
        _normalized_grid(float("nan"), float("nan"))


def test_over_under_over_plus_under_sum_to_one_per_line():
    for row in over_under(LH, LA, rho=-0.08):
        assert abs(row["over"] + row["under"] - 1.0) < 1e-12


def test_over_is_monotonically_decreasing_as_line_rises():
    rows = over_under(LH, LA, lines=(0.5, 1.5, 2.5, 3.5, 4.5))
    overs = [r["over"] for r in rows]
    assert rows == sorted(rows, key=lambda r: r["line"])  # lines already ascending
    assert all(overs[i] > overs[i + 1] for i in range(len(overs) - 1))
    assert all(0.0 <= o <= 1.0 for o in overs)


def test_over_under_2_5_matches_independent_poisson():
    # rho=0 => independent Poisson; P(total > 2.5) = P(total >= 3).
    o = next(r for r in over_under(2.0, 0.5, rho=0.0) if r["line"] == 2.5)["over"]
    total_pmf = [
        sum(
            math.exp(-2.0) * 2.0**h / math.factorial(h)
            * math.exp(-0.5) * 0.5**a / math.factorial(a)
            for h in range(11)
            for a in range(11)
            if h + a == n
        )
        for n in range(21)
    ]
    norm = sum(total_pmf)
    expected = sum(total_pmf[3:]) / norm
    assert abs(o - expected) < 1e-6


def test_over_under_2_5_matches_goal_markets():
    # Consistency with the already-shipped poisson.goal_markets over_2_5. The
    # exact-to-1e-6 agreement is asserted against the unrounded independent
    # Poisson above; goal_markets rounds to 4 dp, so match it at that precision.
    o = next(r for r in over_under(2.0, 0.5, rho=-0.1) if r["line"] == 2.5)["over"]
    assert o == pytest.approx(goal_markets(2.0, 0.5, rho=-0.1)["total"]["over_2_5"], abs=5e-5)


def test_btts_yes_plus_no_and_bounded_by_each_side():
    grid = _normalized_grid(LH, LA)
    p_home_scores = sum(grid[h][a] for h in range(1, 11) for a in range(11))
    p_away_scores = sum(grid[h][a] for h in range(11) for a in range(1, 11))
    btts = both_teams_to_score(LH, LA)
    assert abs(btts["yes"] + btts["no"] - 1.0) < 1e-12
    assert btts["yes"] <= min(p_home_scores, p_away_scores) + 1e-12


def test_correct_score_sums_to_one_and_sorted_desc():
    cs = correct_score(LH, LA, rho=-0.08)
    assert abs(sum(c["prob"] for c in cs) - 1.0) < 1e-9
    probs = [c["prob"] for c in cs]
    assert probs == sorted(probs, reverse=True)
    # Every cell of the 11x11 grid is represented exactly once.
    assert len(cs) == 121
    assert {(c["home"], c["away"]) for c in cs} == {(i, j) for i in range(11) for j in range(11)}


def test_correct_score_top_n_truncates():
    cs = correct_score(LH, LA, top_n=5)
    assert len(cs) == 5
    full = correct_score(LH, LA)
    assert cs == full[:5]


def test_asian_handicap_half_line_no_push_and_home_plus_away_one():
    ah = asian_handicap(LH, LA, line=-0.5)
    assert ah["push"] == 0.0
    assert abs(ah["home"] + ah["away"] - 1.0) < 1e-12
    assert ah["line"] == -0.5


def test_asian_handicap_integer_line_three_way_sums_to_one():
    ah = asian_handicap(LH, LA, line=0.0)
    assert abs(ah["home"] + ah["push"] + ah["away"] - 1.0) < 1e-12
    # Level line push == P(draw) on the normalized grid.
    grid = _normalized_grid(LH, LA)
    p_draw = sum(grid[i][i] for i in range(11))
    assert abs(ah["push"] - p_draw) < 1e-12


def test_asian_handicap_quarter_line_is_average_of_bounding_half_steps():
    # +0.25 splits between 0.0 (integer) and +0.5 (half) neighbours.
    q = asian_handicap(LH, LA, line=0.25)
    lo = asian_handicap(LH, LA, line=0.0)
    hi = asian_handicap(LH, LA, line=0.5)
    for k in ("home", "push", "away"):
        assert abs(q[k] - (lo[k] + hi[k]) / 2) < 1e-12
    # -0.75 splits between -0.5 and -1.0.
    q2 = asian_handicap(LH, LA, line=-0.75)
    lo2 = asian_handicap(LH, LA, line=-1.0)
    hi2 = asian_handicap(LH, LA, line=-0.5)
    for k in ("home", "push", "away"):
        assert abs(q2[k] - (lo2[k] + hi2[k]) / 2) < 1e-12


def test_asian_handicap_home_line_shifts_probability_to_home():
    # Giving the home side a +1 head start raises its win chance vs level.
    level = asian_handicap(LH, LA, line=0.0)["home"]
    plus_one = asian_handicap(LH, LA, line=1.0)["home"]
    assert plus_one > level


def test_asian_handicap_lines_returns_row_per_line():
    lines = (-1.0, -0.5, 0.0, 0.5, 1.0)
    rows = asian_handicap_lines(LH, LA, lines=lines)
    assert [r["line"] for r in rows] == list(lines)
    for r in rows:
        assert abs(r["home"] + r["push"] + r["away"] - 1.0) < 1e-12


def test_double_chance_from_triple_sums_correctly():
    dc = double_chance_from_triple(0.5, 0.3, 0.2)
    assert dc["home_or_draw"] == pytest.approx(0.8)
    assert dc["home_or_away"] == pytest.approx(0.7)
    assert dc["draw_or_away"] == pytest.approx(0.5)


def test_derive_scoreline_markets_bundles_all_shapes():
    out = derive_scoreline_markets(LH, LA, rho=-0.08)
    assert set(out) == {"totals", "btts", "correct_score", "asian_handicap"}
    # correct_score bundled form is truncated to the headline top 12.
    assert len(out["correct_score"]) == 12
    assert out["totals"] == over_under(LH, LA, rho=-0.08)
    assert out["btts"] == both_teams_to_score(LH, LA, rho=-0.08)
    assert out["asian_handicap"] == asian_handicap_lines(LH, LA, rho=-0.08)
    # Bundle is built off one shared grid — matches the standalone correct_score.
    assert out["correct_score"] == correct_score(LH, LA, rho=-0.08, top_n=12)
