"""Leak-safe paired comparison for a champion and one challenger.

The two predictors are always scored on the same realized matches.  The
primary quantity is per-match challenger log loss minus champion log loss;
negative values favour the challenger.  Optional cluster labels let callers
resample whole tournaments or league-seasons instead of pretending correlated
matches are independent.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

from ml.evaluation.backtest import compute_metrics

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15


@dataclass(frozen=True)
class PromotionPolicy:
    """Evidence required before a shadow model may replace its champion."""

    min_matches: int = 500
    min_clusters: int = 4
    min_coverage: float = 0.90
    max_mean_brier_regression: float = 0.0
    max_accuracy_drop: float = 0.0

    def __post_init__(self) -> None:
        if self.min_matches < 1 or self.min_clusters < 1:
            raise ValueError("minimum matches and clusters must be positive")
        if not 0.0 < self.min_coverage <= 1.0:
            raise ValueError("minimum coverage must be within (0, 1]")
        if self.max_mean_brier_regression < 0.0 or self.max_accuracy_drop < 0.0:
            raise ValueError("guardrail tolerances must be non-negative")


def _normalized(probs: Sequence[float]) -> tuple[float, float, float]:
    if len(probs) != 3:
        raise ValueError("each probability row must contain home/draw/away")
    values = tuple(float(value) for value in probs)
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("probabilities must be finite and non-negative")
    total = sum(values)
    if total <= 0.0:
        raise ValueError("probabilities must have positive mass")
    return tuple(value / total for value in values)  # type: ignore[return-value]


def _losses(
    probs: Sequence[tuple[float, float, float]], labels: Sequence[str]
) -> tuple[list[float], list[float], list[float]]:
    log_losses: list[float] = []
    briers: list[float] = []
    correct: list[float] = []
    for row, label in zip(probs, labels):
        if label not in _LABEL_INDEX:
            raise ValueError(f"unknown result label {label!r}; expected H, D or A")
        idx = _LABEL_INDEX[label]
        log_losses.append(-math.log(max(_EPS, min(1.0 - _EPS, row[idx]))))
        briers.append(
            sum((row[k] - (1.0 if k == idx else 0.0)) ** 2 for k in range(3))
        )
        correct.append(float(max(range(3), key=lambda k: row[k]) == idx))
    return log_losses, briers, correct


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _percentile_interval(samples: list[float]) -> tuple[float, float]:
    samples.sort()
    n = len(samples)
    return samples[int(0.025 * n)], samples[min(n - 1, int(0.975 * n))]


def _bootstrap_mean_ci(
    values: Sequence[float],
    clusters: Sequence[Hashable] | None,
    *,
    n_bootstrap: int,
    seed: int,
) -> tuple[float, float]:
    if n_bootstrap < 100:
        raise ValueError("n_bootstrap must be at least 100")
    rng = random.Random(seed)
    if clusters is None:
        n = len(values)
        samples = [
            _mean([values[rng.randrange(n)] for _ in range(n)])
            for _ in range(n_bootstrap)
        ]
        return _percentile_interval(samples)

    grouped: dict[Hashable, list[float]] = defaultdict(list)
    for cluster, value in zip(clusters, values):
        grouped[cluster].append(value)
    keys = list(grouped)
    samples: list[float] = []
    for _ in range(n_bootstrap):
        drawn: list[float] = []
        for _ in keys:
            drawn.extend(grouped[keys[rng.randrange(len(keys))]])
        samples.append(_mean(drawn))
    return _percentile_interval(samples)


def benchmark_paired_challenger(
    champion_probs: Sequence[Sequence[float]],
    challenger_probs: Sequence[Sequence[float]],
    labels: Sequence[str],
    *,
    clusters: Sequence[Hashable] | None = None,
    n_bootstrap: int = 5000,
    seed: int = 2026,
) -> dict:
    """Compare paired forecasts; negative deltas favour the challenger.

    The promotion verdict is intentionally based on the log-loss confidence
    interval only.  Accuracy and Brier remain visible guardrails, but neither
    is silently combined into an arbitrary composite score.
    """
    n = len(labels)
    if n == 0:
        raise ValueError("no paired predictions to benchmark")
    if len(champion_probs) != n or len(challenger_probs) != n:
        raise ValueError("champion, challenger and labels must have equal length")
    if clusters is not None and len(clusters) != n:
        raise ValueError("clusters must have one label per prediction")

    champion = [_normalized(row) for row in champion_probs]
    challenger = [_normalized(row) for row in challenger_probs]
    champion_ll, champion_brier, champion_correct = _losses(champion, labels)
    challenger_ll, challenger_brier, challenger_correct = _losses(challenger, labels)

    delta_ll = [new - old for old, new in zip(champion_ll, challenger_ll)]
    delta_brier = [new - old for old, new in zip(champion_brier, challenger_brier)]
    delta_accuracy = [new - old for old, new in zip(champion_correct, challenger_correct)]
    ll_ci = _bootstrap_mean_ci(
        delta_ll, clusters, n_bootstrap=n_bootstrap, seed=seed
    )
    brier_ci = _bootstrap_mean_ci(
        delta_brier, clusters, n_bootstrap=n_bootstrap, seed=seed + 1
    )
    accuracy_ci = _bootstrap_mean_ci(
        delta_accuracy, clusters, n_bootstrap=n_bootstrap, seed=seed + 2
    )
    verdict = "no_credible_difference"
    if ll_ci[1] < 0.0:
        verdict = "challenger_beats_champion"
    elif ll_ci[0] > 0.0:
        verdict = "champion_beats_challenger"

    return {
        "n_matches": n,
        # Match-level resampling is useful for descriptive intervals, but it is
        # not evidence of independent competitions/time periods.  Keep that
        # distinction explicit so the promotion gate cannot mistake n matches
        # for n independent clusters.
        "n_clusters": len(set(clusters)) if clusters is not None else None,
        "clusters_explicit": clusters is not None,
        "champion": compute_metrics(champion, list(labels)),
        "challenger": compute_metrics(challenger, list(labels)),
        "delta": {
            "log_loss": _mean(delta_ll),
            "log_loss_ci95": ll_ci,
            "brier": _mean(delta_brier),
            "brier_ci95": brier_ci,
            "accuracy": _mean(delta_accuracy),
            "accuracy_ci95": accuracy_ci,
        },
        "challenger_win_rate": sum(value < 0.0 for value in delta_ll) / n,
        "verdict": verdict,
    }


def promotion_gate(
    benchmark: dict,
    *,
    eligible_matches: int,
    policy: PromotionPolicy = PromotionPolicy(),
) -> dict:
    """Apply minimum evidence and guardrails to a paired benchmark.

    A confidence interval that favours the challenger is necessary but not
    sufficient.  Promotion also requires broad coverage, independent clusters,
    and no mean Brier/accuracy regression beyond the explicit policy.
    """
    paired = int(benchmark.get("n_matches", 0))
    raw_clusters = benchmark.get("n_clusters")
    clusters = int(raw_clusters) if raw_clusters is not None else 0
    if eligible_matches < paired or eligible_matches < 1:
        raise ValueError("eligible_matches must be positive and at least n_matches")
    coverage = paired / eligible_matches
    delta = benchmark.get("delta", {})
    ll_ci = delta.get("log_loss_ci95")
    valid_ll_ci = (
        isinstance(ll_ci, (tuple, list))
        and len(ll_ci) == 2
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in ll_ci)
        and ll_ci[0] <= ll_ci[1]
    )
    brier_delta = delta.get("brier")
    accuracy_delta = delta.get("accuracy")
    valid_brier = isinstance(brier_delta, (int, float)) and math.isfinite(brier_delta)
    valid_accuracy = isinstance(accuracy_delta, (int, float)) and math.isfinite(
        accuracy_delta
    )
    reasons: list[str] = []
    if paired < policy.min_matches:
        reasons.append(f"need at least {policy.min_matches} paired matches")
    if raw_clusters is None or not benchmark.get("clusters_explicit", False):
        reasons.append("explicit independent cluster labels are required")
    elif clusters < policy.min_clusters:
        reasons.append(f"need at least {policy.min_clusters} independent clusters")
    if coverage < policy.min_coverage:
        reasons.append(f"coverage {coverage:.1%} is below {policy.min_coverage:.1%}")
    if not valid_ll_ci:
        reasons.append("log-loss confidence interval must be finite and ordered")
    elif ll_ci[1] >= 0.0:
        reasons.append("log-loss confidence interval does not favour challenger")
    if not valid_brier:
        reasons.append("mean Brier delta must be finite")
    elif brier_delta > policy.max_mean_brier_regression:
        reasons.append("mean Brier score regresses")
    if not valid_accuracy:
        reasons.append("mean accuracy delta must be finite")
    elif accuracy_delta < -policy.max_accuracy_drop:
        reasons.append("mean accuracy regresses")
    return {
        "promote": not reasons,
        "coverage": coverage,
        "reasons": reasons,
        "policy": {
            "min_matches": policy.min_matches,
            "min_clusters": policy.min_clusters,
            "min_coverage": policy.min_coverage,
            "max_mean_brier_regression": policy.max_mean_brier_regression,
            "max_accuracy_drop": policy.max_accuracy_drop,
        },
    }
