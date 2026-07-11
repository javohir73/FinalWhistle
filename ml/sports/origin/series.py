"""Best-of-three series odds by exact enumeration (design 2026-07-11).

Pure math, DB-free. A drawn game is a real outcome (pre-golden-point Origin
had them) and contributes to neither side's win count; a series with equal
wins after three games is drawn ("p_drawn"). Callers map home/away per game
onto a stable (team A, team B) orientation before calling.
"""
from __future__ import annotations

from itertools import product


def series_odds(
    wins_a: int, wins_b: int, remaining: list[tuple[float, float, float]]
) -> dict:
    """P(A wins series), P(B wins series), P(series drawn).

    `remaining`: one (p_a_wins_game, p_draw_game, p_b_wins_game) triple per
    game not yet played (0-3 of them). With no games remaining the current
    score decides with probability 1. Enumeration is exact: <= 3**3 outcomes.
    """
    totals = {"p_a": 0.0, "p_b": 0.0, "p_drawn": 0.0}
    for combo in product(range(3), repeat=len(remaining)):
        prob = 1.0
        a, b = wins_a, wins_b
        for game_idx, outcome in enumerate(combo):
            prob *= remaining[game_idx][outcome]
            if outcome == 0:
                a += 1
            elif outcome == 2:
                b += 1
        key = "p_a" if a > b else "p_b" if b > a else "p_drawn"
        totals[key] += prob
    return totals
