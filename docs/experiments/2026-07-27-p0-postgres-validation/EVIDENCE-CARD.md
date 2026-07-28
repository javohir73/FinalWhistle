# P0 disposable PostgreSQL validation — 2026-07-27

## Scope

Local, disposable PostgreSQL 16 validation only. No production database, paid
service, deployment, or venue credential was used.

## Migration result

- Upgraded a blank PostgreSQL database through the complete Alembic chain to
  `e1f2a3b4c5d6`.
- PostgreSQL reported all five additive tables: `canonical_entity`,
  `entity_source_map`, `venue_market`, `venue_price_tick`, and
  `capture_heartbeat`.
- `venue_price_tick` was a range-partitioned parent on `ts`; the validation rows
  landed in `venue_price_tick_2026_07`.
- Downgraded exactly one revision to `d9e0f1a2b3c4`, verified the new registry
  was absent and `market_odds_snapshots` remained present, then upgraded back to
  the new head and verified all five additive tables returned.

## Recorded-fixture worker result

The production `CaptureWorker`, real Kalshi/Polymarket adapters, and local raw
store were exercised with the repository's sanitized multi-page catalogue,
full-order-book, and settlement fixtures.

| Measure | Result |
|---|---:|
| Kalshi markets seen / successful quotes / errors | 3 / 3 / 0 |
| Polymarket markets seen / successful quotes / errors | 3 / 1 / 0 |
| Canonical entities / verified source maps | 3 / 3 |
| Venue markets / normalized ticks / heartbeats | 6 / 4 / 2 |
| Settled markets | 1 (`polymarket:0xccc`, `Yes`) |
| Raw JSON objects | 11 |
| Raw-store disk allocation | 44 KiB |

All 11 raw objects produced SHA-256 digests. Repeated fixture content correctly
shared a content digest while retaining separate deterministic market paths.
Malformed fixture siblings were logged and excluded without aborting valid
Polymarket markets.

## Verdict

`pass` for task 5.1. This proves the additive migration and recorded-fixture
capture path on disposable PostgreSQL. It does not prove live venue behavior,
weekend reliability, production cost, or production readiness.
