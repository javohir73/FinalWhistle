"""Deterministic held-out model/market blend search over [0, 1]."""

from __future__ import annotations

import math
from typing import Sequence


def _log_loss(probs: Sequence[Sequence[float]], labels: Sequence[int]) -> float:
    return sum(-math.log(max(row[label], 1e-15)) for row, label in zip(probs, labels)) / len(labels)


def search_blend_weight(
    model: Sequence[Sequence[float]],
    market: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    minimum_scored_pairs: int = 30,
    steps: int = 101,
) -> dict:
    if not (len(model) == len(market) == len(labels)) or not labels:
        raise ValueError("model, market, and labels must have the same non-zero length")
    if steps < 2:
        raise ValueError("steps must be at least 2")
    for row in [*model, *market]:
        if len(row) != 3 or any(not 0 <= value <= 1 for value in row) or sum(row) <= 0:
            raise ValueError("each row must contain three non-negative probabilities")
    if any(label not in {0, 1, 2} for label in labels):
        raise ValueError("labels must be 0, 1, or 2")
    normalized_model = [[value / sum(row) for value in row] for row in model]
    normalized_market = [[value / sum(row) for value in row] for row in market]
    candidates = []
    for index in range(steps):
        weight = index / (steps - 1)
        blended = [
            [(1 - weight) * p + weight * q for p, q in zip(p_row, q_row)]
            for p_row, q_row in zip(normalized_model, normalized_market)
        ]
        candidates.append({"weight": weight, "log_loss": _log_loss(blended, labels)})
    best = min(candidates, key=lambda item: (item["log_loss"], item["weight"]))
    production = candidates[0]
    eligible = len(labels) >= minimum_scored_pairs and best["log_loss"] < production["log_loss"]
    return {
        "n": len(labels),
        "minimum_scored_pairs": minimum_scored_pairs,
        "best": best,
        "production": production,
        "eligible_for_owner_review": eligible,
        "promotion_blocked_reason": None if eligible else (
            "insufficient scored pairs" if len(labels) < minimum_scored_pairs else "blend did not beat production"
        ),
        "grid": candidates,
    }
