"""Scoreline-derived betting markets (Phase 2, docs/ROADMAP-ENGINE.md).

Everything here is pure grid math on top of the Dixon-Coles Poisson scoreline
grid built by ``ml.models.poisson.score_matrix``. No new model, no training, no
DB, no lineups — just marginalizations of the *same* normalized distribution the
engine already prices, so every market stays consistent with the predicted score
and with ``poisson.goal_markets``.

``score_matrix`` returns an UNNORMALIZED grid (Dixon-Coles rho baked in); the
caller must divide by the grid sum. ``_normalized_grid`` does that once, and the
``_*_from_grid`` helpers operate on the already-normalized grid so a bundle
(``derive_scoreline_markets``) can build the grid a single time and reuse it
across every market.

Shapes are JSON-friendly (plain dicts/lists of floats) for the versioned public
API (``/v1/markets/{match}``).
"""
from __future__ import annotations

import math

from ml.models.poisson import MAX_GOALS, score_matrix


def _normalized_grid(
    lam_home: float, lam_away: float, rho: float = 0.0, max_goals: int = MAX_GOALS
) -> list[list[float]]:
    """Normalized scoreline grid where cell[h][a] = P(home=h, away=a).

    Built from the unnormalized Dixon-Coles ``score_matrix``: NaN/negative cells
    are clamped to 0, then every cell is divided by the grid sum. Raises
    ``ValueError`` on a degenerate (non-positive total mass) grid, mirroring
    ``poisson.score_cdf``."""
    matrix = score_matrix(lam_home, lam_away, max_goals=max_goals, rho=rho)
    cleaned = [
        [c if (isinstance(c, (int, float)) and math.isfinite(c) and c > 0.0) else 0.0 for c in row]
        for row in matrix
    ]
    total = sum(sum(row) for row in cleaned)
    if total <= 0.0:
        raise ValueError("degenerate score grid: non-positive total mass")
    return [[c / total for c in row] for row in cleaned]


def _over_under_from_grid(grid: list[list[float]], lines) -> list[dict]:
    """Totals over/under for each line off a normalized grid. ``over`` is the
    mass of scorelines whose total goals strictly exceed the line (lines are
    half/whole points, so no scoreline ever lands exactly on one)."""
    n = len(grid)
    out = []
    for line in lines:
        over = sum(grid[h][a] for h in range(n) for a in range(n) if (h + a) > line)
        out.append({"line": float(line), "over": over, "under": 1.0 - over})
    return out


def over_under(
    lam_home: float,
    lam_away: float,
    rho: float = 0.0,
    lines=(0.5, 1.5, 2.5, 3.5, 4.5),
    max_goals: int = MAX_GOALS,
) -> list[dict]:
    """Match totals over/under for each line. Each row is
    ``{"line": float, "over": p, "under": p}``; ``over`` counts scorelines with
    (home+away) goals strictly greater than the line."""
    return _over_under_from_grid(_normalized_grid(lam_home, lam_away, rho, max_goals), lines)


def _btts_from_grid(grid: list[list[float]]) -> dict:
    n = len(grid)
    yes = sum(grid[h][a] for h in range(1, n) for a in range(1, n))
    return {"yes": yes, "no": 1.0 - yes}


def both_teams_to_score(
    lam_home: float, lam_away: float, rho: float = 0.0, max_goals: int = MAX_GOALS
) -> dict:
    """Both-teams-to-score: ``{"yes": P(home>=1 and away>=1), "no": ...}``."""
    return _btts_from_grid(_normalized_grid(lam_home, lam_away, rho, max_goals))


def _correct_score_from_grid(grid: list[list[float]], top_n: int | None = None) -> list[dict]:
    """Every exact scoreline as ``{"home": i, "away": j, "prob": p}``, sorted by
    probability descending. Ties broken by (home, away) for a stable order.
    Truncated to ``top_n`` entries when given."""
    scores = [
        {"home": h, "away": a, "prob": grid[h][a]}
        for h in range(len(grid))
        for a in range(len(grid))
    ]
    scores.sort(key=lambda s: (-s["prob"], s["home"], s["away"]))
    if top_n is not None:
        return scores[:top_n]
    return scores


def correct_score(
    lam_home: float,
    lam_away: float,
    rho: float = 0.0,
    max_goals: int = MAX_GOALS,
    top_n: int | None = None,
) -> list[dict]:
    """Correct-score market: exact scorelines sorted by probability descending,
    optionally truncated to the ``top_n`` most likely."""
    return _correct_score_from_grid(_normalized_grid(lam_home, lam_away, rho, max_goals), top_n)


def _ah_half_or_integer_from_grid(grid: list[list[float]], line: float) -> dict:
    """Asian handicap for a HALF or INTEGER line off a normalized grid.

    Home-handicap convention: for each scoreline the home margin is
    m = home - away, adjusted by ``line`` (adjusted = m + line). Home wins the
    bet when adjusted > 0, away when adjusted < 0, push when adjusted == 0. Half
    lines can never push (adjusted is a non-integer), so ``push`` is 0 there."""
    n = len(grid)
    home = push = away = 0.0
    for h in range(n):
        for a in range(n):
            adjusted = (h - a) + line
            p = grid[h][a]
            if adjusted > 0:
                home += p
            elif adjusted < 0:
                away += p
            else:
                push += p
    return {"line": float(line), "home": home, "push": push, "away": away}


def _asian_handicap_from_grid(grid: list[list[float]], line: float) -> dict:
    """Asian handicap for any line off a normalized grid.

    QUARTER lines (odd multiples of 0.25) split the stake equally across the two
    neighbouring 0.5-step lines and average their {home, push, away}. Half and
    integer lines are priced directly."""
    if (line * 2) % 1 != 0:  # quarter line: not a multiple of 0.5
        lo = math.floor(line * 2) / 2.0
        hi = math.ceil(line * 2) / 2.0
        low = _ah_half_or_integer_from_grid(grid, lo)
        high = _ah_half_or_integer_from_grid(grid, hi)
        return {
            "line": float(line),
            "home": (low["home"] + high["home"]) / 2.0,
            "push": (low["push"] + high["push"]) / 2.0,
            "away": (low["away"] + high["away"]) / 2.0,
        }
    return _ah_half_or_integer_from_grid(grid, line)


def asian_handicap(
    lam_home: float,
    lam_away: float,
    line: float,
    rho: float = 0.0,
    max_goals: int = MAX_GOALS,
) -> dict:
    """Asian handicap for a single line: ``{"line", "home", "push", "away"}``.

    Home-handicap convention (adjusted = home_margin + line). Half lines never
    push; integer lines push on adjusted == 0; quarter lines average the two
    bounding 0.5-step lines (split-stake)."""
    return _asian_handicap_from_grid(_normalized_grid(lam_home, lam_away, rho, max_goals), line)


def _asian_handicap_lines_from_grid(grid: list[list[float]], lines) -> list[dict]:
    return [_asian_handicap_from_grid(grid, line) for line in lines]


def asian_handicap_lines(
    lam_home: float,
    lam_away: float,
    rho: float = 0.0,
    lines=(-1.0, -0.5, 0.0, 0.5, 1.0),
    max_goals: int = MAX_GOALS,
) -> list[dict]:
    """Asian handicap priced across several home-handicap lines."""
    return _asian_handicap_lines_from_grid(_normalized_grid(lam_home, lam_away, rho, max_goals), lines)


def double_chance_from_triple(p_home: float, p_draw: float, p_away: float) -> dict:
    """Double-chance market from a W/D/L triple.

    Takes the 1X2 triple as input (rather than recomputing it from the grid) so
    callers can pass the CALIBRATED stored 1X2 — the double-chance numbers then
    match the published 1X2 rather than a second, uncalibrated derivation."""
    return {
        "home_or_draw": p_home + p_draw,
        "home_or_away": p_home + p_away,
        "draw_or_away": p_draw + p_away,
    }


def derive_scoreline_markets(
    lam_home: float, lam_away: float, rho: float = 0.0, max_goals: int = MAX_GOALS
) -> dict:
    """All scoreline-derived markets from a SINGLE shared grid.

    Builds the normalized grid once and marginalizes totals, BTTS, the top-12
    correct scores and the Asian-handicap ladder off it — the JSON-friendly
    payload behind the versioned markets API. (Double chance is intentionally
    excluded: it needs the calibrated stored 1X2 triple, which this pure
    grid-only path does not have — call ``double_chance_from_triple`` at the
    caller with the stored probabilities.)"""
    grid = _normalized_grid(lam_home, lam_away, rho, max_goals)
    return {
        "totals": _over_under_from_grid(grid, (0.5, 1.5, 2.5, 3.5, 4.5)),
        "btts": _btts_from_grid(grid),
        "correct_score": _correct_score_from_grid(grid, top_n=12),
        "asian_handicap": _asian_handicap_lines_from_grid(grid, (-1.0, -0.5, 0.0, 0.5, 1.0)),
    }
