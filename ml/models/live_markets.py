"""In-play (live) scoreline-derived markets (Phase 3, docs/ROADMAP-ENGINE.md).

The pre-match markets in ``ml.models.markets`` marginalize the frozen pre-match
scoreline grid. These are their LIVE counterpart: they marginalize the SHARED
live final-score grid (``ml.models.live_grid.build_live_final_grid``) — the exact
grid the live 1X2 bar (``app.live_winprob``) reads. Because both consume the same
normalized distribution, the live 1X2 returned here is identical (bit-for-bit) to
the live bar, and every derived market stays consistent with it AND with the live
predicted score.

The grid is over FINAL scorelines (current score + remaining goals), so totals,
correct-score and Asian-handicap are on the final score automatically — no extra
offset bookkeeping at this layer. Pure grid math: no new model, no training, no
DB. Shapes are JSON-friendly (plain dicts/lists/tuples of floats).
"""
from __future__ import annotations

from ml.models.live_grid import REGULATION_MINUTES, build_live_final_grid
from ml.models.markets import (
    _asian_handicap_lines_from_grid,
    _btts_from_grid,
    _correct_score_from_grid,
    _over_under_from_grid,
    double_chance_from_triple,
)
from ml.models.poisson import MAX_GOALS, outcome_probabilities


def live_markets(
    current_score_home: int | None,
    current_score_away: int | None,
    lam_home: float | None,
    lam_away: float | None,
    minutes_remaining: float | None,
    rho: float = 0.0,
    regulation: float = REGULATION_MINUTES,
    max_goals: int = MAX_GOALS,
    red_home: int = 0,
    red_away: int = 0,
    yellow_home: int = 0,
    yellow_away: int = 0,
) -> dict | None:
    """All live scoreline-derived markets off one shared FINAL-score grid.

    Builds the normalized live grid via ``build_live_final_grid`` (decay + cards +
    Dixon-Coles, offset by the current score) and marginalizes it with the same
    ``markets.py`` helpers the pre-match bundle uses. Returns ``None`` on missing
    or invalid inputs (the caller keeps the frozen pre-match markets).

    Keys:
      - ``one_x_two``: (p_home, p_draw, p_away) from ``outcome_probabilities`` —
        IDENTICAL to the live bar (``app.live_winprob``) for the same state.
      - ``double_chance``: from that same triple.
      - ``totals``: over/under on the FINAL total goals, lines 0.5..4.5.
      - ``btts``: both-teams-to-score on the FINAL score.
      - ``correct_score``: top-12 FINAL scorelines by probability.
      - ``asian_handicap``: home-handicap ladder -1.0..+1.0 on the FINAL margin.
    """
    grid = build_live_final_grid(
        current_score_home, current_score_away, lam_home, lam_away,
        minutes_remaining, rho=rho, regulation=regulation, max_goals=max_goals,
        red_home=red_home, red_away=red_away,
        yellow_home=yellow_home, yellow_away=yellow_away,
    )
    if grid is None:
        return None

    one_x_two = outcome_probabilities(grid)
    return {
        "one_x_two": one_x_two,
        "double_chance": double_chance_from_triple(*one_x_two),
        "totals": _over_under_from_grid(grid, (0.5, 1.5, 2.5, 3.5, 4.5)),
        "btts": _btts_from_grid(grid),
        "correct_score": _correct_score_from_grid(grid, top_n=12),
        "asian_handicap": _asian_handicap_lines_from_grid(grid, (-1.0, -0.5, 0.0, 0.5, 1.0)),
    }
