"""Hourly phased closing-line odds snapshot (pipeline/ingest/odds.py).

Usage:
    PYTHONPATH=backend:. python -m pipeline.snapshot_odds [--budget N]
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, help="max fetches this pass (default: MAX_FETCHES_PER_PASS)")
    args = ap.parse_args()

    from app.config import settings
    from app.db import SessionLocal
    from pipeline.ingest.odds import MAX_FETCHES_PER_PASS, snapshot_phased_odds

    logging.basicConfig(level=logging.INFO)

    if not settings.api_football_api_key:
        log.info("odds snapshot skipped: no API_FOOTBALL_API_KEY")
        return

    budget = args.budget if args.budget is not None else MAX_FETCHES_PER_PASS
    session = SessionLocal()
    try:
        summary = snapshot_phased_odds(session, settings.api_football_api_key,
                                       budget=budget, now=datetime.now(timezone.utc))
        print(summary)
    finally:
        session.close()


if __name__ == "__main__":
    main()
