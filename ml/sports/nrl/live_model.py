"""In-play NRL win-probability model (Wave 3).

A small logistic regression layered on TOP of (never replacing) the
pre-game predict() in ml.sports.nrl.model, over three engineered features:
  1. score_diff -- home points minus away points, right now.
  2. score_diff * sqrt(minutes_remaining) -- interaction term (spec: "sqrt
     of minutes remaining interaction"); lets the model learn how much a
     given differential should move win probability as time runs out.
  3. logit(pregame_prob) -- the SAME p_home the pre-game model already
     froze for this fixture (spec: "pre-game probability offset"), so a
     0-0 scoreline at minute 1 still reflects the pre-game favourite.

See pipeline/sports/nrl_live_fit.py for how training rows are generated
(there is no real minute-level history to fit on -- read that module's
docstring before assuming this was fit on genuine play-by-play data).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression

from ml.sports.nrl.live_params import NrlLiveParams


def _logit(p: float, eps: float = 1e-6) -> float:
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def _features(score_diff: float, minutes_remaining: float, pregame_prob: float) -> list[float]:
    minutes_remaining = max(minutes_remaining, 0.0)
    return [score_diff, score_diff * math.sqrt(minutes_remaining), _logit(pregame_prob)]


@dataclass
class LiveWinProbModel:
    """Wraps a fitted sklearn LogisticRegression over the 3 features above.
    Used only at FIT time (pipeline/sports/nrl_live_fit.py); at inference
    time the live poller uses the pure-math predict_live_prob() below."""

    model: LogisticRegression | None = None

    def fit(self, rows: list[dict]) -> "LiveWinProbModel":
        """rows: [{"score_diff", "minutes_remaining", "pregame_prob", "home_won"}, ...]"""
        X = np.array([
            _features(r["score_diff"], r["minutes_remaining"], r["pregame_prob"])
            for r in rows
        ])
        y = np.array([1 if r["home_won"] else 0 for r in rows])
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X, y)
        return self

    def predict_proba(self, score_diff: float, minutes_remaining: float, pregame_prob: float) -> float:
        if self.model is None:
            raise RuntimeError("model not fitted")
        x = np.array([_features(score_diff, minutes_remaining, pregame_prob)])
        classes = list(self.model.classes_)
        proba = self.model.predict_proba(x)[0]
        return float(proba[classes.index(1)])

    def coefficients(self) -> dict:
        """Raw fitted coefficients, for persistence via live_params.py."""
        if self.model is None:
            raise RuntimeError("model not fitted")
        coef = self.model.coef_[0]
        return {
            "intercept": float(self.model.intercept_[0]),
            "coef_score_diff": float(coef[0]),
            "coef_interaction": float(coef[1]),
            "coef_pregame_logit": float(coef[2]),
        }


def predict_live_prob(
    score_diff: float, minutes_remaining: float, pregame_prob: float, params: NrlLiveParams,
) -> float:
    """Pure-math inference from persisted coefficients (no sklearn object
    needed) -- called on every live-poll tick and every /live read."""
    x = _features(score_diff, minutes_remaining, pregame_prob)
    z = (
        params.intercept
        + params.coef_score_diff * x[0]
        + params.coef_interaction * x[1]
        + params.coef_pregame_logit * x[2]
    )
    return 1.0 / (1.0 + math.exp(-z))
