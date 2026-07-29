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
from pipeline.ingest.venue_coordinates import (
    STATUS_DATED,
    STATUS_SINGLE_UNDATED,
    ClubVenueHistory,
    VenueInterval,
)


def _iv(qid, lat, lon, frm="2000-01-01", to=None):
    return VenueInterval(
        qid, qid, lat, lon, 30000,
        date.fromisoformat(frm), date.fromisoformat(to) if to else None, "NormalRank",
    )


def _venues(override: dict | None = None) -> dict[tuple[str, str], ClubVenueHistory]:
    # Two grounds ~111 km apart (1 degree of latitude), both temporally dated.
    base = {
        ("E0", "Alpha"): ClubVenueHistory(
            "Alpha", "E0", "Alpha F.C.", (_iv("Q1", 51.0, 0.0),), STATUS_DATED),
        ("E0", "Beta"): ClubVenueHistory(
            "Beta", "E0", "Beta F.C.", (_iv("Q2", 52.0, 0.0),), STATUS_DATED),
    }
    base.update(override or {})
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
    assert ctx.travel_excluded_because == "club_absent_from_snapshot"


def test_travel_abstains_for_a_club_whose_venue_history_is_undated():
    undated = _venues({("E0", "Beta"): ClubVenueHistory(
        "Beta", "E0", "Beta F.C.", (_iv("Q2", 52.0, 0.0),), STATUS_SINGLE_UNDATED)})
    ctx = schedule_contexts(_season()[:1], undated)[0]
    assert ctx.travel_km is None
    assert ctx.travel_excluded_because == STATUS_SINGLE_UNDATED


def test_travel_abstains_before_a_venue_interval_opens():
    """The defect this rewrite removes: a later ground answering an earlier date."""
    late = _venues({("E0", "Beta"): ClubVenueHistory(
        "Beta", "E0", "Beta F.C.", (_iv("Q2", 52.0, 0.0, "2019-04-03"),), STATUS_DATED)})
    early = schedule_contexts([Fixture(date(2016, 9, 10), "E0", "Alpha", "Beta")], late)[0]
    later = schedule_contexts([Fixture(date(2023, 8, 5), "E0", "Alpha", "Beta")], late)[0]
    assert early.travel_km is None
    assert early.travel_excluded_because == "interval_gap"
    assert later.travel_km is not None


def test_travel_abstains_in_a_relocation_risk_season():
    ctx = schedule_contexts([Fixture(date(2021, 2, 3), "E0", "Alpha", "Beta")], _venues())[0]
    assert ctx.travel_km is None
    assert ctx.travel_excluded_because == "relocation_risk_season"


def test_travel_is_none_rather_than_zero_when_no_table_is_supplied():
    # Zero would read as "no journey", which is a claim. None is the absence.
    ctx = schedule_contexts(_season())[0]
    assert ctx.travel_km is None
    assert ctx.travel_excluded_because == "no_venue_table"


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


def test_M3_no_future_venue_state_reaches_an_earlier_fixture():
    """M3 restated. The first cut asserted one coordinate per club and called
    that PASS; uniqueness does not prevent a 2019 ground answering a 2016
    fixture, which is exactly what it was doing.

    The real property is temporal: a venue whose interval opens later must not
    contribute to any earlier fixture, at any distance.
    """
    moved = _venues({("E0", "Beta"): ClubVenueHistory(
        "Beta", "E0", "Beta F.C.",
        (_iv("Q_OLD", 51.1, 0.0, "2000-01-01", "2017-05-14"),
         _iv("Q_NEW", 55.0, 0.0, "2019-04-03")), STATUS_DATED)})
    before = schedule_contexts([Fixture(date(2016, 9, 10), "E0", "Alpha", "Beta")], moved)[0]
    during = schedule_contexts([Fixture(date(2018, 3, 4), "E0", "Alpha", "Beta")], moved)[0]
    after = schedule_contexts([Fixture(date(2023, 8, 5), "E0", "Alpha", "Beta")], moved)[0]

    # Before the move: the OLD ground, ~11 km away — not the new one at ~445 km.
    assert before.travel_km == pytest.approx(11.12, abs=0.5)
    # In the gap between intervals: abstain, never a neighbouring guess.
    assert during.travel_km is None and during.travel_excluded_because == "interval_gap"
    # After: the new ground.
    assert after.travel_km == pytest.approx(445.0, abs=1.0)


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
    assert cov["travel_excluded"] == 1
    assert cov["travel_defined"] == 4
    assert cov["travel_exclusions_by_reason"] == {"club_absent_from_snapshot": 1}
