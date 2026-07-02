"""Tests for the empirical scoreline prior (FR-3.1d/e).

The prior is a historical scoreline-frequency table conditioned on Elo-gap
bucket. The one property that matters above all others is NO LEAKAGE: a table
fitted at date D must contain nothing from D onward — the walk-forward harness
refits it at each tournament edition's first match date.
"""
from __future__ import annotations

from datetime import date, datetime

from ml.evaluation.empirical_prior import DEFAULT_BUCKET_BOUNDS, EmpiricalScorePrior


def _row(d, ph, pa, sh, sa):
    return {"date": d, "pre_home": ph, "pre_away": pa, "score_home": sh, "score_away": sa}


# --- no leakage (the load-bearing property) -----------------------------------

def test_fit_uses_only_matches_strictly_before_the_cutoff():
    # Every match before D is a favorite 1-0; every match ON or AFTER D is a 5-5
    # freak. A table fitted at D must hold zero 5-5 mass in every bucket.
    cutoff = date(2018, 6, 14)
    rows = [_row(date(2010 + i % 8, 3, 1), 1600, 1500, 1, 0) for i in range(40)]
    rows += [_row(cutoff, 1600, 1500, 5, 5)]  # exactly ON the cutoff: excluded too
    rows += [_row(date(2019, 7, 1), 1600, 1500, 5, 5) for _ in range(10)]

    prior = EmpiricalScorePrior().fit(rows, before=cutoff)

    assert prior.n_fitted == 40
    for gap in (0.0, 100.0, 400.0):
        assert prior.prob(gap, 5, 5) == 0.0
    assert prior.prob(100.0, 1, 0) == 1.0  # the only scoreline seen before D


def test_fit_coerces_datetime_rows_like_the_enriched_pipeline():
    # HistoricalMatch.date is a DateTime in prod; plain dates in tests. Both must
    # compare correctly against the cutoff (same _as_date normalization as
    # training_rows).
    cutoff = date(2020, 1, 1)
    rows = [
        _row(datetime(2019, 12, 31, 23, 0), 1600, 1500, 2, 0),  # before: counted
        _row(datetime(2020, 1, 1, 0, 0), 1600, 1500, 5, 5),     # on: excluded
    ]
    prior = EmpiricalScorePrior().fit(rows, before=cutoff)
    assert prior.n_fitted == 1
    assert prior.prob(100.0, 2, 0) == 1.0


# --- gap bucketing -------------------------------------------------------------

def test_default_bucket_boundaries_are_0_50_150():
    prior = EmpiricalScorePrior()
    assert prior.bucket_bounds == DEFAULT_BUCKET_BOUNDS
    assert prior.bucket_index(0.0) == 0
    assert prior.bucket_index(49.9) == 0
    assert prior.bucket_index(50.0) == 1
    assert prior.bucket_index(149.9) == 1
    assert prior.bucket_index(150.0) == 2
    assert prior.bucket_index(700.0) == 2


def test_bucket_boundaries_are_parameterized():
    prior = EmpiricalScorePrior(bucket_bounds=(30.0, 80.0, 200.0))
    assert prior.bucket_index(29.9) == 0
    assert prior.bucket_index(30.0) == 1
    assert prior.bucket_index(79.9) == 1
    assert prior.bucket_index(80.0) == 2
    assert prior.bucket_index(200.0) == 3


def test_matches_are_counted_into_their_own_gap_bucket():
    cutoff = date(2020, 1, 1)
    rows = [
        _row(date(2019, 1, 1), 1510, 1500, 1, 1),   # gap 10  -> bucket 0
        _row(date(2019, 1, 2), 1600, 1500, 2, 0),   # gap 100 -> bucket 1
        _row(date(2019, 1, 3), 1900, 1500, 4, 0),   # gap 400 -> bucket 2
    ]
    prior = EmpiricalScorePrior().fit(rows, before=cutoff)
    assert prior.prob(10.0, 1, 1) == 1.0
    assert prior.prob(10.0, 2, 0) == 0.0   # the 2-0 lives in the 50-150 bucket
    assert prior.prob(100.0, 2, 0) == 1.0
    assert prior.prob(400.0, 4, 0) == 1.0
    assert prior.bucket_n(10.0) == 1 and prior.bucket_n(100.0) == 1


# --- favorite orientation ------------------------------------------------------

def test_scores_are_stored_favorite_first():
    # The favorite (higher pre-Elo side) wins 2-0 twice: once as home, once as
    # away. Both must land on the SAME favorite-oriented cell (2, 0).
    cutoff = date(2020, 1, 1)
    rows = [
        _row(date(2019, 1, 1), 1600, 1500, 2, 0),  # home favorite wins 2-0
        _row(date(2019, 1, 2), 1500, 1600, 0, 2),  # away favorite wins 0-2
    ]
    prior = EmpiricalScorePrior().fit(rows, before=cutoff)
    assert prior.prob(100.0, 2, 0) == 1.0
    assert prior.prob(100.0, 0, 2) == 0.0


def test_equal_elo_ties_orient_home_first():
    cutoff = date(2020, 1, 1)
    prior = EmpiricalScorePrior().fit([_row(date(2019, 1, 1), 1500, 1500, 3, 1)], before=cutoff)
    assert prior.prob(0.0, 3, 1) == 1.0


# --- edge behavior -------------------------------------------------------------

def test_freak_scorelines_fold_into_the_grid_cap():
    # A 31-0 must not blow past the table: it folds into the edge cell, the same
    # convention as scoreline_metrics._clamp_cell.
    cutoff = date(2020, 1, 1)
    prior = EmpiricalScorePrior(max_goals=10).fit(
        [_row(date(2019, 1, 1), 1900, 1200, 31, 0)], before=cutoff)
    assert prior.prob(700.0, 10, 0) == 1.0
    assert prior.prob(700.0, 31, 0) == 1.0  # query side clamps too


def test_unpopulated_bucket_returns_zero_everywhere():
    cutoff = date(2020, 1, 1)
    prior = EmpiricalScorePrior().fit([_row(date(2019, 1, 1), 1600, 1500, 1, 0)], before=cutoff)
    assert prior.bucket_n(400.0) == 0
    assert prior.prob(400.0, 1, 0) == 0.0


def test_bucket_frequencies_sum_to_one_over_seen_scorelines():
    cutoff = date(2020, 1, 1)
    rows = [
        _row(date(2019, 1, 1), 1600, 1500, 1, 0),
        _row(date(2019, 1, 2), 1600, 1500, 1, 0),
        _row(date(2019, 1, 3), 1600, 1500, 2, 1),
        _row(date(2019, 1, 4), 1600, 1500, 0, 0),
    ]
    prior = EmpiricalScorePrior().fit(rows, before=cutoff)
    assert prior.prob(100.0, 1, 0) == 0.5
    assert prior.prob(100.0, 2, 1) == 0.25
    assert prior.prob(100.0, 0, 0) == 0.25
    total = sum(prior.prob(100.0, f, d) for f in range(11) for d in range(11))
    assert abs(total - 1.0) < 1e-12
