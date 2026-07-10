"""Tuned parameter loader for the in-play win-probability logistic (Wave 3).
Mirrors ml/sports/nrl/params.py's load/save pattern exactly."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_PARAMS_FILE = Path(__file__).with_name("live_params.json")


@dataclass(frozen=True)
class NrlLiveParams:
    version: str = "nrl-live-v0.1"
    intercept: float = 0.0
    coef_score_diff: float = 0.25
    coef_interaction: float = 0.02
    coef_pregame_logit: float = 0.5


def load_nrl_live_params() -> NrlLiveParams:
    """Load tuned params from live_params.json, or NrlLiveParams() defaults
    if absent/invalid (missing file, bad JSON, or a missing/malformed field)."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlLiveParams(
            version=data.get("version", NrlLiveParams().version),
            intercept=float(data["intercept"]),
            coef_score_diff=float(data["coef_score_diff"]),
            coef_interaction=float(data["coef_interaction"]),
            coef_pregame_logit=float(data["coef_pregame_logit"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return NrlLiveParams()


def save_nrl_live_params(params: NrlLiveParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")
