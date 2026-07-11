"""Tuned model parameters for the production prediction engine.

The walk-forward tuner (ml/evaluation/tune.py, run via pipeline/tune_model.py)
writes the fitted values to model_params.json next to this module. Everything
that serves predictions loads them through load_params() so the same calibrated
engine is used in generate_predictions and the Monte-Carlo simulators.

If the JSON is absent (e.g. a fresh checkout before tuning has run), we fall back
to the original hand-set v0.1 constants so nothing breaks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA
from ml.ratings.elo import HOME_ADVANTAGE

_PARAMS_FILE = Path(__file__).with_name("model_params.json")


@dataclass(frozen=True)
class ModelParams:
    version: str
    base: float
    beta: float
    home_adv: float
    rho: float
    temperature: float
    pk_beta: float = 0.0
    # Extra-time goals-per-minute rate relative to regulation (ml/models/knockout.py).
    # 1.0 = same tempo; fittable later with shrinkage, like pk_beta.
    et_tempo: float = 1.0
    # Shootout shift when a first-choice keeper is out (ml/models/knockout.py
    # shootout_p ``shift``; pipeline/suspensions.keeper_pk_shift). 0.0 = no-op.
    pk_keeper_delta: float = 0.0
    calibrator: dict | None = None  # vector-scaling blob or None (temperature-only)
    wdl_blend: dict | None = None    # {"weight": float, "calibrator": dict|None} or None
    # Market-odds anchoring weight for the SHADOW model (exact-score FR-4.3):
    # how far the lambda SUM moves toward the bookmaker total. 0 = blend off —
    # the shipped default; promotion is a manual owner decision (FR-4.8).
    w_odds: float = 0.0
    # Announced-XI / injury availability offsets in the PRODUCTION lambdas:
    # False (the shipped default) keeps serving bit-identical — the signal only
    # runs in the shadow twin (AVAILABILITY_MODEL_VERSION). Promotion to the
    # headline is a manual owner decision, mirroring w_odds/form_channels.
    use_availability: bool = False
    # Market-odds anchoring in the PRODUCTION lambdas: False (the shipped
    # default) keeps serving bit-identical — w_odds > 0 alone only arms the
    # shadow twin (SHADOW_MODEL_VERSION). Flipped by pipeline/promote_blend.py
    # --use-odds once the shadow gate clears (docs/RUNBOOK-WC26-ENDGAME.md).
    use_odds: bool = False
    team_offsets: dict | None = None  # {"file": "team_offsets.json"} or None (disabled, FR-5.3)
    # Split, decayed, boundary-free form channels (model v2 C1):
    # {"c_atk": float, "c_def": float, "cap": float, "half_life": float} or
    # None (disabled — the shipped default). None means the serving path is
    # bit-identical to today's legacy single-scalar form_adjustment; enabling
    # it also turns OFF that legacy scalar so the two never double-count.
    form_channels: dict | None = None
    # Suspension signal (signal pack, v0.5): {"enabled": true} or None (off —
    # the shipped default). The +bans shadow twin runs regardless.
    suspensions: dict | None = None
    # Rest-days signal: {"coef": float, "cap": float} or None (off — the
    # shipped default). The +rest shadow twin runs on DEFAULT_REST regardless.
    rest_days: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# Original uncalibrated engine — used as the fallback and as the "v0.1" baseline.
DEFAULT_PARAMS = ModelParams(
    version="poisson-elo-v0.1",
    base=BASE_GOALS,
    beta=ELO_TO_GOALS_BETA,
    home_adv=HOME_ADVANTAGE,
    rho=0.0,
    temperature=1.0,
    pk_beta=0.0,
)


def load_params() -> ModelParams:
    """Load tuned params from model_params.json, or the v0.1 defaults if missing."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return DEFAULT_PARAMS
    return ModelParams(
        version=data.get("version", "poisson-elo-v0.2"),
        base=float(data["base"]),
        beta=float(data["beta"]),
        home_adv=float(data["home_adv"]),
        rho=float(data["rho"]),
        temperature=float(data["temperature"]),
        pk_beta=float(data.get("pk_beta", 0.0)),
        et_tempo=float(data.get("et_tempo", 1.0)),
        pk_keeper_delta=float(data.get("pk_keeper_delta", 0.0)),
        calibrator=data.get("calibrator"),
        wdl_blend=data.get("wdl_blend"),
        w_odds=float(data.get("w_odds", 0.0)),
        use_availability=bool(data.get("use_availability", False)),
        use_odds=bool(data.get("use_odds", False)),
        team_offsets=data.get("team_offsets"),
        form_channels=data.get("form_channels"),
        suspensions=data.get("suspensions"),
        rest_days=data.get("rest_days"),
    )


def save_params(params: ModelParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(params.to_dict(), indent=2) + "\n")
