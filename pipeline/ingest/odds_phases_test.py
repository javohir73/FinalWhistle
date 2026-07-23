"""Tests for the pre-kickoff band schedule (phased closing-line archive)."""
import pytest

from pipeline.ingest.odds_phases import current_band, due_phase


@pytest.mark.parametrize("hours,expected", [
    (48.0, "opening"),
    (24.0, "t24"),
    (6.0, "t6"),
    (1.0, "t1"),
    (0.5, "closing"),
    (0.0, "closing"),
    (48.01, None),
    (-0.1, None),
])
def test_current_band_boundaries(hours, expected):
    assert current_band(hours) == expected


def test_due_phase_returns_the_band_when_not_yet_captured():
    assert due_phase(6.0, existing_phases=set()) == "t6"
    assert due_phase(6.0, existing_phases={"opening", "t24"}) == "t6"


def test_due_phase_returns_none_when_the_band_is_already_captured():
    assert due_phase(6.0, existing_phases={"t6"}) is None


def test_due_phase_returns_none_outside_the_48h_window():
    assert due_phase(48.01, existing_phases=set()) is None
    assert due_phase(-0.1, existing_phases=set()) is None
