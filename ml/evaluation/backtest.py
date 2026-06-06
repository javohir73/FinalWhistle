"""Backtest the model against past World Cups (PRD §9.5, Goal #3).

Strategy: replay Elo over all history (leak-free — each match is predicted from
ratings that reflect only earlier matches), then evaluate the Poisson-Elo model
and the naive baselines on the matches of a target World Cup. Primary metric is
log-loss (punishes confident wrong predictions); we also report Brier and
accuracy.
"""
from __future__ import annotations

import math

from ml.evaluation.naive_baseline import BaseRateBaseline, FavoriteBaseline, Probs
from ml.models.baseline_logistic import result_label
from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, predict_match
from ml.ratings.elo import HOME_ADVANTAGE

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15


def model_probs(
    pre_home: float, pre_away: float, is_neutral: bool,
    base: float = BASE_GOALS, beta: float = ELO_TO_GOALS_BETA,
) -> Probs:
    adv = 0.0 if is_neutral else HOME_ADVANTAGE
    p = predict_match(pre_home, pre_away, home_adv=adv, base=base, beta=beta)
    return (p.prob_home_win, p.prob_draw, p.prob_away_win)


def compute_metrics(probs_list: list[Probs], labels: list[str]) -> dict:
    """log-loss, multiclass Brier, and accuracy for a set of predictions."""
    n = len(labels)
    if n == 0:
        return {"log_loss": float("nan"), "brier": float("nan"), "accuracy": float("nan"), "n": 0}

    ll = brier = correct = 0.0
    for probs, label in zip(probs_list, labels):
        idx = _LABEL_INDEX[label]
        p = [max(_EPS, min(1 - _EPS, x)) for x in probs]
        ll -= math.log(p[idx])
        brier += sum((p[k] - (1.0 if k == idx else 0.0)) ** 2 for k in range(3))
        if max(range(3), key=lambda k: probs[k]) == idx:
            correct += 1

    return {
        "log_loss": ll / n,
        "brier": brier / n,
        "accuracy": correct / n,
        "n": n,
    }


def is_world_cup_final_match(competition: str | None) -> bool:
    c = (competition or "").lower()
    return "fifa world cup" in c and "qualif" not in c


def backtest(rows: list[dict], year: int, base=1.35, beta=0.0017) -> dict:
    """Evaluate model vs baselines on a target World Cup year.

    `rows` are enriched replay rows with keys: pre_home, pre_away, is_neutral,
    score_home, score_away, date (datetime), competition (str). Pure of DB.
    """
    target = [
        r for r in rows if is_world_cup_final_match(r["competition"]) and r["date"].year == year
    ]
    if not target:
        raise ValueError(f"no World Cup matches found for {year}")

    first_date = min(r["date"] for r in target)
    train = [r for r in rows if r["date"] < first_date]

    favorite = FavoriteBaseline().fit(train)
    base_rate = BaseRateBaseline().fit(train)

    labels = [result_label(r["score_home"], r["score_away"]) for r in target]
    model_p = [model_probs(r["pre_home"], r["pre_away"], r["is_neutral"], base, beta) for r in target]
    fav_p = [favorite.predict_proba(r["pre_home"], r["pre_away"], r["is_neutral"]) for r in target]
    base_p = [base_rate.predict_proba(r["pre_home"], r["pre_away"], r["is_neutral"]) for r in target]

    return {
        "year": year,
        "n_matches": len(target),
        "model": compute_metrics(model_p, labels),
        "favorite_baseline": compute_metrics(fav_p, labels),
        "base_rate_baseline": compute_metrics(base_p, labels),
    }
