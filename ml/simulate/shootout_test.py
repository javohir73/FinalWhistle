from ml.simulate.bracket import shootout_p, fit_pk_beta


def test_equal_teams_are_a_coin_flip():
    assert abs(shootout_p(1500, 1500, pk_beta=0.002) - 0.5) < 1e-9


def test_favorite_edge_is_capped_well_below_old_value():
    # Old PK_BETA=0.0025 gave ~0.562 for a 100-Elo gap. Capped band [0.45, 0.55].
    p = shootout_p(1600, 1500, pk_beta=0.0025)
    assert p <= 0.55
    assert 0.50 < p  # still favors the stronger side a touch


def test_zero_beta_is_pure_coin_flip():
    assert shootout_p(1700, 1400, pk_beta=0.0) == 0.5


def test_fit_pk_beta_shrinks_toward_zero_on_thin_data():
    samples = [(200, True), (150, True), (-100, False)]  # (elo_gap, favorite_won)
    assert abs(fit_pk_beta(samples)) < 0.001


def test_fit_pk_beta_returns_zero_on_empty():
    assert fit_pk_beta([]) == 0.0
