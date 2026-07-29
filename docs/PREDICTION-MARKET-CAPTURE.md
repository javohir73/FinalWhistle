# Prediction-market capture worker

**Status: DEFAULT OFF. Not scheduled anywhere. No credentials committed.**

Polls public Kalshi and Polymarket endpoints for a bounded, explicitly listed
set of markets, and writes normalized ticks plus the untouched raw payload.
It does nothing else: no entity resolution, no pricing, no benchmark, no
serving surface.

## It will not start by accident

Two independent gates, both fail-closed:

| Gate | Default | Effect |
|---|---|---|
| `MARKET_CAPTURE_ENABLED` | `false` | process exits 2 with the reason |
| `MARKET_CAPTURE_MARKET_KEYS` | empty | process exits 2 with the reason |

An empty allowlist means **capture nothing**. It is never read as "capture
every market the venue lists" — that reading turns a missing decision into a
worker quietly polling a whole catalogue against a public rate limit.

`CaptureWorker.run_all` re-checks both before touching an adapter, and
`_capture_keys` returns an empty set for an empty allowlist, so a direct
programmatic call cannot bypass the gates either. Importing any module in the
layer opens no connection; a test enforces that with `socket.connect` made
fatal.

## Running it locally

```bash
MARKET_CAPTURE_ENABLED=true \
MARKET_CAPTURE_MARKET_KEYS=kalshi:KXEPLGAME-26AUG01ARSCHE-ARS \
PYTHONPATH=backend:. .venv/bin/python -m worker.main
```

Discovery runs six-hourly, quotes at 300s pre-match and 30s in-play, bounded
by `MARKET_CAPTURE_MAX_MARKETS_PER_VENUE`. Selection is sorted, so the cap
truncates identically every cycle rather than rotating which markets get
covered.

## What a tick is allowed to claim

Identity comes from `tick_identity()` — the same function the stream path
uses. Polling keys on its scheduled cycle, streams key on the venue event id,
transport is provenance and not part of the key, and `observed_at` is our real
arrival time.

Polling cadence queries **polling ticks only**. Stream traffic arrives on its
own schedule and says nothing about when we last polled; counting it would let
a busy stream silence the fallback exactly when the primary was noisiest.

### Neither venue publishes match state

Both adapters declare `in_play_state_fields = frozenset()`, so every tick is
written with `in_play_state_supported = False`.

- **Kalshi** returns no clock, score or cards anywhere capture reads.
- **Polymarket** Gamma *events* do carry `live`, `elapsed` and `period` — but
  they arrive on the six-hourly discovery response, not on the CLOB book a
  quote is built from. Attaching a clock that may be hours old to a
  thirty-second tick would be a fabricated observation, and fabricated state
  is worse than absent state because it looks like evidence.

`live` is still read, for **cadence only**: a stale hint that makes us poll
faster is harmless.

**Consequence for the benchmark phase:** there is no venue-side score to match
a model state against. A score-matched in-play comparison cannot be built from
these two venues as they stand. Match state has to come from our own live
ledger, or from a venue that publishes it.

## Raw payloads

Byte-exact JSON with a sha256, written once, never rewritten, never parsed on
the way in. Objects are `0600` inside `0700` directories; S3/R2 writes are
server-side encrypted.

Bounded on two axes:

- a payload over `MARKET_CAPTURE_MAX_RAW_PAYLOAD_BYTES` is **refused**, not
  truncated, and the refusal is not retried — it would fail identically every
  time;
- rejected payloads are retained for diagnosis up to
  `MARKET_CAPTURE_MAX_REJECTED_PER_CYCLE` per venue cycle. A venue that starts
  returning garbage returns it every poll, so the overflow is counted rather
  than written.

Paths never carry a venue string verbatim unless it is already plain
(alphanumerics, dot, dash, underscore, no leading dot, ≤64 chars). Anything
else is filed under its digest alone — sanitizing is a guess about which
fragments are harmless, and `Bearer xyz` survives a character-class filter
intact. Error messages are scrubbed by `worker.redaction.redact` before they
reach a log line or the heartbeat row.

## Failure behaviour

| Situation | Behaviour |
|---|---|
| 429 | retried with capped exponential backoff and jitter; counted separately on the heartbeat |
| 5xx / timeout / connection | retried to `MARKET_CAPTURE_RETRY_LIMIT`, then recorded |
| 4xx (not 429) | not retried |
| malformed venue payload | that market fails, siblings continue, raw payload kept (bounded) |
| raw store outage | retried; the tick is not written without a raw reference |
| one venue down | the other still runs |

Every cycle writes a `capture_heartbeat` row keyed `(worker, venue,
scheduled_cycle_at)`, so gaps are queryable rather than inferred from missing
ticks. Retrying a cycle updates that row and keeps counters cumulative.

## Concurrency

There is none, deliberately. One SQLAlchemy `Session` is not thread-safe,
venue rate limits are per-account rather than per-connection, and the eligible
set is a handful of markets. The dead `MARKET_CAPTURE_CONCURRENCY` setting was
removed rather than left as a knob that does nothing.

## Dependencies

`boto3` lives in `worker/requirements.txt`, which includes
`backend/requirements.txt`. The API image never installs an S3 client it does
not use.
