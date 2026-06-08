"""Tests for the full-tournament (knockout) Monte-Carlo simulator."""
import numpy as np

from ml.simulate.bracket import (
    R32,
    THIRD_SLOTS,
    GroupFixture,
    _assign_thirds,
    simulate_tournament,
)

GROUP_LETTERS = list("ABCDEFGHIJKL")


def _build_tournament():
    """12 groups of 4 teams (ids 1..48), all distinct Elo, full round-robins."""
    groups = {}
    fixtures = {}
    elos = {}
    tid = 1
    for letter in GROUP_LETTERS:
        members = list(range(tid, tid + 4))
        tid += 4
        groups[letter] = members
        for i, m in enumerate(members):
            elos[m] = 2000 - (m * 7)  # strictly decreasing, distinct
        a, b, c, d = members
        pairs = [(a, b), (c, d), (a, c), (d, b), (d, a), (b, c)]
        fixtures[letter] = [GroupFixture(h, w) for h, w in pairs]
    return elos, groups, fixtures


def test_structure_is_consistent():
    # 12 winners + 12 runners-up + 8 third slots = 32 teams.
    winners = [s for _, h, a in R32 for s in (h, a) if s[0] == "pos" and s[2] == 1]
    runners = [s for _, h, a in R32 for s in (h, a) if s[0] == "pos" and s[2] == 2]
    thirds = [s for _, h, a in R32 for s in (h, a) if s[0] == "third"]
    assert len(winners) == 12
    assert len(runners) == 12
    assert len(thirds) == 8
    assert {s[1] for s in winners} == set(GROUP_LETTERS)
    assert {s[1] for s in runners} == set(GROUP_LETTERS)
    assert len(THIRD_SLOTS) == 8


def test_third_assignment_is_a_valid_matching():
    rng = np.random.default_rng(0)
    # eight distinct qualified groups
    groups = ["A", "B", "C", "D", "E", "F", "G", "H"]
    assignment = _assign_thirds(groups, rng)
    assert len(assignment) == 8  # every slot filled
    assert len(set(assignment.values())) == 8  # each group used once
    slot_elig = dict(THIRD_SLOTS)
    for mno, g in assignment.items():
        assert g in slot_elig[mno]  # respects eligibility


def test_probabilities_valid_and_one_champion():
    elos, groups, fixtures = _build_tournament()
    res = simulate_tournament(elos, groups, fixtures, n_sims=1500, seed=2026)
    assert len(res) == 48
    for r in res.values():
        # monotonic by round, all in [0,1]
        assert 0.0 <= r["win_title"] <= r["reach_final"] <= r["reach_sf"] <= 1.0
        assert r["reach_sf"] <= r["reach_qf"] <= r["reach_r16"] <= r["make_knockout"] <= 1.0
    # exactly one champion per sim -> title probs sum to ~1
    assert abs(sum(r["win_title"] for r in res.values()) - 1.0) < 0.001
    # 16 teams reach the round of 16 each sim -> sum ~16
    assert abs(sum(r["reach_r16"] for r in res.values()) - 16.0) < 0.05
    # 32 teams make the knockout each sim -> sum ~32
    assert abs(sum(r["make_knockout"] for r in res.values()) - 32.0) < 0.05


def test_stronger_teams_more_likely_to_win():
    elos, groups, fixtures = _build_tournament()
    res = simulate_tournament(elos, groups, fixtures, n_sims=1500, seed=1)
    strongest = max(elos, key=elos.get)
    weakest = min(elos, key=elos.get)
    assert res[strongest]["win_title"] > res[weakest]["win_title"]


def test_deterministic_with_seed():
    elos, groups, fixtures = _build_tournament()
    r1 = simulate_tournament(elos, groups, fixtures, n_sims=500, seed=99)
    r2 = simulate_tournament(elos, groups, fixtures, n_sims=500, seed=99)
    assert r1 == r2
