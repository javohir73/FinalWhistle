from ml.simulate.bracket import simulate_tournament
from ml.simulate.bracket_rho_test import _full_groups


def test_host_team_gets_a_knockout_boost_at_its_venue():
    elos, groups, fixtures = _full_groups()
    elos[1] = 1700  # team 1 a clear group winner
    ko_host = {mno: 1 for mno in range(73, 105)}  # team 1 hosts every KO match
    base = simulate_tournament(elos, groups, fixtures, n_sims=400, seed=7,
                               rho=-0.06, home_adv=0.0, ko_host_by_match={})
    boosted = simulate_tournament(elos, groups, fixtures, n_sims=400, seed=7,
                                  rho=-0.06, home_adv=80.0, ko_host_by_match=ko_host)
    assert boosted[1]["win_title"] > base[1]["win_title"]


def test_no_host_map_is_neutral():
    elos, groups, fixtures = _full_groups()
    a = simulate_tournament(elos, groups, fixtures, n_sims=200, seed=5,
                            rho=-0.06, home_adv=80.0, ko_host_by_match={})
    b = simulate_tournament(elos, groups, fixtures, n_sims=200, seed=5,
                            rho=-0.06, home_adv=0.0, ko_host_by_match={})
    assert a == b  # empty map -> home_adv never applied -> identical
