import pytest

from ml.models.params import DEFAULT_PARAMS
from pipeline.promote_blend import promoted_params


def test_promoted_params_sets_capped_w_odds_and_version():
    out = promoted_params(DEFAULT_PARAMS, w_odds=0.35, use_availability=False,
                          version="poisson-elo-v0.6")
    assert out.w_odds == 0.35
    assert out.version == "poisson-elo-v0.6"
    assert out.use_availability is False


def test_promoted_params_rejects_weight_above_cap():
    with pytest.raises(ValueError):
        promoted_params(DEFAULT_PARAMS, w_odds=0.51, use_availability=False,
                        version="poisson-elo-v0.6")


def test_promoted_params_rejects_nonpositive_weight_without_availability():
    with pytest.raises(ValueError):
        promoted_params(DEFAULT_PARAMS, w_odds=0.0, use_availability=False,
                        version="poisson-elo-v0.6")


def test_promoted_params_availability_only_flip_is_allowed():
    out = promoted_params(DEFAULT_PARAMS, w_odds=0.0, use_availability=True,
                          version="poisson-elo-v0.6")
    assert out.w_odds == 0.0
    assert out.use_availability is True
