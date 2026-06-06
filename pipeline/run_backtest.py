"""Run the model backtest against past World Cups and print metrics (task 4/7).

Usage:
    PYTHONPATH=backend:. python -m pipeline.run_backtest
"""
from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from pipeline.backtest_data import build_enriched_rows
    from pipeline.ingest.historical_results import download_results_df, load_historical
    from ml.evaluation.backtest import backtest

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    log.info("Downloading historical results …")
    load_historical(db, download_results_df())
    rows = build_enriched_rows(db)

    for year in (2018, 2022):
        r = backtest(rows, year)
        log.info("\n=== World Cup %s (%d matches) ===", year, r["n_matches"])
        for key in ("model", "favorite_baseline", "base_rate_baseline"):
            m = r[key]
            log.info(
                "  %-20s log_loss=%.4f brier=%.4f acc=%.3f",
                key, m["log_loss"], m["brier"], m["accuracy"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
