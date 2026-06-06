"""Naive baselines for the beat-the-baseline gate (PRD Goal #3).

The model must beat a naive baseline on log-loss, otherwise it adds no value.

- FavoriteBaseline: knows ONLY who the favorite is (higher effective Elo), not by
  how much. It predicts learned average P(favorite wins / draw / favorite loses).
  This is the PRD's "always back the higher-ranked team" idea, made probabilistic.
- BaseRateBaseline: predicts the constant class frequencies of the training set,
  ignoring the teams entirely. A true floor.

Beating FavoriteBaseline shows that the *magnitude* of the Elo gap (which the
Poisson model uses) carries real predictive signal.
"""
from __future__ import annotations

from ml.models.baseline_logistic import result_label
from ml.ratings.elo import HOME_ADVANTAGE

Probs = tuple[float, float, float]  # (P home win, P draw, P away win)


def _effective_home_elo(pre_home: float, pre_away: float, is_neutral: bool) -> float:
    adv = 0.0 if is_neutral else HOME_ADVANTAGE
    return pre_home + adv


class BaseRateBaseline:
    def __init__(self) -> None:
        self.probs: Probs = (1 / 3, 1 / 3, 1 / 3)

    def fit(self, rows: list[dict]) -> "BaseRateBaseline":
        n = len(rows) or 1
        h = sum(result_label(r["score_home"], r["score_away"]) == "H" for r in rows)
        d = sum(result_label(r["score_home"], r["score_away"]) == "D" for r in rows)
        a = sum(result_label(r["score_home"], r["score_away"]) == "A" for r in rows)
        self.probs = (h / n, d / n, a / n)
        return self

    def predict_proba(self, pre_home: float, pre_away: float, is_neutral: bool) -> Probs:
        return self.probs


class FavoriteBaseline:
    def __init__(self) -> None:
        # P(favorite wins), P(draw), P(favorite loses)
        self.p_fav_win = 0.45
        self.p_draw = 0.25
        self.p_fav_loss = 0.30

    def fit(self, rows: list[dict]) -> "FavoriteBaseline":
        fav_win = draw = fav_loss = 0
        for r in rows:
            eff_home = _effective_home_elo(r["pre_home"], r["pre_away"], r["is_neutral"])
            home_is_fav = eff_home >= r["pre_away"]
            label = result_label(r["score_home"], r["score_away"])
            if label == "D":
                draw += 1
            elif (label == "H") == home_is_fav:
                fav_win += 1
            else:
                fav_loss += 1
        n = (fav_win + draw + fav_loss) or 1
        self.p_fav_win = fav_win / n
        self.p_draw = draw / n
        self.p_fav_loss = fav_loss / n
        return self

    def predict_proba(self, pre_home: float, pre_away: float, is_neutral: bool) -> Probs:
        eff_home = _effective_home_elo(pre_home, pre_away, is_neutral)
        if eff_home >= pre_away:  # home favored
            return (self.p_fav_win, self.p_draw, self.p_fav_loss)
        return (self.p_fav_loss, self.p_draw, self.p_fav_win)  # away favored
