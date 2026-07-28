# Independent validation data sources

**Status: DEFAULT OFF. Nothing enabled, nothing scheduled, no credentials
committed, no serving change.**

Redundant fixture/result and market observations from providers OTHER than the
one the served engine uses, for **reconciliation** and **secondary** market
benchmarking. Nothing here feeds ratings, predictions, or any served surface.

## The boundary that matters most

The pre-registered q3 confirmation benchmark
(`pipeline/run_calibrator_benchmark.py`) reads the **API-Football `odds`
table**. That baseline is **frozen** and this work does not change it — not its
semantics, not `_closing_market`, not one row.

New provider observations are therefore written to their **own two tables** and
never to `odds` or `market_odds_snapshots`. Two tests enforce it: one asserts
the row counts of both are unchanged after ingesting from every source, and one
is structural — no module in the package may even import the frozen baseline
models.

Why not the existing tables:

| Table | Why not |
|---|---|
| `odds` | The q3 benchmark reads it. A second provider there would silently change a merged, pre-registered comparison |
| `market_odds_snapshots` | The intel **product** surface: replaced hourly per `(sport, source, hour)` and swept by a retention prune. Evidence must not live behind a delete cycle |
| `venue_market` / `entity_source_map` | An unmerged resolver (#203) targets these. A second writer with different conventions would collide |

## Schema — two append-only tables

Migration `a7c3d9e2f481`, purely additive. Verified: single alembic head,
upgrade→downgrade→upgrade round-trips on Postgres, and `odds`,
`market_odds_snapshots` and `venue_market` all survive the downgrade.

`validation_fixture_observation` — one row per `(source, source_event_id,
payload_sha256)`. `validation_market_snapshot` — one row per `(source,
source_market_id, outcome, captured_at, bookmaker_key)`.

Both carry: immutable provenance (`payload_sha256`), source ids, **both**
timestamps (the provider's own `captured_at`/`source_updated_at` and our
`retrieved_at`), **raw** provider labels alongside normalized canonical labels,
a nullable canonical `match_id`, and `reconciliation_status` +
`reconciliation_note`.

**Append-only.** A re-observed payload is a no-op via the uniqueness key; a
*changed* payload appends a new row and leaves the original readable. Nothing
is updated or deleted. **There is no retention sweep.**

`bookmaker_key` defaults to `""` rather than NULL: SQL treats NULLs as
distinct, which would silently defeat the uniqueness key for sources with no
bookmaker.

## Identity — deliberately local

`pipeline/ingest/validation/identity.py` owns an explicit German-club alias
table (94 entries) and a deterministic rule. It does **not** write
`entity_source_map`, because #203 has an unmerged resolver targeting that table
and two writers with different confidence semantics would collide.

Rule: both labels must map via the explicit alias table (no fuzzy scoring); a
candidate must share **both** clubs in the **same orientation**; kickoff within
36h; exactly one survivor. Zero → `unmatched`. More than one → `conflict`.
An unmapped label is reported with the alias it needs — never guessed.

**If this rule ever proves insufficient without shared entity state, the
correct move is to stop and report, not to invent a competing convention.**

## Statistical rules

- **One finished match is n=1.** Sources, bookmakers and snapshots are
  *columns*. `distinct_matches` counts matches, never rows. Tested with two
  sources on one match.
- **Only 2026-27 counts toward the live q3 gate.** Training seasons
  (2016-17…2024-25) and the consumed 2025-26 holdout are barred by
  `LIVE_VALIDATION_SEASON_START`; they appear only under `--include-pre-live`,
  for provenance.
- **Strictly pre-kickoff.** A snapshot at or after kickoff is dropped, not
  clamped.
- **No pooling** of EPL, La Liga or lower divisions.
- **No cross-source consensus.** De-vig happens *within* one source+market
  group. A blend across sources would be a new predictor, not evidence.

## Sources

| Source | Fetches? | Cost / licensing | Env |
|---|---|---|---|
| OpenLigaDB | yes | free, **no key** | — |
| football-data.org | yes | free tier covers BL1; attribution required | `FOOTBALL_DATA_API_KEY` |
| The Odds API | yes (pre-match only) | free tier ~500 req/mo; **historical odds is a PAID add-on, never called here** | `ODDS_API_KEY` |
| Betfair Historical | **no — importer only** | Basic tier needs an account; **Advanced/Pro required here**; licensed data | — |

Unconfigured, timed-out, rate-limited or malformed always returns an empty
result plus a reason. Never raises, never touches production or shadow writes.

### Betfair: importer only, and why

Archives sit behind an account login and a data licence, so this reads a file
**you** downloaded. It never authenticates, never fetches, never touches a
betting account.

It emits **available-to-back** prices, reconstructed statefully:

- `rc` runner changes are **partial deltas**; `atb` entries are `[price,
  size]`, and **size 0 removes that level**. Ladders accumulate across
  messages.
- Best back = highest price still offered.
- A snapshot is emitted only once **all three** runners have a best back, at a
  publish time **strictly before** kickoff, and only when a price actually
  moved.
- Sides come from `marketDefinition.runners[].sortPriority` (1=home, 2=away,
  3=draw), **never list order**, with the draw cross-checked by name.
- Positively required: `eventTypeId == "1"` (Soccer), `marketType ==
  "MATCH_ODDS"`, and `competitionId` equal to the operator-supplied
  `--competition-id`, validated against archive metadata. Anything else is
  **rejected, not stamped**. In-play is excluded.

**`ltp` is LAST TRADED PRICE, not available-to-back, and is never substituted.**
A Basic-tier archive carries no `atb` ladder, so it **fails closed** with
`BetfairArchiveUnsupported` naming the required tier. Both the archive sha256
and an operator acquisition note are mandatory: an offline source must still be
citable.

## Commands

```bash
# free, no key
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_validation_ingest \
    --source openligadb --season 2026

# needs FOOTBALL_DATA_API_KEY / ODDS_API_KEY
... --source football_data_org --season 2026
... --source the_odds_api

# offline import of an archive YOU downloaded (Advanced/Pro tier)
... --source betfair_historical --archive /path/to/market.jsonl \
    --acquisition-note "downloaded 2026-09-01, Betfair historical Pro tier" \
    --competition-id <betfair Bundesliga competitionId>

# reports (read-only, safe any time)
PYTHONPATH=backend:. .venv/bin/python -m pipeline.report_validation_sources
```

There is no all-sources default and no env var that turns everything on.

## Confirmatory vs secondary evidence

| Evidence | Role |
|---|---|
| API-Football `odds` closing line, via `run_calibrator_benchmark.py` | **CONFIRMATORY.** The pre-registered baseline. Untouched by this work |
| The Odds API, per bookmaker | **SECONDARY.** Reported in its own column |
| Betfair exchange back prices | **SECONDARY.** Reported in its own column |
| Any cross-source consensus | **NOT COMPUTED.** It would be a new predictor |
| Fixture/result reconciliation | **INTEGRITY ONLY.** Disagreement is reported; nothing is ever overwritten |

## What works without credentials

Every parser, the identity layer, the loader, both reports and the Betfair
importer are fully hermetic — 42 tests, no network, no keys. OpenLigaDB also
runs live with no key.

**You must provide:** `FOOTBALL_DATA_API_KEY` and `ODDS_API_KEY` for live
fetches, and Betfair Advanced/Pro archives (downloaded yourself) plus the
Bundesliga `competitionId`. **Nothing here purchases anything.**
