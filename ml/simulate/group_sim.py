"""Group qualification simulation (PRD §4.2 req 10-11).

Monte-Carlo a group's remaining fixtures thousands of times to estimate each
team's chance of advancing and the predicted final table. Each simulated match
samples goals from the Poisson model derived from the teams' Elo.

MVP scope: "qualifies" = finishing in the top 2 of the group. (WC2026 also
advances the 8 best third-placed teams across groups; that cross-group logic is
the full Monte-Carlo tournament simulator in Phase 3.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ml.models.poisson import expected_goals_from_elo


@dataclass
class GroupFixture:
    home_id: int
    away_id: int
    home_adv: float = 0.0  # +Elo for a host playing at home, else 0


def simulate_group(
    team_elos: dict[int, float],
    fixtures: list[GroupFixture],
    n_sims: int = 10000,
    seed: int | None = None,
    advance_count: int = 2,
) -> dict[int, dict]:
    """Return {team_id: {qualification_prob, avg_points, avg_gd, avg_gf}}."""
    rng = np.random.default_rng(seed)
    team_ids = list(team_elos)

    # Pre-compute Poisson means per fixture (constant across sims).
    lams = []
    for fx in fixtures:
        lh, la = expected_goals_from_elo(
            team_elos[fx.home_id], team_elos[fx.away_id], home_adv=fx.home_adv
        )
        lams.append((fx.home_id, fx.away_id, lh, la))

    qualify = {tid: 0 for tid in team_ids}
    sum_points = {tid: 0 for tid in team_ids}
    sum_gd = {tid: 0 for tid in team_ids}
    sum_gf = {tid: 0 for tid in team_ids}

    for _ in range(n_sims):
        points = {tid: 0 for tid in team_ids}
        gf = {tid: 0 for tid in team_ids}
        ga = {tid: 0 for tid in team_ids}

        for home_id, away_id, lh, la in lams:
            sh = int(rng.poisson(lh))
            sa = int(rng.poisson(la))
            gf[home_id] += sh
            ga[home_id] += sa
            gf[away_id] += sa
            ga[away_id] += sh
            if sh > sa:
                points[home_id] += 3
            elif sh < sa:
                points[away_id] += 3
            else:
                points[home_id] += 1
                points[away_id] += 1

        # Rank by points, then goal difference, then goals for, then a random
        # tiebreak (drawing of lots) to avoid bias.
        order = sorted(
            team_ids,
            key=lambda t: (points[t], gf[t] - ga[t], gf[t], rng.random()),
            reverse=True,
        )
        for tid in order[:advance_count]:
            qualify[tid] += 1
        for tid in team_ids:
            sum_points[tid] += points[tid]
            sum_gd[tid] += gf[tid] - ga[tid]
            sum_gf[tid] += gf[tid]

    return {
        tid: {
            "qualification_prob": round(qualify[tid] / n_sims, 3),
            "avg_points": round(sum_points[tid] / n_sims, 2),
            "avg_gd": round(sum_gd[tid] / n_sims, 2),
            "avg_gf": round(sum_gf[tid] / n_sims, 2),
        }
        for tid in team_ids
    }
