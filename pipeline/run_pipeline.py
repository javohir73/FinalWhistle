"""Daily pipeline orchestrator (PRD §7, task 7).

Runs the full refresh: load WC2026 structure -> ingest historical results ->
recompute Elo -> compute team stats -> (optional FIFA rankings) -> generate
predictions + standings. Every step is idempotent and logged; any failure is
logged loudly and re-raised so the scheduler (GitHub Actions) marks the run failed.

Usage:
    PYTHONPATH=backend:. python -m pipeline.run_pipeline
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy.orm import Session

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [pipeline] %(message)s"
)
log = logging.getLogger(__name__)


def run_pipeline(db: Session, results_df=None, n_sims: int = 5000) -> dict:
    """Execute the full refresh. Pass results_df to skip the network download
    (used by tests). Returns a summary of every step."""
    from app.config import settings
    from pipeline.compute_elo import compute_and_store_elo
    from pipeline.generate_predictions import generate_predictions
    from pipeline.ingest.fifa_rankings import LOCAL_RANKINGS_CSV, apply_rankings, load_rankings_df
    from pipeline.ingest.historical_results import download_results_df, load_historical
    from pipeline.ingest.wc26_structure import load_structure
    from pipeline.prune_auth import prune_auth_rows
    from pipeline.team_stats import compute_team_stats

    summary: dict = {}

    def step(name: str, fn):
        log.info("step: %s …", name)
        try:
            result = fn()
        except Exception:  # noqa: BLE001 - log + re-raise so the scheduler fails
            log.exception("step FAILED: %s", name)
            raise
        log.info("step done: %s -> %s", name, result)
        summary[name] = result
        return result

    step("structure", lambda: load_structure(db))
    df = results_df if results_df is not None else step("download_results", download_results_df)
    step("historical", lambda: load_historical(db, df))
    step("elo", lambda: compute_and_store_elo(db))
    step("team_stats", lambda: compute_team_stats(db))

    # FIFA rankings are optional (Elo is primary). Skip cleanly if no source.
    if LOCAL_RANKINGS_CSV.exists():
        step("fifa_rankings", lambda: apply_rankings(db, load_rankings_df()))
    else:
        log.info("step skipped: fifa_rankings (no %s)", LOCAL_RANKINGS_CSV.name)

    step("predictions", lambda: generate_predictions(db, settings.model_version, n_sims))
    step("prune_auth", lambda: prune_auth_rows(db))
    log.info("pipeline complete")
    return summary


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.db import Base
    import app.models  # noqa: F401

    engine = create_engine(settings.sqlalchemy_url, future=True)
    Base.metadata.create_all(engine)  # safety for fresh DBs; Alembic owns prod schema
    db = sessionmaker(bind=engine, future=True)()
    try:
        run_pipeline(db)
    except Exception:  # noqa: BLE001
        log.error("pipeline run failed")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
