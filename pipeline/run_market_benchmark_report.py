"""Shadow venue benchmark + capture health. READ-ONLY; research data only.

Nothing here trains, tunes, promotes, deploys or flips anything. The output
is a research artifact: readiness in it means "enough data to discuss",
never "switch anything on". Nothing schedules this; an operator runs it.

Usage::

    # benchmark report to stdout (never writes anything anywhere)
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_market_benchmark_report benchmark

    # write the JSON artifact the research API serves
    ... benchmark --output backend/app/research_data/market_benchmark.json

    # capture/mapping health, fixture-denominated
    ... health
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

from ml.evaluation.venue_benchmark import (
    DEFAULT_HOLDOUT_FRACTION,
    DEFAULT_MIN_MATCHES,
    run_benchmark,
)

from pipeline.market_benchmark_data import build_observations
from pipeline.report_market_health import build_health

ARTIFACT_VERSION = "market-benchmark-artifact-v1"

#: The research floor is not lowerable at artifact level: --min-matches may
#: only RAISE it. A published artifact claiming READY on 3 matches is exactly
#: the "tiny sample ranked" failure the gate exists to prevent.
MIN_MATCHES_FLOOR = DEFAULT_MIN_MATCHES
MIN_BOOTSTRAP = 100


def build_artifact(db, *, holdout_fraction: float, min_matches: int,
                   n_bootstrap: int, seed: int,
                   now: datetime | None = None) -> dict:
    """The full research artifact: lineage, exclusions, benchmark, health.

    Gates here are non-lowerable: min_matches clamps UP to the floor,
    bootstrap has a sensible minimum, and a naive clock is refused.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if n_bootstrap < MIN_BOOTSTRAP:
        raise ValueError(
            f"n_bootstrap must be at least {MIN_BOOTSTRAP}; an uncertainty "
            "estimate from fewer samples is decoration")
    effective_min = max(min_matches, MIN_MATCHES_FLOOR)
    data = build_observations(db)
    benchmark = run_benchmark(
        data.observations, holdout_fraction=holdout_fraction,
        min_matches=effective_min, n_bootstrap=n_bootstrap, seed=seed)
    return {
        "artifact_version": ARTIFACT_VERSION,
        "experimental": True,
        "min_matches_floor": MIN_MATCHES_FLOOR,
        "role": (
            "shadow research benchmark; not the pre-registered odds gate, "
            "not a deployment signal"
        ),
        "generated_at": now.isoformat(),
        "lineage": {
            "venue_side": "venue_price_tick mids, latest logical ts <= kickoff",
            "model_side": (
                "the exact frozen prediction from the audited "
                "prediction_results ledger when it exists; otherwise the "
                "latest non-shadow Prediction created before kickoff"),
            "outcome_side": (
                "REGULATION-TIME result: ledger outcome, else 90-minute "
                "score columns, else full time only for non-knockout stages "
                "with no shootout; anything else excluded"),
            "snapshot_side": (
                "coherent 1X2 snapshot: two-sided legs from one polling "
                "cycle where available, otherwise within the cross-leg skew "
                "bound; leg timestamps and skew persisted"),
        },
        "coverage": data.coverage,
        "exclusions": data.exclusions,
        "exclusion_notes": data.notes,
        "benchmark": benchmark,
        "health": build_health(db, now=now),
    }


def _print(artifact: dict) -> None:
    print(json.dumps(artifact, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    bench = sub.add_parser("benchmark", help="shadow benchmark report")
    bench.add_argument("--output", type=Path,
                       help="also write the JSON artifact here")
    bench.add_argument("--holdout-fraction", type=float,
                       default=DEFAULT_HOLDOUT_FRACTION)
    bench.add_argument(
        "--min-matches", type=int, default=DEFAULT_MIN_MATCHES,
        help=f"readiness floor; values below {DEFAULT_MIN_MATCHES} are "
             "clamped UP -- the floor is not lowerable")
    bench.add_argument("--bootstrap", type=int, default=2000)
    bench.add_argument("--seed", type=int, default=20260729)

    sub.add_parser("health", help="capture/mapping health report")

    args = parser.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.command == "benchmark":
            artifact = build_artifact(
                db, holdout_fraction=args.holdout_fraction,
                min_matches=args.min_matches, n_bootstrap=args.bootstrap,
                seed=args.seed)
            _print(artifact)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                # Atomic: a reader (the research API) must never see a
                # half-written artifact. Same-directory temp + os.replace.
                temporary = args.output.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(artifact, indent=2, sort_keys=True) + "\n")
                os.replace(temporary, args.output)
                print(f"\nwrote {args.output}", file=sys.stderr)
        else:
            _print(build_health(db, now=datetime.now(timezone.utc)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
