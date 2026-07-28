# P0 bounded weekend shadow — START validation

## Decision

**Started.** The isolated worker and disposable PostgreSQL database are running.
The exact six-outcome allowlist covers one complete Inter Miami CF vs. Columbus
Crew home/draw/away fixture on each venue. Task 5.3 remains incomplete until the
second heartbeat stops the worker and reviews the complete capture window.

All timestamps below are UTC. This START heartbeat ran on 2026-07-27 UTC
(2026-07-28 Australia/Sydney).

## Official venue revalidation

### Polymarket

Checked through the official Gamma event API and CLOB book API at
`2026-07-27T23:44:22.268038Z`.

- Event ID: `722007`
- Event slug: `mls-mia-clb-2026-08-01`
- Event title: `Inter Miami CF vs. Columbus Crew`
- Scheduled start: `2026-08-01T23:30:00Z`
- Market type: `moneyline`
- Event/markets: active, not closed, and accepting orders

| Outcome | Exact condition ID | Bid levels | Ask levels | Best bid | Best ask |
|---|---|---:|---:|---:|---:|
| Inter Miami win | `0xc9ebb271f7322ff192c164023a952619b075599bfe92f9196b03ccc1d5439a7e` | 32 | 35 | 0.56 | 0.57 |
| Draw | `0x0280d4facd96bc9bf1ca31160f0ecad1b5db2f79c1cda7c9a953a4db7a2689c7` | 20 | 44 | 0.21 | 0.23 |
| Columbus Crew win | `0x6d9971aaabc470ee6055d881524b9b5d2887fe5fe0ceff244ce5fe0b548a028c` | 19 | 43 | 0.20 | 0.21 |

The event identity, scheduled time, and all three precommitted condition IDs
matched the plan exactly. No replacement was made.

### Kalshi

The official Soccer catalogue was rescanned at
`2026-07-27T23:44:46.334350Z`. The scan covered 95 exact series names ending in
`GAME` and 194 open game events. Selection used the API-provided
`expected_expiration_time`; no ticker was constructed or guessed.

The complete, unambiguous fixture found in `KXMLSGAME` was:

- Event ticker: `KXMLSGAME-26AUG01MIACLB`
- Event title/subtitle: `Miami vs Columbus` / `MIA vs CLB (Aug 1)`
- Shared `expected_expiration_time`: `2026-08-02T02:30:00Z`

Books were revalidated at `2026-07-27T23:45:37.536011Z`.

| Outcome | Exact ticker | Bid levels | Ask levels | Best bid | Best ask |
|---|---|---:|---:|---:|---:|
| Inter Miami win | `KXMLSGAME-26AUG01MIACLB-MIA` | 17 | 22 | 0.59 | 0.60 |
| Draw | `KXMLSGAME-26AUG01MIACLB-TIE` | 18 | 24 | 0.22 | 0.23 |
| Columbus Crew win | `KXMLSGAME-26AUG01MIACLB-CLB` | 17 | 28 | 0.20 | 0.21 |

All three markets were active with usable two-sided books, so Kalshi was
included.

## Disposable runtime

### PostgreSQL

- Container: `wc26-market-shadow-20260731-db`
- Container ID: `c2436b1aa2ee24781e6a35cd2563f4ff59161e2c09bacb7a67dad2cdcd6403e9`
- Image: PostgreSQL 16, image ID
  `sha256:ab47a724d0e37131ac950b98ff2beeb3fdb3bfcc592d73c6cc4b4e7626649671`
- Started: `2026-07-27T23:46:04.806048045Z`
- Binding: `127.0.0.1:55433 -> 5432`
- Storage: container tmpfs at `/var/lib/postgresql/data`, 512 MiB
- Restart policy: `no`; observed restarts: 0
- Database/user: `wc26_shadow`; local-only credential (not recorded here)
- Alembic heads: one, `e1f2a3b4c5d6 (head)`
- Applied version rows: one, `e1f2a3b4c5d6`

Migrations were applied only through the local port above. No production URL or
production database was used.

### Worker

- Container: `wc26-market-shadow-20260731-worker`
- Container ID: `b39f710082e7de5385561da4c0c7d618a26f2a219c0a5ea6ca7262f72158bf02`
- Image ID: `sha256:e038943d16abc67c88c2ea00c785189400b65b8db21834afaf4896f8cc9b66a1`
- Started: `2026-07-27T23:57:04.079317961Z`
- Restart policy: `no`; observed restarts: 0; OOM killed: false
- Limits: 1 CPU, 768 MiB memory, concurrency 1
- Raw bind: `/tmp/wc26-market-shadow-20260731-raw -> /raw`
- Raw backend: local only
- Venues: `kalshi,polymarket`
- Registry scope: `eligible`
- Maximum: 5 markets per venue
- Discovery/prematch/in-play: 21,600 / 300 / 30 seconds
- Exact allowlist: the three Kalshi tickers and three Polymarket condition IDs
  listed above

The final startup cycle was scheduled at `2026-07-27T23:57:04Z`:

| Venue | Catalogue markets seen | Allowlisted quotes | Errors | Retries | Rate limits | Duration |
|---|---:|---:|---:|---:|---:|---:|
| Kalshi | 6,674 | 3 | 0 | 0 | 0 | 23.292 s |
| Polymarket | 47,273 | 3 | 0 | 0 | 0 | 29.056 s |

All six normalized ticks were active, two-sided, stored with top-10 bid and ask
levels, and had no validation flags. Their best prices matched the validation
table above.

## Startup corrections retained as evidence

The first image build exposed a 4.3 GB local `.claude` directory in its Docker
context. `.dockerignore` was narrowed to exclude local agent/design artefacts;
the rebuilt context was approximately 75 kB.

The first worker retained the entire venue catalogues and reached the original
512 MiB memory limit (about 531 MiB process RSS). A bounded-cache change now
retains only the exact eligible set while preserving full catalogue counts in
heartbeats. A first implementation recomputed the allowlist set per catalogue
row and was caught live as quadratic CPU; it was corrected before the final
worker start. The two stopped diagnostic containers are deliberately preserved:

- `wc26-market-shadow-20260731-worker-precache`
- `wc26-market-shadow-20260731-worker-quadratic`

The final worker's first-pass high-water RSS was about 540 MiB; after the pass it
was about 424 MiB in Docker stats (55% of its 768 MiB limit). Subsequent
catalogue refreshes can reuse allocator memory while the retained Python
catalogue contains only the six eligible markets.

Focused verification after the correction:

`PYTHONPATH=backend:. .venv/bin/python -m pytest worker pipeline/ingest/venues pipeline/report_capture_health_test.py backend/tests/test_prediction_market_schema.py`

Result: **128 passed in 0.95 seconds**.

## Start baseline for later review

- Raw objects: 18 files, 73,611 logical bytes (104 KiB allocated)
- Database size: 11 MB
- `venue_market`: 160 KiB
- July `venue_price_tick` partition: 96 KiB
- `capture_heartbeat`: 64 KiB
- `canonical_entity`: 32 KiB
- `entity_source_map`: 24 KiB
- Start sample worker usage: 0% CPU, 424.3 MiB / 768 MiB
- Start sample database usage: 0.02% CPU, 98.37 MiB

The review heartbeat must calculate the final health/gap/coverage/settlement and
cost evidence from the retained database and raw objects. These start values do
not satisfy task 5.3 by themselves.

## Safety confirmation

No production resource was read from or written to, no paid service was
provisioned, no deployment or workflow was dispatched, no trade was placed, and
the legacy market-intelligence workflow was not modified. The disposable worker
and database are intentionally still running for the REVIEW phase.
