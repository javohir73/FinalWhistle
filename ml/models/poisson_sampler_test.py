import numpy as np
import pytest

import ml.models.poisson as poisson
from ml.models.poisson import (
    score_cdf, sample_scoreline_from_cdf, sample_scoreline,
    score_matrix, outcome_probabilities,
)


def test_sampler_matches_score_matrix_distribution():
    rng = np.random.default_rng(0)
    lh, la, rho = 1.6, 1.1, -0.06
    cdf = score_cdf(lh, la, rho)
    n = 60000
    hw = d = aw = 0
    for _ in range(n):
        sh, sa = sample_scoreline_from_cdf(rng, cdf)
        if sh > sa: hw += 1
        elif sh == sa: d += 1
        else: aw += 1
    exp_h, exp_d, exp_a = outcome_probabilities(score_matrix(lh, la, rho=rho))
    assert abs(hw / n - exp_h) < 0.02
    assert abs(d / n - exp_d) < 0.02
    assert abs(aw / n - exp_a) < 0.02


def test_cdf_is_normalized_and_monotonic():
    cdf = score_cdf(1.5, 1.2, -0.05)
    assert abs(cdf[-1] - 1.0) < 1e-9
    assert np.all(np.diff(cdf) >= 0)


def test_dixon_coles_raises_draw_rate_vs_plain_poisson():
    _, d_plain, _ = outcome_probabilities(score_matrix(1.3, 1.3, rho=0.0))
    _, d_dc, _ = outcome_probabilities(score_matrix(1.3, 1.3, rho=-0.1))
    assert d_dc > d_plain


def test_score_cdf_raises_on_zero_mass(monkeypatch):
    monkeypatch.setattr(poisson, "score_matrix", lambda *a, **k: [[0.0, 0.0], [0.0, 0.0]])
    with pytest.raises(ValueError):
        score_cdf(1.0, 1.0, 0.0, max_goals=1)


def test_convenience_wrapper_returns_valid_scoreline():
    rng = np.random.default_rng(3)
    sh, sa = sample_scoreline(rng, 1.4, 1.0, -0.05)
    assert 0 <= sh <= poisson.MAX_GOALS and 0 <= sa <= poisson.MAX_GOALS
