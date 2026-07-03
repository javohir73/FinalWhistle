"""Tests for the paired production-vs-availability benchmark."""
import pytest

from ml.evaluation.availability_benchmark import benchmark_availability


def test_availability_beats_production_when_closer_to_outcomes():
    # Home always wins ("H"); availability puts more mass on H than production.
    labels = ["H"] * 40
    prod = [(0.40, 0.30, 0.30)] * 40
    avail = [(0.70, 0.20, 0.10)] * 40
    res = benchmark_availability(avail_probs=avail, prod_probs=prod, labels=labels)
    assert res["diff_log_loss"] < 0            # availability LL - production LL < 0
    assert res["diff_ci95"][1] < 0             # whole CI below 0 => credible
    assert res["availability_win_rate"] == 1.0
    assert res["n_matches"] == 40


def test_identical_predictors_have_zero_diff():
    labels = ["H", "D", "A"] * 10
    p = [(0.4, 0.3, 0.3)] * 30
    res = benchmark_availability(prod_probs=p, avail_probs=p, labels=labels)
    assert res["diff_log_loss"] == 0.0


def test_raises_on_empty():
    with pytest.raises(ValueError):
        benchmark_availability(prod_probs=[], avail_probs=[], labels=[])
