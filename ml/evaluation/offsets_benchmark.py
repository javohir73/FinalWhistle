"""Paired production-vs-offsets comparison on realized outcomes.

Once finished matches carry BOTH a production prediction AND an xG-offsets
twin (pipeline.generate_predictions writes the twin tagged
OFFSETS_MODEL_VERSION), this scores whether folding the StatsBomb xG-nudged
team offsets into the forecast improves out-of-sample log-loss — the gate for
ever promoting the twin to the published number
(docs/superpowers/plans/2026-07-04-statsbomb-xg-team-offsets.md).

Pure module — no DB, no network. Orchestration lives in
pipeline/run_offsets_benchmark.py. Clone of ml.evaluation.availability_benchmark
(same bootstrap/CI95 math, seed=26); only dict keys "availability"->"offsets"
and "availability_win_rate"->"offsets_win_rate" renamed.
"""
from __future__ import annotations

import math
import random

from ml.evaluation.backtest import compute_metrics

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15


def _log_loss_one(probs, label: str) -> float:
    p = max(_EPS, min(1.0 - _EPS, probs[_LABEL_INDEX[label]]))
    return -math.log(p)


def benchmark_offsets(
    prod_probs: list, offsets_probs: list, labels: list[str],
    n_bootstrap: int = 2000, seed: int = 26,
) -> dict:
    """Paired (offsets LL - production LL) over the same finished matches.

    diff_log_loss < 0 with diff_ci95 fully below 0 => the xG-offsets-adjusted
    forecast beats the published team-level one out of sample (the promotion
    signal). Straddling 0 => no credible difference.
    """
    if not labels:
        raise ValueError("no matches to benchmark")

    diffs = [
        _log_loss_one(of, lb) - _log_loss_one(pr, lb)
        for pr, of, lb in zip(prod_probs, offsets_probs, labels)
    ]
    rng = random.Random(seed)
    n = len(diffs)
    boot = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_bootstrap)
    )
    lo, hi = boot[int(0.025 * n_bootstrap)], boot[int(0.975 * n_bootstrap)]
    return {
        "n_matches": n,
        "production": compute_metrics(prod_probs, labels),
        "offsets": compute_metrics(offsets_probs, labels),
        "diff_log_loss": sum(diffs) / n,
        "diff_ci95": (lo, hi),
        "offsets_win_rate": sum(1 for d in diffs if d < 0) / n,
    }
