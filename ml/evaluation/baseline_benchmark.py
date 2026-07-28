"""Paired promoted-params-vs-previous-params comparison on realized outcomes.

Once finished matches carry BOTH a published prediction AND a "+baseline" twin
(pipeline.generate_predictions writes it when ``baseline_params`` is passed),
this scores whether the promoted parameters actually beat the ones they
replaced, out of sample, in live conditions.

Unlike the availability/offsets twins this is not a feature gate — the
promotion has already happened. It is the live receipt behind a params-only
promotion whose offline evidence is a single confirmation season: the club
v0.1 -> v0.2 per-league refit (docs/MODEL-EXPERIMENTS.md, "Club program"),
where three of five candidate changes died on the held-out season and the two
survivors rest on n=306 and n=380 unseen matches respectively.

Deliberately DELEGATES the bootstrap math to availability_benchmark rather
than cloning it. ml/evaluation/offsets_benchmark.py is already a full copy of
that module with the dict keys renamed; a third copy of the same resampling
code would be three places to fix a bug in. Only the key names differ here, so
only the key names are written here.

Pure module — no DB, no network. Orchestration lives in
pipeline/run_baseline_benchmark.py.
"""
from __future__ import annotations

from ml.evaluation.availability_benchmark import benchmark_availability


def benchmark_baseline(
    served_probs: list, baseline_probs: list, labels: list[str],
    n_bootstrap: int = 2000, seed: int = 26,
) -> dict:
    """Paired (served LL - baseline LL) over the same finished matches.

    NOTE THE SIGN, which is inverted relative to the feature-twin benchmarks.
    There the twin is the challenger and a NEGATIVE diff favours it. Here the
    twin is the OLD model and the served params are what we already promoted,
    so ``diff_log_loss`` < 0 with the CI fully below zero means **the
    promotion was right**; above zero means the previous params were better
    and the promotion should be reconsidered.

    Same bootstrap, same seed, same CI convention as every other twin
    benchmark in this package.
    """
    # benchmark_availability computes (second arg LL - first arg LL), so
    # passing (baseline, served) yields served-minus-baseline.
    res = benchmark_availability(
        prod_probs=baseline_probs, avail_probs=served_probs, labels=labels,
        n_bootstrap=n_bootstrap, seed=seed,
    )
    return {
        "n_matches": res["n_matches"],
        "baseline": res["production"],
        "served": res["availability"],
        "diff_log_loss": res["diff_log_loss"],
        "diff_ci95": res["diff_ci95"],
        "served_win_rate": res["availability_win_rate"],
    }
