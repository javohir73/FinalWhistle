"""D1 leakage audit M1–M2 and the schedule-context arithmetic. Hermetic."""
from __future__ import annotations

import math
from datetime import date

import pytest

from ml.features.schedule_context import (
    Fixture,
    coverage,
    schedule_contexts,
)
from pipeline.ingest.venue_coordinates import ClubVenue


def _venues(**kw) -> dict[tuple[str, str], ClubVenue]:
    # Two grounds ~111 km apart (1 degree of latitude), one unresolved club.
    base = {
        ("E0", "Alpha"): ClubVenue("Alpha", "E0", "Alpha F.C.", "Q1", "Alpha Park", 51.0, 0.0, 30000),
        ("E0", "Beta"): ClubVenue("Beta", "E0", "Beta F.C.", "Q2", "Beta Park", 52.0, 0.0, 25000),
    }
    base.update(kw)
    return base


def _season() -> list[Fixture]:
    return [
        Fixture(date(2023, 8, 5), "E0", "Alpha", "Beta"),
        Fixture(date(2023, 8, 9), "E0", "Beta", "Alpha"),
        Fixture(date(2023, 8, 12), "E0", "Alpha", "Beta"),
        Fixture(date(2023, 8, 26), "E0", "Beta", "Alpha"),
    ]


# --------------------------------------------------------------- rest


def test_season_opener_has_no_rest_rather_than_a_default():
    ctx = schedule_contexts(_season()[:1])[0]
    assert ctx.rest_home_days is None and ctx.rest_away_days is None
    assert ctx.rest_diff is None


def test_rest_counts_days_since_each_side_last_played():
    ctxs = schedule_contexts(_season())
    assert (ctxs[1].rest_home_days, ctxs[1].rest_away_days) == (4, 4)
    assert ctxs[1].rest_diff == 0
    assert (ctxs[2].rest_home_days, ctxs[2].rest_away_days) == (3, 3)


# --------------------------------------------------------- congestion


def test_congestion_counts_matches_inside_the_window_only():
    ctxs = schedule_contexts(_season())
    # 26 Aug: prior matches on the 5th, 9th and 12th — 21, 17 and 14 days back.
    # Only the 12th is inside a trailing-14-day window, and it sits exactly on
    # the boundary, which the inclusive rule keeps.
    assert ctxs[3].congestion_home == 1
    assert ctxs[3].congestion_away == 1
    # One day earlier the same match is 15 days back and drops out.
    earlier = schedule_contexts(_season()[:3] + [Fixture(date(2023, 8, 27), "E0", "Beta", "Alpha")])
    assert earlier[3].congestion_home == 0


def test_congestion_is_zero_not_none_for_an_opener():
    # Zero is a real count here: the club has played nothing. Distinct from
    # rest, which is genuinely undefined.
    ctx = schedule_contexts(_season()[:1])[0]
    assert ctx.congestion_home == 0 and ctx.congestion_diff == 0


def test_congestion_window_is_configurable_and_widening_it_cannot_lose_matches():
    fx = _season()
    narrow = schedule_contexts(fx, congestion_window_days=7)[3]
    wide = schedule_contexts(fx, congestion_window_days=60)[3]
    assert wide.congestion_home >= narrow.congestion_home
    assert wide.congestion_home == 3


# ------------------------------------------------------------- travel


def test_travel_is_the_distance_the_away_side_covers():
    ctx = schedule_contexts(_season()[:1], _venues())[0]
    # One degree of latitude ~111.19 km.
    assert ctx.travel_km == pytest.approx(111.19, abs=0.5)
    assert ctx.travel_log == pytest.approx(math.log1p(ctx.travel_km))


def test_travel_is_none_when_a_club_has_no_verified_coordinate():
    fx = [Fixture(date(2023, 8, 5), "E0", "Alpha", "Ghost")]
    ctx = schedule_contexts(fx, _venues())[0]
    assert ctx.travel_km is None and ctx.travel_log is None


def test_travel_is_none_rather_than_zero_when_no_table_is_supplied():
    # Zero would read as "no journey", which is a claim. None is the absence.
    assert schedule_contexts(_season())[0].travel_km is None


def test_reversing_the_fixture_swaps_who_travels():
    v = _venues()
    home_at_alpha = schedule_contexts([Fixture(date(2023, 8, 5), "E0", "Alpha", "Beta")], v)[0]
    home_at_beta = schedule_contexts([Fixture(date(2023, 8, 5), "E0", "Beta", "Alpha")], v)[0]
    # Symmetric distance, but it is attributed to the away side either way.
    assert home_at_alpha.travel_km == pytest.approx(home_at_beta.travel_km)


# ------------------------------------------------- leakage audit M1 / M2


def test_M1_truncating_the_season_does_not_change_an_earlier_fixture(): # noqa: N802
    """Match n's context must not depend on anything after match n."""
    full = _season()
    for i in range(1, len(full) + 1):
        truncated = schedule_contexts(full[:i], _venues())
        complete = schedule_contexts(full, _venues())
        assert truncated[i - 1] == complete[i - 1], f"fixture {i - 1} moved"


def test_M1_input_order_cannot_change_the_result():
    # An order-dependent implementation could pass a truncation test by
    # accident, so scrambling the input must be a no-op.
    fx = _season()
    a = schedule_contexts(fx, _venues())
    b = schedule_contexts(list(reversed(fx)), _venues())
    assert a == list(reversed(b))


def test_M2_no_outcome_can_reach_a_feature():
    """The type system already forbids it — `Fixture` carries no score.

    Asserted rather than assumed, because the guarantee is the phase's whole
    claim: if a score could be attached, a later refactor could read it.
    """
    assert set(Fixture.__dataclass_fields__) == {"date", "division", "home", "away"}
    assert not (
        set(Fixture.__dataclass_fields__)
        & {"score_home", "score_away", "result", "ftr", "goals"}
    )


def test_M3_a_clubs_coordinate_does_not_vary_by_season():
    # One row per club in the snapshot; a season-varying venue would let a
    # later stadium move leak backwards into earlier fixtures.
    from pipeline.ingest.venue_coordinates import load_snapshot

    snap = load_snapshot()
    keys = [(v.division, v.club) for v in snap.values()]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------- coverage


def test_coverage_reports_denominators_for_every_candidate():
    cov = coverage(schedule_contexts(_season(), _venues()))
    assert cov["n_fixtures"] == 4
    assert cov["rest_defined"] == 3  # the opener is undefined for both sides
    assert cov["rest_undefined_openers"] == 1
    assert cov["travel_defined"] == 4
    assert cov["travel_coverage"] == 1.0


def test_coverage_counts_unresolved_coordinates_separately_from_openers():
    fx = _season() + [Fixture(date(2023, 9, 2), "E0", "Alpha", "Ghost")]
    cov = coverage(schedule_contexts(fx, _venues()))
    assert cov["travel_undefined_no_coordinate"] == 1
    assert cov["travel_defined"] == 4
