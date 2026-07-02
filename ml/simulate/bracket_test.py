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


def test_played_results_lock_group_outcomes():
    elos, groups, fixtures = _build_tournament()
    # Group A fully decided in reality: the WEAKEST member won all three games,
    # the Elo favourite lost all three. Knockout odds must respect the facts.
    a, b, c, d = groups["A"]
    pairs = [(a, b), (c, d), (a, c), (d, b), (d, a), (b, c)]
    scores = [(0, 2), (0, 1), (0, 1), (1, 0), (2, 0), (2, 0)]
    fixtures["A"] = [GroupFixture(h, w, score=s) for (h, w), s in zip(pairs, scores)]

    res = simulate_tournament(elos, groups, fixtures, n_sims=300, seed=5, rho=0.0)
    assert res[d]["make_knockout"] == 1.0  # real group winner — locked
    assert res[b]["make_knockout"] == 1.0  # real runner-up — locked
    assert res[a]["make_knockout"] == 0.0  # finished last with 0 points
    # The favourite's title odds are gone despite the highest Elo in the group.
    assert res[a]["win_title"] == 0.0


def _build_locked_tournament():
    """Full 12-group stage with every fixture PLAYED and a deterministic order.

    In each group members are (a, b, c, d); results force the standing a>b>c>d,
    with the third-placed team (c) given a group-specific winning margin so the
    twelve thirds are strictly ranked A>B>...>L (top-8 thirds = groups A..H,
    fully determined, not tie-broken by rng)."""
    groups, fixtures, elos = {}, {}, {}
    tid = 1
    for i, letter in enumerate(GROUP_LETTERS):
        a, b, c, d = range(tid, tid + 4)
        tid += 4
        groups[letter] = [a, b, c, d]
        for m in (a, b, c, d):
            elos[m] = 2000 - m * 7
        margin = 12 - i  # c beats d by this many — distinct GD per group
        pairs_scores = [
            ((a, b), (2, 0)),        # a beats b
            ((c, d), (margin, 0)),   # c beats d by `margin`
            ((a, c), (1, 0)),        # a beats c
            ((d, b), (0, 1)),        # b beats d
            ((d, a), (0, 1)),        # a beats d
            ((b, c), (1, 0)),        # b beats c
        ]
        fixtures[letter] = [GroupFixture(h, w, score=s) for (h, w), s in pairs_scores]
    return elos, groups, fixtures


def test_played_knockout_winner_locked_and_loser_pinned():
    elos, groups, fixtures = _build_locked_tournament()
    # Match 73 = (Group A runner-up) vs (Group B runner-up): a pure position
    # pairing, so the two teams are fixed once the groups are decided. Record a
    # played result — the winner must reach the R16 in every draw, the loser never.
    a2, b2 = groups["A"][1], groups["B"][1]
    res = simulate_tournament(
        elos, groups, fixtures, n_sims=200, seed=7, rho=0.0,
        ko_results={73: (a2, b2, a2)},
    )
    assert res[a2]["reach_r16"] == 1.0     # winner advances in every draw
    assert res[b2]["reach_r16"] == 0.0     # loser is out in every draw
    assert res[a2]["make_knockout"] == 1.0
    assert res[b2]["make_knockout"] == 1.0


def test_played_knockout_pins_third_place_loser():
    elos, groups, fixtures = _build_locked_tournament()
    # Match 82 = (Group G winner) vs (a third-placed team). Group A's third is the
    # strongest third, so it always qualifies; the random third-slot assignment
    # would otherwise let it advance from a different slot. A played result must
    # pin it into slot 82 and OUT of the R16 in every draw.
    g1 = groups["G"][0]        # group G winner (pos side)
    a3 = groups["A"][2]        # best third; eligible for slot 82
    res = simulate_tournament(
        elos, groups, fixtures, n_sims=300, seed=11, rho=0.0,
        ko_results={82: (g1, a3, g1)},
    )
    assert res[g1]["reach_r16"] == 1.0
    assert res[a3]["reach_r16"] == 0.0
    assert res[a3]["make_knockout"] == 1.0   # it did qualify, as a third


def test_played_knockout_preserves_monotonicity():
    elos, groups, fixtures = _build_locked_tournament()
    a2, b2 = groups["A"][1], groups["B"][1]
    g1, a3 = groups["G"][0], groups["A"][2]
    res = simulate_tournament(
        elos, groups, fixtures, n_sims=400, seed=3, rho=0.0,
        ko_results={73: (a2, b2, a2), 82: (g1, a3, g1)},
    )
    for r in res.values():
        assert 0.0 <= r["win_title"] <= r["reach_final"] <= r["reach_sf"] <= 1.0
        assert r["reach_sf"] <= r["reach_qf"] <= r["reach_r16"] <= r["make_knockout"] <= 1.0


def test_probabilities_valid_and_one_champion():
    elos, groups, fixtures = _build_tournament()
    res = simulate_tournament(elos, groups, fixtures, n_sims=1500, seed=2026, rho=0.0)
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
    res = simulate_tournament(elos, groups, fixtures, n_sims=1500, seed=1, rho=0.0)
    strongest = max(elos, key=elos.get)
    weakest = min(elos, key=elos.get)
    assert res[strongest]["win_title"] > res[weakest]["win_title"]


def test_deterministic_with_seed():
    elos, groups, fixtures = _build_tournament()
    r1 = simulate_tournament(elos, groups, fixtures, n_sims=500, seed=99, rho=0.0)
    r2 = simulate_tournament(elos, groups, fixtures, n_sims=500, seed=99, rho=0.0)
    assert r1 == r2


def test_team_offsets_shift_knockout_odds_and_default_is_identity():
    """Per-team attack/defence offsets (FR-5.3) must reach the tournament
    Monte-Carlo too: reach_*/win_title must be simulated from the SAME
    offset-adjusted lambdas the match cards use — in the group stage AND in the
    knockout rounds. Omitted/None/empty offsets stay bit-identical, so the
    dormant flag remains a strict no-op."""
    elos, groups, fixtures = _build_tournament()
    base = simulate_tournament(elos, groups, fixtures, n_sims=400, seed=13, rho=0.0)
    assert simulate_tournament(elos, groups, fixtures, n_sims=400, seed=13, rho=0.0,
                               team_offsets=None) == base
    assert simulate_tournament(elos, groups, fixtures, n_sims=400, seed=13, rho=0.0,
                               team_offsets={}) == base
    # A big attack (+) / defence (-) edge turns the weakest team into a
    # contender: both its group-exit and its title odds must rise.
    weakest = min(elos, key=elos.get)
    boosted = simulate_tournament(elos, groups, fixtures, n_sims=400, seed=13, rho=0.0,
                                  team_offsets={weakest: (0.7, -0.7)})
    assert boosted[weakest]["make_knockout"] > base[weakest]["make_knockout"]
    assert boosted[weakest]["win_title"] > base[weakest]["win_title"]
