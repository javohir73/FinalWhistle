"""D1 — deterministic pre-match schedule context: rest, congestion, travel.

Every quantity here is computable **strictly before kickoff** from two inputs
and nothing else: the dates of matches that already finished, and a static
club→venue coordinate table. No score, no result, no lineup, no price.

That is the whole design constraint, and it is what makes these features
testable for leakage rather than merely argued to be leak-free: feeding the
fixture list truncated at match *n* must give match *n* the same values as
feeding the full season.

What is new, and what is not
----------------------------
**Rest was already tested and refuted.** `docs/MODEL-EXPERIMENTS.md` T3.2
pre-registered a linear function of the rest differential, ran it, and refuted
it in all three leagues. `ml/models/rest.py` already ships that machinery. This
module does **not** re-run it.

`congestion_14d` is a *different* hypothesis, declared as such before the run:
T3.2 asked how long the gap was, this asks how much was played. A side on its
third match in fourteen days is loaded even if its last gap was four days.

**Travel is genuinely new.** No coordinate existed in this repository before
D1, so distance has never been a candidate here.

Pure module — no I/O, no network, no DB.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date as date_type

from pipeline.ingest.venue_coordinates import ClubVenue, UnresolvedVenue, travel_km

#: Congestion window, fixed before the run. Two weeks spans a
#: midweek-plus-weekend cluster without reaching back into the previous month.
CONGESTION_WINDOW_DAYS = 14


@dataclass(frozen=True)
class Fixture:
    """One scheduled match. Carries no outcome, by construction."""

    date: date_type
    division: str
    home: str
    away: str


@dataclass(frozen=True)
class ScheduleContext:
    """Pre-match context for one fixture. ``None`` means genuinely unknown.

    Never a default, never zero-as-missing: a season opener has no prior match,
    so its rest is ``None`` and the caller applies no offset — the behaviour
    `ml.models.rest.rest_offsets` already implements.
    """

    rest_home_days: int | None
    rest_away_days: int | None
    congestion_home: int
    congestion_away: int
    travel_km: float | None  # None when either club has no verified coordinate

    @property
    def rest_diff(self) -> int | None:
        if self.rest_home_days is None or self.rest_away_days is None:
            return None
        return self.rest_home_days - self.rest_away_days

    @property
    def congestion_diff(self) -> int:
        return self.congestion_home - self.congestion_away

    @property
    def travel_log(self) -> float | None:
        """``log1p(km)``. A 400 km trip is not twice the burden of a 200 km one."""
        return None if self.travel_km is None else math.log1p(self.travel_km)


def _prior_dates(history: list[date_type], today: date_type) -> list[date_type]:
    """Dates strictly before ``today``. The leakage boundary, in one line.

    ``history`` must be sorted ascending. Strictly-before is deliberate: a club
    playing twice on one calendar day is a data error, and including same-day
    matches would let a fixture see its own kickoff.
    """
    return history[: bisect_left(history, today)]


def schedule_contexts(
    fixtures: list[Fixture],
    venues: dict[tuple[str, str], ClubVenue] | None = None,
    congestion_window_days: int = CONGESTION_WINDOW_DAYS,
) -> list[ScheduleContext]:
    """Context for every fixture, using only fixtures strictly earlier than it.

    ``fixtures`` need not be sorted; each fixture is scored against the full
    set filtered to strictly-earlier dates, so the result does not depend on
    input order. That property is what makes the leakage test meaningful — an
    order-dependent implementation could pass a truncation test by accident.

    A club with no verified coordinate yields ``travel_km=None`` for its
    fixtures. It is not given a fallback distance.
    """
    by_club: dict[tuple[str, str], list[date_type]] = {}
    for f in fixtures:
        by_club.setdefault((f.division, f.home), []).append(f.date)
        by_club.setdefault((f.division, f.away), []).append(f.date)
    for dates in by_club.values():
        dates.sort()

    out: list[ScheduleContext] = []
    for f in fixtures:
        ctx = {}
        for side, club in (("home", f.home), ("away", f.away)):
            prior = _prior_dates(by_club[(f.division, club)], f.date)
            ctx[f"rest_{side}"] = (f.date - prior[-1]).days if prior else None
            # Inclusive at the far edge: a match exactly `window` days ago is
            # inside a "trailing N days" window. Spelling the comparison as a
            # day count rather than an ordinal cutoff keeps the boundary
            # legible instead of off-by-one bait.
            ctx[f"cong_{side}"] = sum(
                1 for d in prior if 0 < (f.date - d).days <= congestion_window_days
            )

        km: float | None = None
        if venues is not None:
            try:
                km = travel_km(venues, f.division, f.home, f.away)
            except UnresolvedVenue:
                km = None

        out.append(
            ScheduleContext(
                rest_home_days=ctx["rest_home"],
                rest_away_days=ctx["rest_away"],
                congestion_home=ctx["cong_home"],
                congestion_away=ctx["cong_away"],
                travel_km=km,
            )
        )
    return out


def coverage(contexts: list[ScheduleContext]) -> dict:
    """Denominators for every candidate, in the D0 house style.

    A candidate's usable count is reported against the full fixture count, so a
    feature that is only defined for two thirds of matches cannot be read as if
    it were defined for all of them.
    """
    n = len(contexts)
    rest = sum(1 for c in contexts if c.rest_diff is not None)
    travel = sum(1 for c in contexts if c.travel_km is not None)
    return {
        "n_fixtures": n,
        "rest_defined": rest,
        "rest_undefined_openers": n - rest,
        "rest_coverage": round(rest / n, 4) if n else None,
        "travel_defined": travel,
        "travel_undefined_no_coordinate": n - travel,
        "travel_coverage": round(travel / n, 4) if n else None,
        "congestion_defined": n,  # always defined; zero is a real count
    }
