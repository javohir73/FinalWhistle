"""Promote the market-odds blend / availability adjustment (spec §4.2).

Params-only: flips ``w_odds`` (hard cap 0.5 — the market is never primary)
and/or ``use_availability`` on model_params.json and bumps the version.
Dry-run by default; --ship writes the file. Merge + deploy stay human-gated.

Run this ONLY after the shadow gate clears: >=30 scored shadow pairs with the
blended twin ahead of production on log loss (see docs/RUNBOOK-WC26-ENDGAME.md).

Usage:
    PYTHONPATH=backend:. python -m pipeline.promote_blend --w-odds 0.35 [--use-availability] [--ship]
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import replace

from ml.models.params import ModelParams, load_params, save_params

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

W_ODDS_CAP = 0.5


def promoted_params(params: ModelParams, w_odds: float, use_availability: bool,
                    version: str) -> ModelParams:
    """The promoted engine: same params with the blend legs flipped on."""
    if w_odds > W_ODDS_CAP:
        raise ValueError(f"w_odds {w_odds} exceeds cap {W_ODDS_CAP} (market is never primary)")
    if w_odds < 0:
        raise ValueError(f"w_odds must be >= 0, got {w_odds}")
    if w_odds == 0 and not use_availability:
        raise ValueError("nothing to promote: w_odds is 0 and use_availability is False")
    return replace(params, w_odds=w_odds, use_availability=use_availability, version=version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--w-odds", type=float, default=0.0)
    parser.add_argument("--use-availability", action="store_true")
    parser.add_argument("--version", default="poisson-elo-v0.6")
    parser.add_argument("--ship", action="store_true")
    args = parser.parse_args()

    shipped = promoted_params(load_params(), args.w_odds, args.use_availability, args.version)
    log.info("promoted engine: %s", shipped.to_dict())
    if not args.ship:
        log.info("dry run — pass --ship to write model_params.json")
        return 0
    save_params(shipped)
    log.info("shipped %s to model_params.json", args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
