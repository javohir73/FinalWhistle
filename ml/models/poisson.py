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

import numpy as np

from ml.evaluation.calibration import apply_temperature, calibrate, effective_gap

BASE_GOALS = 1.35          # average international goals per team per match
ELO_TO_GOALS_BETA = 0.0019  # goals sensitivity per Elo pt (tuned on pre-2018 WCs, task 4.6)
MAX_GOALS = 10              # scoreline grid cap (0..10 each side)
# Headline draw band: only show the (grid-modal) draw scoreline when the two win
# probabilities are within this gap — i.e. a genuine coin-flip. Outside it one
# side is clearly favored, so we show their scoreline instead of an odd 1-1.
DRAW_HEADLINE_BAND = 0.08


def poisson_pmf(k: int, lam: float) -> float:
    """Probability of exactly k goals given mean lam."""
    return math.exp(-lam) * lam**k / math.factorial(k)


def _apply_temperature(probs: tuple[float, float, float], temperature: float):
    """Backwards-compatible shim — delegates to the canonical implementation in
    ml.evaluation.calibration. Kept because the tuner and the eval harness import
    this name; do not re-implement temperature scaling here (avoids divergence)."""
    return apply_temperature(probs, temperature)


def expected_goals_from_elo(
    elo_home: float,
    elo_away: float,
    home_adv: float = 0.0,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
    atk_home: float = 0.0,
    def_home: float = 0.0,
    atk_away: float = 0.0,
    def_away: float = 0.0,
) -> tuple[float, float]:
    """Map an Elo matchup to (expected_home_goals, expected_away_goals).

    The optional per-team attack/defence offsets (log-lambda units, from the
    offline fit in pipeline/fit_attack_defence.py) enrich the symmetric Elo
    mapping: lambda_home ×= exp(atk_home + def_away) and mirrored for away
    (FR-5.2). All four default to 0.0 and are only applied when non-zero, so
    with team offsets disabled the lambdas are bit-identical to the historical
    behavior.
    """
    diff = (elo_home + home_adv) - elo_away
    lam_home = base * math.exp(beta * diff)
    lam_away = base * math.exp(-beta * diff)
    if atk_home or def_away:
        lam_home *= math.exp(atk_home + def_away)
    if atk_away or def_home:
        lam_away *= math.exp(atk_away + def_home)
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


def goal_markets(
    lam_home: float | None,
    lam_away: float | None,
    rho: float | None = 0.0,
    max_goals: int = MAX_GOALS,
) -> dict | None:
    """Per-team goal bands, match totals and both-teams-to-score, marginalized
    from the NORMALIZED Dixon-Coles score grid. Same distribution that yields the
    predicted score, so the numbers stay consistent. Returns None when a rate is
    missing (legacy predictions). All probabilities rounded to 4 dp."""
    if lam_home is None or lam_away is None:
        return None
    matrix = score_matrix(lam_home, lam_away, max_goals=max_goals, rho=rho or 0.0)
    total = sum(sum(row) for row in matrix)
    if total <= 0.0:
        return None
    p = [[matrix[h][a] / total for a in range(max_goals + 1)] for h in range(max_goals + 1)]
    home_goals = [sum(p[h]) for h in range(max_goals + 1)]
    away_goals = [sum(p[h][a] for h in range(max_goals + 1)) for a in range(max_goals + 1)]

    def at_least(dist: list[float], n: int) -> float:
        return round(sum(dist[n:]), 4)

    def total_ge(m: int) -> float:
        return round(
            sum(p[h][a] for h in range(max_goals + 1) for a in range(max_goals + 1) if h + a >= m),
            4,
        )

    btts = round(
        sum(p[h][a] for h in range(1, max_goals + 1) for a in range(1, max_goals + 1)), 4
    )
    return {
        "home": {"to_score": at_least(home_goals, 1), "p2": at_least(home_goals, 2),
                 "p3": at_least(home_goals, 3), "p4": at_least(home_goals, 4)},
        "away": {"to_score": at_least(away_goals, 1), "p2": at_least(away_goals, 2),
                 "p3": at_least(away_goals, 3), "p4": at_least(away_goals, 4)},
        "total": {"over_1_5": total_ge(2), "over_2_5": total_ge(3), "over_3_5": total_ge(4)},
        "btts": btts,
    }


def score_cdf(lam_home, lam_away, rho=0.0, max_goals=MAX_GOALS):
    """Flattened, normalized CDF over the (max_goals+1)^2 Dixon-Coles grid.
    Build ONCE per fixture; reuse across sims via sample_scoreline_from_cdf.
    Guards against NaN/negative cells and raises on a degenerate (zero-mass) grid."""
    flat = np.asarray(score_matrix(lam_home, lam_away, max_goals=max_goals, rho=rho),
                      dtype=float).ravel()
    flat[~np.isfinite(flat)] = 0.0
    np.clip(flat, 0.0, None, out=flat)
    total = flat.sum()
    if total <= 0.0:
        raise ValueError("degenerate score grid: non-positive total mass")
    return np.cumsum(flat / total)


def sample_scoreline_from_cdf(rng, cdf, max_goals=MAX_GOALS):
    """One rng.random() + searchsorted into a prebuilt CDF -> (home, away)."""
    idx = int(np.searchsorted(cdf, rng.random(), side="right"))
    idx = min(idx, len(cdf) - 1)
    width = max_goals + 1
    return idx // width, idx % width


def sample_scoreline(rng, lam_home, lam_away, rho=0.0, max_goals=MAX_GOALS):
    """Convenience wrapper. NOT for per-sim loops (rebuilds the grid each call)."""
    return sample_scoreline_from_cdf(rng, score_cdf(lam_home, lam_away, rho, max_goals), max_goals)


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
    rho: float = 0.0,
    temperature: float = 1.0,
    calibrator: dict | None = None,
    atk_home: float = 0.0,
    def_home: float = 0.0,
    atk_away: float = 0.0,
    def_away: float = 0.0,
) -> MatchPrediction:
    """Full Poisson prediction for one match from the two Elo ratings.

    The per-team attack/defence offsets pass straight through to
    `expected_goals_from_elo` (0.0 defaults = disabled = bit-identical output;
    FR-5.3 — the caller only supplies them when model_params.json enables the
    offsets store).

    `rho` applies the Dixon–Coles low-score correction. The W/D/L triple is then
    calibrated via `calibrate`: a vector-scaling `calibrator` blob if present
    (which CAN reshape the triple — e.g. lift the under-predicted draw class),
    otherwise scalar `temperature` (a monotone rescaling: T>1 softens
    over-confident calls, T<1 sharpens).

    For a genuine coin-flip (the two win probabilities within DRAW_HEADLINE_BAND)
    the predicted scoreline is the single most-likely EXACT score across the whole
    grid — a draw (e.g. 1-1) for evenly matched teams — so draws can headline even
    matchups even though the draw is rarely the single highest W/D/L bucket in
    football (it tops out near 29% at parity, below each side's ~35%). When one
    side is clearly favored we instead show that side's most-likely scoreline, to
    avoid an odd "one side ~50% but predicted 1-1" headline. Either way the shown
    outcome follows the scoreline, so winner and score stay consistent.
    """
    lam_home, lam_away = expected_goals_from_elo(
        elo_home, elo_away, home_adv, base, beta,
        atk_home=atk_home, def_home=def_home, atk_away=atk_away, def_away=def_away,
    )
    return predict_from_lambdas(
        lam_home, lam_away, rho=rho, temperature=temperature, calibrator=calibrator,
        eff_gap=effective_gap(elo_home, elo_away, home_adv),
    )


def predict_from_lambdas(
    lam_home: float,
    lam_away: float,
    rho: float = 0.0,
    temperature: float = 1.0,
    calibrator: dict | None = None,
    eff_gap: float = 0.0,
) -> MatchPrediction:
    """``predict_match`` entered at the expected-goals level.

    The shadow odds-blend path (exact-score program FR-4.3/FR-4.4) anchors the
    lambda pair to the bookmaker total BEFORE the grid is built, so it needs
    this seam; ``predict_match`` itself delegates here, keeping grid, headline
    rule and calibration in one place. ``eff_gap`` feeds a segmented calibrator
    (callers derive it from the same Elo inputs that produced the lambdas).
    """
    matrix = score_matrix(lam_home, lam_away, rho=rho)
    p_home, p_draw, p_away = outcome_probabilities(matrix)
    p_home, p_draw, p_away = calibrate((p_home, p_draw, p_away), calibrator, temperature, eff_gap=eff_gap)
    if abs(p_home - p_away) <= DRAW_HEADLINE_BAND:
        # Coin-flip: show the grid's single most-likely exact score (a draw for
        # even teams).
        sh, sa, sp = most_likely_score(matrix)
    else:
        # One side clearly favored: show that side's most-likely scoreline.
        outcome = "home" if p_home > p_away else "away"
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
