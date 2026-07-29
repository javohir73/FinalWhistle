"""Assemble benchmark observations from the database. Read-only, fail-closed.

Every row that cannot be scored is EXCLUDED AND COUNTED under a named reason
-- the exclusion table is as much the product as the observations, because a
benchmark that silently drops what it cannot handle reports coverage it does
not have.

Eligibility, in order, all mandatory:

1. the venue market is ``mapped`` with a canonical fixture and a canonical
   1X2 outcome (Phase-3 resolver output; nothing proposed or ambiguous);
2. the venue's three outcome markets for that fixture form a COMPLETE,
   EXCLUSIVE set -- exactly home/draw/away, no duplicates, no conflicts;
3. the fixture is finished with a known final score (one final, not two);
4. each market has a two-sided PRE-KICKOFF quote: the latest tick whose
   logical time is at or before kickoff, with a mid, not stale;
5. the production model has a pre-kickoff, non-shadow prediction.

No in-play or score-matched comparison exists here at all: neither venue
publishes an authoritative score or clock (Phase-2 finding), and internal
live state is never substituted for venue state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Match, Prediction, Tournament, VenueMarket, VenuePriceTick
from ml.evaluation.venue_benchmark import (
    OUTCOMES,
    BenchmarkInputError,
    MatchObservation,
)

#: The last pre-kickoff quote must be at most this old at kickoff. A book
#: whose final quote is days stale was dead, not closing.
DEFAULT_MAX_QUOTE_AGE = timedelta(hours=48)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class BuildResult:
    observations: list[MatchObservation] = field(default_factory=list)
    #: exclusion reason -> count of (venue, match) groups it removed.
    exclusions: dict[str, int] = field(default_factory=dict)
    #: named diagnostics an operator can act on, deterministic order.
    notes: list[str] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)

    def exclude(self, reason: str, note: str | None = None) -> None:
        self.exclusions[reason] = self.exclusions.get(reason, 0) + 1
        if note is not None:
            self.notes.append(note)


def _final_outcome(match: Match) -> str | None:
    if match.status != "finished":
        return None
    if match.score_home is None or match.score_away is None:
        return None
    if match.score_home > match.score_away:
        return "home"
    if match.score_home < match.score_away:
        return "away"
    return "draw"


def _latest_prekickoff_tick(
    db: Session, market_id: int, kickoff: datetime
) -> VenuePriceTick | None:
    rows = (
        db.query(VenuePriceTick)
        .filter(VenuePriceTick.venue_market_id == market_id)
        .order_by(VenuePriceTick.ts.desc())
        .all()
    )
    for tick in rows:
        ts = _aware(tick.ts)
        if ts is not None and ts <= kickoff:
            return tick
    return None


def build_observations(
    db: Session,
    *,
    max_quote_age: timedelta = DEFAULT_MAX_QUOTE_AGE,
) -> BuildResult:
    """One observation per (venue, finished mapped fixture). Deterministic."""
    result = BuildResult()

    mapped = (
        db.query(VenueMarket)
        .filter(
            VenueMarket.mapping_status == "mapped",
            VenueMarket.canonical_event_id.isnot(None),
            VenueMarket.canonical_outcome.isnot(None),
        )
        .order_by(VenueMarket.venue, VenueMarket.canonical_event_id,
                  VenueMarket.canonical_outcome, VenueMarket.venue_key)
        .all()
    )

    groups: dict[tuple[str, int], list[VenueMarket]] = {}
    for market in mapped:
        groups.setdefault(
            (market.venue, market.canonical_event_id), []).append(market)

    total_groups = len(groups)
    for (venue, match_id), markets in sorted(groups.items()):
        label = f"{venue}/match {match_id}"

        by_outcome: dict[str, list[VenueMarket]] = {}
        unknown = [m for m in markets if m.canonical_outcome not in OUTCOMES]
        for market in markets:
            if market.canonical_outcome in OUTCOMES:
                by_outcome.setdefault(market.canonical_outcome, []).append(market)
        if unknown:
            result.exclude(
                "non_1x2_outcome",
                f"{label}: outcomes outside home/draw/away: "
                + ", ".join(sorted(str(m.canonical_outcome) for m in unknown)))
            continue
        duplicates = {k: v for k, v in by_outcome.items() if len(v) > 1}
        if duplicates:
            result.exclude(
                "conflicting_duplicate_outcome",
                f"{label}: more than one mapped market for "
                + ", ".join(sorted(duplicates)))
            continue
        if set(by_outcome) != set(OUTCOMES):
            missing = sorted(set(OUTCOMES) - set(by_outcome))
            result.exclude(
                "incomplete_1x2_set",
                f"{label}: missing mapped outcome(s): {', '.join(missing)}")
            continue

        match = db.get(Match, match_id)
        if match is None:
            result.exclude("fixture_missing", f"{label}: no such match row")
            continue
        kickoff = _aware(match.kickoff_utc)
        if kickoff is None:
            result.exclude("fixture_kickoff_unknown",
                           f"{label}: fixture has no kickoff")
            continue
        outcome = _final_outcome(match)
        if outcome is None:
            result.exclude(
                "no_final_outcome",
                f"{label}: fixture not finished with a full-time score")
            continue

        tournament = db.get(Tournament, match.tournament_id)
        competition = tournament.name if tournament is not None else "unknown"

        raw_prices = {}
        quote_times = {}
        problem = None
        for outcome_name in OUTCOMES:
            market = by_outcome[outcome_name][0]
            tick = _latest_prekickoff_tick(db, market.id, kickoff)
            if tick is None:
                problem = ("no_prekickoff_quote",
                           f"{label}: {outcome_name} has no pre-kickoff tick")
                break
            if tick.mid is None:
                problem = ("no_two_sided_quote",
                           f"{label}: {outcome_name} last pre-kickoff tick "
                           "has no midpoint")
                break
            ts = _aware(tick.ts)
            if kickoff - ts > max_quote_age:
                problem = ("stale_prekickoff_quote",
                           f"{label}: {outcome_name} last quote is "
                           f"{kickoff - ts} before kickoff")
                break
            raw_prices[outcome_name] = tick.mid
            quote_times[outcome_name] = ts
        if problem is not None:
            result.exclude(*problem)
            continue

        prediction = (
            db.query(Prediction)
            .filter(
                Prediction.match_id == match_id,
                Prediction.is_shadow.is_(False),
                Prediction.created_at.isnot(None),
            )
            .order_by(Prediction.created_at.desc(), Prediction.id.desc())
            .all()
        )
        prekickoff = [
            p for p in prediction
            if _aware(p.created_at) is not None and _aware(p.created_at) < kickoff
        ]
        if not prekickoff:
            result.exclude(
                "no_prekickoff_prediction",
                f"{label}: no non-shadow prediction created before kickoff")
            continue
        chosen = prekickoff[0]

        try:
            observation = MatchObservation(
                match_id=match_id,
                venue=venue,
                competition=competition,
                kickoff_utc=kickoff,
                captured_at=max(quote_times.values()),
                outcome=outcome,
                model_probs=(chosen.prob_home_win, chosen.prob_draw,
                             chosen.prob_away_win),
                venue_probs_raw=(raw_prices["home"], raw_prices["draw"],
                                 raw_prices["away"]),
            )
        except BenchmarkInputError as exc:
            result.exclude("invalid_observation", f"{label}: {exc}")
            continue
        result.observations.append(observation)

    result.notes.sort()
    result.exclusions = dict(sorted(result.exclusions.items()))
    result.coverage = {
        "mapped_fixture_venue_groups": total_groups,
        "eligible_observations": len(result.observations),
        "excluded_groups": sum(result.exclusions.values()),
    }
    return result
