"""Run the variant/ablation experiment table and print it (model v2 §5).

Usage:
    PYTHONPATH=backend:. python -m pipeline.run_experiments
    PYTHONPATH=backend:. python -m pipeline.run_experiments --years 2018 2022 \
        --variants v0.1-raw v0.2-tuned
"""
from __future__ import annotations

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", default=[2018, 2022])
    parser.add_argument("--variants", nargs="+", default=None,
                         help="variant names (default: core + available optional variants)")
    args = parser.parse_args()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from ml.evaluation.experiments import format_table, run_experiments
    from pipeline.backtest_data import build_enriched_rows
    from pipeline.ingest.historical_results import download_results_df, load_historical

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    log.info("Downloading historical results …")
    load_historical(db, download_results_df())
    rows = build_enriched_rows(db)
    log.info("Replayed %d historical matches.\n", len(rows))

    for year in args.years:
        result = run_experiments(rows, year, variant_names=args.variants)
        log.info(format_table(result))
        log.info("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
