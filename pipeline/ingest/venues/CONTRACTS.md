# Venue capture contracts

The persistence rules the capture layer must obey. The Python value objects
live in `types.py`; the tables live in `backend/app/models/__init__.py` and are
created by migrations `e1f2a3b4c5d6` and `b1c2d3e4f5a6`.

Nothing in this package performs I/O. It exists so that every adapter and
every transport reaches the same table through the same normalized shape.

## Identity and idempotency

`tick_identity()` derives the **whole** `venue_price_tick` natural key,
including `ts`. Persistence uses what it returns and chooses nothing itself.

| Record | Logical key | Replay behavior |
|---|---|---|
| Venue market | `(venue, venue_key)` | Upsert lifecycle and `last_seen`; never create a second logical market. |
| Polling tick | `(venue_market_id, ts, observation_key)`, where `ts = scheduled_cycle_at` and `observation_key = cycle:<scheduled_cycle_at>` | A retry of the same scheduled cycle is a no-op or updates the incomplete attempt. Completion time is not identity. |
| Stream/recovery tick | `(venue_market_id, ts, observation_key)`, where `ts = source_ts` and `observation_key = event:<source_event_id>` | Duplicate delivery is a no-op **whatever time it arrived and whichever path it arrived by**. |
| Heartbeat | `(worker, venue, scheduled_cycle_at)` | Retrying a worker cycle updates the same heartbeat and preserves attempt/error counters. |
| Entity source map | `(source, source_key)` | Exactly one canonical entity or no mapping; a conflicting entity is an explicit audited correction. |

Four consequences are load-bearing, and each has a test:

- **Transport decides the key shape without being part of the key.** A polling
  quote that happens to carry a venue event id still keys on its cycle —
  keying on the event id would let one retried cycle write two rows whenever
  the venue minted a fresh id. And the `cycle:` / `event:` prefix already
  separates the two families, so the key needs no transport column.
- **`streaming` and `recovery` are the same observation.** A gap-recovery
  fetch of an event the stream already delivered resolves to the identical
  key and is refused by the primary key. With transport *in* the key the two
  deliveries would take two rows and nothing could see it — one venue event
  counted twice, in a table whose whole purpose is counting.
- **`observed_at` is never identity.** It is our arrival time. A stream event
  redelivered a minute later is the same observation; giving it a `ts` from
  arrival would append a duplicate that no uniqueness constraint can catch.
- **A stream event with no venue event id, or no venue timestamp, is
  rejected.** Not hashed, not stamped with arrival time. Inventing identity
  makes redelivery indistinguishable from a new observation, and the damage is
  invisible: the table simply grows a duplicate.

All key timestamps are timezone-aware and normalized to UTC.

### Transport as provenance

`venue_price_tick.transport` records how a tick **first** arrived. First
writer wins, so:

- `recovery` marks exactly the events the stream missed and gap recovery
  backfilled. That is the operational signal worth keeping.
- A recovery redelivery of an already-streamed event is discarded, and nothing
  is lost: the observation is already stored with its own raw payload, and
  what recovery *attempted* belongs to stream-gap accounting (the guard's
  missing-sequence ledger), not to the observation table.

### Arrival time

`ts` is a logical time. For a stream tick it **is** `source_ts`, so
`ts - source_ts` is identically zero and latency computed that way is a
fiction. `venue_price_tick.observed_at` carries the real arrival time and is
`NOT NULL`.

`created_at` is not a substitute: it is database insert time, which separates
from arrival under buffering, batching, retry or replay.

## Live match state

`InPlayState` separates three cases a single nullable column cannot:

| Case | `supported` | Detail fields |
|---|---|---|
| Venue does not publish live state | `False` | all `None` — enforced, not conventional |
| Venue publishes it; none for this observation | `True` | `None` where absent |
| Venue publishes it and reported it | `True` | populated |

There is no fourth case. `venue_price_tick.in_play_state_supported` is
`NOT NULL`, and the guard is written as `supported = true OR (all detail IS
NULL)` rather than `NOT (supported = false AND ...)`. The negated form looks
equivalent but is not: with a nullable capability it evaluates to UNKNOWN, and
a CHECK constraint that evaluates UNKNOWN **passes**. A row could then carry a
score no venue ever published, simply by declining to say whether the venue
publishes scores.

`UNSUPPORTED_IN_PLAY` is the default on `Quote`: an adapter that says nothing
is read as reporting nothing, and its ticks are excluded from state-matched
comparisons with a reason that names the venue rather than the model.

The distinction exists for the in-play benchmark. Comparing a model to a venue
requires both to be describing the same match state, so a tick whose score is
unknown cannot be scored. If "venue never reports score" is stored the same way
as "score disagrees", the benchmark returns zero coverage and attributes it to
mismatch — a true statement about the rows and a false one about the cause.

`InPlayState.as_columns()` returns the tick's in-play columns as one mapping so
capture writes them together; a half-populated state cannot be assembled by
hand at the call site.

## Monthly tick partitions

- PostgreSQL creates `venue_price_tick` as a native `RANGE (ts)` partitioned
  table. The natural primary key includes `ts`, as PostgreSQL requires for a
  unique key on a partitioned table.
- Migration `e1f2a3b4c5d6` creates monthly partitions from July 2026 through
  December 2027 plus a default safety partition. Before each calendar
  extension, create future monthly partitions while the relevant range is still
  empty in the default partition.
- The health report must make rows in the default partition visible. They are
  an operations warning, not a retention mechanism.
- SQLite creates one ordinary `venue_price_tick` table with the same columns and
  constraints. Tests exercise logical keys and queries, not PostgreSQL's
  physical partition implementation.

## Corrections

- Market discovery may update venue lifecycle fields and `last_seen`, but it
  must not replace the original `raw_title` without retaining the newly observed
  raw value in provenance.
- Normalized price ticks are append-only. An exact duplicate is ignored; a later
  correction from a venue is another tick linked to its own source event and raw
  payload.
- Repeating the same settlement is a no-op. A different later settlement is
  stored as an audited correction: retain the previous status/outcome/source/
  time, update the current market state, and make the correction visible to
  downstream scoring.
- Entity mapping corrections change the current mapping and append audit
  metadata. They re-resolve historical markets without rewriting historical
  price ticks.
- Heartbeat retries may update counters for their logical cycle. They must not
  hide an originally failed attempt; attempt and error counts are cumulative.

## Boundary behavior

- Empty and one-sided books are valid observations and have no invented
  midpoint.
- Prices outside `[0, 1]`, non-finite numbers, non-positive sizes, naive
  timestamps, and crossed normalized books are rejected while the untouched raw
  payload is retained by the capture layer for diagnosis.
- Scores and card counts are non-negative integers, stored as home/away pairs
  that are present or absent together.
- `raw_title` may be empty or malformed because discovered-but-unmapped markets
  are first-class data. Venue name, venue key, sport, and market type may not be
  empty.
- A terminal `settled` state requires an outcome. `void` and `cancelled` states
  must not claim an outcome.

## What is not decided here

Fixture resolution, capture scheduling, allowlist policy, and benchmark
admission live in their own layers. This file is the boundary they share.
