"""Hourly phased closing-line odds snapshot (pipeline/ingest/odds.py).

Usage:
    PYTHONPATH=backend:. python -m pipeline.snapshot_odds [--budget N]
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def main() -> int:
    """Exit-code contract (consumed by the odds-snapshots workflow step):

    - 0: the run completed — including a clean no-op when the API key is
      unconfigured, and including per-match misses (no fixture id, feed
      down, no markets), which snapshot_phased_odds already absorbs
      (FR-4.2, never raises).
    - 1: the pass itself failed (e.g. DB unreachable) — surfaced as an
      "error" key in the summary rather than an exception; that's the one
      case the Action should go red on.
    """
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, help="max fetches this pass (default: MAX_FETCHES_PER_PASS)")
    args = ap.parse_args()

    from app.config import settings
    from app.db import SessionLocal
    from pipeline.ingest.odds import MAX_FETCHES_PER_PASS, snapshot_phased_odds

    if not settings.api_football_api_key:
        log.info("odds snapshot skipped: no API_FOOTBALL_API_KEY")
        return 0

    budget = args.budget if args.budget is not None else MAX_FETCHES_PER_PASS
    session = SessionLocal()
    try:
        summary = snapshot_phased_odds(session, settings.api_football_api_key,
                                       budget=budget, now=datetime.now(timezone.utc))
    finally:
        session.close()

    print(summary)
    return 1 if "error" in summary else 0


if __name__ == "__main__":
    raise SystemExit(main())
