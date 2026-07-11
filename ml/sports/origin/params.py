"""Tuned parameter loader for the Origin Elo model (design 2026-07-11).

Same load/save pattern as ml/sports/nrl/params.py, with Origin-flavored
defaults: only 3 games a year means each result carries more information
(higher K), the designated "home" side's edge is weaker than a club ground's
(lower home_adv), the rep player pool is stable era to era (weak season
regression), and pre-golden-point history has real draws (higher p_draw).
These hand-set values are the pre-tuning fallback; ml.sports.origin.backtest
--tune --write fits the real ones into params.json.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ml.sports.nrl.model import NrlParams

_PARAMS_FILE = Path(__file__).with_name("params.json")

ORIGIN_DEFAULTS = NrlParams(
    version="origin-elo-v0.1",
    k=48.0,
    home_adv=30.0,
    margin_mult_cap=2.2,
    season_regress=0.10,
    margin_slope=0.045,
    margin_sigma=14.0,
    p_draw=0.02,
)


def load_origin_params() -> NrlParams:
    """Load tuned params from params.json, or ORIGIN_DEFAULTS if absent/invalid."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlParams(
            version=data.get("version", ORIGIN_DEFAULTS.version),
            k=float(data["k"]),
            home_adv=float(data["home_adv"]),
            margin_mult_cap=float(data["margin_mult_cap"]),
            season_regress=float(data["season_regress"]),
            margin_slope=float(data["margin_slope"]),
            margin_sigma=float(data["margin_sigma"]),
            p_draw=float(data["p_draw"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return ORIGIN_DEFAULTS


def save_origin_params(params: NrlParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")
