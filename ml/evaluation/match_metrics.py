"""Per-match prediction-vs-actual metrics (the learning loop's "receipt math").

Once a match finishes, the frozen pre-kickoff prediction is scored against the
actual result. These are pure functions — storage and orchestration live in the
pipeline; aggregate calibration lives in ml.evaluation.calibration (reuse
``reliability_curve`` there for the bucketed summary).

Probability triples are (home, draw, away), matching calibration.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Probs = tuple[float, float, float]
_EPS = 1e-15

#: Index into a Probs triple for the realized outcome.
HOME, DRAW, AWAY = 0, 1, 2


def outcome_index(home_goals: int, away_goals: int) -> int:
    """The realized outcome class for a final score."""
    if home_goals > away_goals:
        return HOME
    if home_goals < away_goals:
        return AWAY
    return DRAW


def predicted_index(probs: Probs) -> int:
    """The model's pick: argmax probability (first max wins exact ties)."""
    return max(range(3), key=lambda i: (probs[i], -i))


def winner_correct(probs: Probs, home_goals: int, away_goals: int) -> bool:
    return predicted_index(probs) == outcome_index(home_goals, away_goals)


def exact_score_correct(
    pred_home: int, pred_away: int, home_goals: int, away_goals: int
) -> bool:
    return pred_home == home_goals and pred_away == away_goals


def brier(probs: Probs, outcome_idx: int) -> float:
    """Multiclass Brier score: sum of squared errors over the 3 outcomes.

    0 is a perfect, fully-confident call; 2 is a fully-confident miss.
    """
    return sum(
        (p - (1.0 if i == outcome_idx else 0.0)) ** 2 for i, p in enumerate(probs)
    )


def log_loss(probs: Probs, outcome_idx: int) -> float:
    """Negative log-likelihood of the realized outcome (clamped away from 0)."""
    return -math.log(max(_EPS, min(1 - _EPS, probs[outcome_idx])))


def goal_error(
    pred_home: int, pred_away: int, home_goals: int, away_goals: int
) -> int:
    """L1 distance between predicted and actual scoreline."""
    return abs(pred_home - home_goals) + abs(pred_away - away_goals)


@dataclass(frozen=True)
class MatchEvaluation:
    """Everything the DB stores per evaluated match."""

    winner_correct: bool
    exact_score_correct: bool
    brier: float
    log_loss: float
    goal_error: int
    outcome_idx: int
    predicted_idx: int


def evaluate_match(
    probs: Probs,
    pred_home: int,
    pred_away: int,
    home_goals: int,
    away_goals: int,
) -> MatchEvaluation:
    """Score one frozen prediction against one final result."""
    actual = outcome_index(home_goals, away_goals)
    return MatchEvaluation(
        winner_correct=winner_correct(probs, home_goals, away_goals),
        exact_score_correct=exact_score_correct(
            pred_home, pred_away, home_goals, away_goals
        ),
        brier=brier(probs, actual),
        log_loss=log_loss(probs, actual),
        goal_error=goal_error(pred_home, pred_away, home_goals, away_goals),
        outcome_idx=actual,
        predicted_idx=predicted_index(probs),
    )
