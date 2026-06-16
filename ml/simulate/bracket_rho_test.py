import pytest

from ml.simulate.bracket import simulate_tournament, GroupFixture


def _full_groups():
    groups, fixtures, elos = {}, {}, {}
    tid = 1
    for letter in "ABCDEFGHIJKL":
        members = [tid, tid + 1, tid + 2, tid + 3]
        groups[letter] = members
        for t in members:
            elos[t] = 1500 + (t % 7) * 20
        fixtures[letter] = [GroupFixture(members[0], members[1]),
                            GroupFixture(members[2], members[3]),
                            GroupFixture(members[0], members[2])]
        tid += 4
    return elos, groups, fixtures


def test_simulate_tournament_requires_rho_keyword():
    elos, groups, fixtures = _full_groups()
    with pytest.raises(TypeError):
        simulate_tournament(elos, groups, fixtures, n_sims=2)  # no rho=


def test_simulate_tournament_runs_with_rho():
    elos, groups, fixtures = _full_groups()
    res = simulate_tournament(elos, groups, fixtures, n_sims=20, seed=2026, rho=-0.06)
    assert len(res) == 48
    total_title = sum(r["win_title"] for r in res.values())
    assert abs(total_title - 1.0) < 0.001  # exactly one champion per sim
