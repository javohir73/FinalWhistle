# Prediction-market intelligence runbook

Last updated: 2026-07-27 AEST. Implementation branch:
`codex/prediction-market-intelligence-layer`. Requirements are traced to
`tasks/prd-prediction-market-intelligence-layer.md` and design commit `a94bdf0`
(`docs/superpowers/specs/2026-07-25-prediction-market-intelligence-layer-design.md`).

## Phase checklist and stop gates

| Phase | Entry | Exit evidence | Stop gate |
|---|---|---|---|
| P0 capture | Adapter contracts and additive migration pass locally | Full listed-soccer weekend, health report, settlement exception report, measured cost | Before paid PostgreSQL, object bucket, worker provisioning, migration merge/application, or deploy |
| P1 audit | Frozen WC26 inputs and source-design values reconcile | Reproducible artifact, tested public page, evidence card | Before public merge/deploy or distribution |
| P2 resolver | P0 registry exists | Every market is mapped, unmapped, or ambiguous; parity and retroactive reconciliation pass | Before retiring a legacy mapping consumer |
| P2b streams | Polling is healthy and venue stream semantics are documented | Full matchday control, forced reconnect, gap/latency report | Before enabling a production stream or credentials |
| P3/P4 benchmark | Held-out capture and resolver coverage meet the precommitted checks | Immutable evidence card and CI-based `beating`, `beaten`, or `inconclusive` verdict | Before blend shipping or selecting P5 |
| P5 | A dated P4 record selects exactly one branch | Selected product tests, security/privacy review, manual QA | Before schema merge, public launch, alerts, or deployment |

Never provision, merge to `main`, apply a production migration, dispatch
`refresh.yml`, deploy, or send an external announcement without explicit owner
approval after showing the actual diff, cost, evidence, and rollback.

## P0 measured evidence

### Disposable PostgreSQL validation — 2026-07-27

PostgreSQL 16 migration, rollback, partition routing, recorded-fixture worker,
raw-object, settlement, and heartbeat validation passed. The dated evidence card
is `docs/experiments/2026-07-27-p0-postgres-validation/EVIDENCE-CARD.md`.
The isolated additive schema was merged through PR
https://github.com/javohir73/FinalWhistle/pull/197 at commit `797af23` after
explicit owner approval. GitHub Python, frontend, Vercel, and preview-comment
checks passed before merge. Production migration remains unapplied: this
repository applies it only through an explicit `refresh.yml` dispatch, which is
a separate stop gate. Post-merge `main` CI run 30230396239 passed both jobs,
including the single-Alembic-head check, and the production `/api/health`
endpoint remained `status: ok` with zero missing prediction rows.

### Read-only live venue smoke — 2026-07-27

Both public adapters completed paginated discovery, full-book capture, and
terminal settlement normalization without credentials. Exact counts, payload
volume, samples, and the still-unresolved in-play clock question are recorded in
`docs/experiments/2026-07-27-p0-live-smoke/EVIDENCE-CARD.md`.

### Operational review and capture bound — 2026-07-27

The smoke exposed unsafe catalogue-driven volume in the former defaults. Exact
market allowlisting, a hard five-market-per-venue ceiling, a six-hour catalogue
refresh, unchanged-discovery raw deduplication, and eligible-only registry/raw
persistence were added and verified. Full-catalogue registry persistence now
requires an explicit `MARKET_CAPTURE_REGISTRY_SCOPE=all` override. The
measurements and projections are in
`docs/experiments/2026-07-27-p0-operational-review/EVIDENCE-CARD.md`.

Read-only probes were run 2026-07-27 against the public venue APIs.

| Measurement | Kalshi | Polymarket |
|---|---:|---:|
| Catalogue coordinate | Exact `Soccer` series tag | Dynamically resolved `soccer` tag ID 100350 |
| Catalogue pages | 35 event pages, limit 200 | 40 keyset pages, limit 100 |
| Catalogue objects | 1,074 soccer series; 2,089 open soccer markets | 3,971 active events; 47,748 nested markets, 45,451 marked active |
| Catalogue response bytes | 1.69 MB series + 138.47 MB events | 212.68 MB events |
| Wall time from this machine | 13.28 seconds | 23.55 seconds |
| Sample complete book | 494 bytes | 7,215 bytes plus 460-byte condition lookup |
| Observed throttling | None during the bounded probe | None during the bounded probe |

The polling implementations use two public requests per quote (book plus market
metadata/token resolution): a naive full active sweep is therefore about 4,178
Kalshi calls and 90,902 Polymarket calls per cycle before retries or settlement
lookups. The worker defaults are deliberately conservative, but these counts still
require a bounded eligibility policy and measured control before deployment.

These counts are point-in-time catalogue measurements, not promised capacities.
The unexpectedly large Polymarket catalogue is a deployment blocker until a
weekend control measures the actually eligible pre-match/in-play subset. Naively
polling all 45,451 active nested markets every five minutes would require at least
90,902 public CLOB calls per cycle and is not an approved operating plan.

### OQ-1 — per-match EPL availability

- Kalshi exposed 34 EPL-labelled soccer series. On 2026-07-27, the match series
  (`KXEPLGAME`, spread, total, score, BTTS and related legs) each returned zero
  open markets. Only 20 relegation and 60 season-leader/outcome markets were open.
- Polymarket's Premier League tag returned three active events: Conference League
  qualification, PFA Team of the Year, and a Liverpool ownership proposition.
  None was a per-match EPL market.

Conclusion for the dated probe: **no currently open per-match EPL contracts were
surfaced on either venue**. This must be probed again when the EPL fixture market
window opens; it is evidence about 2026-07-27, not proof the venues never list them.

### OQ-3 — Polymarket in-play continuity

The Gamma catalogue exposes `live`, `elapsed`, `period`, and CLOB book timestamps,
but a post-hoc closed-market response cannot prove liquidity persisted after
kickoff. OQ-3 remains explicitly unresolved until the P0 weekend worker records
book depth/spread before and after kickoff for the same condition IDs. Do not infer
continuous in-play liquidity from current or closing prices alone.

## Configuration

All settings are environment variables documented in `.env.example` and validated
by `worker.config.CaptureSettings`.

| Setting | Safe local default | Meaning |
|---|---:|---|
| discovery | 21,600 s | Full catalogue refresh; live smoke showed ~349 MB/cycle |
| pre-match polling | 300 s | Quote cadence outside a trusted live state |
| in-play polling | 30 s | Quote cadence when fixture or venue state says live |
| market keys | empty | Exact `venue:venue_key` allowlist; configure before a live run |
| market ceiling | 5/venue | Hard limit even if the allowlist contains more keys |
| registry scope | eligible | Persist discovery rows/raw only for the bounded capture set; `all` is explicit opt-in |
| concurrency | 1 | Conservative request concurrency until the control run |
| request timeout | 15 s | Independent venue HTTP timeout |
| retries | 3 | Transient retry count |
| backoff | 0.5–8 s | Bounded exponential delay with jitter |
| stored depth | top 10 + full raw | Normalized database depth; raw book remains lossless |
| stale threshold | 300 s | Adds `stale_source_timestamp` validation flag |
| settlement warning | 24 h | Closed unresolved market becomes actionable |

The worker uses the trusted internal fixture-state callback when available. If it
disagrees with a venue `live` flag, the internal value wins and the tick receives
`fixture_venue_state_disagreement`. With neither source, state remains null and the
pre-match cadence is used; no live state is invented.

## Raw-payload storage decision and cost gate

Local/test operation uses private mode-0600 files. Production selection is
Cloudflare R2 Standard through the S3-compatible implementation because it offers
private buckets, S3 API compatibility, encryption metadata, lifecycle controls,
and no egress charge. Normalized ticks have no retention deletion. R2 lifecycle
rules, if later approved, may apply only to raw objects and must be documented.

Alternatives considered:

- AWS S3 Standard: mature durability/IAM/lifecycle, but more account surface and
  egress complexity for this project.
- Render persistent disk: simple, but tied to one service and weaker as a durable,
  independently recoverable object archive.
- Local ephemeral filesystem: suitable only for tests; not durable across deploys.

Pricing checked 2026-07-27: R2 Standard lists 10 GB-month, one million Class A
writes, and ten million Class B reads in its monthly free tier; overage is
$0.015/GB-month, $4.50/million Class A, and $0.36/million Class B. Render's July
2026 small always-on service plus small paid PostgreSQL baseline is approximately
$13/month before storage, bandwidth, and catalogue-driven growth. The full-catalogue
probe shows raw writes could dominate this baseline, so **no monthly total is
approved yet**. A bounded weekend measurement must supply object count, compressed
bytes, database growth, CPU, memory, and API calls before provisioning.

## Local operation

1. Apply the additive migration only to a disposable database.
2. Set `DATABASE_URL` and the `MARKET_CAPTURE_*` variables from `.env.example`.
   Keep `MARKET_CAPTURE_REGISTRY_SCOPE=eligible` for bounded shadow runs. This
   writes discovery payloads and registry rows only for the exact allowlisted,
   capped market set while heartbeats still report the full catalogue count.
   `all` is reserved for an explicitly approved full-catalogue acceptance run.
3. Run `PYTHONPATH=backend:. python -m worker.main`.
4. Stop with SIGTERM or Ctrl-C; the current transaction finishes before exit.
5. Generate health JSON with:

   `PYTHONPATH=backend:. python -m pipeline.report_capture_health --start <UTC> --end <UTC> --output capture-health.json`

The process command is also encoded in `worker/Dockerfile`. `render.yaml` is not
modified with a paid worker until approval.

## P2 resolver and coverage operations

- Seed internal team and competition primary keys only with
  `PYTHONPATH=backend:. python -m pipeline.entities.reconcile --seed-internal`.
  This does not promote fuzzy aliases from the legacy modules to verified venue
  mappings.
- Venue resolvers must provide structured participant and outcome keys. Exact
  `entity_source_map` rows are the only automatic identity authority.
- Similarity results are operator suggestions only. `ambiguous`, `unmapped`,
  unsupported, and outcome-incomplete rows are not serveable.
- Mapping corrections append to `venue_market.mapping_history`; reconciliation
  never modifies `venue_price_tick`. Run an audited batch with
  `python -m pipeline.entities.reconcile --descriptors <exact-markets.json> --fixtures <canonical-fixtures.json>`;
  optional `--venue` and `--venue-key` filters make corrections targeted. The
  descriptor file uses the `ExactMarketDescriptor` fields and the fixture file
  uses the `CanonicalFixture` fields; both are reviewed JSON arrays.
- Coverage is available from `pipeline.report_market_coverage` or the
  token-guarded `/api/internal/market-coverage` endpoint. The operations token
  stays in a server or CLI client and is never compiled into browser JavaScript.
- Triage heartbeat gaps separately from capture gaps, raw-reference presence,
  mapping coverage, and settlement completeness; the report deliberately keeps
  these denominators separate.

## P2b stream support decision (checked 2026-07-27)

- Polymarket documents a public market WebSocket at
  `wss://ws-subscriptions-clob.polymarket.com/ws/market`, subscribed by asset
  ID. It sends full `book` snapshots and `price_change` updates, has no numeric
  sequence field in the documented messages, and requires client `PING` every
  10 seconds. Hash/event identity and source timestamp therefore drive dedupe;
  a disconnect without a venue history endpoint is recorded as a permanent
  gap and polling is the recovery source. Official contract:
  https://docs.polymarket.com/market-data/websocket/overview
- Kalshi documents `orderbook_snapshot` followed by sequenced
  `orderbook_delta` messages. The WebSocket handshake requires API-key signing,
  even for market data, and supports subscription updates plus `get_snapshot`.
  Official contracts: https://docs.kalshi.com/getting_started/quick_start_websockets
  and https://docs.kalshi.com/websockets/orderbook-updates
- `worker.streaming` provides transport-neutral dedupe, out-of-order rejection,
  sequence-gap detection, reconnect policy, explicit permanent-gap reporting,
  polling fallback, and the same raw-object/normalized-tick persistence path.
  Kalshi remains polling-only until read-only WebSocket credentials are
  approved; no trading credentials or order channels are needed. A real
  full-matchday parallel-control run remains an acceptance gate.

## Failure, recovery, and rollback

- A venue failure cannot abort the other venue's cycle. Each heartbeat records
  success, errors, retries, rate limits, duration, and sanitized categories.
- A malformed quote stores its rejected raw payload and reason when possible;
  valid sibling markets continue.
- Poll retries use the scheduled cycle timestamp, so restarts cannot create a
  duplicate logical tick. Streaming/recovery uses the venue event ID.
- Markets missing from a later complete active catalogue remain in the registry
  as settlement candidates. Closed-but-unsettled markets are revisited and aged
  exceptions appear in the health report.
- Settlement changes append the previous and replacement provenance; price ticks
  are never rewritten.
- Rollback before production is to stop the worker. The legacy
  `market_odds_snapshots` path remains unchanged. Dropping the additive tables is
  destructive and requires a separate explicit stop gate.

## Acceptance commands

- Focused: `pytest worker pipeline/ingest/venues pipeline/report_capture_health_test.py backend/tests/test_prediction_market_schema.py`
- Python: `.venv/bin/python -m pytest`
- Full: `make test`

### Local verification record — 2026-07-27

- `.venv/bin/python -m pytest`: **1,905 passed**, 34 pre-existing warning-class
  messages, 143.33 seconds on the post-smoke safety changes.
- `npm run typecheck`: passed.
- `npm run lint`: passed with no warnings or errors (plus the framework's
  `next lint` deprecation notice).
- `npm test`: **134 suites / 691 tests passed**. Existing React `act(...)`
  console warnings remain non-failing.
- `npm run build`: passed; 36 static/dynamic routes include
  `/research/venue-calibration` and its `/evidence` page. Expected local backend
  `ECONNREFUSED`/`ETIMEDOUT` logs appeared during fallback static generation.
- `make test`: passed with the same 1,905 Python tests and 134/691 frontend
  result.
- Browser QA: audit and evidence routes loaded, the same-site evidence link was
  followed successfully, and 1440×900 plus 390×844 checks had no horizontal
  document overflow.

Do not mark the P0 weekend, production cutover, streaming control, held-out
benchmark, P4 verdict, P5 selection, public distribution, or production verification
complete without their real dated artifacts.
