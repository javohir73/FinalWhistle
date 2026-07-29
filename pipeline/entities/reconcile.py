"""Apply resolver decisions to venue_market rows. Dry-run first, always.

Write rules, each with a test:

* **Verified rows are untouchable.** A mapping carrying operator verification
  (``resolution_context.verified``) is never modified by replay, whatever the
  resolver now thinks. Corrections flow through :func:`apply_correction`,
  which appends to the audit history instead of overwriting it.
* **No silent remap.** A row already mapped that re-resolves to a DIFFERENT
  fixture or outcome is a conflict: the stored mapping stands, the
  disagreement is recorded in ``resolution_context['conflict']`` and one
  audited history entry, and a human decides. The resolver being newly
  confident is precisely when quiet rewrites are most dangerous.
* **Proposals never touch canonical fields.** ``proposed`` and ``ambiguous``
  put their candidate and explanation in ``resolution_context`` only;
  ``canonical_event_id`` / ``canonical_outcome`` stay NULL until a human or a
  fully-consistent resolution sets them.
* **Idempotent replay.** Re-running against unchanged inputs rewrites
  nothing and appends no history. History entries record transitions, not
  executions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    CanonicalEntity,
    EntitySourceMap,
    Match,
    Tournament,
    VenueMarket,
)
from pipeline.entities.descriptors import (
    ExtractionFailure,
    kalshi_descriptor,
    descriptor_from_metadata,
)
from pipeline.entities.resolver import (
    AMBIGUOUS,
    MAPPED,
    RESOLVER_VERSION,
    UNMAPPED,
    FixtureCandidate,
    Resolution,
    resolve_market,
)

#: entity_source_map source for our own primary keys. The internal side of a
#: fixture is just another source with exact keys, so the resolver compares
#: entity ids only and never sees a raw name.
INTERNAL_SOURCE = "internal"


def internal_team_key(team_id: int) -> str:
    return f"team:{team_id}"


def internal_competition_key(tournament_id: int) -> str:
    return f"tournament:{tournament_id}"


def source_entity_index(db: Session) -> dict[tuple[str, str], int]:
    rows = db.query(EntitySourceMap).order_by(
        EntitySourceMap.source, EntitySourceMap.source_key).all()
    return {(row.source, row.source_key): row.entity_id for row in rows}


def entity_kind_index(db: Session) -> dict[int, str]:
    return {row.id: row.kind for row in db.query(CanonicalEntity).all()}


def fixture_candidates(db: Session) -> tuple[list[FixtureCandidate], list[str]]:
    """Every Match liftable into entity space, plus the ones that are NOT.

    A match whose team or tournament has no verified internal entity mapping
    cannot be compared, so it cannot be matched -- and that absence must be
    visible, not silent: a market for a missing fixture would otherwise
    resolve to a bland "no fixture shares this pairing". The second return
    value names every missing internal key so the report can say exactly
    which ``link-entity`` rows are owed.

    Season is the tournament's starting year as a four-digit token (a 2026-27
    season is "2026", January fixtures included) -- Tournament.year, never
    the display name.
    """
    index = source_entity_index(db)
    candidates = []
    gaps: list[str] = []
    rows = (
        db.query(Match, Tournament)
        .join(Tournament, Tournament.id == Match.tournament_id)
        .filter(Match.team_home_id.isnot(None), Match.team_away_id.isnot(None))
        .order_by(Match.id)
        .all()
    )
    for match, tournament in rows:
        home = index.get((INTERNAL_SOURCE, internal_team_key(match.team_home_id)))
        away = index.get((INTERNAL_SOURCE, internal_team_key(match.team_away_id)))
        competition = index.get(
            (INTERNAL_SOURCE, internal_competition_key(tournament.id)))
        missing = [
            key for key, entity in (
                (internal_team_key(match.team_home_id), home),
                (internal_team_key(match.team_away_id), away),
                (internal_competition_key(tournament.id), competition),
            ) if entity is None
        ]
        if home is None or away is None:
            gaps.append(
                f"match {match.id} is not a candidate: no internal entity for "
                + ", ".join(missing))
            continue
        if competition is None:
            gaps.append(
                f"match {match.id}: no internal entity for {missing[0]} "
                "(candidate kept; competition checks will reject it)")
        candidates.append(FixtureCandidate(
            match_id=match.id,
            home_entity_id=home,
            away_entity_id=away,
            competition_entity_id=competition,
            kickoff_utc=match.kickoff_utc,
            status=match.status or "scheduled",
            season_label=str(tournament.year) if tournament.year else None,
        ))
    return candidates, gaps


@dataclass
class MarketOutcome:
    """What reconciliation decided for one market, dry-run or applied."""

    venue: str
    venue_key: str
    action: str
    status: str
    reason: str
    match_id: int | None = None
    outcome: str | None = None


@dataclass
class ReconcileReport:
    dry_run: bool
    resolver_version: str = RESOLVER_VERSION
    outcomes: list[MarketOutcome] = field(default_factory=list)
    #: Fixtures that could not become candidates, with the missing internal
    #: keys named. Data gaps are report content, not log noise.
    data_gaps: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for outcome in self.outcomes:
            tally[outcome.action] = tally.get(outcome.action, 0) + 1
        return dict(sorted(tally.items()))


def _is_verified(row: VenueMarket) -> bool:
    context = row.resolution_context or {}
    return isinstance(context, dict) and bool(context.get("verified"))


def _resolution_context(
    resolution: Resolution, descriptor_grammar: dict | None, now: datetime,
    verification: dict | None = None,
) -> dict:
    return {
        "resolver_version": RESOLVER_VERSION,
        "decided_at": now.isoformat(),
        "status": resolution.status,
        "reason": resolution.reason,
        "grammar": descriptor_grammar,
        "verification": verification,
        "proposed_match_id": resolution.proposed_match_id,
        "missing": list(resolution.missing),
        "candidates": [
            {
                "match_id": assessment.match_id,
                "accepted": assessment.accepted,
                "checks": [list(check) for check in assessment.checks],
                "rejections": list(assessment.rejections),
            }
            for assessment in resolution.assessments
        ],
    }


def _fingerprint(context: dict) -> dict:
    """The decision minus its timestamp: what idempotency compares."""
    return {key: value for key, value in context.items() if key != "decided_at"}


def _descriptor_for(row: VenueMarket, index, metadata_by_key):
    metadata = (metadata_by_key or {}).get((row.venue, row.venue_key))
    if metadata is not None:
        return descriptor_from_metadata(
            venue=row.venue, venue_key=row.venue_key,
            market_type=row.market_type, metadata=metadata)
    if row.venue == "kalshi":
        verified = frozenset(
            key for (source, key) in index if source == "kalshi")
        return kalshi_descriptor(
            venue_key=row.venue_key, market_type=row.market_type,
            verified_team_keys=verified)
    return ExtractionFailure(
        reason=(
            f"no deterministic descriptor for venue {row.venue!r}: the stored "
            "row carries no structured participants; supply operator metadata"
        )
    )


def reconcile_markets(
    db: Session,
    *,
    apply: bool = False,
    now: datetime | None = None,
    metadata_by_key: dict[tuple[str, str], dict] | None = None,
) -> ReconcileReport:
    """Resolve every venue market. Writes nothing unless ``apply=True``.

    A dry run must not alter the caller's transaction state: no commit, no
    rollback, and reads run under ``no_autoflush`` so the caller's unrelated
    pending work is neither flushed early nor discarded. Rolling back here --
    the old behavior -- silently destroyed whatever the caller had pending.
    """
    now = now or datetime.now(timezone.utc)
    with db.no_autoflush:
        index = source_entity_index(db)
        kinds = entity_kind_index(db)
        fixtures, gaps = fixture_candidates(db)
        report = ReconcileReport(dry_run=not apply, data_gaps=gaps)

        rows = (
            db.query(VenueMarket)
            .order_by(VenueMarket.venue, VenueMarket.venue_key)
            .all()
        )
        for row in rows:
            if _is_verified(row):
                report.outcomes.append(MarketOutcome(
                    venue=row.venue, venue_key=row.venue_key, action="locked",
                    status=row.mapping_status,
                    reason="operator-verified mapping; replay never touches it",
                    match_id=row.canonical_event_id, outcome=row.canonical_outcome))
                continue

            descriptor = _descriptor_for(row, index, metadata_by_key)
            if isinstance(descriptor, ExtractionFailure):
                resolution = Resolution(
                    status=AMBIGUOUS if descriptor.ambiguous else UNMAPPED,
                    reason=descriptor.reason)
                grammar = None
                verification = None
            else:
                resolution = resolve_market(
                    descriptor, source_entities=index, entity_kinds=kinds,
                    fixtures=fixtures)
                grammar = dict(descriptor.grammar)
                verification = (dict(descriptor.verification)
                                if descriptor.verification else None)

            context = _resolution_context(resolution, grammar, now, verification)

            if row.mapping_status == MAPPED and row.canonical_event_id is not None:
                same = (
                    resolution.status == MAPPED
                    and resolution.match_id == row.canonical_event_id
                    and resolution.canonical_outcome == row.canonical_outcome
                )
                if same:
                    report.outcomes.append(MarketOutcome(
                        venue=row.venue, venue_key=row.venue_key,
                        action="unchanged", status=MAPPED,
                        reason="replay agrees with the stored mapping",
                        match_id=row.canonical_event_id,
                        outcome=row.canonical_outcome))
                    continue
                # No silent remap: the stored mapping stands, the disagreement is
                # recorded once, and a human resolves it via apply_correction.
                conflict = {
                    "resolver_version": RESOLVER_VERSION,
                    "stored": {"match_id": row.canonical_event_id,
                               "outcome": row.canonical_outcome},
                    "replay": {"status": resolution.status,
                               "match_id": resolution.match_id,
                               "outcome": resolution.canonical_outcome,
                               "reason": resolution.reason},
                }
                existing = (row.resolution_context or {}).get("conflict")
                if apply and existing != conflict:
                    history = list(row.mapping_history or [])
                    history.append({
                        "kind": "conflict_detected", "at": now.isoformat(),
                        **conflict,
                    })
                    row.mapping_history = history
                    row.resolution_context = {
                        **(row.resolution_context or {}), "conflict": conflict}
                report.outcomes.append(MarketOutcome(
                    venue=row.venue, venue_key=row.venue_key, action="conflict",
                    status=MAPPED,
                    reason="replay disagrees with the stored mapping; kept stored, "
                           "flagged for correction",
                    match_id=row.canonical_event_id, outcome=row.canonical_outcome))
                continue

            previous_context = row.resolution_context or {}
            unchanged = (
                row.mapping_status == resolution.status
                and _fingerprint(previous_context) == _fingerprint(context)
            )
            if unchanged:
                report.outcomes.append(MarketOutcome(
                    venue=row.venue, venue_key=row.venue_key, action="unchanged",
                    status=resolution.status, reason=resolution.reason,
                    match_id=resolution.match_id,
                    outcome=resolution.canonical_outcome))
                continue

            action = "map" if resolution.status == MAPPED else resolution.status
            if apply:
                history = list(row.mapping_history or [])
                history.append({
                    "kind": "resolution", "at": now.isoformat(),
                    "resolver_version": RESOLVER_VERSION,
                    "from": {"status": row.mapping_status,
                             "match_id": row.canonical_event_id,
                             "outcome": row.canonical_outcome},
                    "to": {"status": resolution.status,
                           "match_id": resolution.match_id,
                           "outcome": resolution.canonical_outcome},
                    "reason": resolution.reason,
                })
                row.mapping_history = history
                row.mapping_status = resolution.status
                row.resolution_context = context
                if resolution.status == MAPPED:
                    row.canonical_event_id = resolution.match_id
                    row.canonical_outcome = resolution.canonical_outcome
                else:
                    row.canonical_event_id = None
                    row.canonical_outcome = None
            report.outcomes.append(MarketOutcome(
                venue=row.venue, venue_key=row.venue_key, action=action,
                status=resolution.status, reason=resolution.reason,
                match_id=resolution.match_id, outcome=resolution.canonical_outcome))

    if apply:
        db.commit()
    return report


def apply_correction(
    db: Session,
    *,
    venue: str,
    venue_key: str,
    verified_by: str,
    note: str,
    match_id: int | None = None,
    outcome: str | None = None,
    clear: bool = False,
    apply: bool = False,
    now: datetime | None = None,
) -> MarketOutcome:
    """Operator correction: the only path that may override a mapping.

    Verification is a claim by a named person, recorded append-only. ``clear``
    removes a mapping (back to unmapped, history kept); otherwise both
    ``match_id`` and ``outcome`` are required and the target match must exist.
    """
    now = now or datetime.now(timezone.utc)
    if not verified_by.strip():
        raise ValueError("verified_by must name a person")
    if not note.strip():
        raise ValueError("a correction requires a note explaining the evidence")
    with db.no_autoflush:
        row = (
            db.query(VenueMarket)
            .filter_by(venue=venue, venue_key=venue_key)
            .one_or_none()
        )
        if row is None:
            raise ValueError(f"no venue market ({venue!r}, {venue_key!r})")
        if not clear:
            if match_id is None or not (outcome or "").strip():
                raise ValueError("a correction requires --match-id and "
                                 "--outcome, or --clear")
            if outcome not in {"home", "draw", "away"}:
                raise ValueError(
                    f"outcome must be home/draw/away, got {outcome!r}")
            if db.get(Match, match_id) is None:
                raise ValueError(f"match {match_id} does not exist")

    entry = {
        "kind": "manual_correction", "at": now.isoformat(),
        "verified_by": verified_by, "note": note,
        "from": {"status": row.mapping_status,
                 "match_id": row.canonical_event_id,
                 "outcome": row.canonical_outcome},
        "to": ({"status": UNMAPPED, "match_id": None, "outcome": None}
               if clear else
               {"status": MAPPED, "match_id": match_id, "outcome": outcome}),
    }
    result = MarketOutcome(
        venue=venue, venue_key=venue_key,
        action="clear" if clear else "correct",
        status=UNMAPPED if clear else MAPPED,
        reason=f"manual correction by {verified_by}: {note}",
        match_id=None if clear else match_id,
        outcome=None if clear else outcome)
    if not apply:
        # Dry run: the caller's transaction state is untouched -- no commit,
        # no rollback, nothing flushed.
        return result

    history = list(row.mapping_history or [])
    history.append(entry)
    row.mapping_history = history
    if clear:
        row.mapping_status = UNMAPPED
        row.canonical_event_id = None
        row.canonical_outcome = None
        row.resolution_context = {
            "verified": None,
            "cleared_by": verified_by, "cleared_at": now.isoformat(),
            "note": note,
        }
    else:
        row.mapping_status = MAPPED
        row.canonical_event_id = match_id
        row.canonical_outcome = outcome
        row.resolution_context = {
            "verified": {"by": verified_by, "at": now.isoformat(), "note": note},
            "resolver_version": RESOLVER_VERSION,
        }
    db.commit()
    return result


def link_entity(
    db: Session,
    *,
    kind: str,
    canonical_name: str,
    source: str,
    source_key: str,
    verified_by: str,
    sport: str = "football",
    apply: bool = False,
    now: datetime | None = None,
) -> str:
    """Create/verify one exact (source, source_key) -> entity mapping.

    This is where verification enters the system: every key the resolver
    trusts was written here by a named person. A source key already mapped to
    a DIFFERENT entity is refused -- remapping identity is a correction with
    its own audit trail, not an upsert.
    """
    now = now or datetime.now(timezone.utc)
    if kind not in {"team", "competition"}:
        raise ValueError("kind must be team or competition")
    if not verified_by.strip():
        raise ValueError("verified_by must name a person")
    with db.no_autoflush:
        entity = (
            db.query(CanonicalEntity)
            .filter_by(sport=sport, kind=kind, canonical_name=canonical_name)
            .one_or_none()
        )
        existing = (
            db.query(EntitySourceMap)
            .filter_by(source=source, source_key=source_key)
            .one_or_none()
        )
    if existing is not None:
        if entity is not None and existing.entity_id == entity.id:
            return f"already linked: ({source}, {source_key}) -> entity {entity.id}"
        raise ValueError(
            f"({source!r}, {source_key!r}) is already linked to entity "
            f"{existing.entity_id}; refusing to remap identity implicitly"
        )
    message = (
        f"link ({source}, {source_key}) -> {kind} {canonical_name!r}"
        + ("" if entity is not None else " (new entity)")
    )
    if not apply:
        return f"DRY RUN: {message}"
    if entity is None:
        entity = CanonicalEntity(
            sport=sport, kind=kind, canonical_name=canonical_name)
        db.add(entity)
        db.flush()
    db.add(EntitySourceMap(
        entity_id=entity.id, source=source, source_key=source_key,
        confidence=1.0, verified_at=now, verified_by=verified_by))
    db.commit()
    return message
