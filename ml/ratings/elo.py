"""World-Football-style Elo ratings.

Elo is the MVP's primary strength signal (PRD §9.2 step 1): one number per team,
updated after every match. Higher = stronger. It is simple, interpretable, needs
no training, and is a strong baseline.

Formula (per the World Football Elo convention):
  expected_home = 1 / (1 + 10 ** (-(R_home - R_away + home_adv) / 400))
  R_home' = R_home + K * G * (W - expected_home)
where W is 1/0.5/0 for win/draw/loss, K scales with match importance, G is a
goal-difference multiplier, and home_adv is added for the home/host side.

`home_adv` doubles as the PRD Decision #2 host bonus (+60) for WC2026 host matches.
"""
from __future__ import annotations

from dataclasses import dataclass

BASE_RATING = 1500.0
HOME_ADVANTAGE = 60.0  # also the WC2026 host bonus (PRD Decision #2)


def k_factor(competition: str | None) -> float:
    """Match-importance weight. Bigger competitions move ratings more."""
    c = (competition or "").lower()
    if "world cup" in c and "qualif" not in c:
        return 60.0
    if "qualif" in c:
        return 40.0
    if any(
        x in c
        for x in ("euro", "copa", "nations cup", "asian cup", "gold cup", "confederations")
    ):
        return 50.0
    if "nations league" in c:
        return 40.0
    if "friendly" in c:
        return 20.0
    return 30.0


def goal_diff_multiplier(goal_diff: int) -> float:
    """Reward bigger wins, with diminishing returns (World Football Elo curve)."""
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


def expected_score(rating_home: float, rating_away: float, home_adv: float) -> float:
    """Probability-like expectation of the home side scoring the 'win' (0..1)."""
    return 1.0 / (1.0 + 10.0 ** (-(rating_home - rating_away + home_adv) / 400.0))


def update_ratings(
    rating_home: float,
    rating_away: float,
    score_home: int,
    score_away: int,
    competition: str | None = None,
    is_neutral: bool = False,
    home_advantage: float = HOME_ADVANTAGE,
) -> tuple[float, float]:
    """Return updated (home, away) ratings after one match. Pure."""
    adv = 0.0 if is_neutral else home_advantage
    exp_home = expected_score(rating_home, rating_away, adv)

    if score_home > score_away:
        w_home = 1.0
    elif score_home == score_away:
        w_home = 0.5
    else:
        w_home = 0.0

    k = k_factor(competition)
    g = goal_diff_multiplier(score_home - score_away)
    delta = k * g * (w_home - exp_home)
    # Elo is zero-sum: what home gains, away loses.
    return rating_home + delta, rating_away - delta


@dataclass
class MatchInput:
    """Minimal match shape the runner needs (decoupled from the ORM)."""

    home_id: int
    away_id: int
    score_home: int
    score_away: int
    competition: str | None
    is_neutral: bool


def run_elo(
    matches: list[MatchInput],
    base: float = BASE_RATING,
    home_advantage: float = HOME_ADVANTAGE,
) -> dict[int, float]:
    """Replay matches in order, returning final {team_id: rating}.

    Matches MUST be pre-sorted oldest-first; Elo is path-dependent.
    """
    ratings: dict[int, float] = {}
    for m in matches:
        rh = ratings.get(m.home_id, base)
        ra = ratings.get(m.away_id, base)
        new_h, new_a = update_ratings(
            rh, ra, m.score_home, m.score_away,
            competition=m.competition, is_neutral=m.is_neutral,
            home_advantage=home_advantage,
        )
        ratings[m.home_id] = new_h
        ratings[m.away_id] = new_a
    return ratings
