"""Tests for the generic champion/challenger evidence gate."""
import pytest

from ml.evaluation.paired_challenger import (
    PromotionPolicy,
    benchmark_paired_challenger,
    promotion_gate,
)


def test_clear_challenger_win_has_negative_deltas_and_passes_gate():
    labels = ["H", "D", "A"] * 20
    champion = [(0.45, 0.30, 0.25), (0.45, 0.30, 0.25), (0.45, 0.30, 0.25)] * 20
    challenger = [(0.75, 0.15, 0.10), (0.15, 0.70, 0.15), (0.10, 0.15, 0.75)] * 20

    result = benchmark_paired_challenger(
        champion, challenger, labels, n_bootstrap=400, seed=7
    )

    assert result["verdict"] == "challenger_beats_champion"
    assert result["n_clusters"] is None
    assert result["clusters_explicit"] is False
    assert result["delta"]["log_loss"] < 0
    assert result["delta"]["brier"] < 0
    assert result["delta"]["accuracy"] > 0


def test_identical_predictions_are_an_honest_null():
    labels = ["H", "D", "A", "H"]
    probs = [(0.5, 0.3, 0.2)] * len(labels)

    result = benchmark_paired_challenger(
        probs, probs, labels, n_bootstrap=200
    )

    assert result["verdict"] == "no_credible_difference"
    assert result["delta"]["log_loss"] == pytest.approx(0.0)
    assert result["delta"]["log_loss_ci95"] == pytest.approx((0.0, 0.0))


def test_cluster_bootstrap_resamples_whole_editions():
    labels = ["H", "A", "H", "A"]
    champion = [(0.6, 0.2, 0.2), (0.6, 0.2, 0.2)] * 2
    challenger = [(0.7, 0.15, 0.15), (0.5, 0.2, 0.3)] * 2

    result = benchmark_paired_challenger(
        champion,
        challenger,
        labels,
        clusters=["2018", "2018", "2022", "2022"],
        n_bootstrap=200,
    )

    assert result["n_matches"] == 4
    assert result["n_clusters"] == 2


@pytest.mark.parametrize(
    "champion, challenger, labels, clusters, message",
    [
        ([], [], [], None, "no paired"),
        ([(0.5, 0.3, 0.2)], [], ["H"], None, "equal length"),
        ([(0.5, 0.3, 0.2)], [(0.5, 0.3, 0.2)], ["X"], None, "unknown"),
        ([(0.5, 0.3, 0.2)], [(0.5, 0.3, 0.2)], ["H"], [], "clusters"),
    ],
)
def test_invalid_inputs_fail_closed(champion, challenger, labels, clusters, message):
    with pytest.raises(ValueError, match=message):
        benchmark_paired_challenger(
            champion,
            challenger,
            labels,
            clusters=clusters,
            n_bootstrap=100,
        )


def test_probability_rows_are_normalized_but_invalid_mass_is_rejected():
    result = benchmark_paired_challenger(
        [(50, 30, 20)], [(60, 25, 15)], ["H"], n_bootstrap=100
    )
    assert result["challenger"]["log_loss"] < result["champion"]["log_loss"]

    with pytest.raises(ValueError, match="positive mass"):
        benchmark_paired_challenger(
            [(0, 0, 0)], [(0.6, 0.25, 0.15)], ["H"], n_bootstrap=100
        )


def test_promotion_gate_requires_sample_clusters_coverage_and_guardrails():
    benchmark = {
        "n_matches": 80,
        "n_clusters": 2,
        "clusters_explicit": True,
        "delta": {
            "log_loss_ci95": (-0.05, -0.01),
            "brier": -0.01,
            "accuracy": 0.02,
        },
    }
    policy = PromotionPolicy(min_matches=100, min_clusters=3, min_coverage=0.9)

    gate = promotion_gate(benchmark, eligible_matches=100, policy=policy)

    assert gate["promote"] is False
    assert len(gate["reasons"]) == 3


def test_promotion_gate_passes_only_when_every_condition_holds():
    benchmark = {
        "n_matches": 100,
        "n_clusters": 4,
        "clusters_explicit": True,
        "delta": {
            "log_loss_ci95": (-0.05, -0.01),
            "brier": -0.01,
            "accuracy": 0.01,
        },
    }
    policy = PromotionPolicy(min_matches=100, min_clusters=4, min_coverage=0.9)

    gate = promotion_gate(benchmark, eligible_matches=105, policy=policy)

    assert gate == {
        "promote": True,
        "coverage": pytest.approx(100 / 105),
        "reasons": [],
        "policy": {
            "min_matches": 100,
            "min_clusters": 4,
            "min_coverage": 0.9,
            "max_mean_brier_regression": 0.0,
            "max_accuracy_drop": 0.0,
        },
    }


def test_promotion_gate_rejects_guardrail_regression_and_bad_denominator():
    benchmark = {
        "n_matches": 100,
        "n_clusters": 4,
        "clusters_explicit": True,
        "delta": {
            "log_loss_ci95": (-0.05, -0.01),
            "brier": 0.001,
            "accuracy": -0.001,
        },
    }

    gate = promotion_gate(
        benchmark,
        eligible_matches=100,
        policy=PromotionPolicy(min_matches=1, min_clusters=1),
    )
    assert gate["promote"] is False
    assert "mean Brier score regresses" in gate["reasons"]
    assert "mean accuracy regresses" in gate["reasons"]

    with pytest.raises(ValueError, match="eligible_matches"):
        promotion_gate(benchmark, eligible_matches=99)


def test_promotion_gate_never_invents_independent_clusters_from_matches():
    result = benchmark_paired_challenger(
        [(0.4, 0.3, 0.3)] * 20,
        [(0.8, 0.1, 0.1)] * 20,
        ["H"] * 20,
        n_bootstrap=200,
    )
    gate = promotion_gate(
        result,
        eligible_matches=20,
        policy=PromotionPolicy(min_matches=1, min_clusters=1),
    )
    assert gate["promote"] is False
    assert "explicit independent cluster labels are required" in gate["reasons"]


def test_promotion_gate_fails_closed_on_nan_or_malformed_metrics():
    benchmark = {
        "n_matches": 100,
        "n_clusters": 4,
        "clusters_explicit": True,
        "delta": {
            "log_loss_ci95": (-0.1, float("nan")),
            "brier": float("nan"),
            "accuracy": float("nan"),
        },
    }
    gate = promotion_gate(
        benchmark,
        eligible_matches=100,
        policy=PromotionPolicy(min_matches=1, min_clusters=1),
    )
    assert gate["promote"] is False
    assert "log-loss confidence interval must be finite and ordered" in gate["reasons"]
    assert "mean Brier delta must be finite" in gate["reasons"]
    assert "mean accuracy delta must be finite" in gate["reasons"]
