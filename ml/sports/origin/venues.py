"""Neutral-venue detection for State of Origin fixtures.

Origin's "home" team designation at an interstate/neutral ground is
administrative — nobody has a crowd edge at the MCG. Venue strings missing
from this set (including the seed file's many empty venues) default to
NON-neutral: the designated home side keeps its advantage. Accepted
approximation per the design doc.
"""
from __future__ import annotations

NEUTRAL_VENUES = frozenset({
    "melbourne cricket ground",
    "mcg",
    "docklands stadium",
    "etihad stadium",
    "marvel stadium",
    "optus stadium",
    "perth stadium",
    "adelaide oval",
    "tio stadium",
})


def is_neutral(venue: str | None) -> bool:
    return bool(venue) and venue.strip().lower() in NEUTRAL_VENUES
