"""Logistic-regression W/D/L baseline (PRD §9.2 step 3).

A deliberately simple, transparent classifier. Its job is to be the bar the
Poisson/boosted models must clear: if a fancier model can't beat plain logistic
regression on Elo difference, something is wrong. Features are the effective Elo
difference and its magnitude (the magnitude lets the draw class peak near 0).
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from ml.ratings.elo import HOME_ADVANTAGE

CLASSES = ["H", "D", "A"]  # home win / draw / away win


def result_label(score_home: int, score_away: int) -> str:
    if score_home > score_away:
        return "H"
    if score_home == score_away:
        return "D"
    return "A"


def _features(elo_diff: float) -> list[float]:
    return [elo_diff, abs(elo_diff)]


class LogisticBaseline:
    def __init__(self, home_advantage: float = HOME_ADVANTAGE):
        self.home_advantage = home_advantage
        self.model: LogisticRegression | None = None

    def effective_diff(self, pre_home: float, pre_away: float, is_neutral: bool) -> float:
        adv = 0.0 if is_neutral else self.home_advantage
        return pre_home + adv - pre_away

    def fit(self, rows: list[dict]) -> "LogisticBaseline":
        """Train on replay rows (dicts with pre_home/pre_away/is_neutral/scores)."""
        X = np.array(
            [
                _features(self.effective_diff(r["pre_home"], r["pre_away"], r["is_neutral"]))
                for r in rows
            ]
        )
        y = np.array([result_label(r["score_home"], r["score_away"]) for r in rows])
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X, y)
        return self

    def predict_proba(self, elo_diff: float) -> dict[str, float]:
        """Return {'H','D','A': prob} for an effective Elo difference."""
        if self.model is None:
            raise RuntimeError("model not fitted")
        probs = self.model.predict_proba(np.array([_features(elo_diff)]))[0]
        return {cls: float(probs[i]) for i, cls in enumerate(self.model.classes_)}
