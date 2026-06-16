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


def test_global_split_ci_uses_edition_clustering(monkeypatch):
    # The global-split ci() must resample editions, not IID matches. We assert the
    # rec carries edition keys and ci() routes through block_bootstrap_ci.
    import pipeline.experiment_model_eval as ev
    calls = {"n": 0}
    real = ev.block_bootstrap_ci

    def spy(values, edition_keys, n_boot, rng, pct=(2.5, 97.5)):
        calls["n"] += 1
        assert len(edition_keys) == len(values)  # tagged per test row
        return real(values, edition_keys, n_boot, rng, pct)

    monkeypatch.setattr(ev, "block_bootstrap_ci", spy)
    from datetime import datetime
    def row(year, ph, pa, sh, sa):
        return {"competition": "FIFA World Cup", "date": datetime(year, 6, 1),
                "pre_home": ph, "pre_away": pa, "is_neutral": True,
                "score_home": sh, "score_away": sa}
    rows = [row(2014, 1600, 1500, 2, 1), row(2014, 1500, 1600, 0, 1),
            row(2018, 1700, 1400, 3, 0), row(2018, 1450, 1450, 1, 1)] * 60
    res = ev.run_global_split(rows, train_lo=2014, train_hi=2014, test_since=2014, n_boot=200)
    assert calls["n"] >= 4  # one per delta metric (log_loss, rps, exact_nll, top5)
    assert "delta" in res
