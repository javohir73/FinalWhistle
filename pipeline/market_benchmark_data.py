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
3. the fixture is finished with a known REGULATION-TIME result (see below);
4. the three legs form ONE COHERENT pre-kickoff snapshot: genuinely
   two-sided quotes (bid AND ask AND mid), same capture timestamp where the
   venue was polled as a cycle, otherwise within a strict cross-leg skew
   bound -- three legs captured hours apart are a fictitious book, however
   fresh each one looks individually;
5. the model vector is the exact frozen pre-kickoff prediction -- taken from
   the audited ``prediction_results`` ledger when it exists, so the vector
   scored here is the vector the public record scored.

Outcome basis: the model's 1X2 is a REGULATION-TIME distribution. A knockout
match 1-1 after 90 that finishes 2-1 in extra time is a DRAW for this
benchmark; using the full final would systematically mislabel every match
that went long. The ledger outcome is used when present; otherwise the
90-minute score columns; otherwise the full-time score ONLY for non-knockout
stages with no shootout, where full time IS regulation. Anything else is
excluded, not guessed.

No in-play or score-matched comparison exists here at all: neither venue
publishes an authoritative score or clock (Phase-2 finding), and internal
live state is never substituted for venue state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import (
    Match,
    Prediction,
    PredictionResult,
    Tournament,
    VenueMarket,
    VenuePriceTick,
)
from ml.evaluation.venue_benchmark import (
    OUTCOMES,
    BenchmarkInputError,
    MatchObservation,
)

#: The oldest leg of the snapshot must be at most this old at kickoff. A book
#: whose final quote is days stale was dead, not closing.
DEFAULT_MAX_QUOTE_AGE = timedelta(hours=48)

#: Legs not sharing an exact capture timestamp may differ by at most this
#: much. Wide enough for consecutive polling cycles of one venue pass, far
#: too narrow to stitch a morning quote onto an evening book.
DEFAULT_MAX_CROSS_LEG_SKEW = timedelta(minutes=15)

#: Stages where full time IS regulation time: no extra time, no shootout.
_NON_KNOCKOUT_STAGES = frozenset({"group", "league"})


def _db_aware(value: datetime | None, *, sqlite_naive_ok: bool) -> datetime | None:
    """Timezone policy for database timestamps, explicit per dialect.

    SQLite drops timezone metadata on columns this schema DEFINES as UTC, so
    under SQLite a naive value is re-tagged UTC. Under any other dialect a
    naive timestamp is corrupt data and fails closed -- silently assuming UTC
    in production is how an hour of skew becomes a wrong closing line.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        if sqlite_naive_ok:
            return value.replace(tzinfo=timezone.utc)
        raise BenchmarkInputError(
            "naive timestamp from a non-SQLite database; refusing to assume UTC")
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


def _regulation_outcome(match: Match, result: BuildResult, label: str) -> str | None:
    """The 90-minute result, or None (excluded and counted) when unknowable."""
    if match.status != "finished":
        result.exclude("no_final_outcome",
                       f"{label}: fixture not finished")
        return None
    home_90, away_90 = match.score_home_90, match.score_away_90
    if home_90 is not None and away_90 is not None:
        basis = "score_90"
        home, away = home_90, away_90
    else:
        went_long = (
            match.penalty_home is not None
            or match.penalty_away is not None
            or (match.stage or "").strip().casefold() not in _NON_KNOCKOUT_STAGES
        )
        if went_long:
            result.exclude(
                "no_regulation_time_basis",
                f"{label}: knockout/shootout fixture without 90-minute score "
                "columns; the full-time score may include extra time")
            return None
        if match.score_home is None or match.score_away is None:
            result.exclude("no_final_outcome",
                           f"{label}: finished fixture without a score")
            return None
        basis = "full_time_is_regulation (non-knockout)"
        home, away = match.score_home, match.score_away
    del basis  # recorded at artifact level via lineage docs
    if home > away:
        return "home"
    if home < away:
        return "away"
    return "draw"


def _two_sided_prekickoff_ticks(
    db: Session, market_id: int, kickoff: datetime, *, sqlite_naive_ok: bool
) -> dict[datetime, VenuePriceTick]:
    """Every genuinely two-sided pre-kickoff tick, keyed by capture time.

    Two-sided means bid AND ask AND mid. "Latest tick, then reject if
    one-sided" was the earlier bug: a newer one-sided update must not hide an
    older valid quote behind it.
    """
    ticks = (
        db.query(VenuePriceTick)
        .filter(VenuePriceTick.venue_market_id == market_id)
        .order_by(VenuePriceTick.ts)
        .all()
    )
    usable: dict[datetime, VenuePriceTick] = {}
    for tick in ticks:
        if tick.yes_bid is None or tick.yes_ask is None or tick.mid is None:
            continue
        ts = _db_aware(tick.ts, sqlite_naive_ok=sqlite_naive_ok)
        if ts is None or ts > kickoff:
            continue
        usable[ts] = tick
    return usable


def _coherent_snapshot(
    legs: dict[str, dict[datetime, VenuePriceTick]],
    *,
    kickoff: datetime,
    max_quote_age: timedelta,
    max_cross_leg_skew: timedelta,
) -> tuple[dict[str, VenuePriceTick], dict[str, datetime]] | str:
    """One coherent 1X2 snapshot, or the exclusion reason.

    Preference order: the latest capture timestamp at which ALL THREE legs
    have a two-sided quote (one polling cycle -- zero skew); otherwise each
    leg's latest quote if the spread between them is within the skew bound.
    """
    common = set.intersection(*(set(times) for times in legs.values()))
    if common:
        ts = max(common)
        chosen = {outcome: times[ts] for outcome, times in legs.items()}
        when = {outcome: ts for outcome in legs}
    else:
        chosen = {}
        when = {}
        for outcome, times in legs.items():
            latest = max(times)
            chosen[outcome] = times[latest]
            when[outcome] = latest
        skew = max(when.values()) - min(when.values())
        if skew > max_cross_leg_skew:
            return (
                f"legs captured up to {skew} apart (bound "
                f"{max_cross_leg_skew}); refusing to stitch a fictitious book")
    oldest = min(when.values())
    if kickoff - oldest > max_quote_age:
        return (f"oldest leg is {kickoff - oldest} before kickoff "
                f"(bound {max_quote_age}); the book was dead, not closing")
    return chosen, when


def _model_vector(
    db: Session, match: Match, kickoff: datetime, result: BuildResult,
    label: str, *, sqlite_naive_ok: bool,
) -> tuple[tuple[float, float, float], str | None] | None:
    """The exact frozen prediction, plus the ledger outcome when audited.

    The audited prediction_results ledger (is_shadow=False) pins BOTH the
    outcome and the precise prediction row the public record scored; when it
    exists, this benchmark scores the same vector against the same result.
    Without it, the latest pre-kickoff non-shadow prediction is used and the
    outcome comes from the fixture's regulation-time score.
    """
    ledger = (
        db.query(PredictionResult)
        .filter(PredictionResult.match_id == match.id,
                PredictionResult.is_shadow.is_(False))
        .one_or_none()
    )
    if ledger is not None:
        prediction = db.get(Prediction, ledger.prediction_id)
        if prediction is None:
            result.exclude(
                "ledger_prediction_missing",
                f"{label}: prediction_results points at a missing prediction")
            return None
        created = _db_aware(prediction.created_at,
                            sqlite_naive_ok=sqlite_naive_ok)
        if created is None or created >= kickoff or prediction.is_shadow:
            result.exclude(
                "ledger_prediction_not_prekickoff",
                f"{label}: the audited prediction is not a pre-kickoff "
                "non-shadow row")
            return None
        if ledger.outcome not in OUTCOMES:
            result.exclude(
                "ledger_outcome_invalid",
                f"{label}: ledger outcome {ledger.outcome!r}")
            return None
        return ((prediction.prob_home_win, prediction.prob_draw,
                 prediction.prob_away_win), ledger.outcome)

    rows = (
        db.query(Prediction)
        .filter(
            Prediction.match_id == match.id,
            Prediction.is_shadow.is_(False),
            Prediction.created_at.isnot(None),
        )
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .all()
    )
    prekickoff = [
        p for p in rows
        if (_db_aware(p.created_at, sqlite_naive_ok=sqlite_naive_ok) or kickoff)
        < kickoff
    ]
    if not prekickoff:
        result.exclude(
            "no_prekickoff_prediction",
            f"{label}: no non-shadow prediction created before kickoff")
        return None
    chosen = prekickoff[0]
    return ((chosen.prob_home_win, chosen.prob_draw, chosen.prob_away_win),
            None)


def build_observations(
    db: Session,
    *,
    max_quote_age: timedelta = DEFAULT_MAX_QUOTE_AGE,
    max_cross_leg_skew: timedelta = DEFAULT_MAX_CROSS_LEG_SKEW,
) -> BuildResult:
    """One observation per (venue, finished mapped fixture). Deterministic."""
    if max_quote_age <= timedelta(0):
        raise BenchmarkInputError("max_quote_age must be positive")
    if max_cross_leg_skew <= timedelta(0):
        raise BenchmarkInputError("max_cross_leg_skew must be positive")
    sqlite_naive_ok = db.get_bind().dialect.name == "sqlite"
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
        try:
            kickoff = _db_aware(match.kickoff_utc,
                                sqlite_naive_ok=sqlite_naive_ok)
        except BenchmarkInputError as exc:
            result.exclude("naive_timestamp", f"{label}: {exc}")
            continue
        if kickoff is None:
            result.exclude("fixture_kickoff_unknown",
                           f"{label}: fixture has no kickoff")
            continue

        vector = _model_vector(db, match, kickoff, result, label,
                               sqlite_naive_ok=sqlite_naive_ok)
        if vector is None:
            continue
        model_probs, ledger_outcome = vector
        outcome = ledger_outcome or _regulation_outcome(match, result, label)
        if outcome is None:
            continue

        tournament = db.get(Tournament, match.tournament_id)
        competition = tournament.name if tournament is not None else "unknown"

        try:
            legs = {
                outcome_name: _two_sided_prekickoff_ticks(
                    db, by_outcome[outcome_name][0].id, kickoff,
                    sqlite_naive_ok=sqlite_naive_ok)
                for outcome_name in OUTCOMES
            }
        except BenchmarkInputError as exc:
            result.exclude("naive_timestamp", f"{label}: {exc}")
            continue
        empty = sorted(name for name, times in legs.items() if not times)
        if empty:
            result.exclude(
                "no_two_sided_prekickoff_quote",
                f"{label}: no two-sided pre-kickoff quote for "
                + ", ".join(empty))
            continue
        snapshot = _coherent_snapshot(
            legs, kickoff=kickoff, max_quote_age=max_quote_age,
            max_cross_leg_skew=max_cross_leg_skew)
        if isinstance(snapshot, str):
            reason = ("stale_prekickoff_quote" if "dead" in snapshot
                      else "incoherent_market_snapshot")
            result.exclude(reason, f"{label}: {snapshot}")
            continue
        chosen, when = snapshot

        try:
            observation = MatchObservation(
                match_id=match_id,
                venue=venue,
                competition=competition,
                kickoff_utc=kickoff,
                captured_at=max(when.values()),
                outcome=outcome,
                model_probs=model_probs,
                venue_probs_raw=(chosen["home"].mid, chosen["draw"].mid,
                                 chosen["away"].mid),
                leg_captured_at=(when["home"], when["draw"], when["away"]),
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
