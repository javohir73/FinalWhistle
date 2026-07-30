"""E1 — does the club engine need a per-team TEMPO channel?

Pre-registration: `docs/experiments/2026-07-30-e1-tempo-channel/
SELECTION-PRE-REGISTRATION.md`, committed alone in `3989145` and corrected in
`758963a`, both pushed before this module existed.

The question
------------
`ml/models/poisson.py` maps one Elo difference symmetrically into both lambdas,
so ``lam_home * lam_away == base**2`` identically and the expected total is
``2*base*cosh(beta*diff)`` — a function of the rating gap alone, minimised at
parity. D0-B measured what that costs: the served model is credibly behind the
closing over/under line in all three leagues, and Bundesliga priced P(over 2.5)
below 0.5 **zero times in 612 matches** because with ``base=1.44`` its floor is
2.88 goals.

Per-team attack/defence offsets break that identity. Written out:

    log lam_h - log lam_a  =  (Elo term) + (a_h + d_h) - (a_a + d_a)   -> 1X2
    log lam_h + log lam_a  =  2*log base + (a_h + a_a) + (d_h + d_a)   -> TOTALS

``(a_i + d_i)`` is STRENGTH and moves the ratio, which Elo already handles
(D0-B: 64-84% of the 1X2 budget). ``(a_i - d_i)`` is TEMPO and moves the sum,
which the served engine cannot express at all. E1 asks only whether the second
channel earns its complexity.

Three traps this module is shaped around (pre-registration §12)
---------------------------------------------------------------
1. **``GridConfig`` is frozen and used as a dict key** for replay memoization in
   ``walk_forward``. A per-team offsets mapping is unhashable, so putting it
   there raises ``TypeError`` at grid-scan time — not at import. Offsets are
   therefore threaded separately and ``GridConfig`` is untouched.
2. **``walk_forward`` calls losses positionally** as
   ``loss(matches, pre, elo, grid, rest_deltas=rest)``, and ``loss_totals``'s
   fifth positional is ``line``. Every new parameter here is **keyword-only**,
   so a positional caller cannot bind one by accident.
3. **Offsets must be refit per scored season** from strictly-prior matches. One
   fit over the whole window applied backwards is the defect D1 found in its
   venue table, with a different name.

Pure module — no DB, no network, no I/O. The fitter is injected as a callable
so this stays testable with a fake, and orchestration lives in
`pipeline/run_e1_tempo.py`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ml.evaluation.calibration import calibrate, effective_gap
from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
)
from ml.models.poisson import (
    expected_goals_from_elo,
    outcome_probabilities,
    score_matrix,
)

_EPS = 1e-12

#: (atk, def) per team name. Absent team -> (0.0, 0.0), i.e. served behaviour.
Offsets = dict


@dataclass(frozen=True)
class TempoPoint:
    """One point of E1.1's frozen grid. Hashable, so it can key a cache."""

    half_life_days: int
    n0: float
    cap: float = 0.075  # the shipped OFFSET_CAP; on the grid only as sensitivity

    def label(self) -> str:
        return f"hl{self.half_life_days}_n0{self.n0:g}_cap{self.cap:g}"


#: §4's SELECTABLE grid — 9 points. Frozen before the run.
GRID: tuple[TempoPoint, ...] = tuple(
    TempoPoint(hl, n0) for hl in (180, 365, 730) for n0 in (10.0, 30.0, 60.0)
)

#: §4's cap sensitivity — reported alongside, NEVER eligible to win. Kept in a
#: separate tuple rather than flagged inside GRID, so a selection loop cannot
#: pick one by iterating the wrong collection.
CAP_SENSITIVITY: tuple[TempoPoint, ...] = tuple(
    TempoPoint(365, 30.0, cap) for cap in (0.05, 0.10, 0.15)
)

#: §8: a club with fewer than this many prior matches gets EXACTLY zero, not a
#: shrunk guess and not a league average. Promoted clubs are the common case.
MIN_PRIOR_MATCHES = 10


def offsets_for(offsets: Offsets | None, team: str) -> tuple[float, float]:
    """``(atk, def)`` for a club; ``(0.0, 0.0)`` when absent or disabled.

    A zero pair is a real prediction — it says "this club behaves like the
    served Elo baseline" — not a missing value. §8 is explicit that it must
    never be filled with a league average.
    """
    if not offsets:
        return 0.0, 0.0
    entry = offsets.get(team)
    if entry is None:
        return 0.0, 0.0
    return float(entry[0]), float(entry[1])


def lambdas_with_offsets(
    pre: tuple[float, float],
    grid: GridConfig,
    home_adv: float,
    home: str,
    away: str,
    offsets: Offsets | None,
) -> tuple[float, float]:
    """Served Elo lambdas, then FR-5's multiplicative offsets on top.

    Delegates to the production ``expected_goals_from_elo`` rather than
    re-deriving the map, so E1 cannot drift from what serves. With ``offsets``
    empty this is bit-identical to ``club_walkforward._lambdas`` at
    ``rest_delta=0``, which a test asserts.
    """
    atk_h, def_h = offsets_for(offsets, home)
    atk_a, def_a = offsets_for(offsets, away)
    return expected_goals_from_elo(
        pre[0], pre[1], home_adv=home_adv, base=grid.base, beta=grid.beta,
        atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
    )


def loss_totals_offsets(
    matches: Sequence[ClubMatch],
    pre: Sequence[tuple[float, float]],
    elo: EloConfig,
    grid: GridConfig,
    *,
    offsets: Offsets | None = None,
    line: float = 2.5,
) -> list[float]:
    """Per-match NLL of the realized Over/Under outcome — E1's PRIMARY metric.

    Mirrors ``club_walkforward.loss_totals`` exactly, with the offsets applied
    at the lambda step. Same grid, same normalization, same clip, so E1's number
    is comparable to the one T1.1 was gated on.
    """
    out: list[float] = []
    for m, p in zip(matches, pre):
        lam_h, lam_a = lambdas_with_offsets(p, grid, elo.home_adv, m.home, m.away, offsets)
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


def loss_1x2_offsets(
    matches: Sequence[ClubMatch],
    pre: Sequence[tuple[float, float]],
    elo: EloConfig,
    grid: GridConfig,
    *,
    offsets: Offsets | None = None,
) -> list[float]:
    """Per-match NLL of the realized W/D/L outcome — E1's GUARDRAIL metric.

    §6: a candidate that buys totals by giving up 1X2 has moved the problem, not
    solved it. Calibration is applied exactly as ``loss_1x2`` does, because the
    served 1X2 triple is calibrated and comparing an uncalibrated candidate
    against a calibrated control would measure the calibrator, not the offsets.
    """
    out: list[float] = []
    for m, p in zip(matches, pre):
        lam_h, lam_a = lambdas_with_offsets(p, grid, elo.home_adv, m.home, m.away, offsets)
        probs = outcome_probabilities(score_matrix(lam_h, lam_a, rho=grid.rho))
        probs = calibrate(
            probs, grid.calibrator, grid.temperature,
            eff_gap=effective_gap(p[0], p[1], elo.home_adv),
        )
        idx = 0 if m.goals_home > m.goals_away else (1 if m.goals_home == m.goals_away else 2)
        out.append(-math.log(max(probs[idx], _EPS)))
    return out


def season_cutoffs(matches: Sequence[ClubMatch]) -> dict[str, str]:
    """Season -> its earliest match date (ISO). The exclusive fitting cutoff.

    Using the season's own first kickoff, rather than a calendar boundary, means
    the fit for season S sees every match that had actually been played when S
    began and not one more.
    """
    out: dict[str, str] = {}
    for m in matches:
        if not m.date:
            continue
        cur = out.get(m.season)
        if cur is None or m.date < cur:
            out[m.season] = m.date
    return out


def walk_forward_tempo(
    matches: Sequence[ClubMatch],
    pre: Sequence[tuple[float, float]],
    elo: EloConfig,
    grid: GridConfig,
    *,
    points: Sequence[TempoPoint],
    fit: Callable[[str, TempoPoint], Offsets],
    loss: Callable[..., list[float]],
    scored_seasons: Iterable[str] | None = None,
    allow_confirm_season: bool = False,
) -> dict:
    """Select a grid point per season using only strictly-earlier seasons.

    Mirrors ``club_walkforward.walk_forward``'s protocol — same selection rule,
    same delta definition, same quarantine — but refits offsets per season
    rather than treating the candidate as a static config, which is the whole
    point of the candidate.

    ``fit(cutoff_iso, point) -> Offsets`` is injected so this module stays pure
    and can be tested with a fake fitter that returns known offsets.

    Returns ``deltas`` (per season, per match: candidate loss - control loss),
    ``chosen`` (the winning point per season) and the control losses, so the
    caller can interval them without recomputing.
    """
    all_seasons = sorted({m.season for m in matches})
    scored = sorted(scored_seasons) if scored_seasons is not None else all_seasons
    if not allow_confirm_season and CONFIRM_SEASON in scored:
        raise ValueError(
            f"season {CONFIRM_SEASON} is the quarantined confirmation season and "
            "E1 never scores it — it was consumed by #202's confirmation phase"
        )

    by_season: dict[str, list[int]] = {}
    for i, m in enumerate(matches):
        by_season.setdefault(m.season, []).append(i)
    cutoffs = season_cutoffs(matches)

    # Control: the served config, no offsets. Scored season by season so its
    # indices line up with the candidate's.
    control: dict[str, list[float]] = {}
    for s in all_seasons:
        idx = by_season[s]
        control[s] = loss(
            [matches[i] for i in idx], [pre[i] for i in idx], elo, grid, offsets=None,
        )

    # Candidate: one fit per (point, season), on matches strictly before the
    # season's first kickoff.
    losses: dict[TempoPoint, dict[str, list[float]]] = {}
    fitted: dict[TempoPoint, dict[str, Offsets]] = {}
    for point in points:
        losses[point] = {}
        fitted[point] = {}
        for s in all_seasons:
            offs = fit(cutoffs[s], point) if s in cutoffs else {}
            fitted[point][s] = offs
            idx = by_season[s]
            losses[point][s] = loss(
                [matches[i] for i in idx], [pre[i] for i in idx], elo, grid,
                offsets=offs,
            )

    deltas: dict[str, list[float]] = {}
    guard_deltas: dict[str, list[float]] = {}
    chosen: dict[str, TempoPoint] = {}
    for season in scored:
        prior = [s for s in all_seasons if s < season]
        if not prior:
            continue  # nothing to select on; the opening season is never scored

        def mean_prior(point: TempoPoint) -> float:
            vals = [v for s in prior for v in losses[point][s]]
            return sum(vals) / len(vals)

        # Ties broken by the grid's declared order, so selection is
        # deterministic and does not depend on dict iteration.
        best = min(points, key=lambda p: (mean_prior(p), points.index(p)))
        chosen[season] = best
        deltas[season] = [
            c - k for c, k in zip(losses[best][season], control[season])
        ]

    return {
        "deltas": deltas,
        "chosen": chosen,
        "control": control,
        "losses": losses,
        "fitted": fitted,
        "scored_seasons": sorted(deltas),
        "guard_deltas": guard_deltas,
    }


def offset_diagnostics(fitted: dict[str, Offsets], cap: float) -> dict:
    """§S4 and §13: is the fit a result, or an artifact?

    A solution where most clubs sit on the cap is not a measurement of tempo —
    it is the policy bound being reported as a finding. §S4 stops the phase
    above 20%.
    """
    total = 0
    saturated = 0
    zeroed = 0
    tempo: list[float] = []
    for offs in fitted.values():
        for atk, dfn in offs.values():
            total += 1
            if atk == 0.0 and dfn == 0.0:
                zeroed += 1
            # Cap is applied to each component before the ramp, so a component
            # within 1e-9 of it is saturated at full confidence.
            if abs(abs(atk) - cap) < 1e-9 or abs(abs(dfn) - cap) < 1e-9:
                saturated += 1
            tempo.append(atk - dfn)
    if not total:
        return {"n": 0, "saturated_frac": 0.0, "zeroed_frac": 0.0}
    mean_t = sum(tempo) / len(tempo)
    sd_t = (sum((x - mean_t) ** 2 for x in tempo) / len(tempo)) ** 0.5
    return {
        "n": total,
        "saturated": saturated,
        "saturated_frac": saturated / total,
        "zeroed": zeroed,
        "zeroed_frac": zeroed / total,
        "tempo_sd": sd_t,
        "tempo_min": min(tempo),
        "tempo_max": max(tempo),
    }
