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


def test_finished_match_counts_as_fact_not_probability():
    # The weakest team (1) actually UPSET the strongest (2) 2–0. Every draw
    # must credit those 3 points as fact — never re-roll the played game.
    elos = {1: 1400, 2: 2000, 3: 1600, 4: 1500}
    fx = _round_robin([1, 2, 3, 4])
    fx[0] = GroupFixture(1, 2, score=(2, 0))  # pair (1, 2) already played
    res = simulate_group(elos, fx, n_sims=400, seed=11)
    assert res[1]["avg_points"] >= 3.0  # the win is locked in
    assert res[2]["avg_points"] <= 6.0  # only two games left to win


def test_fully_played_group_is_deterministic():
    # All six games played: team 4 (lowest Elo) won everything, team 1
    # (highest Elo) lost everything. The table must be the real table —
    # if any sampling leaked in, the Elo favourite couldn't end on 0.0.
    elos = {1: 2000, 2: 1800, 3: 1600, 4: 1400}
    scores = [(0, 2), (0, 1), (0, 1), (1, 0), (2, 0), (2, 0)]
    # pairs: (1,2) (3,4) (1,3) (4,2) (4,1) (2,3)
    fx = [GroupFixture(f.home_id, f.away_id, score=s)
          for f, s in zip(_round_robin([1, 2, 3, 4]), scores)]
    res = simulate_group(elos, fx, n_sims=200, seed=3)
    assert res[4] == {"qualification_prob": 1.0, "avg_points": 9.0, "avg_gd": 4.0, "avg_gf": 4.0}
    assert res[1]["qualification_prob"] == 0.0
    assert res[1]["avg_points"] == 0.0
    assert res[2]["qualification_prob"] == 1.0  # 6 points, clear runner-up
    assert res[3]["avg_points"] == 3.0
