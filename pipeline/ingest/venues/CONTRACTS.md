# Venue capture contracts

This file records the P0 persistence rules that must be stable before the new
database migration is written. The Python value objects live in `types.py`.

## Identity and idempotency

| Record | Logical key | Replay behavior |
|---|---|---|
| Venue market | `(venue, venue_key)` | Upsert lifecycle and `last_seen`; never create a second logical market. |
| Polling tick | `(venue_market_id, ts, transport, observation_key)`, where `ts = scheduled_cycle_at` and `observation_key = cycle:<scheduled_cycle_at>` | A retry of the same scheduled cycle is a no-op or updates the incomplete attempt; completion time is not part of identity. |
| Stream/recovery tick | `(venue_market_id, ts, transport, observation_key)`, where `ts = source_ts` and `observation_key = event:<source_event_id>` | Duplicate delivery is a no-op. A stream event without a stable venue event/sequence ID is rejected rather than given a random identity. |
| Heartbeat | `(worker, venue, scheduled_cycle_at)` | Retrying a worker cycle updates the same heartbeat and preserves attempt/error counters. |
| Entity source map | `(source, source_key)` | Exactly one canonical entity or no mapping; a conflicting entity is an explicit audited correction. |

All key timestamps are timezone-aware and normalized to UTC.

## Monthly tick partitions

- PostgreSQL creates `venue_price_tick` as a native `RANGE (ts)` partitioned
  table. The natural primary key includes `ts`, as PostgreSQL requires for a
  unique key on a partitioned table.
- The initial migration creates monthly partitions from July 2026 through
  December 2027 plus a default safety partition. Before each calendar extension,
  create future monthly partitions while the relevant range is still empty in the
  default partition.
- The health report must make rows in the default partition visible. They are an
  operations warning, not a retention mechanism.
- SQLite creates one ordinary `venue_price_tick` table with the same columns and
  constraints. Tests exercise logical keys and queries, not PostgreSQL's physical
  partition implementation.

## Corrections

- Market discovery may update venue lifecycle fields and `last_seen`, but it must
  not replace the original `raw_title` without retaining the newly observed raw
  value in provenance.
- Normalized price ticks are append-only. An exact duplicate is ignored; a later
  correction from a venue is another tick linked to its own source event and raw
  payload.
- Repeating the same settlement is a no-op. A different later settlement is stored
  as an audited correction: retain the previous status/outcome/source/time, update
  the current market state, and make the correction visible to downstream scoring.
- Entity mapping corrections change the current mapping and append audit metadata.
  They re-resolve historical markets without rewriting historical price ticks.
- Heartbeat retries may update counters for their logical cycle. They must not hide
  an originally failed attempt; attempt and error counts are cumulative.

## Boundary behavior

- Empty and one-sided books are valid observations and have no invented midpoint.
- Prices outside `[0, 1]`, non-positive sizes, naive timestamps, and crossed
  normalized books are rejected while the untouched raw payload is retained by the
  capture layer for diagnosis.
- `raw_title` may be empty or malformed because discovered-but-unmapped markets are
  first-class data. Venue name, venue key, sport, and market type may not be empty.
- A terminal `settled` state requires an outcome. `void` and `cancelled` states must
  not claim an outcome.
