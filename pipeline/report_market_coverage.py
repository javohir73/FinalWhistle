"""Coverage and unresolved-market reporting for the shadow registry."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CaptureHeartbeat, Match, Tournament, VenueMarket, VenuePriceTick


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def build_coverage_report(
    db: Session,
    *,
    venue: str | None = None,
    competition: str | None = None,
    market_type: str | None = None,
    status: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    unresolved_limit: int = 100,
) -> dict:
    query = db.query(VenueMarket)
    if venue:
        query = query.filter(VenueMarket.venue == venue)
    if market_type:
        query = query.filter(VenueMarket.market_type == market_type)
    if status:
        query = query.filter(VenueMarket.mapping_status == status)
    if start:
        query = query.filter(VenueMarket.last_seen >= start)
    if end:
        query = query.filter(VenueMarket.first_seen < end)
    markets = query.order_by(VenueMarket.venue, VenueMarket.venue_key).all()

    event_ids = {row.canonical_event_id for row in markets if row.canonical_event_id is not None}
    competition_by_event = {}
    if event_ids:
        for match_id, name in (
            db.query(Match.id, Tournament.name)
            .join(Tournament, Tournament.id == Match.tournament_id)
            .filter(Match.id.in_(event_ids))
            .all()
        ):
            competition_by_event[match_id] = name
    if competition:
        markets = [row for row in markets if competition_by_event.get(row.canonical_event_id) == competition]

    ids = [row.id for row in markets]
    tick_query = db.query(VenuePriceTick)
    heartbeat_query = db.query(CaptureHeartbeat)
    if ids:
        tick_query = tick_query.filter(VenuePriceTick.venue_market_id.in_(ids))
    else:
        tick_query = tick_query.filter(False)
    if venue:
        heartbeat_query = heartbeat_query.filter(CaptureHeartbeat.venue == venue)
    if start:
        tick_query = tick_query.filter(VenuePriceTick.ts >= start)
        heartbeat_query = heartbeat_query.filter(CaptureHeartbeat.scheduled_cycle_at >= start)
    if end:
        tick_query = tick_query.filter(VenuePriceTick.ts < end)
        heartbeat_query = heartbeat_query.filter(CaptureHeartbeat.scheduled_cycle_at < end)
    ticks = tick_query.all()
    heartbeats = heartbeat_query.order_by(CaptureHeartbeat.scheduled_cycle_at).all()

    mapping = Counter(row.mapping_status for row in markets)
    settlement_candidates = [row for row in markets if row.status in {"closed", "settled", "void", "cancelled", "finalized"}]
    settled = [row for row in settlement_candidates if row.settled_at is not None or row.status in {"void", "cancelled"}]
    raw_present = sum(bool(row.raw_payload_ref) for row in ticks)
    observed_cycles = len(heartbeats)
    stale_heartbeats = 0
    for previous, current in zip(heartbeats, heartbeats[1:]):
        gap = (current.scheduled_cycle_at - previous.scheduled_cycle_at).total_seconds()
        if gap > previous.intended_cadence_seconds * 1.5:
            stale_heartbeats += 1

    denominator = len(markets)
    report = {
        "filters": {
            "venue": venue,
            "competition": competition,
            "market_type": market_type,
            "status": status,
            "start": _utc(start),
            "end": _utc(end),
        },
        "registry": {
            "markets": denominator,
            "by_venue": dict(sorted(Counter(row.venue for row in markets).items())),
            "by_market_type": dict(sorted(Counter(row.market_type for row in markets).items())),
            "by_mapping_status": {key: mapping.get(key, 0) for key in ("mapped", "unmapped", "ambiguous")},
            "mapping_coverage": mapping.get("mapped", 0) / denominator if denominator else 0.0,
        },
        "capture": {
            "observed_ticks": len(ticks),
            "heartbeat_cycles": observed_cycles,
            "heartbeat_gap_count": stale_heartbeats,
            "heartbeat_errors": sum(row.error_count for row in heartbeats),
            "heartbeat_rate_limits": sum(row.rate_limit_count for row in heartbeats),
        },
        "raw_payloads": {
            "tick_refs_present": raw_present,
            "tick_refs_missing": len(ticks) - raw_present,
            "reference_coverage": raw_present / len(ticks) if ticks else 0.0,
            "note": "Reference presence only; use the raw-store integrity verifier to validate object hashes.",
        },
        "settlements": {
            "closed_candidates": len(settlement_candidates),
            "complete": len(settled),
            "incomplete": len(settlement_candidates) - len(settled),
            "coverage": len(settled) / len(settlement_candidates) if settlement_candidates else 0.0,
        },
        "unresolved": [
            {
                "venue": row.venue,
                "venue_key": row.venue_key,
                "raw_title": row.raw_title,
                "market_type": row.market_type,
                "mapping_status": row.mapping_status,
                "first_seen": _utc(row.first_seen),
                "last_seen": _utc(row.last_seen),
                "resolution_context": row.resolution_context,
                "review_command": f"python -m pipeline.report_market_coverage --venue {row.venue} --status {row.mapping_status}",
            }
            for row in markets
            if row.mapping_status != "mapped"
        ][:unresolved_limit],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue")
    parser.add_argument("--competition")
    parser.add_argument("--market-type")
    parser.add_argument("--status", choices=("mapped", "unmapped", "ambiguous"))
    parser.add_argument("--start", type=datetime.fromisoformat)
    parser.add_argument("--end", type=datetime.fromisoformat)
    args = parser.parse_args()
    with SessionLocal() as db:
        report = build_coverage_report(
            db, venue=args.venue, competition=args.competition,
            market_type=args.market_type, status=args.status,
            start=args.start, end=args.end,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
