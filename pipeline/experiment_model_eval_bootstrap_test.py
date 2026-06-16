import numpy as np

from pipeline.experiment_model_eval import block_bootstrap_ci


def test_block_bootstrap_is_wider_than_iid_under_within_edition_correlation():
    # 5 editions x 20 matches; every match in edition e has value e -> strong
    # within-edition correlation. IID resampling of 100 points gives a tight CI;
    # resampling whole editions gives a much wider (honest) CI.
    values, editions = [], []
    for e in range(5):
        values += [float(e)] * 20
        editions += [("CompA", 2000 + e)] * 20
    rng = np.random.default_rng(0)
    blo, bhi = block_bootstrap_ci(values, editions, n_boot=2000, rng=rng)

    rng2 = np.random.default_rng(0)
    v = np.array(values); n = len(v)
    idx = rng2.integers(0, n, size=(2000, n))
    iid = v[idx].mean(axis=1)
    ilo, ihi = float(np.percentile(iid, 2.5)), float(np.percentile(iid, 97.5))

    assert (bhi - blo) > 3 * (ihi - ilo)  # block CI dramatically wider


def test_block_bootstrap_resamples_whole_editions():
    # Single edition -> every resample is that whole edition -> mean is constant.
    values = [1.0, 2.0, 3.0, 4.0]
    editions = [("X", 1)] * 4
    rng = np.random.default_rng(1)
    lo, hi = block_bootstrap_ci(values, editions, n_boot=500, rng=rng)
    assert lo == hi == 2.5  # mean of the only edition, every draw
