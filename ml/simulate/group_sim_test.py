"""Tests for the group qualification simulator (task 3.7)."""
from ml.simulate.group_sim import GroupFixture, simulate_group


def _round_robin(ids: list[int]) -> list[GroupFixture]:
    a, b, c, d = ids
    pairs = [(a, b), (c, d), (a, c), (d, b), (d, a), (b, c)]
    return [GroupFixture(h, w) for h, w in pairs]


def test_qualification_probs_in_range_and_two_advance_on_average():
    elos = {1: 2000, 2: 1800, 3: 1600, 4: 1400}
    res = simulate_group(elos, _round_robin([1, 2, 3, 4]), n_sims=2000, seed=42)
    for tid, r in res.items():
        assert 0.0 <= r["qualification_prob"] <= 1.0
    # exactly two qualify each sim -> probabilities sum to ~2
    assert abs(sum(r["qualification_prob"] for r in res.values()) - 2.0) < 0.01


def test_stronger_team_more_likely_to_qualify():
    elos = {1: 2000, 2: 1800, 3: 1600, 4: 1400}
    res = simulate_group(elos, _round_robin([1, 2, 3, 4]), n_sims=2000, seed=7)
    assert res[1]["qualification_prob"] > res[4]["qualification_prob"]
    assert res[1]["avg_points"] > res[4]["avg_points"]


def test_deterministic_with_seed():
    elos = {1: 1900, 2: 1850, 3: 1700, 4: 1500}
    fx = _round_robin([1, 2, 3, 4])
    r1 = simulate_group(elos, fx, n_sims=1000, seed=123)
    r2 = simulate_group(elos, fx, n_sims=1000, seed=123)
    assert r1 == r2
