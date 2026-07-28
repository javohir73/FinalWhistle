"""Idempotent canonical seeding and venue-market reconciliation command."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CanonicalEntity, EntitySourceMap, Team, Tournament, VenueMarket
from pipeline.entities.resolver import CanonicalFixture, ExactMarketDescriptor, Resolution, resolve_market


def seed_internal_entities(db: Session, *, verified_by: str = "internal-primary-key") -> dict[str, int]:
    """Seed exact internal identities only; legacy fuzzy aliases are excluded."""
    now = datetime.now(timezone.utc)
    created = mapped = 0
    sources: list[tuple[str, str, str, int]] = []
    for team in db.query(Team).all():
        sources.append(("team", team.name, "internal_team", team.id))
    for competition in db.query(Tournament).all():
        sources.append(("competition", competition.name, "internal_tournament", competition.id))
    for kind, name, source, source_id in sources:
        entity = db.query(CanonicalEntity).filter_by(sport="football", kind=kind, canonical_name=name).one_or_none()
        if entity is None:
            entity = CanonicalEntity(sport="football", kind=kind, canonical_name=name)
            db.add(entity)
            db.flush()
            created += 1
        source_key = str(source_id)
        existing = db.query(EntitySourceMap).filter_by(source=source, source_key=source_key).one_or_none()
        if existing is None:
            db.add(EntitySourceMap(entity_id=entity.id, source=source, source_key=source_key, confidence=1.0, verified_at=now, verified_by=verified_by))
            mapped += 1
    db.commit()
    return {"entities_created": created, "source_maps_created": mapped}


def source_entity_index(db: Session) -> dict[tuple[str, str], int]:
    return {
        (row.source, row.source_key): row.entity_id
        for row in db.query(EntitySourceMap).all()
    }


def reconcile_markets(
    db: Session,
    *,
    descriptor_for: Callable[[VenueMarket], ExactMarketDescriptor | None],
    fixtures: Iterable[CanonicalFixture],
    venue: str | None = None,
    venue_key: str | None = None,
    verified_by: str = "resolver",
) -> dict[str, int]:
    """Re-resolve registry rows without reading or rewriting price ticks."""
    query = db.query(VenueMarket)
    if venue:
        query = query.filter(VenueMarket.venue == venue)
    if venue_key:
        query = query.filter(VenueMarket.venue_key == venue_key)
    index = source_entity_index(db)
    entity_kinds = {row.id: row.kind for row in db.query(CanonicalEntity).all()}
    fixture_list = list(fixtures)
    counts = {"mapped": 0, "unmapped": 0, "ambiguous": 0, "corrected": 0}
    now = datetime.now(timezone.utc).isoformat()
    for row in query.all():
        descriptor = descriptor_for(row)
        result = (
            resolve_market(
                descriptor,
                source_entities=index,
                fixtures=fixture_list,
                entity_kinds=entity_kinds,
            )
            if descriptor is not None
            else Resolution(status="unmapped", reason="no structured venue descriptor")
        )
        previous = (row.mapping_status, row.canonical_event_id, row.canonical_outcome)
        replacement = (result.status, result.canonical_event_id, result.canonical_outcome)
        if previous != replacement:
            history = list(row.mapping_history or [])
            history.append({
                "observed_at": now,
                "verified_by": verified_by,
                "from": {"status": previous[0], "event_id": previous[1], "outcome": previous[2]},
                "to": {"status": replacement[0], "event_id": replacement[1], "outcome": replacement[2]},
            })
            row.mapping_history = history
            counts["corrected"] += 1
        row.mapping_status = result.status
        row.canonical_event_id = result.canonical_event_id
        row.canonical_outcome = result.canonical_outcome
        row.resolution_context = {
            "reason": result.reason,
            "candidate_event_ids": list(result.candidate_event_ids),
            "venue_key": row.venue_key,
        }
        counts[result.status] += 1
    db.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-internal", action="store_true")
    parser.add_argument("--descriptors", type=argparse.FileType("r"))
    parser.add_argument("--fixtures", type=argparse.FileType("r"))
    parser.add_argument("--venue")
    parser.add_argument("--venue-key")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.seed_internal:
            result = seed_internal_entities(db)
        elif args.descriptors and args.fixtures:
            descriptor_rows = [ExactMarketDescriptor(**row) for row in json.load(args.descriptors)]
            descriptors = {(row.venue, row.venue_key): row for row in descriptor_rows}
            fixtures = [CanonicalFixture(**row) for row in json.load(args.fixtures)]
            result = reconcile_markets(
                db,
                descriptor_for=lambda row: descriptors.get((row.venue, row.venue_key)),
                fixtures=fixtures,
                venue=args.venue,
                venue_key=args.venue_key,
            )
        else:
            result = {"error": "provide --seed-internal or both --descriptors and --fixtures"}
    print(json.dumps(result, sort_keys=True))
    return 2 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
