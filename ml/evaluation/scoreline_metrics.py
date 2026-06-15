"""Proper scoring metrics for match-outcome and exact-scoreline quality.

The existing harness reports log-loss / Brier / accuracy on the W/D/L triple
(ml.evaluation.backtest, ml.evaluation.match_metrics). Those miss two things we
care about for FinalWhistle:

  * W/D/L is an *ordered* outcome (home win → draw → away win). Predicting "home
    win" when the result is a draw is a smaller error than predicting "home win"
    when it is an away win. Plain Brier/log-loss treat the three classes as
    unordered. The **Ranked Probability Score (RPS)** rewards ordinal closeness
    and is the standard proper score for ordered football outcomes (Epstein 1969).
  * The product also predicts a *scoreline*. To judge that we need the quality of
    the whole Poisson score grid, not just whether the single modal cell matched:
    **exact-score NLL** (negative log-likelihood of the realized scoreline under
    the normalized grid) and **top-k scoreline hit rate**.

Plus **ECE** (expected calibration error) as a single tracked calibration number
to complement the existing reliability curve.

All functions are pure. Probability triples are (home, draw, away), matching
ml.evaluation.calibration and ml.evaluation.match_metrics.
"""
from __future__ import annotations

import math

Probs = tuple[float, float, float]
Grid = list[list[float]]

_EPS = 1e-15

#: Outcome order for RPS — home win < draw < away win on the result axis.
HOME, DRAW, AWAY = 0, 1, 2


def ranked_probability_score(probs: Probs, outcome_idx: int) -> float:
    """RPS for the ordered W/D/L outcome (0 = perfect, 1 = worst).

    RPS = 1/(K-1) * Σ_k (CDF_pred_k - CDF_obs_k)^2 over the K=3 ordered classes.
    Lower is better. Unlike Brier, an adjacent miss (predict home, get draw) is
    penalized less than a far miss (predict home, get away).
    """
    k = len(probs)
    cum_pred = 0.0
    cum_obs = 0.0
    total = 0.0
    for i in range(k):
        cum_pred += probs[i]
        cum_obs += 1.0 if i == outcome_idx else 0.0
        total += (cum_pred - cum_obs) ** 2
    return total / (k - 1)


def _normalized_grid(grid: Grid) -> tuple[Grid, float]:
    total = sum(sum(row) for row in grid)
    if total <= 0:
        return grid, 0.0
    return [[c / total for c in row] for row in grid], total


def _clamp_cell(grid: Grid, home_goals: int, away_goals: int) -> tuple[int, int]:
    """Clamp a realized scoreline onto the grid (goals beyond the cap fold into
    the last row/column — the grid's tail mass)."""
    max_h = len(grid) - 1
    max_a = len(grid[0]) - 1 if grid else 0
    return min(max(home_goals, 0), max_h), min(max(away_goals, 0), max_a)


def exact_score_nll(grid: Grid, home_goals: int, away_goals: int) -> float:
    """Negative log-likelihood of the realized scoreline under the normalized grid.

    The Poisson grid is truncated (0..MAX each side) so it sums to slightly under
    1; we normalize first. Scorelines beyond the cap fold into the edge cell.
    Lower is better. This is the real exact-score quality metric — it rewards
    putting mass near the right score, not just nailing the modal cell.
    """
    norm, total = _normalized_grid(grid)
    if total <= 0:
        return -math.log(_EPS)
    h, a = _clamp_cell(norm, home_goals, away_goals)
    return -math.log(max(_EPS, norm[h][a]))


def top_k_scorelines(grid: Grid, k: int = 5) -> list[tuple[int, int, float]]:
    """The k most likely (home, away, probability) cells, normalized, desc."""
    norm, total = _normalized_grid(grid)
    if total <= 0:
        return []
    cells = [
        (h, a, norm[h][a])
        for h, row in enumerate(norm)
        for a in range(len(row))
    ]
    cells.sort(key=lambda c: c[2], reverse=True)
    return cells[:k]


def top_k_scoreline_hit(grid: Grid, home_goals: int, away_goals: int, k: int = 5) -> bool:
    """Was the realized scoreline among the model's k most likely cells?"""
    h, a = _clamp_cell(grid, home_goals, away_goals)
    return any(ch == h and ca == a for ch, ca, _ in top_k_scorelines(grid, k))


def expected_calibration_error(
    probs_list: list[Probs], labels: list[int], bins: int = 10
) -> float:
    """Pooled multiclass ECE over all (predicted prob, was-correct) pairs.

    Same pooling as calibration.reliability_curve: every class probability of
    every match is a sample. ECE = Σ_b (n_b/N) · |mean_pred_b − empirical_freq_b|.
    0 is perfectly calibrated. Use few bins at small N.
    """
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    n = 0
    for probs, idx in zip(probs_list, labels):
        for cls in range(len(probs)):
            p = probs[cls]
            b = min(bins - 1, int(p * bins))
            buckets[b].append((p, 1 if cls == idx else 0))
            n += 1
    if n == 0:
        return float("nan")
    ece = 0.0
    for pairs in buckets:
        if not pairs:
            continue
        mean_pred = sum(p for p, _ in pairs) / len(pairs)
        freq = sum(hit for _, hit in pairs) / len(pairs)
        ece += (len(pairs) / n) * abs(mean_pred - freq)
    return ece


def mean_ranked_probability_score(probs_list: list[Probs], labels: list[int]) -> float:
    """Average RPS over a set of predictions (lower is better)."""
    if not labels:
        return float("nan")
    return sum(ranked_probability_score(p, idx) for p, idx in zip(probs_list, labels)) / len(labels)
