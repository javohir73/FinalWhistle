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

The gate lives at the top of `run_venue_cycle`, before any adapter, network or
database call — not in `run_all`, which only ever iterates venues that already
passed. Four conditions refuse, each tested for zero discovery, zero quote,
zero raw write, zero DB row and zero heartbeat:

- capture disabled;
- the global allowlist is empty;
- **the venue is not in `MARKET_CAPTURE_VENUES`.** Being reachable through the
  adapter map is not being enabled;
- **the venue has no allowlisted key of its own.** Eligibility is computed from
  settings alone; deriving it from the catalogue meant fetching the catalogue
  first, so an allowlist naming only `kalshi:…` still sent Polymarket's
  discovery request;
- retention could not be enforced (below).

Importing any module in the layer opens no connection; a test enforces that
with `socket.connect` made fatal.

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

The venue's **original response bytes**, written once with a sha256 and never
parsed on the way in. Not a re-serialization of the parse: `json.loads` then
`json.dumps(sort_keys=True)` discards whitespace, key order, duplicate keys and
every number's lexical form — `"0.4300"` becomes `0.43` — and those bytes are
what a venue would be held to if it ever disputed a price.

A quote assembled from several responses (Kalshi reads an orderbook and a
market; Polymarket a CLOB market and a book) stores every response verbatim
plus a manifest of their digests, so the tick's single `raw_payload_ref` still
resolves to the complete record. Discovery works the same way, but its pages
are stored **once per cycle** rather than once per market — the same two
responses back every market on them — and every market row points at that one
shared manifest.

A response that fails to decode or fails ANY later validation carries its
bytes out on the exception (`VenuePayloadError.raw_documents` — a tuple), and
is stored under the bounded reject policy. An error raised after the second
response of a pair keeps both: the good orderbook is part of the evidence for
why the malformed market response could not be normalized. Settlement failures
keep their bytes the same way. One failure counts once against the per-cycle
bound however many documents it carried.

Discovery pages are stored eagerly, the moment discovery ran — not lazily when
the first good market needs a reference. An all-invalid catalogue is the one
most worth keeping, and with zero good markets there is no market row to carry
the reference, so the heartbeat carries it instead
(`category: discovery_provenance`, with the reference and per-page digests).

Each document records the **finalized** request URL — query string included,
passed through the shared credential redaction — because the pre-params URL
loses the cursor, tag_id, limit and token_id that make a response auditable.

`put()` — which re-serializes — is used only for payloads we authored
ourselves: rejected-item diagnostics with no original response, the manifest,
and the registry-recovery stub.

Objects are `0600` inside `0700` directories; S3/R2 writes are server-side
encrypted.

Bounded on **three** axes, because a byte ceiling caps each object and nothing
else caps the total:

- a payload over `MARKET_CAPTURE_MAX_RAW_PAYLOAD_BYTES` is **refused**, not
  truncated, and the refusal is not retried — it would fail identically every
  time;
- rejected payloads are retained for diagnosis up to
  `MARKET_CAPTURE_MAX_REJECTED_PER_CYCLE` per venue cycle. Both the stored and
  the **dropped** counts reach the cycle result and the heartbeat, so overflow
  is a number rather than an absence;
- everything is deleted past `MARKET_CAPTURE_RAW_RETENTION_DAYS`. Locally the
  worker prunes **before** each cycle's capture work, and a prune failure
  refuses the cycle: pruning afterwards and logging the failure is not
  enforcement, because the next cycle writes regardless. Only a genuine
  disappearance race (`FileNotFoundError`) is suppressed — a permission error
  or an unreadable tree means retention did not happen and is raised. For
  object storage the worker cannot delete anything, so the bucket lifecycle
  rule is the only enforcement: it is **read and verified at construction**,
  and a missing, disabled, non-covering or longer-than-configured rule is a
  refusal to write. `Filter.And.Prefix` is parsed as the string AWS sends,
  not iterated character by character — and a rule conditioned on tags or
  object size does not count at all: `And` means **all** of its conditions,
  the worker writes objects with no Tagging, so a Prefix+Tag rule expires
  none of them, ever.

Malformed discovery items are evidence too. Adapters return them alongside the
good markets rather than logging and dropping them, so the payload is retained
under the same bounded policy and counted — a venue quietly breaking half its
catalogue must not look like a venue with a smaller catalogue. A malformed
top-level catalogue response still records a heartbeat; without one, a venue
serving garbage is indistinguishable from a worker that never ran.

Paths never carry a venue string verbatim unless it is plain in shape
(alphanumerics, dot, dash, underscore, no leading dot, ≤64 chars) **and** clean
by the shared credential detector. Shape alone is not enough:
`api_key_live_sk_1234` and `Bearer_xyz` are perfectly plain and contain no
separator for a scrubber to find. Anything that trips either check is filed
under its digest alone.

`pipeline.ingest.venues.redaction` is the single detector, used by the raw
store, the worker and both adapters — including adapter warnings that
interpolate venue-controlled identifiers and exception text. It matches
structured bodies (`{"apiKey":"secret"}`, `{'api_key':'secret'}`) as well as
`key: value`, because a venue error usually arrives serialized.

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
