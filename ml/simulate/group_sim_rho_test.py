import pytest

from ml.simulate.group_sim import simulate_group, GroupFixture


def test_simulate_group_requires_rho_keyword():
    with pytest.raises(TypeError):
        simulate_group({1: 1500, 2: 1500}, [GroupFixture(1, 2)], n_sims=10)  # no rho=


def test_simulate_group_runs_with_rho():
    res = simulate_group(
        {1: 1600, 2: 1400, 3: 1500, 4: 1500},
        [GroupFixture(1, 2), GroupFixture(3, 4), GroupFixture(1, 3)],
        n_sims=300, seed=1, rho=-0.06,
    )
    assert set(res) == {1, 2, 3, 4}
    assert all(0.0 <= res[t]["qualification_prob"] <= 1.0 for t in res)
