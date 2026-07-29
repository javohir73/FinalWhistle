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


def build_artifact(db, *, holdout_fraction: float, min_matches: int,
                   n_bootstrap: int, seed: int,
                   now: datetime | None = None) -> dict:
    """The full research artifact: lineage, exclusions, benchmark, health."""
    now = now or datetime.now(timezone.utc)
    data = build_observations(db)
    benchmark = run_benchmark(
        data.observations, holdout_fraction=holdout_fraction,
        min_matches=min_matches, n_bootstrap=n_bootstrap, seed=seed)
    return {
        "experimental": True,
        "role": (
            "shadow research benchmark; not the pre-registered odds gate, "
            "not a deployment signal"
        ),
        "generated_at": now.isoformat(),
        "lineage": {
            "venue_side": "venue_price_tick mids, latest logical ts <= kickoff",
            "model_side": "latest non-shadow Prediction created before kickoff",
            "outcome_side": "Match full-time score, finished fixtures only",
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
    bench.add_argument("--min-matches", type=int, default=DEFAULT_MIN_MATCHES)
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
                args.output.write_text(
                    json.dumps(artifact, indent=2, sort_keys=True) + "\n")
                print(f"\nwrote {args.output}", file=sys.stderr)
        else:
            _print(build_health(db, now=datetime.now(timezone.utc)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
