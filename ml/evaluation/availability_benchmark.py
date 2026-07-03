"""Paired production-vs-availability comparison on realized outcomes.

Once finished matches carry BOTH a production prediction AND an availability twin
(pipeline.generate_predictions writes the twin tagged AVAILABILITY_MODEL_VERSION),
this scores whether folding announced-XI availability into the forecast improves
out-of-sample log-loss — the gate for ever promoting the twin to the published
number (docs/superpowers/specs/2026-07-03-availability-signal-design.md).

Pure module — no DB, no network. Orchestration lives in
pipeline/run_availability_benchmark.py. Mirrors market_benchmark.benchmark's shape,
but compares two model predictors against the outcome instead of model vs market.
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


def benchmark_availability(
    prod_probs: list, avail_probs: list, labels: list[str],
    n_bootstrap: int = 2000, seed: int = 26,
) -> dict:
    """Paired (availability LL - production LL) over the same finished matches.

    diff_log_loss < 0 with diff_ci95 fully below 0 => the availability-adjusted
    forecast beats the published team-level one out of sample (the promotion
    signal). Straddling 0 => no credible difference.

    Caveat: if a W/D/L booster blend (``params.wdl_blend``) is ever shipped, the
    published production triple would be booster-blended while the availability
    twin stays pure Poisson (like the odds shadow, per write_shadow_prediction's
    NOTE), so this paired reading would mix the availability effect with the
    blend effect. Not a live concern today — ``wdl_blend`` is not currently shipped.
    """
    if not labels:
        raise ValueError("no matches to benchmark")

    diffs = [
        _log_loss_one(av, lb) - _log_loss_one(pr, lb)
        for pr, av, lb in zip(prod_probs, avail_probs, labels)
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
        "availability": compute_metrics(avail_probs, labels),
        "diff_log_loss": sum(diffs) / n,
        "diff_ci95": (lo, hi),
        "availability_win_rate": sum(1 for d in diffs if d < 0) / n,
    }
