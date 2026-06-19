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

# Effective-Elo-gap segmentation for draw-aware calibration. The probability
# engine responds to (elo_home + home_adv) - elo_away (see poisson.py
# expected_goals_from_elo), so the calibrator buckets on that, NOT the raw gap —
# otherwise a host-boosted close match is mis-bucketed. Both the gate (fit) and
# the serving path bucket through these two helpers, so they cannot drift.
_GAP_EDGES = (50.0, 150.0, 300.0)
_GAP_BUCKETS = ("0-50", "50-150", "150-300", "300+")


def effective_gap(elo_home: float, elo_away: float, home_adv: float) -> float:
    """Absolute effective Elo gap the engine actually responds to."""
    return abs((elo_home + home_adv) - elo_away)


def gap_bucket(eff_gap: float) -> str:
    """Map an effective gap to one of the four coarse buckets."""
    for edge, name in zip(_GAP_EDGES, _GAP_BUCKETS):
        if eff_gap < edge:
            return name
    return _GAP_BUCKETS[-1]


def apply_temperature(probs: Probs, temperature: float) -> Probs:
    """Soften/sharpen a probability triple by temperature T."""
    powered = [max(_EPS, p) ** (1.0 / temperature) for p in probs]
    total = sum(powered)
    return (powered[0] / total, powered[1] / total, powered[2] / total)


def apply_vector_scaling(probs: Probs, t: float, b: Probs) -> Probs:
    """Vector-scale a W/D/L triple in log-space.

        z_c  = log(max(eps, p_c)) / t + b_c
        p'_c = softmax(z)

    `t` is a shared temperature; `b = (b_home, b_draw, b_away)` are per-class
    biases (fix b_home = 0 as the softmax reference). Unlike scalar temperature
    this can reshape the triple — e.g. b_draw > 0 lifts the under-predicted draw
    class. At t = 1 and b = (0, 0, 0) it is the identity (softmax of logs of a
    normalized triple returns the triple).
    """
    z = [math.log(max(_EPS, p)) / t + bc for p, bc in zip(probs, b)]
    m = max(z)  # shift for numerical stability; softmax is shift-invariant
    exps = [math.exp(zc - m) for zc in z]
    total = sum(exps)
    return (exps[0] / total, exps[1] / total, exps[2] / total)


def calibrate(probs: Probs, calibrator: dict | None, temperature: float = 1.0,
              *, eff_gap: float | None = None) -> Probs:
    """Apply the shipped calibrator to a W/D/L triple — the one shared helper for
    the card path. `calibrator` is one of:
      - None: scalar `temperature` fallback (t=1 is the identity);
      - {"method": "vector_scaling", "t", "b"}: one global vector scaling;
      - {"method": "vector_scaling_segmented", "buckets": {bucket: {t,b}}, "default": {t,b}}:
        per effective-Elo-gap bucket. `eff_gap` selects the bucket via gap_bucket();
        a missing bucket or a None eff_gap falls back to "default".
    The global and None paths ignore `eff_gap`, so existing callers are unchanged."""
    if calibrator and calibrator.get("method") == "vector_scaling_segmented":
        key = gap_bucket(eff_gap) if eff_gap is not None else None
        cell = calibrator["buckets"].get(key) if key is not None else None
        if cell is None:
            cell = calibrator["default"]
        return apply_vector_scaling(probs, cell["t"], tuple(cell["b"]))
    if calibrator and calibrator.get("method") == "vector_scaling":
        return apply_vector_scaling(probs, calibrator["t"], tuple(calibrator["b"]))
    return apply_temperature(probs, temperature)


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


def fit_vector_scaling(
    probs_list: list[Probs],
    labels: list[int],
    t_lo: float = 0.5,
    t_hi: float = 3.0,
    t_steps: int = 26,
    b_lo: float = -1.5,
    b_hi: float = 1.5,
    b_steps: int = 31,
    passes: int = 3,
) -> tuple[float, Probs]:
    """Fit (T, b_draw, b_away) minimizing validation log-loss by coordinate
    descent over bounded grids. b_home is fixed at 0 (softmax reference). A few
    passes (default 3) converge the three coordinates; each grid needs >= 2
    points. Returns (t, (0.0, b_draw, b_away))."""
    if t_steps < 2 or b_steps < 2:
        raise ValueError("t_steps and b_steps must each be >= 2")
    t, b_draw, b_away = 1.0, 0.0, 0.0

    def ll(tt: float, bd: float, ba: float) -> float:
        scaled = [apply_vector_scaling(p, tt, (0.0, bd, ba)) for p in probs_list]
        return _log_loss(scaled, labels)

    def grid(lo: float, hi: float, steps: int) -> list[float]:
        return [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]

    for _ in range(passes):
        t = min(grid(t_lo, t_hi, t_steps), key=lambda x: ll(x, b_draw, b_away))
        b_draw = min(grid(b_lo, b_hi, b_steps), key=lambda x: ll(t, x, b_away))
        b_away = min(grid(b_lo, b_hi, b_steps), key=lambda x: ll(t, b_draw, x))
    return round(t, 3), (0.0, round(b_draw, 3), round(b_away, 3))


def fit_segmented_vector_scaling(
    probs_list: list[Probs],
    labels: list[int],
    eff_gaps: list[float],
    min_bucket: int = 200,
) -> dict:
    """Fit one vector-scaling (t, b_draw, b_away) per effective-gap bucket.

    A global fit over all rows is always computed and stored as "default"; any
    bucket with fewer than `min_bucket` rows inherits it (sparse buckets degrade
    gracefully instead of over-fitting). Returns a vector_scaling_segmented blob."""
    gt, gb = fit_vector_scaling(probs_list, labels)
    default = {"t": gt, "b": list(gb)}

    by_bucket: dict[str, list[int]] = {}
    for i, g in enumerate(eff_gaps):
        by_bucket.setdefault(gap_bucket(g), []).append(i)

    buckets: dict[str, dict] = {}
    for name in _GAP_BUCKETS:
        ix = by_bucket.get(name, [])
        if len(ix) >= min_bucket:
            t, b = fit_vector_scaling([probs_list[i] for i in ix], [labels[i] for i in ix])
            buckets[name] = {"t": t, "b": list(b)}
        else:
            buckets[name] = default
    return {
        "method": "vector_scaling_segmented",
        "by": "effective_elo_gap",
        "buckets": buckets,
        "default": default,
    }


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
