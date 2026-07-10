"""Loader for Wave 1's NRL margin+total model (predicted_margin/predicted_total
on SportPrediction). Mirrors ml/sports/nrl/params.py's load/save pattern:
pipeline/sports/nrl_margin_total_fit.py's least-squares fit writes this file;
everything that serves predicted_margin/predicted_total loads through
load_margin_total_params so a missing/corrupt file never breaks serving --
it falls back to NrlMarginTotalParams()'s hand-set v0.1 defaults, exactly
like ml.sports.nrl.params falls back to NrlParams().

Distinct from ml/sports/nrl/params.py (the win-probability Elo model): that
module tunes NrlParams (k, home_adv in Elo points, margin_slope -- the
existing `expected_margin` field's source). This module fits a SEPARATE
margin+total regression (predicted_margin/predicted_total, version
"nrl-elo-v0.2") that Wave 1 adds to the detail endpoint and the prose preview.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_PARAMS_FILE = Path(__file__).with_name("nrl_model_params.json")


@dataclass(frozen=True)
class NrlMarginTotalParams:
    version: str = "nrl-elo-v0.1"
    margin_coef_elo_diff: float = 0.045  # points per Elo-diff point (matches
                                          # ml.sports.nrl.model's own margin_slope
                                          # default until the real fit runs)
    margin_intercept: float = 4.0        # fitted home advantage, in POINTS
    expected_total: float = 40.0         # recency-weighted league scoring mean


def load_margin_total_params() -> NrlMarginTotalParams:
    """Load fitted params from nrl_model_params.json, or the v0.1 defaults if
    missing, corrupt, or missing a field."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlMarginTotalParams(
            version=data.get("version", NrlMarginTotalParams().version),
            margin_coef_elo_diff=float(data["margin_coef_elo_diff"]),
            margin_intercept=float(data["margin_intercept"]),
            expected_total=float(data["expected_total"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return NrlMarginTotalParams()


def save_margin_total_params(params: NrlMarginTotalParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")


def predict_margin_total(
    elo_home: float, elo_away: float, p: NrlMarginTotalParams | None = None
) -> tuple[float, float]:
    """Return (predicted_margin, predicted_total) for a fixture's pre-match
    Elo ratings. predicted_margin is home-minus-away points (same sign
    convention as SportMatch.score_home - score_away and the existing
    `expected_margin` field); predicted_total does not depend on Elo."""
    p = p or load_margin_total_params()
    margin = p.margin_coef_elo_diff * (elo_home - elo_away) + p.margin_intercept
    return margin, p.expected_total
