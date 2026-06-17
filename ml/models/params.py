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
    calibrator: dict | None = None  # vector-scaling blob or None (temperature-only)

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
        calibrator=data.get("calibrator"),
    )


def save_params(params: ModelParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(params.to_dict(), indent=2) + "\n")
