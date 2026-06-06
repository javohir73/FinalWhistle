"""Probability calibration (PRD §9.5, Goal #2).

The Poisson model is over-confident on big mismatches. Temperature scaling fixes
this: raise each probability to the power 1/T and renormalize. T > 1 softens
(less confident), T < 1 sharpens. We pick the T that minimizes log-loss on a
validation set. A well-calibrated "60%" should happen ~60% of the time.

Also provides a reliability curve for the methodology page.
"""
from __future__ import annotations

import math

Probs = tuple[float, float, float]
_EPS = 1e-15


def apply_temperature(probs: Probs, temperature: float) -> Probs:
    """Soften/sharpen a probability triple by temperature T."""
    powered = [max(_EPS, p) ** (1.0 / temperature) for p in probs]
    total = sum(powered)
    return (powered[0] / total, powered[1] / total, powered[2] / total)


def _log_loss(probs_list: list[Probs], labels: list[int]) -> float:
    n = len(labels) or 1
    return -sum(
        math.log(max(_EPS, min(1 - _EPS, probs[idx])))
        for probs, idx in zip(probs_list, labels)
    ) / n


def fit_temperature(
    probs_list: list[Probs],
    labels: list[int],
    lo: float = 0.5,
    hi: float = 3.0,
    steps: int = 51,
) -> float:
    """Grid-search the temperature that minimizes validation log-loss."""
    best_t, best_ll = 1.0, float("inf")
    for i in range(steps):
        t = lo + (hi - lo) * i / (steps - 1)
        scaled = [apply_temperature(p, t) for p in probs_list]
        ll = _log_loss(scaled, labels)
        if ll < best_ll:
            best_ll, best_t = ll, t
    return round(best_t, 3)


def reliability_curve(
    probs_list: list[Probs], labels: list[int], bins: int = 10
) -> list[dict]:
    """Bin all (predicted prob, was-correct) pairs across classes.

    Returns per-bin {mean_predicted, empirical_freq, count} — the data for a
    reliability/calibration plot. A perfectly calibrated model sits on y = x.
    """
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for probs, idx in zip(probs_list, labels):
        for cls in range(3):
            p = probs[cls]
            b = min(bins - 1, int(p * bins))
            buckets[b].append((p, 1 if cls == idx else 0))

    curve = []
    for b, pairs in enumerate(buckets):
        if not pairs:
            continue
        mean_pred = sum(p for p, _ in pairs) / len(pairs)
        freq = sum(hit for _, hit in pairs) / len(pairs)
        curve.append(
            {"mean_predicted": round(mean_pred, 3),
             "empirical_freq": round(freq, 3),
             "count": len(pairs)}
        )
    return curve
