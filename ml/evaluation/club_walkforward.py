"""Walk-forward candidate selection for the CLUB engine.

The internationals gate (`pipeline/experiment_model_eval.py`) clusters by
tournament edition and resamples whole editions. Club football has no editions:
the honest cluster is the **season**, since every match in a season shares the
rating trajectory that produced it.

Protocol (pre-registered — see `docs/MODEL-EXPERIMENTS.md`, "Club program"):

1. Replay Elo leak-free across every season in the window. A match's pre-match
   ratings depend only on earlier matches, so one replay yields leak-free
   features for every match at once.
2. For each grid point, score every match. Then walk forward: to score season
   S, the grid point is chosen by its mean loss on seasons strictly BEFORE S.
   Nothing that scores S was fitted on S.
3. Delta per match = candidate loss - control loss, where control is whatever
   production currently serves.
4. Bootstrap the mean delta by resampling **whole seasons** with replacement.

The confirmation season is quarantined by a hard guard (`CONFIRM_SEASON`), not
by convention: `walk_forward` raises if asked to score it without an explicit
opt-in, so it cannot be consumed by accident during selection.

Pure module — no DB, no network. Orchestration lives in
`pipeline/experiment_club_eval.py`.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ml.evaluation.calibration import calibrate, effective_gap
from ml.models.poisson import expected_goals_from_elo, outcome_probabilities, score_matrix
from ml.ratings.elo import BASE_RATING, update_ratings

# The held-out season. Never scored during selection; touched exactly once, at
# the end, on the final chosen config per track.
CONFIRM_SEASON = "2526"

_EPS = 1e-12


@dataclass(frozen=True)
class ClubMatch:
    """One club match, provider-agnostic.

    ``date`` is an ISO day string, used only by the rest-days signal (T3.2);
    everything else works without it, so it is optional.
    """

    season: str
    home: str
    away: str
    goals_home: int
    goals_away: int
    date: str = ""


@dataclass(frozen=True)
class EloConfig:
    """Everything that changes the RATINGS (and so requires a fresh replay)."""

    home_adv: float = 60.0
    # None -> ml.ratings.elo.k_factor(competition), i.e. current behaviour.
    k: float | None = None
    # Season-boundary regression toward the league mean. 0.0 = off (current
    # behaviour); 0.25 pulls every rating a quarter of the way to the mean each
    # summer. Elo is zero-sum from a common start, so the mean over all rated
    # teams is exactly BASE_RATING and shrinking toward it preserves that.
    shrinkage: float = 0.0
    # Rating for a club appearing for the FIRST time after the opening season
    # (i.e. promoted into the window). None -> BASE_RATING, current behaviour.
    promoted_prior: float | None = None


@dataclass(frozen=True)
class GridConfig:
    """Everything that turns ratings into probabilities (no replay needed)."""

    base: float = 1.2
    beta: float = 0.0021
    rho: float = -0.06
    temperature: float = 1.0
    calibrator: dict | None = None
    # log-lambda adjustment per day of rest advantage, and its cap. 0.0 = off.
    rest_coef: float = 0.0
    rest_cap: float = 0.075


def seasons_of(matches: Sequence[ClubMatch]) -> list[str]:
    """Season codes present, chronological (football-data.co.uk 'YYZZ' sorts)."""
    return sorted({m.season for m in matches})


def rest_deltas(matches: Sequence[ClubMatch], default_rest: int = 7,
                cap_days: int = 14) -> list[float]:
    """Per-match (home_rest - away_rest) in days, from each side's last match.

    A team's first match in the window has no predecessor and takes
    ``default_rest``. Rest is capped at ``cap_days`` before differencing so an
    international break or a winter shutdown doesn't dominate the signal — the
    hypothesis is short-turnaround fatigue, not months off.

    Club football is the first place this is measurable at all: the
    internationals holdout had a near-constant ~3-day tournament rhythm
    (docs/CHALLENGERS.md), so the feature had no variance to learn from.
    """
    from datetime import date

    last: dict[str, date] = {}
    out: list[float] = []
    for m in matches:
        if not m.date:
            out.append(0.0)
            continue
        d = date.fromisoformat(m.date)

        def rest_for(team: str) -> float:
            prev = last.get(team)
            return float(default_rest) if prev is None else min((d - prev).days, cap_days)

        out.append(rest_for(m.home) - rest_for(m.away))
        last[m.home] = d
        last[m.away] = d
    return out


def replay(matches: Sequence[ClubMatch], cfg: EloConfig, competition: str) -> list[tuple[float, float]]:
    """Leak-free chronological replay -> each match's (pre_home, pre_away).

    Reduces EXACTLY to ml.ratings.elo.replay_with_prematch when the config is
    all-defaults (k=None, shrinkage=0.0, promoted_prior=None); that equivalence
    is asserted in the tests, so enabling nothing changes nothing.

    ``matches`` MUST be sorted oldest-first — Elo is path-dependent.
    """
    ratings: dict[str, float] = {}
    pre: list[tuple[float, float]] = []
    opening_season = matches[0].season if matches else None
    current_season = opening_season

    def seed_for(team: str, season: str) -> float:
        # Teams present in the opening season are the window's starting
        # population, not promotions — they take the standard base rating.
        if cfg.promoted_prior is not None and season != opening_season:
            return cfg.promoted_prior
        return BASE_RATING

    for m in matches:
        if m.season != current_season:
            current_season = m.season
            if cfg.shrinkage:
                ratings = {
                    t: BASE_RATING + (1.0 - cfg.shrinkage) * (r - BASE_RATING)
                    for t, r in ratings.items()
                }

        rh = ratings.get(m.home)
        if rh is None:
            rh = seed_for(m.home, m.season)
        ra = ratings.get(m.away)
        if ra is None:
            ra = seed_for(m.away, m.season)
        pre.append((rh, ra))

        new_h, new_a = _update(rh, ra, m, cfg, competition)
        ratings[m.home] = new_h
        ratings[m.away] = new_a

    return pre


def _update(rh: float, ra: float, m: ClubMatch, cfg: EloConfig, competition: str):
    """Delegates to the production update rule — never re-implements it, so the
    harness cannot drift from what actually serves."""
    return update_ratings(
        rh, ra, m.goals_home, m.goals_away,
        competition=competition, is_neutral=False,
        home_advantage=cfg.home_adv, k=cfg.k,
    )


def _lambdas(pre: tuple[float, float], cfg: GridConfig, home_adv: float,
             rest_delta: float = 0.0) -> tuple[float, float]:
    lam_h, lam_a = expected_goals_from_elo(
        pre[0], pre[1], home_adv=home_adv, base=cfg.base, beta=cfg.beta,
    )
    if cfg.rest_coef and rest_delta:
        adj = max(-cfg.rest_cap, min(cfg.rest_cap, cfg.rest_coef * rest_delta))
        lam_h *= math.exp(adj)
        lam_a *= math.exp(-adj)
    return lam_h, lam_a


def loss_1x2(matches: Sequence[ClubMatch], pre: Sequence[tuple[float, float]],
             elo: EloConfig, grid: GridConfig,
             rest_deltas: Sequence[float] | None = None) -> list[float]:
    """Per-match negative log likelihood of the realized W/D/L outcome."""
    out: list[float] = []
    for i, (m, p) in enumerate(zip(matches, pre)):
        lam_h, lam_a = _lambdas(p, grid, elo.home_adv,
                                rest_deltas[i] if rest_deltas else 0.0)
        probs = outcome_probabilities(score_matrix(lam_h, lam_a, rho=grid.rho))
        probs = calibrate(
            probs, grid.calibrator, grid.temperature,
            eff_gap=effective_gap(p[0], p[1], elo.home_adv),
        )
        idx = 0 if m.goals_home > m.goals_away else (1 if m.goals_home == m.goals_away else 2)
        out.append(-math.log(max(probs[idx], _EPS)))
    return out


def loss_totals(matches: Sequence[ClubMatch], pre: Sequence[tuple[float, float]],
                elo: EloConfig, grid: GridConfig, line: float = 2.5,
                rest_deltas: Sequence[float] | None = None) -> list[float]:
    """Per-match NLL of the realized Over/Under outcome at ``line``.

    Read off the same Dixon-Coles grid the served markets use, not a
    independent-Poisson shortcut, so the number matches what ml/models/markets.py
    would price.
    """
    out: list[float] = []
    for i, (m, p) in enumerate(zip(matches, pre)):
        lam_h, lam_a = _lambdas(p, grid, elo.home_adv,
                                rest_deltas[i] if rest_deltas else 0.0)
        matrix = score_matrix(lam_h, lam_a, rho=grid.rho)
        p_over = sum(
            matrix[h][a]
            for h in range(len(matrix))
            for a in range(len(matrix[h]))
            if h + a > line
        )
        total = sum(sum(row) for row in matrix)
        p_over = min(max(p_over / total, _EPS), 1.0 - _EPS)
        over = (m.goals_home + m.goals_away) > line
        out.append(-math.log(p_over if over else 1.0 - p_over))
    return out


def walk_forward(
    matches: Sequence[ClubMatch],
    *,
    grid_points: Sequence[tuple],
    build: Callable[[tuple], tuple[EloConfig, GridConfig]],
    control: tuple[EloConfig, GridConfig],
    loss: Callable[..., list[float]],
    competition: str,
    scored_seasons: Iterable[str] | None = None,
    allow_confirm_season: bool = False,
    rest: Sequence[float] | None = None,
) -> dict:
    """Select per season using only prior seasons; return per-season deltas.

    ``grid_points`` are opaque tuples; ``build`` turns one into the
    (EloConfig, GridConfig) pair it represents. ``control`` is what production
    serves today. Returns per-season lists of (candidate - control) per-match
    losses, plus which grid point won each season's selection.
    """
    all_seasons = seasons_of(matches)
    if scored_seasons is not None:
        scored = list(scored_seasons)
    else:
        # Default to every season EXCEPT the quarantined one: the safe path is
        # the one you get by not thinking about it. Asking for it explicitly
        # still trips the guard below.
        scored = [s for s in all_seasons if s != CONFIRM_SEASON]
    if CONFIRM_SEASON in scored and not allow_confirm_season:
        raise ValueError(
            f"season {CONFIRM_SEASON} is the quarantined confirmation season; "
            "pass allow_confirm_season=True only for the single final "
            "confirmation run per track (see docs/MODEL-EXPERIMENTS.md)"
        )

    by_season_index: dict[str, list[int]] = {}
    for i, m in enumerate(matches):
        by_season_index.setdefault(m.season, []).append(i)

    # One scoring pass per grid point over every match.
    losses: dict[tuple, list[float]] = {}
    replays: dict[EloConfig, list[tuple[float, float]]] = {}
    for point in grid_points:
        elo, grid = build(point)
        if elo not in replays:
            replays[elo] = replay(matches, elo, competition)
        losses[point] = loss(matches, replays[elo], elo, grid, rest_deltas=rest)

    c_elo, c_grid = control
    if c_elo not in replays:
        replays[c_elo] = replay(matches, c_elo, competition)
    control_losses = loss(matches, replays[c_elo], c_elo, c_grid, rest_deltas=rest)

    deltas: dict[str, list[float]] = {}
    chosen: dict[str, tuple] = {}
    for season in scored:
        prior = [s for s in all_seasons if s < season]
        if not prior:
            continue  # nothing to fit on; the first season can never be scored
        prior_idx = [i for s in prior for i in by_season_index[s]]

        def mean_prior(point: tuple) -> float:
            vals = losses[point]
            return sum(vals[i] for i in prior_idx) / len(prior_idx)

        best = min(grid_points, key=mean_prior)
        chosen[season] = best
        idx = by_season_index[season]
        deltas[season] = [losses[best][i] - control_losses[i] for i in idx]

    return {"deltas": deltas, "chosen": chosen, "scored_seasons": sorted(deltas)}


def season_clustered_ci(deltas: dict[str, list[float]], *, n_bootstrap: int = 2000,
                        seed: int = 12345) -> dict:
    """Bootstrap the mean per-match delta by resampling WHOLE SEASONS.

    Matches inside a season share the rating trajectory that produced them, so
    the season is the honest resampling unit — the club analogue of the
    internationals gate's edition clustering.
    """
    keys = sorted(deltas)
    pooled = [v for k in keys for v in deltas[k]]
    if not pooled:
        return {"n": 0, "mean": float("nan"), "ci95": None, "verdict": "no data"}
    mean = sum(pooled) / len(pooled)

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_bootstrap):
        sampled = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [v for k in sampled for v in deltas[k]]
        means.append(sum(vals) / len(vals))
    means.sort()
    lo = means[int(0.025 * n_bootstrap)]
    hi = means[min(n_bootstrap - 1, int(0.975 * n_bootstrap))]

    if hi < 0:
        verdict = "CANDIDATE BETTER (credible: CI fully below 0)"
    elif lo > 0:
        verdict = "CANDIDATE WORSE (credible: CI fully above 0)"
    else:
        verdict = "NO CREDIBLE DIFFERENCE (CI straddles 0)"

    return {
        "n": len(pooled),
        "n_seasons": len(keys),
        "mean": mean,
        "ci95": (lo, hi),
        "verdict": verdict,
    }
