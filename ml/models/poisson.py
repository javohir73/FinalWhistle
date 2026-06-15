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


def _apply_temperature(probs: tuple[float, float, float], temperature: float):
    """Temperature-scale a probability triple (see ml.evaluation.calibration)."""
    eps = 1e-15
    powered = [max(eps, p) ** (1.0 / temperature) for p in probs]
    total = sum(powered)
    return (powered[0] / total, powered[1] / total, powered[2] / total)


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


def _dixon_coles_tau(h: int, a: int, lam: float, mu: float, rho: float) -> float:
    """Dixon–Coles low-score dependence adjustment for the four cells where
    independent Poisson misprices football scores (it under-counts draws and
    1–0/0–1 games). rho ≈ -0.1 in practice; rho = 0 recovers plain Poisson."""
    if h == 0 and a == 0:
        return 1.0 - lam * mu * rho
    if h == 0 and a == 1:
        return 1.0 + lam * rho
    if h == 1 and a == 0:
        return 1.0 + mu * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lam_home: float, lam_away: float, max_goals: int = MAX_GOALS, rho: float = 0.0
) -> list[list[float]]:
    """Grid where cell [h][a] = P(home scores h AND away scores a).

    Goals are independent Poisson draws, optionally corrected for the well-known
    low-score dependence via the Dixon–Coles tau factor (rho). Cells are clamped
    non-negative; callers normalize.
    """
    home_pmf = [poisson_pmf(h, lam_home) for h in range(max_goals + 1)]
    away_pmf = [poisson_pmf(a, lam_away) for a in range(max_goals + 1)]
    matrix = [[home_pmf[h] * away_pmf[a] for a in range(max_goals + 1)] for h in range(max_goals + 1)]
    if rho:
        for h in range(min(2, max_goals + 1)):
            for a in range(min(2, max_goals + 1)):
                matrix[h][a] = max(0.0, matrix[h][a] * _dixon_coles_tau(h, a, lam_home, lam_away, rho))
    return matrix


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


@dataclass(frozen=True)
class ScorelineProbability:
    home: int
    away: int
    probability: float
    outcome: str


def top_scorelines_by_outcome(
    matrix: list[list[float]], per_outcome: int = 5
) -> dict[str, list[ScorelineProbability]]:
    """Return the most likely scorelines grouped by result class.

    Grouping avoids the UX trap where the absolute top cells can visually
    contradict the headline W/D/L pick. Probabilities are normalized to the
    displayed grid mass, matching outcome_probabilities().
    """
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return {"home": [], "draw": [], "away": []}

    buckets: dict[str, list[ScorelineProbability]] = {
        "home": [],
        "draw": [],
        "away": [],
    }
    for h, row in enumerate(matrix):
        for a, raw_p in enumerate(row):
            if h > a:
                outcome = "home"
            elif h == a:
                outcome = "draw"
            else:
                outcome = "away"
            buckets[outcome].append(
                ScorelineProbability(
                    home=h,
                    away=a,
                    probability=raw_p / total,
                    outcome=outcome,
                )
            )

    return {
        outcome: sorted(cells, key=lambda cell: cell.probability, reverse=True)[
            :per_outcome
        ]
        for outcome, cells in buckets.items()
    }


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
    scorelines_by_outcome: dict[str, list[ScorelineProbability]]


def predict_match(
    elo_home: float,
    elo_away: float,
    home_adv: float = 0.0,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
    rho: float = 0.0,
    temperature: float = 1.0,
) -> MatchPrediction:
    """Full Poisson prediction for one match from the two Elo ratings.

    `rho` applies the Dixon–Coles low-score correction; `temperature` calibrates
    the W/D/L triple (T>1 softens over-confident calls). Temperature is a
    monotone reshaping, so the argmax outcome — and thus the chosen scoreline —
    is unchanged: the displayed winner and score never contradict each other.
    """
    lam_home, lam_away = expected_goals_from_elo(elo_home, elo_away, home_adv, base, beta)
    matrix = score_matrix(lam_home, lam_away, rho=rho)
    p_home, p_draw, p_away = outcome_probabilities(matrix)
    if temperature != 1.0:
        p_home, p_draw, p_away = _apply_temperature((p_home, p_draw, p_away), temperature)
    # Scoreline consistent with the predicted result (argmax W/D/L), so the
    # displayed winner and scoreline never contradict each other.
    outcome = max(
        (("home", p_home), ("draw", p_draw), ("away", p_away)), key=lambda kv: kv[1]
    )[0]
    sh, sa, sp = most_likely_score(matrix, outcome)
    scorelines = top_scorelines_by_outcome(matrix)
    return MatchPrediction(
        prob_home_win=p_home,
        prob_draw=p_draw,
        prob_away_win=p_away,
        score_home=sh,
        score_away=sa,
        score_prob=sp,
        lambda_home=lam_home,
        lambda_away=lam_away,
        scorelines_by_outcome=scorelines,
    )
