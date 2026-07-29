# Prediction-market intelligence layer

**Status: DEFAULT OFF. Capture code exists and runs nowhere. The worker
refuses to start without an explicit opt-in AND an explicit market list. No
schedule, no credentials, no serving change.**

Capturing prediction-market (Kalshi / Polymarket) order books to benchmark the
engine against a liquid market — pre-match and in-play. This document is the
map. It is written from what has landed, not from what is planned.

## Where the work stands

| Layer | State |
|---|---|
| Tables `canonical_entity`, `entity_source_map`, `venue_market`, `venue_price_tick`, `capture_heartbeat` | landed dormant, migration `e1f2a3b4c5d6` |
| Structured in-play state on `venue_price_tick` | landed dormant, migration `b1c2d3e4f5a6` |
| Adapter contracts `pipeline/ingest/venues` | landed |
| Capture worker, venue adapters, raw store | landed (#208), **default off** |
| Fixture resolution / reconciliation | landed (#209), operator-run, dry-run default |
| Benchmark, gating, reporting, research UI | this PR — shadow, operator-run, artifact-served |

Nothing schedules the worker: no cron, no Render service, no GitHub Action.
It runs only when a person runs it, with `MARKET_CAPTURE_ENABLED=true` and a
non-empty `MARKET_CAPTURE_MARKET_KEYS`. See
[PREDICTION-MARKET-CAPTURE.md](PREDICTION-MARKET-CAPTURE.md).

## Why it is being landed in pieces

The layer first arrived as one 96-file, +13.5k-line branch (#203) spanning
schema, a worker, two venue adapters, an entity resolver, a benchmark, reports,
a research page and generated design artifacts. Reviewing it as a unit is not
realistic, and several defects in it are the kind that only surface under
review — a stream tick keyed on arrival time, a fixture resolver that treats
home/away as an unordered pair, hardcoded confidence intervals reported as if
computed.

So it is being rebuilt from `main` as small dependency-ordered PRs, each
dormant on merge, each carrying its own tests:

1. **Contracts + schema foundation** (this PR) — value objects, identity
   derivation, in-play state, and the tables to hold it.
2. **Capture** — the worker, venue adapters, raw payload store. Default off.
3. **Resolution** — venue market to canonical fixture, and reconciliation.
4. **Benchmark and reporting** — scoring, gating, coverage and health reports.

Phase 2 does not begin until Phase 1 is reviewed.

## What this PR fixes, and why here

Three defects in #203 are properties of the contract, so they are fixed where
they can be made unrepresentable rather than merely absent.

**Stream identity came from arrival time.** #203's stream path wrote
`ts = quote.observed_at` while its polling path wrote `ts = scheduled_cycle_at`
— two implementations of one key, disagreeing. A redelivered event arriving a
minute later got a different primary key, so the uniqueness constraint never
fired and the duplicate was invisible. `tick_identity()` is now the only thing
that derives a tick's key, and it returns `ts` along with the rest of it.
Persistence chooses nothing.

Two consequences fall out. Transport decides the key shape, so a polling cycle
that carries a venue event id still keys on its cycle — otherwise a venue that
mints a fresh id per poll turns one retried cycle into two rows. And a stream
event with no venue event id is rejected, not hashed: #203 hashed the payload,
which gives redelivery a brand-new identity by construction.

**Transport was in the key, so one event could be counted twice.** The
original key was `(venue_market_id, ts, transport, observation_key)`. Gap
recovery re-fetches events the stream may already have delivered; the same
venue event arriving first as `streaming` and later as `recovery` took two
different keys, and no constraint could see it. The `cycle:` / `event:` prefix
on `observation_key` already separates the polling and stream families, so the
key does not need transport at all — it drops to `(venue_market_id, ts,
observation_key)` and transport becomes first-delivery provenance. Rows
reading `recovery` are then exactly the events the stream missed, which is the
signal worth keeping.

**Arrival time had nowhere to live.** `ts` is a logical time; for a stream
tick it *is* `source_ts`, so `ts - source_ts` is identically zero — and that
is precisely how #203's `report_stream_control` computed latency, which would
have reported zero for every stream tick forever. `venue_price_tick` now
carries `observed_at` (NOT NULL). `created_at` is not a substitute: it is
database insert time and separates from arrival under buffering or replay.

**Live match state was a free-text string.** #203 stored `score:1-0;cards:2-0`
in an 80-character column and regex-parsed it back out in the benchmark,
returning `(-1, -1)` when absent. Those sentinels then failed an equality check
against the model's state and were counted as `score_state_mismatch`. A venue
that simply does not publish scores would therefore produce zero benchmark
coverage, reported as disagreement — true about the rows, false about the
cause. `InPlayState` separates *venue does not report* from *reported nothing
here* from *reported and disagrees*, and the columns and check constraints hold
that distinction at the table.

The capability column is `NOT NULL`, and its guard is written positively
(`supported = true OR all detail IS NULL`) rather than as a negation. That is
not style: with a nullable capability, `NOT (supported = false AND …)`
evaluates UNKNOWN, and **a CHECK constraint that evaluates UNKNOWN passes**. A
row could carry a score no venue ever published, purely by declining to say
whether the venue publishes scores.

**Two live safeguards were quietly dropped.** #203 removed the 14-day
retention sweep on `market_odds_snapshots` and the `W_ODDS_CAP = 0.5` ceiling
on blend promotion, the latter opening `w_odds = 1.0` — a market passthrough
carrying the engine's version string. Both still stand on `main`. This PR adds
regression tests that pin them, so the later phases cannot remove them
silently.

The remaining #203 review blockers belong to code that has not been extracted
yet and are listed against their phase in the PR description.

## Boundaries this layer must not cross

| Surface | Rule |
|---|---|
| `odds` (API-Football) | The pre-registered q3 benchmark reads it. Frozen. Never written here |
| `market_odds_snapshots` | Legacy hourly intel product. Replaced hourly, swept at 14 days. Not an evidence store |
| `validation_*` tables | Independent reconciliation sources (#206). Separate concern, separate writer |
| `w_odds` | Capped at 0.5. The market is an input, never the model |

## Reading the contracts

`pipeline/ingest/venues/CONTRACTS.md` is the persistence contract: identity and
idempotency per record type, the in-play state cases, partitioning, correction
semantics and boundary behavior. `types.py` implements it; `types_test.py`
holds it to it. Neither performs I/O, and a test asserts that.
