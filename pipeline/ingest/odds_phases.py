"""Pre-kickoff band schedule for the phased closing-line odds archive.

Five bands carve up the pre-kickoff window into the snapshots a closing-line
study wants: opening (24, 48]; t24 (6, 24]; t6 (1, 6]; t1 (0.5, 1]; closing
[0, 0.5] (hours to kickoff). A match first seen late (e.g. the scheduler was
down, or the match entered the 48h window after this band already closed)
starts at whatever band it's currently in rather than backfilling missed
ones. Since each band is captured at most once per match, a match's whole
lifetime costs at most 5 fetches.

REALISTIC GUARANTEE, given an hourly cron: ``t1`` (0.5, 1]h is the floor —
some hourly pass always lands inside that 30-minute-wide window for every
match. ``closing`` is only 30 minutes wide, so an hourly cadence can miss it
entirely for a match whose kickoff lands near the top of the hour; capturing
it is best-effort, not guaranteed. We deliberately do NOT tighten the cron to
close that gap (GitHub Actions minutes cost on a private repo).
``run_market_benchmark.market_record`` already falls back to the latest
pre-kickoff row when no ``closing`` row exists, so a missed closing snapshot
degrades gracefully rather than breaking the benchmark. For matches where the
true closing line actually matters (e.g. a final), capture it out-of-band —
either an ad-hoc near-kickoff workflow_dispatch (as was done for the WC26
final) or a temporarily tightened cron.

Pure — no DB, no network; the caller (pipeline.ingest.odds) owns persistence.
"""
from __future__ import annotations

PHASES = ("opening", "t24", "t6", "t1", "closing")


def current_band(hours_to_kickoff: float) -> str | None:
    """Which band ``hours_to_kickoff`` falls in, or None outside [0, 48]."""
    h = hours_to_kickoff
    if h > 48.0 or h < 0.0:
        return None
    if h > 24.0:
        return "opening"
    if h > 6.0:
        return "t24"
    if h > 1.0:
        return "t6"
    if h > 0.5:
        return "t1"
    return "closing"


def due_phase(hours_to_kickoff: float, existing_phases: set[str]) -> str | None:
    """The band to capture now, or None when out of range or already captured."""
    band = current_band(hours_to_kickoff)
    if band is None or band in existing_phases:
        return None
    return band
