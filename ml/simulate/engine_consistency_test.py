import numpy as np

from ml.models.poisson import score_cdf, sample_scoreline_from_cdf, score_matrix, outcome_probabilities


def test_sampler_wdl_matches_predict_match_engine():
    """The sims and the match cards now speak one language: the sampler's implied
    W/D/L over many draws == the card engine's W/D/L for the same (lambda, rho)."""
    rng = np.random.default_rng(11)
    lh, la, rho = 1.7, 0.9, -0.06
    exp_h, exp_d, exp_a = outcome_probabilities(score_matrix(lh, la, rho=rho))
    cdf = score_cdf(lh, la, rho)
    n = 80000
    hw = d = aw = 0
    for _ in range(n):
        sh, sa = sample_scoreline_from_cdf(rng, cdf)
        if sh > sa: hw += 1
        elif sh == sa: d += 1
        else: aw += 1
    assert abs(hw / n - exp_h) < 0.015
    assert abs(d / n - exp_d) < 0.015
    assert abs(aw / n - exp_a) < 0.015
