"""Per-team attack/defence offset policy + store loader (PRD FR-5.1/FR-5.2).

The offline fitter (pipeline/fit_attack_defence.py) writes team_offsets.json
next to this module: {team_name: {"atk": float, "def": float, "n_matches": int}}.
Offsets are log-lambda units — the match cards AND both Monte-Carlo simulators
(group qualification + tournament bracket) apply λ_home ×= exp(atk_home +
def_away) (and mirrored for away) at the single choke point in
ml/models/poisson.py (expected_goals_from_elo), and ONLY when model_params.json
enables them ("team_offsets" is null by default, so production behavior is
unchanged). The pipeline routes all three paths through one loader
(pipeline/generate_predictions._offsets_by_team_id) so a served page can never
mix offset-adjusted match probabilities with offset-free simulation odds.

Anti-overfitting policy mirrors the in-tournament form layer
(ml/ratings/tournament.py): a √(n/full-weight) confidence ramp plus a hard cap,
translated from Elo points into log-lambda units. This module stays dependency-
light (stdlib only) — it IS imported on the serving path; the fitter is not.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

#: Hard cap on |offset| in log-lambda units. The form layer caps its rating nudge
#: at ±FORM_CAP_ELO = 35 Elo; through the served elo→goals slope (beta = 0.0021)
#: that is a log-lambda shift of 0.0021 × 35 ≈ 0.0735 → 0.075. exp(0.075) ≈ 1.078,
#: so no single fitted offset may move a team's expected goals by more than ~8%.
OFFSET_CAP = 0.075

#: Decay-weighted effective match count at which an offset reaches full weight.
#: Same √ ramp shape as the form layer's √(n/4), but a STATIC fit claims a
#: persistent trait, so full confidence needs ~30 effective matches (≈ 3 years
#: of a typical international calendar), not 4.
FULL_WEIGHT_EFF_MATCHES = 30.0

_OFFSETS_FILE = Path(__file__).with_name("team_offsets.json")


def shrink_and_cap(atk: float, dfn: float, n_eff: float) -> tuple[float, float]:
    """Apply the anti-overfitting policy to one team's raw fitted offsets.

    Cap FIRST, then ramp: clamping to ±OFFSET_CAP and multiplying by the
    √(n_eff/full-weight) confidence ramp guarantees a team below the
    effective-match floor keeps at most OFFSET_CAP·√(n_eff/full) — a few-match
    team gets a near-zero adjustment no matter how extreme its raw fit (FR-5.2).
    """
    if n_eff <= 0:
        return 0.0, 0.0
    ramp = min(1.0, math.sqrt(n_eff / FULL_WEIGHT_EFF_MATCHES))
    clamp = lambda v: max(-OFFSET_CAP, min(OFFSET_CAP, v)) * ramp  # noqa: E731
    return clamp(atk), clamp(dfn)


def load_team_offsets(path: str | Path | None = None) -> dict:
    """Read the fitted offsets store ({team_name: {atk, def, n_matches}}).

    Relative paths resolve next to this module (where the fitter writes).
    Missing or invalid file -> {} so serving degrades to a no-op, never raises.
    """
    p = Path(path) if path is not None else _OFFSETS_FILE
    if not p.is_absolute():
        p = Path(__file__).parent / p
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def offsets_for(store: dict, team_name: str) -> tuple[float, float]:
    """(atk, def) for a team, hard-clamped to OFFSET_CAP; (0, 0) when unknown.

    The clamp is defence in depth: the fitter already caps at write time, but a
    hand-edited store must never push a served lambda past the policy ceiling.
    """
    entry = store.get(team_name)
    if not isinstance(entry, dict):
        return 0.0, 0.0

    def _clamped(key: str) -> float:
        try:
            v = float(entry.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(-OFFSET_CAP, min(OFFSET_CAP, v))

    return _clamped("atk"), _clamped("def")
