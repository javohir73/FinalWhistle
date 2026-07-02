"""In-tournament rating updates: conservative Elo deltas + a capped form layer.

The learning loop's rating math (brief tasks 3+4). Design contract
(tasks/design-learning-loop.md):

- ``teams.elo_rating`` stays the HISTORICAL base — rewritten daily from the
  full 49,000-match replay. This module never touches it.
- Each run REPLAYS all finished tournament matches chronologically from that
  base, producing per-team ``elo_delta`` — idempotent by construction (same
  inputs → same deltas), so it survives daily base rewrites and re-runs
  without double-applying anything.
- Updates are deliberately conservative: ``K_eff = K_wc × LIVE_DAMPING ×
  stage_weight`` — half the historical convention. One upset informs the
  forecast; it cannot flip a bracket.
- The form layer compares actual goals to the model's own pre-match Poisson
  expectations and folds the (capped) result into a single Elo-equivalent
  adjustment: ±FORM_CAP_ELO ≈ ±5 percentage points of win probability, the
  brief's anti-overfitting ceiling. Inputs are stored for explainability.

Everything here is pure; DB orchestration lives in pipeline/learning_loop.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ml.models.poisson import expected_goals_from_elo
from ml.ratings.elo import expected_score, goal_diff_multiplier, k_factor

# --- Conservative-update knobs (asserted in tests; change deliberately) -----

#: Damping applied to the historical K for live in-tournament updates. The
#: full-history replay remains the source of truth; live deltas are a nudge.
LIVE_DAMPING = 0.5

#: Extra weight for later stages — elimination football carries more signal.
STAGE_WEIGHTS = {
    "group": 1.0,
    "R32": 1.1,
    "R16": 1.1,
    "QF": 1.2,
    "SF": 1.2,
    "final": 1.2,
}

#: Form layer: Elo-equivalent points per goal of mean residual, and the hard
#: cap. ±35 Elo ≈ ±5 pp win probability for an even match (logistic slope
#: ln10/1600 per point) — inside the brief's ±5–8% ceiling.
FORM_ELO_PER_GOAL = 40.0
FORM_CAP_ELO = 35.0

#: Matches needed before the form layer reaches full weight (√(n/4) ramp:
#: one match carries half the influence of four).
FORM_FULL_WEIGHT_MATCHES = 4


@dataclass(frozen=True)
class TournamentMatch:
    """One finished tournament match, in kickoff order."""

    home_id: int
    away_id: int
    score_home: int
    score_away: int
    stage: str = "group"
    home_adv: float = 0.0  # host bonus in Elo points; 0 on neutral ground


@dataclass
class TeamState:
    """Per-team learning state produced by the replay."""

    elo_delta: float = 0.0
    matches_played: int = 0
    gf_residual_sum: float = 0.0  # actual goals − expected goals (attack)
    ga_residual_sum: float = 0.0  # conceded − expected conceded (defense)
    detail: list[dict] = field(default_factory=list)

    @property
    def gf_residual_mean(self) -> float:
        return self.gf_residual_sum / self.matches_played if self.matches_played else 0.0

    @property
    def ga_residual_mean(self) -> float:
        return self.ga_residual_sum / self.matches_played if self.matches_played else 0.0

    @property
    def form_adjustment(self) -> float:
        return form_adjustment(
            self.gf_residual_mean, self.ga_residual_mean, self.matches_played
        )

    @property
    def total_adjustment(self) -> float:
        """What gets added to the historical base rating."""
        return self.elo_delta + self.form_adjustment


def stage_weight(stage: str) -> float:
    return STAGE_WEIGHTS.get(stage, 1.0)


def form_adjustment(gf_residual_mean: float, ga_residual_mean: float, n: int) -> float:
    """Capped Elo-equivalent form adjustment.

    Positive residual difference = scoring more AND/OR conceding less than the
    model expected. The √(n/4) ramp keeps one hot match from carrying full
    weight; the clamp is the hard anti-overfitting ceiling.
    """
    if n <= 0:
        return 0.0
    weight = min(1.0, math.sqrt(n / FORM_FULL_WEIGHT_MATCHES))
    raw = FORM_ELO_PER_GOAL * (gf_residual_mean - ga_residual_mean) * weight
    return max(-FORM_CAP_ELO, min(FORM_CAP_ELO, raw))


def replay_tournament(
    base_elos: dict[int, float],
    matches: list[TournamentMatch],
    goals_base: float | None = None,
    goals_beta: float | None = None,
) -> dict[int, TeamState]:
    """Replay finished tournament matches from the historical base ratings.

    ``matches`` MUST be in kickoff order (Elo is path-dependent). Teams absent
    from ``base_elos`` are skipped defensively (shouldn't happen — all 48
    teams carry ratings after a pipeline run).

    Expectations for the form residuals use the PRE-match effective rating
    (base + delta-so-far), mirroring exactly what the model would have
    predicted at that point — so "overperformance" means beating the model,
    not beating a fixed pre-tournament view.
    """
    states: dict[int, TeamState] = {}
    k_wc = k_factor("FIFA World Cup")
    goal_kw = {}
    if goals_base is not None:
        goal_kw["base"] = goals_base
    if goals_beta is not None:
        goal_kw["beta"] = goals_beta

    for m in matches:
        if m.home_id not in base_elos or m.away_id not in base_elos:
            continue
        sh = states.setdefault(m.home_id, TeamState())
        sa = states.setdefault(m.away_id, TeamState())

        eff_home = base_elos[m.home_id] + sh.elo_delta
        eff_away = base_elos[m.away_id] + sa.elo_delta

        # --- form residuals vs the model's own pre-match expectation ---
        # Measured against the SERVED goal model (goals_base/goals_beta from
        # model_params.json) so stored residuals carry no systematic bias;
        # None falls back to the v0.1 constants for old callers/tests (FR-2.4).
        lam_home, lam_away = expected_goals_from_elo(eff_home, eff_away, m.home_adv, **goal_kw)
        sh.gf_residual_sum += m.score_home - lam_home
        sh.ga_residual_sum += m.score_away - lam_away
        sa.gf_residual_sum += m.score_away - lam_away
        sa.ga_residual_sum += m.score_home - lam_home

        # --- conservative, stage-weighted Elo delta (zero-sum) ---
        exp_home = expected_score(eff_home, eff_away, m.home_adv)
        if m.score_home > m.score_away:
            w_home = 1.0
        elif m.score_home == m.score_away:
            w_home = 0.5
        else:
            w_home = 0.0
        k_eff = k_wc * LIVE_DAMPING * stage_weight(m.stage)
        delta = k_eff * goal_diff_multiplier(m.score_home - m.score_away) * (
            w_home - exp_home
        )
        sh.elo_delta += delta
        sa.elo_delta -= delta
        sh.matches_played += 1
        sa.matches_played += 1

        record = {
            "stage": m.stage,
            "score": f"{m.score_home}-{m.score_away}",
            "k_eff": round(k_eff, 2),
            "delta_home": round(delta, 2),
            "expected_home": round(exp_home, 4),
            "lambda_home": round(lam_home, 3),
            "lambda_away": round(lam_away, 3),
        }
        sh.detail.append({**record, "opponent_id": m.away_id, "side": "home"})
        sa.detail.append({**record, "opponent_id": m.home_id, "side": "away"})

    return states
