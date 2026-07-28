# Prediction-market intelligence architecture

The new path is additive and shadow-only until a separately approved cutover.
It does not replace `market_odds_snapshots`, the current intel panel, public
`/v1` endpoints, or embeds.

```text
Kalshi REST ─────┐
                 ├─ discovery adapters ─ raw private objects
Polymarket REST ─┘             │
                               ├─ venue_market registry
                               ├─ append-only venue_price_tick
                               └─ capture_heartbeat

verified source keys ─ canonical resolver ─ mapped / unmapped / ambiguous
                                              │
                                              ├─ internal coverage report/API
pure model ledger + settled mapped ticks ─────┴─ held-out P3 benchmark
                                                     │
                                                     └─ mechanical P4 gate
                                                            │
                                                   exactly one P5 branch
```

## Boundaries

- Venue adapters own network I/O and venue parsing. They return transport-neutral
  immutable contracts and retain rejected payloads.
- The capture worker persists source facts only. It does not resolve identities,
  calculate fair values, benchmark the model, or serve a product.
- Raw payload objects are private, content-addressed, and encrypted by the
  S3-compatible backend. Normalized ticks have no retention deletion.
- The resolver accepts only exact verified source keys. Similarity is a review
  suggestion and cannot write a mapping or make a market serveable.
- Reconciliation changes registry resolution fields and appends correction
  history; it never rewrites ticks.
- The coverage API is under `/api/internal`, fails closed without
  `RECOMPUTE_TOKEN`, and is `Cache-Control: no-store`. There is no browser-held
  operations secret.
- Benchmark groups are separated by venue, contract type, and horizon. A
  match-clustered bootstrap carries all selected ticks from each sampled match.
- P4 selects P5B only when the model-minus-market log-loss CI95 is entirely below
  zero. Inconclusive or beaten selects P5A; insufficient data selects neither.

## Mapping inventory and compatibility

The legacy `pipeline/ingest/market_names.py` normalizes exchange display text and
contains national-team aliases. `pipeline/team_mapping.py` contains provider
aliases for national teams and selected EPL, La Liga, and Bundesliga clubs.
Those tables remain live compatibility inputs, but they are not automatically
promoted into `entity_source_map`: they lack venue-key provenance and some return
unknown strings unchanged. The new resolver path therefore cannot silently
inherit a fuzzy or incomplete guess. Existing importers may continue using the
legacy wrappers until a captured-data parity report reviews every difference.

## OQ-4 model universe (2026-07-27)

- FIFA World Cup 2026 is the established international model/fixture universe.
- EPL, La Liga, and Bundesliga 2026–27 are active locally in `ACTIVE_LEAGUES`.
  La Liga/Bundesliga activation evidence covers roster reconciliation,
  historical backfill, competition-specific home-advantage fits, and API quota:
  `docs/experiments/2026-07-27-league-phase2-activation/EVIDENCE-CARD.md`.
- Production remains on the World Cup pipeline target until its separate
  stop-gated configuration change is approved.
- Any other captured competition is capture-only until a separate held-out model
  gate establishes support. Coverage reporting keeps capture and model coverage
  as different measures.

## Operational rollback

Before production, rollback means stopping the worker and leaving the additive
tables untouched for inspection. In production, migration and worker rollout are
separate approvals: apply/verify tables before code depends on them. Dropping
tables, merging to `main`, applying production migrations, provisioning paid
services, and deploying remain explicit stop gates.
