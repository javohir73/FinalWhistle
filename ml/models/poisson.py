"""Poisson goals model — the MVP's main match engine (PRD §9.2 step 2).

Idea: turn each team's expected goals into a Poisson distribution, build the grid
of every scoreline probability, then read off W/D/L probabilities and the most
likely score. Unlike raw Elo, this gives scorelines AND sensible draw chances.

Expected goals come from the Elo gap:
  lambda_home = BASE * exp( beta * (elo_home + home_adv - elo_away))
  lambda_away = BASE * exp(-beta * (elo_home + home_adv - elo_away))
BASE is the average goals a team scores; beta controls how much an Elo edge
inflates scoring. Both are tunable knobs (task 4.6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

BASE_GOALS = 1.35          # average international goals per team per match
ELO_TO_GOALS_BETA = 0.0019  # goals sensitivity per Elo pt (tuned on pre-2018 WCs, task 4.6)
MAX_GOALS = 10              # scoreline grid cap (0..10 each side)


def poisson_pmf(k: int, lam: float) -> float:
    """Probability of exactly k goals given mean lam."""
    return math.exp(-lam) * lam**k / math.factorial(k)


def expected_goals_from_elo(
    elo_home: float,
    elo_away: float,
    home_adv: float = 0.0,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
) -> tuple[float, float]:
    """Map an Elo matchup to (expected_home_goals, expected_away_goals)."""
    diff = (elo_home + home_adv) - elo_away
    lam_home = base * math.exp(beta * diff)
    lam_away = base * math.exp(-beta * diff)
    return lam_home, lam_away


def score_matrix(
    lam_home: float, lam_away: float, max_goals: int = MAX_GOALS
) -> list[list[float]]:
    """Grid where cell [h][a] = P(home scores h AND away scores a).

    Goals are modeled as independent Poisson draws.
    """
    home_pmf = [poisson_pmf(h, lam_home) for h in range(max_goals + 1)]
    away_pmf = [poisson_pmf(a, lam_away) for a in range(max_goals + 1)]
    return [[home_pmf[h] * away_pmf[a] for a in range(max_goals + 1)] for h in range(max_goals + 1)]


def outcome_probabilities(matrix: list[list[float]]) -> tuple[float, float, float]:
    """Aggregate the grid into (P(home win), P(draw), P(away win)), normalized."""
    p_home = p_draw = p_away = 0.0
    for h, row in enumerate(matrix):
        for a, p in enumerate(row):
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total == 0:
        return 0.0, 1.0, 0.0
    return p_home / total, p_draw / total, p_away / total


def most_likely_score(
    matrix: list[list[float]], outcome: str | None = None
) -> tuple[int, int, float]:
    """Return (home_goals, away_goals, probability) of the single likeliest score.

    With `outcome` ("home" | "draw" | "away") the search is restricted to
    scorelines that produce that result, so the predicted score can be made
    consistent with the predicted winner (avoids "winner X, score 1–1")."""
    best_h = best_a = 0
    best_p = -1.0
    for h, row in enumerate(matrix):
        for a, p in enumerate(row):
            if outcome == "home" and not h > a:
                continue
            if outcome == "draw" and h != a:
                continue
            if outcome == "away" and not h < a:
                continue
            if p > best_p:
                best_p, best_h, best_a = p, h, a
    return best_h, best_a, best_p


@dataclass
class MatchPrediction:
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    score_home: int
    score_away: int
    score_prob: float
    lambda_home: float
    lambda_away: float


def predict_match(
    elo_home: float,
    elo_away: float,
    home_adv: float = 0.0,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
) -> MatchPrediction:
    """Full Poisson prediction for one match from the two Elo ratings."""
    lam_home, lam_away = expected_goals_from_elo(elo_home, elo_away, home_adv, base, beta)
    matrix = score_matrix(lam_home, lam_away)
    p_home, p_draw, p_away = outcome_probabilities(matrix)
    # Scoreline consistent with the predicted result (argmax W/D/L), so the
    # displayed winner and scoreline never contradict each other.
    outcome = max(
        (("home", p_home), ("draw", p_draw), ("away", p_away)), key=lambda kv: kv[1]
    )[0]
    sh, sa, sp = most_likely_score(matrix, outcome)
    return MatchPrediction(
        prob_home_win=p_home,
        prob_draw=p_draw,
        prob_away_win=p_away,
        score_home=sh,
        score_away=sa,
        score_prob=sp,
        lambda_home=lam_home,
        lambda_away=lam_away,
    )
