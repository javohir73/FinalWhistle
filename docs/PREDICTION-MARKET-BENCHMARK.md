# Venue market benchmark (shadow, research only)

**Status: EXPERIMENTAL/SHADOW. Operator-run, read-only, default nothing.
Readiness in this data means "enough to discuss", never "switch anything on".
This is NOT the pre-registered API-Football closing-line gate — that lives in
`pipeline/run_calibrator_benchmark.py`, stays frozen, and is untouched.**

## Lineage — exactly what is compared to what

| Side | Source | Rule |
|---|---|---|
| venue | `venue_price_tick` | **one coherent 1X2 snapshot**: each leg's quote must be genuinely two-sided (bid AND ask AND mid); the snapshot is the latest capture timestamp where **all three legs** were quoted in one polling cycle, else each leg's latest two-sided quote within a **15-minute cross-leg skew bound** — three fresh legs captured hours apart are a fictitious book and are excluded. All legs `ts ≤ kickoff`, oldest leg at most 48h before kickoff. Leg timestamps and skew persist on every observation and aggregate into the artifact. Raw mids retained; vig-normalization explicit |
| model | `prediction_results` → `predictions` | the **exact frozen prediction the audited public record scored** (ledger `prediction_id`, `is_shadow=False`, validated pre-kickoff) — the ledger pins **the vector only**; without a ledger row, the latest non-shadow pre-kickoff prediction |
| outcome | `matches` | **regulation-time result, always derived independently**: `score_home_90`/`score_away_90`, else full time **only** for non-knockout stages with no shootout (where FT *is* regulation). `PredictionResult.outcome` is **never** used as the label — the learning loop deliberately keeps the after-ET winner convention (`learning_loop._result_row`), so a 1-1 at 90 finishing 2-1 in ET is `home` there and a **draw** here. Without a 90-minute basis the match is excluded, not guessed |
| baseline | none | uniform (1/3, 1/3, 1/3) — fit-free by construction, so it can leak nothing |

**No in-play or score-matched comparison exists.** Neither captured venue
publishes an authoritative score or clock (Phase-2 finding, recorded in
`docs/PREDICTION-MARKET-CAPTURE.md`), and internal live state is never
substituted for venue state. This benchmark is pre-kickoff 1X2 only.

## Eligibility and exclusions

A (venue, fixture) group is scored only when **all** hold: resolver-`mapped`
markets forming a complete exclusive 1X2 set (exactly home/draw/away, no
duplicates); finished fixture with one known final; a fresh two-sided
pre-kickoff quote for all three outcomes; a pre-kickoff non-shadow model
prediction. Everything else is **excluded and counted** under a named reason
(`incomplete_1x2_set`, `conflicting_duplicate_outcome`, `no_final_outcome`,
`no_regulation_time_basis`, `no_two_sided_prekickoff_quote`,
`incoherent_market_snapshot`, `stale_prekickoff_quote`,
`no_prekickoff_prediction`, `ledger_prediction_not_prekickoff`,
`naive_timestamp`, `invalid_observation`, …) with a per-group note.
The exclusion table ships inside the artifact — it is part of the result.

Fail-closed validation at construction: non-finite or out-of-domain
probabilities, naive timestamps, post-kickoff "snapshots", unknown outcomes,
model vectors that don't sum to 1, and books whose raw implied sum falls
outside [0.85, 1.30] are refused, never quietly normalized.

## Leakage policy

The unit is the **canonical match**. The chronological split moves whole
matches — every observation for a match (all venues) lands on one side, and
**whole kickoff cohorts move together**: the boundary must fall between
distinct kickoff times, the boundary cohort goes to holdout, and a dataset
with no valid boundary (all simultaneous) fails closed. Strict
train-max < holdout-min is asserted. Two kickoffs for one match is a hard
error. Competition diagnostics flag holdout-only
competitions. Nothing is fitted anywhere in this phase; the train side exists
so a *future* calibration fit has somewhere to live, and no metric reads it.
Metrics are computed on the holdout only, which is what "no improvement claim
without holdout evidence" means in practice.

## Readiness

The readiness floor is **not lowerable at artifact level** — `--min-matches`
below 50 clamps UP, bootstrap has a 100-sample minimum, and a naive clock is
refused. Per venue, on identical eligible matches: log loss, multiclass Brier,
ten-bin reliability + ECE, match counts, capture window, and a
**match-clustered bootstrap** 95% CI on the per-match log-loss delta
(model − venue). Below `--min-matches` (default 50) the group is `NOT_READY`:
counts and a reason, **no verdict, no ranking, no deltas**. Verdicts
(`model_beats_venue` / `venue_beats_model` / `inconclusive`) exist only when
the CI is computable and N clears the floor.

## Health

`pipeline/report_market_health.py` — denominators are **fixtures and
markets, never ticks** (a 30-second market writes ~3k ticks/day; tick-counted
"coverage" lets one liquid market drown fifty silent ones). Enumerates
mapping-status counts, incomplete/conflicting 1X2 fixtures, markets with no
quote at all, complete fixtures missing a pre-match quote, quote freshness by
(venue, transport) and heartbeat freshness by (venue, worker).

## Operator steps

```bash
# report to stdout (writes nothing)
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_market_benchmark_report benchmark

# write the artifact the research API serves
... benchmark --output backend/app/research_data/market_benchmark.json

# health only
... health
```

The artifact is written **atomically** (temp + rename) into
`backend/app/research_data/` — gitignored, never committed. The API
(`GET /api/research/market-benchmark`, no-store) **reconstructs the response
through a strict allowlist**: every rendered field is validated for type and
domain (finite numbers, aware timestamps, enum statuses/verdicts, non-negative
counts), any violation — including nested poison like `groups: [null]` — makes
the whole response `invalid` with the reason, and fields not on the allowlist
never leave the server. That construction, tested against the generator's own
output, is what makes "deliberately public" enforced rather than asserted:
aggregate metrics, counts, public market tickers and timestamps only — no
user data, no credentials. The page (`/research/market-benchmark`, noindex — politeness,
not protection) fetches with true `no-store` on both sides and renders the
experimental banner, N, capture window, coverage, exclusions, mapping and
quote coverage, quote/heartbeat freshness, CI, and explicit not-enough-data
states.

## Known gaps and evidence still needed

1. **There is no real data yet.** Capture is default-off and resolution
   requires named-human verification, so every current number comes from
   synthetic test fixtures — which prove code paths, never real-world
   validity. Real validation needs: capture enabled (stop-gated), entity keys
   linked, fixtures verified, and a season of finished matches.
2. **Stopped fixtures are invisible after ingestion** (Phase-3 finding): a
   postponed fixture ingested today reads `scheduled`, so the "finished with
   a regulation-time result" gate is the only stopped-status protection this
   benchmark has.
3. **90-minute score columns may be sparsely populated** for knockout
   fixtures ingested before `score_90` support: those matches are excluded
   under `no_regulation_time_basis` rather than mislabeled, which shrinks
   knockout coverage until the columns backfill.
4. **Venue quote quality is unmodeled**: mids from thin books are taken at
   face value once two-sided and fresh; depth/liquidity weighting is future
   work and would need its own pre-registration.
