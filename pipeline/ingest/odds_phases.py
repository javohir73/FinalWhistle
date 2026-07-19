"""Pre-kickoff band schedule for the phased closing-line odds archive.

Five bands carve up the pre-kickoff window into the snapshots a closing-line
study wants: opening (24, 48]; t24 (6, 24]; t6 (1, 6]; t1 (0.5, 1]; closing
[0, 0.5] (hours to kickoff). A match first seen late (e.g. the scheduler was
down, or the match entered the 48h window after this band already closed)
starts at whatever band it's currently in rather than backfilling missed
ones — so a match seen for the first time inside 30 minutes of kickoff is
captured straight into ``closing``, which is the one snapshot that matters
most and must never be missed. Since each band is captured at most once per
match, a match's whole lifetime costs at most 5 fetches.

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
