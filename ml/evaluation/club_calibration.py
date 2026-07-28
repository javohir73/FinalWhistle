"""T1.6 — club calibrator recut. Shadow-only, nested, holdout-safe.

The served calibrator (`ml/models/model_params.json`) is a
vector_scaling_segmented blob fitted on INTERNATIONAL tournament football and
applied unchanged to club leagues. The 2026-07-28 post-merge audit measured it
COSTING club 1X2 log loss in 3 of 4 configurations tested. T1.6 was
pre-registered and never run; this is that run.

Two things this module adds over `ml/evaluation/calibration.py`:

1. **Edges as a fitted parameter.** `calibration._GAP_EDGES` is a module
   constant, so the serving bucket boundaries cannot be varied without changing
   what production does. Here edges travel INSIDE the blob, so a recut can be
   evaluated without touching the serving path. A blob produced here is not
   servable until `calibration.calibrate` learns to read `edges` — deliberately
   out of scope.
2. **A hard holdout guard.** `CONFIRM_SEASON` was consumed by the #202
   confirmation run. `assert_holdout_absent` raises if a single row from it
   reaches any function here. The experiment also drops it at load, so the
   guard is a backstop for a mistake, not the only line of defence.

Pure module — no DB, no network.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Sequence

from ml.evaluation.calibration import (
    _GAP_EDGES,
    Probs,
    apply_vector_scaling,
    fit_vector_scaling,
)

# The season the #202 confirmation run consumed. Nothing in T1.6 may read it.
CONFIRM_SEASON = "2526"

_EPS = 1e-15
_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}


class HoldoutViolation(AssertionError):
    """Raised when consumed-holdout data reaches a T1.6 code path."""


def assert_holdout_absent(seasons: Sequence[str], where: str) -> None:
    """Backstop guard. Raises rather than warns: a silent holdout read would
    invalidate the whole experiment and there is no safe way to continue."""
    if any(s == CONFIRM_SEASON for s in seasons):
        raise HoldoutViolation(
            f"{where}: season {CONFIRM_SEASON} was consumed by the #202 "
            "confirmation run and must never be scored, fitted, or inspected "
            "again. The next clean holdout is the live 2026-27 season."
        )


# --- edges-aware bucketing -------------------------------------------------

def bucket_names(edges: Sequence[float]) -> list[str]:
    """Human-readable bucket labels for ``edges`` (ascending, exclusive)."""
    names, lo = [], 0.0
    for e in edges:
        names.append(f"{lo:g}-{e:g}")
        lo = e
    names.append(f"{lo:g}+")
    return names


def bucket_of(eff_gap: float, edges: Sequence[float]) -> str:
    names = bucket_names(edges)
    for edge, name in zip(edges, names):
        if eff_gap < edge:
            return name
    return names[-1]


def quantile_edges(gaps: Sequence[float], n_buckets: int) -> list[float]:
    """Equal-count edges from the TRAINING gap distribution.

    The served edges (50/150/300) were chosen for international matchups. Club
    gaps sit lower and tighter, so equal-count cuts give every bucket a usable
    sample instead of leaving one nearly empty.
    """
    if n_buckets < 2:
        raise ValueError("n_buckets must be >= 2")
    s = sorted(gaps)
    return [round(s[int(len(s) * k / n_buckets)], 1) for k in range(1, n_buckets)]


# --- fit / apply -----------------------------------------------------------

def fit_segmented(
    probs_list: Sequence[Probs],
    labels: Sequence[int],
    eff_gaps: Sequence[float],
    edges: Sequence[float],
    min_bucket: int = 200,
) -> dict:
    """Fit one vector scaling per bucket, with ``edges`` recorded in the blob.

    Mirrors calibration.fit_segmented_vector_scaling (same coordinate-descent
    fitter, same graceful degradation) but carries explicit edges. Any bucket
    with fewer than ``min_bucket`` training rows inherits the global fit rather
    than over-fitting a thin slice.
    """
    gt, gb = fit_vector_scaling(list(probs_list), list(labels))
    default = {"t": gt, "b": list(gb)}

    by_bucket: dict[str, list[int]] = {}
    for i, g in enumerate(eff_gaps):
        by_bucket.setdefault(bucket_of(g, edges), []).append(i)

    buckets, thin = {}, []
    for name in bucket_names(edges):
        ix = by_bucket.get(name, [])
        if len(ix) >= min_bucket:
            t, b = fit_vector_scaling([probs_list[i] for i in ix],
                                      [labels[i] for i in ix])
            buckets[name] = {"t": t, "b": list(b)}
        else:
            buckets[name] = dict(default)
            thin.append(name)
    return {
        "method": "vector_scaling_segmented_edges",
        "by": "effective_elo_gap",
        "edges": [float(e) for e in edges],
        "buckets": buckets,
        "default": default,
        "n_train": len(labels),
        "thin_buckets": thin,
    }


def apply_blob(probs: Probs, blob: dict | None, eff_gap: float) -> Probs:
    """Apply a blob from ``fit_segmented`` (or None for the identity)."""
    if blob is None:
        return probs
    cell = blob["buckets"].get(bucket_of(eff_gap, blob["edges"]), blob["default"])
    return apply_vector_scaling(probs, cell["t"], tuple(cell["b"]))


def occupancy(eff_gaps: Sequence[float], edges: Sequence[float]) -> dict[str, int]:
    c = Counter(bucket_of(g, edges) for g in eff_gaps)
    return {n: c.get(n, 0) for n in bucket_names(edges)}


# --- pre-registered candidate family (T1.6) --------------------------------
# Declared here so the multiplicity count is fixed before any run: every member
# is scored on every outer season, and none may be added post hoc.
CANDIDATES: dict[str, dict] = {
    "prod_calibrator": {"kind": "served"},
    "no_calibrator": {"kind": "none"},
    "refit_served_edges": {"kind": "refit", "edges": list(_GAP_EDGES), "min_bucket": 200},
    "refit_q3": {"kind": "refit", "n_buckets": 3, "min_bucket": 200},
    "refit_q4": {"kind": "refit", "n_buckets": 4, "min_bucket": 200},
    "refit_q4_thin": {"kind": "refit", "n_buckets": 4, "min_bucket": 100},
}
#: Members of the recut FAMILY (used for the multiplicity correction). The two
#: fixed references are not part of the search.
REFIT_FAMILY = tuple(k for k, v in CANDIDATES.items() if v["kind"] == "refit")


# --- metrics ---------------------------------------------------------------

def log_loss_one(p: Probs, i: int) -> float:
    return -math.log(max(_EPS, min(1 - _EPS, p[i])))


def brier_one(p: Probs, i: int) -> float:
    return sum((p[k] - (1.0 if k == i else 0.0)) ** 2 for k in range(3))


def rps_one(p: Probs, i: int) -> float:
    """Ranked probability score on the ordered H/D/A scale."""
    cp = co = tot = 0.0
    for k in range(2):
        cp += p[k]
        co += 1.0 if k == i else 0.0
        tot += (cp - co) ** 2
    return tot / 2.0


def ece(pairs: Sequence[tuple[float, float]], bins: int = 10) -> float:
    """Reliability gap on the predicted-favourite probability."""
    if not pairs:
        return float("nan")
    b: dict[int, list[tuple[float, float]]] = {}
    for conf, hit in pairs:
        b.setdefault(min(int(conf * bins), bins - 1), []).append((conf, hit))
    n = len(pairs)
    return sum(
        len(v) / n * abs(sum(c for c, _ in v) / len(v) - sum(h for _, h in v) / len(v))
        for v in b.values()
    )
