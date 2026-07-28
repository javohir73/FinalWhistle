"""Report prediction-market capture coverage, gaps, and exceptions."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CaptureHeartbeat, VenueMarket, VenuePriceTick


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_capture_health(
    db: Session,
    *,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
    unsettled_warning_seconds: int = 86_400,
) -> dict[str, object]:
    start, end = _utc(start), _utc(end)
    now = _utc(now or datetime.now(timezone.utc))
    if end <= start:
        raise ValueError("end must be later than start")
    if unsettled_warning_seconds <= 0:
        raise ValueError("unsettled_warning_seconds must be greater than 0")

    market_rows = db.query(VenueMarket).all()
    heartbeat_rows = (
        db.query(CaptureHeartbeat)
        .filter(
            CaptureHeartbeat.scheduled_cycle_at >= start,
            CaptureHeartbeat.scheduled_cycle_at < end,
        )
        .order_by(CaptureHeartbeat.venue, CaptureHeartbeat.scheduled_cycle_at)
        .all()
    )
    tick_rows = (
        db.query(VenuePriceTick)
        .filter(VenuePriceTick.ts >= start, VenuePriceTick.ts < end)
        .all()
    )
    market_by_id = {row.id: row for row in market_rows}
    venues = sorted(
        {row.venue for row in market_rows} | {row.venue for row in heartbeat_rows}
    )
    reports: dict[str, dict[str, object]] = {}
    warning_before = now - timedelta(seconds=unsettled_warning_seconds)

    for venue in venues:
        markets = [row for row in market_rows if row.venue == venue]
        heartbeats = [row for row in heartbeat_rows if row.venue == venue]
        ticks = [
            row
            for row in tick_rows
            if market_by_id.get(row.venue_market_id) is not None
            and market_by_id[row.venue_market_id].venue == venue
        ]
        categories: Counter[str] = Counter()
        for heartbeat in heartbeats:
            for error in heartbeat.errors or []:
                if isinstance(error, dict):
                    categories[str(error.get("category") or "unknown")] += 1

        gap_count = missed_cycles = 0
        by_worker: dict[str, list[CaptureHeartbeat]] = {}
        for heartbeat in heartbeats:
            by_worker.setdefault(heartbeat.worker, []).append(heartbeat)
        for rows in by_worker.values():
            for previous, current in zip(rows, rows[1:]):
                cadence = previous.intended_cadence_seconds
                delta = (
                    _utc(current.scheduled_cycle_at) - _utc(previous.scheduled_cycle_at)
                ).total_seconds()
                if delta > cadence * 1.5:
                    gap_count += 1
                    missed_cycles += max(1, int(delta // cadence) - 1)

        stale_ticks = sum(
            "stale_source_timestamp" in (tick.validation_flags or []) for tick in ticks
        )
        unsettled = [
            row
            for row in markets
            if row.settled_at is None
            and row.status
            in {"closed", "determined", "disputed", "amended", "finalized"}
            and row.closed_at is not None
            and _utc(row.closed_at) < warning_before
        ]
        reports[venue] = {
            "markets_discovered": len(markets),
            "mapped": sum(row.mapping_status == "mapped" for row in markets),
            "unmapped": sum(row.mapping_status == "unmapped" for row in markets),
            "ambiguous": sum(row.mapping_status == "ambiguous" for row in markets),
            "heartbeats": len(heartbeats),
            "intended_ticks": sum(
                row.success_count + row.error_count for row in heartbeats
            ),
            "observed_ticks": len(ticks),
            "heartbeat_gaps": gap_count,
            "estimated_missed_cycles": missed_cycles,
            "adapter_errors": sum(row.error_count for row in heartbeats),
            "retries": sum(row.retry_count for row in heartbeats),
            "rate_limits": sum(row.rate_limit_count for row in heartbeats),
            "raw_payload_failures": categories["raw_store"],
            "error_categories": dict(sorted(categories.items())),
            "stale_ticks": stale_ticks,
            "unsettled_exceptions": [
                {
                    "venue_key": row.venue_key,
                    "status": row.status,
                    "closed_at": _utc(row.closed_at).isoformat(),
                }
                for row in unsettled
            ],
        }
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": now.isoformat(),
        "venues": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="inclusive ISO-8601 UTC time")
    parser.add_argument("--end", required=True, help="exclusive ISO-8601 UTC time")
    parser.add_argument("--output", help="optional JSON output path")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
    with SessionLocal() as db:
        report = build_capture_health(db, start=start, end=end)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(rendered + "\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
