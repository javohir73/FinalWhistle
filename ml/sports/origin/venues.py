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
    """DISPLAY fact, not a model input — see MODEL_NEUTRAL_VENUES below for
    the modeling decision. The API badges these venues as neutral regardless
    of what the model does with home_adv there."""
    return bool(venue) and venue.strip().lower() in NEUTRAL_VENUES


# REFUTED (task 4, 2026-07-11): the hypothesis that the model should zero
# home_adv at NEUTRAL_VENUES was tested on the 1985-2024 walk-forward
# backtest (A/B: zeroing vs not, both re-tuned) and refuted — the designated
# home side wins ~65% even at these neutral-labeled venues, so zeroing
# home_adv there cost both accuracy and log loss (avg_log_loss 0.7456 with
# zeroing vs 0.7216 without; winner_accuracy 0.5917 vs 0.65 — see
# backtest_record.json and the task-4 report for the full comparison). The
# model therefore applies home_adv everywhere; reinstating the hypothesis is
# one set-literal away.
MODEL_NEUTRAL_VENUES: frozenset[str] = frozenset()


def model_is_neutral(venue: str | None) -> bool:
    """Whether the MODEL should zero home_adv for this venue. Currently
    always False (see MODEL_NEUTRAL_VENUES above) — distinct from
    is_neutral, which stays a true display fact about the venue."""
    return bool(venue) and venue.strip().lower() in MODEL_NEUTRAL_VENUES
