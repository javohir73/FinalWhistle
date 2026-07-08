"""Tuned parameter loader for the NRL Elo model (task 5).

Mirrors ml/models/params.py's load_params/save_params pattern, scaled down to
NrlParams's small field set: pipeline/sports/nrl_backtest.py's tuner (task 4)
fits the W/D/L-relevant knobs on real seasons; the result is written ONCE to
params.json by this module's save_nrl_params (see nrl_predict.py's --ship-params
step). Everything that serves NRL predictions loads via load_nrl_params so a
missing/corrupt file never breaks the pipeline -- it just falls back to
NrlParams()'s hand-set v0.1 defaults, exactly like the football loader falls
back to DEFAULT_PARAMS.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ml.sports.nrl.model import NrlParams

_PARAMS_FILE = Path(__file__).with_name("params.json")


def load_nrl_params() -> NrlParams:
    """Load tuned params from params.json, or NrlParams() defaults if
    absent/invalid (missing file, bad JSON, or a missing/malformed field)."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlParams(
            version=data.get("version", NrlParams().version),
            k=float(data["k"]),
            home_adv=float(data["home_adv"]),
            margin_mult_cap=float(data["margin_mult_cap"]),
            season_regress=float(data["season_regress"]),
            margin_slope=float(data["margin_slope"]),
            margin_sigma=float(data["margin_sigma"]),
            p_draw=float(data["p_draw"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return NrlParams()


def save_nrl_params(params: NrlParams) -> None:
    """Write `params` to params.json (indent=2, trailing newline, mirroring
    ml.models.params.save_params)."""
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")
