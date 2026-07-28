# P0 bounded weekend shadow plan — 2026-07-31 to 2026-08-03

## Purpose and limits

This is a local, read-only venue-data observation. It does not apply the
production migration, provision paid infrastructure, place trades, deploy a
worker, or change the legacy `market_odds_snapshots` path.

The capture window begins after a final fixture check on Friday 2026-07-31 and
ends Monday 2026-08-03 (Australia/Sydney). Use a dedicated Docker PostgreSQL 16
container with tmpfs storage, a dedicated worker container, and a local raw
object directory. Keep both containers stopped after evidence is generated.

## Precommitted Polymarket fixture

Polymarket's active soccer catalogue was queried on 2026-07-27. The selected
event is **Inter Miami CF vs. Columbus Crew**, scheduled for
2026-08-01 23:30 UTC. It has one active `moneyline` binary market for each
mutually exclusive match result:

| Outcome | Exact condition ID |
|---|---|
| Inter Miami win | `0xc9ebb271f7322ff192c164023a952619b075599bfe92f9196b03ccc1d5439a7e` |
| Draw | `0x0280d4facd96bc9bf1ca31160f0ecad1b5db2f79c1cda7c9a953a4db7a2689c7` |
| Columbus Crew win | `0x6d9971aaabc470ee6055d881524b9b5d2887fe5fe0ceff244ce5fe0b548a028c` |

All three condition IDs returned non-empty bid and ask books through the
production `PolymarketAdapter.fetch_quote` path on 2026-07-27 UTC. Recheck the
event status, scheduled time, condition IDs, and books immediately before the
worker starts. If any identity changes, record the replacement and reason in
the evidence card; never silently substitute a market.

## Kalshi eligibility status

No exact upcoming match-result event was listed on 2026-07-27. A full open-event
scan found only `KXMANAGERSOUT-26AUG01EPL` in the window; it is a manager-dismissal
proposition and is intentionally excluded. On Friday, rescan exact `*GAME`
soccer series and use `expected_expiration_time` as the scheduled-event signal.
Add Kalshi only when a single fixture has a complete, unambiguous home/draw/away
set and every selected ticker returns a usable book. Do not guess future keys.

## Bounded runtime configuration

- `MARKET_CAPTURE_REGISTRY_SCOPE=eligible`
- `MARKET_CAPTURE_MAX_MARKETS_PER_VENUE=5`
- `MARKET_CAPTURE_DISCOVERY_SECONDS=21600`
- `MARKET_CAPTURE_PREMATCH_SECONDS=300`
- `MARKET_CAPTURE_INPLAY_SECONDS=30`
- `MARKET_CAPTURE_CONCURRENCY=1`
- local raw store only; no S3/R2 credentials
- exact venue-qualified allowlist only

If Kalshi is still ineligible on Friday, run Polymarket alone with the three
condition IDs above. If Kalshi becomes eligible, append at most three exact
`kalshi:<ticker>` entries and enable the venue. The hard ceiling remains five
markets per venue.

## Local isolation

Use dedicated names so the normal `wc26-postgres` development service and its
volume are untouched:

- database container: `wc26-market-shadow-20260731-db`, host port `55433`,
  PostgreSQL data on container tmpfs;
- worker container: `wc26-market-shadow-20260731-worker`;
- raw objects: `/tmp/wc26-market-shadow-20260731-raw`;
- database: `wc26_shadow` with local-only credentials.

Apply the full Alembic chain to this disposable database, confirm a single head,
then start the worker. Do not dispatch `refresh.yml` or use any production
database URL.

## Evidence and acceptance

After the window, record:

- worker/container uptime, restarts, CPU, and memory;
- heartbeats expected and observed by venue;
- discovered, registered, quoted, stale, rejected, retry, and rate-limit counts;
- pre-match and in-play coverage by selected market;
- settlement status and exceptions;
- raw object count and bytes, database table sizes, and extrapolated monthly cost;
- any venue/API policy issue or unexplained gap.

Generate `capture-health.json` with `pipeline.report_capture_health` and write an
`EVIDENCE-CARD.md` in this directory. Task 5.3 remains incomplete until the
whole window and evidence review finish.

Primary API references:

- [Polymarket list events](https://docs.polymarket.com/api-reference/events/list-events)
- [Kalshi market lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle)
- [Kalshi market-data quick start](https://docs.kalshi.com/getting_started/quick_start_market_data)

## START record — 2026-07-27 UTC

The START heartbeat completed and the isolated worker/database are running. Live
venue identity, exact allowlists, book validation, migration state, bounded
runtime configuration, initial capture counts, resource baselines, and startup
corrections are recorded in [START-VALIDATION.md](START-VALIDATION.md).

Task 5.3 remains incomplete pending the full-window REVIEW and evidence card.
