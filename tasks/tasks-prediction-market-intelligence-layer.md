# Tasks: Prediction-Market Intelligence Layer

Source PRD: [prd-prediction-market-intelligence-layer.md](prd-prediction-market-intelligence-layer.md)

## Relevant Files

### Product requirements and evidence

- `tasks/prd-prediction-market-intelligence-layer.md` - Product requirements, phase gates, acceptance criteria, and open questions for this task list.
- `docs/superpowers/specs/2026-07-25-prediction-market-intelligence-layer-design.md` - Evidence and architectural decisions that the implementation must preserve.
- `docs/experiments/2026-07-23-wc26-postmortem/` - Existing WC26 market benchmark inputs and evidence used by the P1 public audit.
- `docs/MODEL-EXPERIMENTS.md` - Append-only record for P3/P4 experiment wins, losses, and inconclusive results.
- `docs/RELIABILITY.md` - Existing reliability and live-pricing latency evidence; extend with capture/streaming operating characteristics.
- `docs/PREDICTION-MARKET-RUNBOOK.md` (new) - Worker operations, recovery, gap investigation, settlement exceptions, and rollback instructions.

### Database and configuration

- `backend/app/models/__init__.py` - Add the five market-intelligence models and, conditionally, P5 user-fill or alert models.
- `backend/alembic/versions/<revision>_prediction_market_capture.py` (new) - Additive P0 migration for canonical entities, source maps, venue markets, ticks, and heartbeats.
- `backend/alembic/versions/<revision>_prediction_market_p5a.py` (conditional, new) - Private fill-import and derived-analytics tables if P5A is selected.
- `backend/alembic/versions/<revision>_prediction_market_p5b.py` (conditional, new) - User alert preferences/state if P5B is selected.
- `backend/tests/test_prediction_market_schema.py` (new) - Constraints, idempotency keys, append-only expectations, and migration-shape tests.
- `backend/app/config.py` - Add capture, storage, freshness, and optional stream settings without exposing secrets.
- `render.yaml` - Add a long-lived worker only after the paid-infrastructure stop gate is approved.
- `.env.example` - Document new non-secret settings and secret variable names.

### Venue adapters and capture worker

- `pipeline/market_intel.py` - Remove destructive 14-day pruning; keep the existing `market_odds_snapshots` path working during shadow operation.
- `pipeline/ingest/kalshi.py` - Existing Kalshi adapter to preserve or wrap while moving new behavior into the venue-adapter contract.
- `pipeline/ingest/kalshi_test.py` - Existing fixture tests; retain compatibility coverage.
- `pipeline/ingest/polymarket.py` - Existing Polymarket adapter to preserve or wrap while moving new behavior into the venue-adapter contract.
- `pipeline/ingest/polymarket_test.py` - Existing fixture tests; retain compatibility coverage.
- `pipeline/ingest/venues/__init__.py` (new) - Venue-adapter package and shared exports.
- `pipeline/ingest/venues/types.py` (new) - `VenueMarket`, `Quote`, `Settlement`, order-book, and adapter protocol types.
- `pipeline/ingest/venues/CONTRACTS.md` (new) - Stable idempotency keys, correction semantics, and adapter-boundary rules for the P0 migration.
- `pipeline/ingest/venues/kalshi.py` (new) - Discovery, pagination, full-book, quote, and settlement implementation for Kalshi.
- `pipeline/ingest/venues/kalshi_test.py` (new) - Network-free fixture tests for Kalshi discovery, books, validation, pagination, and settlement.
- `pipeline/ingest/venues/polymarket.py` (new) - Discovery, pagination, full-book, quote, and settlement implementation for Polymarket.
- `pipeline/ingest/venues/polymarket_test.py` (new) - Network-free fixture tests for Polymarket discovery, books, validation, pagination, and settlement.
- `pipeline/ingest/testdata/` - Store sanitized catalogue, order-book, closed, void, malformed, and rate-limit response fixtures.
- `worker/__init__.py` (new) - Capture-worker package.
- `worker/config.py` (new) - Validated capture cadence, concurrency, retry, depth, and raw-storage configuration.
- `worker/capture.py` (new) - Dumb discovery/quote/settlement capture loop with per-venue isolation.
- `worker/raw_store.py` (new) - Lossless raw-payload storage interface and implementation.
- `worker/main.py` (new) - Process entry point, graceful shutdown, and restart behavior.
- `worker/capture_test.py` (new) - Worker tests for idempotency, backoff, partial failure, heartbeat, restart, and settlement retry.
- `worker/raw_store_test.py` (new) - Raw-payload keying, integrity, access failure, and retry tests.
- `worker/Dockerfile` (new) - Long-lived worker image if a separate Render service is selected.
- `pipeline/report_capture_health.py` (new) - P0 command/report for coverage, gaps, errors, and settlement exceptions.
- `pipeline/report_capture_health_test.py` (new) - Report aggregation and boundary tests.

### Entity resolution and internal coverage

- `pipeline/entities/__init__.py` (new) - Entity-resolution package.
- `pipeline/entities/resolver.py` (new) - Exact `mapped`/`unmapped`/`ambiguous` resolution contract.
- `pipeline/entities/resolver_test.py` (new) - Exact-key, ambiguity, outcome, and no-fuzzy-path tests.
- `pipeline/entities/reconcile.py` (new) - Idempotent historical re-resolution command.
- `pipeline/entities/reconcile_test.py` (new) - Retroactive mapping and correction tests.
- `pipeline/ingest/market_names.py` - Legacy mapping logic to retire only after P2 parity is proved.
- `pipeline/ingest/market_names_test.py` - Legacy behavior used to define parity fixtures.
- `pipeline/team_mapping.py` - Duplicate mapping logic to merge into the new source-map data.
- `pipeline/team_mapping_test.py` - Existing mapping cases to preserve in the new resolver.
- `backend/app/api/internal.py` - Add token-guarded coverage and gap endpoints, or route to a dedicated internal module.
- `backend/app/api/market_intelligence_internal.py` (new, optional) - Dedicated internal coverage/resolution API if `internal.py` would become too large.
- `backend/tests/test_market_intelligence_internal_api.py` (new) - Fail-closed auth, aggregation, filters, and unresolved drill-down tests.
- `frontend/app/internal/market-coverage/page.tsx` (new, optional) - Internal coverage dashboard if a browser surface is chosen; must not embed an operations token in client code.
- `frontend/components/MarketCoverageDashboard.tsx` (new, optional) - Coverage, gap, settlement, and unresolved-market presentation.
- `frontend/components/__tests__/marketCoverageDashboard.test.tsx` (new, optional) - Dashboard state and filter tests.

### Streaming

- `worker/streams/__init__.py` (new) - Streaming-adapter package.
- `worker/streams/types.py` (new) - Transport-neutral stream update and lifecycle interfaces.
- `worker/streams/kalshi.py` (new) - Kalshi subscription, sequencing, reconnect, and recovery implementation where supported.
- `worker/streams/polymarket.py` (new) - Polymarket subscription, sequencing, reconnect, and recovery implementation where supported.
- `worker/streams/stream_test.py` (new) - Disconnect, resubscribe, duplicate, out-of-order, gap, and polling-fallback tests.
- `pipeline/report_stream_control.py` (new) - Streaming-versus-polling comparison report for P2b acceptance.

### Audit, benchmark, and gate

- `ml/evaluation/market_benchmark.py` - Existing paired benchmark primitives; preserve pre-match behavior while sharing safe scoring helpers.
- `ml/evaluation/market_benchmark_test.py` - Existing regression coverage for paired scoring.
- `ml/evaluation/inplay_market_benchmark.py` (new) - Match-state alignment, horizon buckets, market-type separation, and match-clustered bootstrap.
- `ml/evaluation/inplay_market_benchmark_test.py` (new) - Alignment, bucket boundaries, exclusions, clustering, metrics, and verdict tests.
- `pipeline/run_market_benchmark.py` - Existing reproducible pre-match command used by P1.
- `pipeline/publish_venue_audit.py` (new) - Generate the P1 audit data artifact from frozen experiment inputs.
- `pipeline/publish_venue_audit_test.py` (new) - Published-value and schema regression tests.
- `pipeline/run_inplay_market_benchmark.py` (new) - Reproducible P3/P4 benchmark CLI and evidence-card output.
- `pipeline/run_inplay_market_benchmark_test.py` (new) - CLI validation, deterministic seed, exclusion counts, and output tests.
- `pipeline/promote_blend.py` - Remove the belief-based 0.5 cap and retain `[0,1]` validation plus the existing promotion gate.
- `pipeline/promote_blend_test.py` - Test full-range weights, invalid weights, dry-run, and promotion behavior.
- `pipeline/generate_predictions.py` - Verify that pure-model and market-blended ledgers remain isolated.
- `backend/tests/test_shadow_isolation.py` - Extend ledger-separation regression coverage if required.
- `frontend/lib/venue-audit-data.json` (new, generated) - Reproducible P1 page input.
- `frontend/app/research/venue-calibration/page.tsx` (new) - Public venue-calibration audit.
- `frontend/app/research/venue-calibration/page.test.tsx` (new) - Audit content, caveat, and data-state tests.
- `frontend/components/MarketComparison.tsx` - Reuse or extend established benchmark visualization patterns.

### Conditional P5 product files

- `backend/app/api/trader_analytics.py` (conditional, new) - Authenticated P5A fill import, fill history, CLV, and segment analytics API.
- `backend/tests/test_trader_analytics_api.py` (conditional, new) - P5A ownership, validation, reference-price, CLV, filters, and privacy tests.
- `pipeline/trader_fills.py` (conditional, new) - P5A CSV parser, exact venue-key resolution, CLV calculation, and aggregate helpers.
- `pipeline/trader_fills_test.py` (conditional, new) - P5A parser and hand-calculated CLV tests.
- `frontend/app/analytics/page.tsx` (conditional, new) - Private P5A trader analytics page.
- `frontend/components/FillImport.tsx` (conditional, new) - P5A upload validation and row-error UI.
- `frontend/components/TraderAnalyticsDashboard.tsx` (conditional, new) - P5A history, filters, CLV, and leak summaries.
- `frontend/components/__tests__/traderAnalytics.test.tsx` (conditional, new) - P5A UI tests.
- `backend/app/api/sharp_intelligence.py` (conditional, new) - P5B supported live-market, fair-value, freshness, and alert API.
- `backend/tests/test_sharp_intelligence_api.py` (conditional, new) - P5B freshness, support, provenance, book-context, and alert tests.
- `frontend/app/live-intelligence/page.tsx` (conditional, new) - P5B live market list and state handling.
- `frontend/app/live-intelligence/[marketId]/page.tsx` (conditional, new) - P5B market detail and evidence context.
- `frontend/components/LiveFairValue.tsx` (conditional, new) - P5B venue/model/blend/gap/book/freshness view.
- `frontend/components/EdgeAlertSettings.tsx` (conditional, new) - P5B in-product threshold and reset configuration.
- `frontend/components/__tests__/liveFairValue.test.tsx` (conditional, new) - P5B UI and stale/unresolved-state tests.
- `backend/app/api/markets.py` and `frontend/app/embed/[matchId]/page.tsx` - Verify that existing `/v1` and `/embed` consumers remain compatible; no bespoke partner feed is required.

### Automation and full-suite verification

- `.github/workflows/market-intel.yml` - Keep the legacy snapshot path during shadow operation; retire or repurpose only after a separately verified cutover.
- `.github/workflows/refresh.yml` - Apply additive migrations before dependent production code.
- `.github/workflows/ci.yml` - Add focused test jobs only if the normal suite does not exercise worker/streaming code.
- `Makefile` - Include new Python tests in the existing full-suite path where necessary.

### Notes

- All adapter unit tests must use stored fixtures and must not call live venue APIs.
- Use live venue calls only for explicit P0/P2b verification and save sanitized evidence without credentials or auth headers.
- Run focused Python tests while developing, then run `.venv/bin/python -m pytest` and `make test` before a phase is declared complete.
- Run frontend tests with `cd frontend && npm run typecheck && npm run lint && npm test`; include a production build for public/P5 surfaces.
- `market_odds_snapshots` remains live and untouched until a separate shadow comparison authorizes cutover.
- Provisioning paid infrastructure, applying migrations to production, merging to `main`, and deploying are stop-gate actions: show the actual cost/diff/result and obtain explicit owner approval first.
- P5A and P5B are mutually exclusive. After P4, annotate the unselected parent task as `N/A — P4 selected <branch>`; do not implement both.
- As each sub-task is completed, change `- [ ]` to `- [x]` immediately. Do not wait for the parent task to finish.

### Current gate status — 2026-07-27

All safe local implementation and verification possible before live capture is
complete. Disposable PostgreSQL validation, bounded live venue smoke capture,
an exact allowlist plus hard capture ceiling, and merged migration PR #197 are
complete. Production migration remains unapplied pending a separate guarded
`refresh.yml` decision. Remaining unchecked work requires one or more of: a full soccer
weekend or matchday observation window, the precommitted held-out window beginning
2026-10-01, P4 evidence sufficient to select exactly one P5 branch, a PR/CI cycle,
or explicit owner approval for paid infrastructure, production migration, merge,
deployment, and public distribution. The current P4 verdict is `insufficient` and
selects neither P5A nor P5B; implementing either branch now would violate the PRD.

## Tasks

- [x] 0.0 Create and check out a feature branch for the prediction-market intelligence layer
  - [x] 0.1 Confirm the current branch and working-tree state; preserve all unrelated tracked and untracked user changes.
  - [x] 0.2 Create and check out `codex/prediction-market-intelligence-layer` from the intended base branch without resetting or deleting existing work.
  - [x] 0.3 Record the source PRD and design-spec commit/reference in the first implementation PR so later phases can trace their requirements.

- [ ] 1.0 Confirm P0 prerequisites, operational budgets, adapter contracts, and capture configuration
  - [x] 1.1 Read the PRD, source design, `CLAUDE.md`, existing venue adapters, current market-intel workflow, live-fixture detection, and migration rules before changing code.
  - [x] 1.2 Create a phase checklist in `docs/PREDICTION-MARKET-RUNBOOK.md` with P0–P5 entry/exit criteria and identify which steps trigger a stop gate.
  - [x] 1.3 Probe the public venue catalogue APIs and record dated evidence for OQ-1: whether either venue exposes per-match EPL markets.
  - [x] 1.4 Probe live or recently archived venue market shapes and record dated evidence for OQ-3: whether Polymarket quotes remain usable after kickoff.
  - [x] 1.5 Measure catalogue size, endpoint pagination, public rate-limit behavior, order-book payload size, and expected calls per pre-match/in-play cadence for each venue.
  - [x] 1.6 Propose safe configurable defaults for pre-match cadence, in-play cadence, concurrency, order-book depth, retries, and backoff; document how each value can be overridden without a code change.
  - [x] 1.7 Compare raw-payload object-storage options for durability, private access, API compatibility, lifecycle controls, and monthly cost; select one without enabling deletion of normalized ticks.
  - [ ] 1.8 Produce a plain-English cost summary for paid PostgreSQL, the long-lived worker, and raw object storage; stop and obtain explicit owner approval before provisioning any paid resource.
  - [x] 1.9 Define and fixture-test the transport-neutral `VenueMarket`, `Quote`, `Settlement`, and adapter protocol contracts, including UTC timestamps, provenance, nullable source fields, raw-payload references, and validation errors.
  - [x] 1.10 Define the idempotency keys and correction semantics for discovery, ticks, heartbeats, and settlements before writing the migration.

- [x] 2.0 Add the permanent market registry, price-tick, heartbeat, entity, and source-mapping data foundation
  - [x] 2.1 Remove the `RETENTION_DAYS` pruning call and deletion function from `pipeline/market_intel.py`; add a regression test proving old market history is no longer deleted.
  - [x] 2.2 Add SQLAlchemy models for `canonical_entity`, `entity_source_map`, `venue_market`, `venue_price_tick`, and `capture_heartbeat` with UTC timestamps and explicit nullability.
  - [x] 2.3 Enforce unique `(source, source_key)` mappings and unique `(venue, venue_key)` market identities at the database level.
  - [x] 2.4 Constrain `canonical_entity.kind` and `venue_market.mapping_status` to the PRD-supported values; reject invalid states rather than storing free-form typos.
  - [x] 2.5 Give `venue_price_tick` a deterministic duplicate key that supports replay while preserving genuinely distinct venue updates at the same wall-clock time.
  - [x] 2.6 Store normalized quote fields, transport, sequence/cursor when available, in-play/clock state, validation flags, and a raw-payload reference on each tick.
  - [x] 2.7 Model settlement status, settled time/outcome/source, void/cancelled states, and auditable correction metadata on `venue_market` or a supporting audit table.
  - [x] 2.8 Add indexes for venue/time, market/time, mapping-status coverage, unsettled closed markets, and heartbeat-gap queries.
  - [x] 2.9 Design monthly production partitioning for `venue_price_tick`; document local SQLite/test behavior if it cannot use native PostgreSQL partitions.
  - [x] 2.10 Write an additive Alembic migration with a safe downgrade for local testing; do not modify, rename, truncate, or backfill `market_odds_snapshots`.
  - [x] 2.11 Add schema tests for uniqueness, foreign keys, valid statuses, duplicate ticks, UTC handling, settlement corrections, and coexistence with `market_odds_snapshots`.
  - [x] 2.12 Run the migration up/down/up against a disposable database and record the result; do not apply it to production yet.

- [x] 3.0 Build discovery-driven Kalshi and Polymarket adapters with full order-book and settlement capture
  - [x] 3.1 Move or wrap the existing adapter behavior behind `pipeline/ingest/venues/` while keeping current `pipeline.market_intel` imports and fixture tests working during the shadow period.
  - [x] 3.2 Implement Kalshi soccer catalogue/series/event/market discovery with complete pagination and no hardcoded World Cup or EPL series dependency.
  - [x] 3.3 Implement Polymarket soccer catalogue/tag/event/market discovery with complete pagination and no hardcoded World Cup or NRL tag dependency.
  - [x] 3.4 Persist every discovered market's raw title and lifecycle metadata even when the market type is unknown, the title is malformed, or no canonical mapping exists.
  - [x] 3.5 Fetch and return each venue's complete available order-book payload; do not discard the payload after calculating a midpoint.
  - [x] 3.6 Normalize yes bid/ask, last, midpoint, sizes, and configured top-N levels without inventing values for missing or one-sided books.
  - [x] 3.7 Validate probability bounds, timestamp order, crossed books, malformed levels, stale venue timestamps, and impossible sizes; retain rejected raw payloads with a reason.
  - [x] 3.8 Implement closed-market discovery and settlement fetching, including settled, void, cancelled, not-yet-settled, and corrected outcomes.
  - [x] 3.9 Keep network access outside pure parser functions and keep per-market failures from aborting the rest of a venue catalogue.
  - [x] 3.10 Add sanitized fixtures for multi-page catalogues, active/in-play/closed markets, full and one-sided books, malformed payloads, rate limits, voids, and settlement corrections.
  - [x] 3.11 Add network-free adapter tests covering discovery completeness, pagination, normalization, validation, provenance, and settlement states.
  - [x] 3.12 Run compatibility tests proving the legacy intel panel still receives its existing expected data shape during shadow operation.

- [x] 4.0 Build the reliable polling capture worker, raw-payload storage, and operational health reporting
  - [x] 4.1 Add validated worker settings for venue enablement, discovery cadence, pre-match/in-play cadence, concurrency, timeouts, retry limits, backoff, order-book depth, and raw-store location.
  - [x] 4.2 Implement the raw-payload store with deterministic keys, content integrity metadata, private-by-default access, retry behavior, and a local test implementation.
  - [x] 4.3 Implement a worker cycle that discovers markets, upserts the registry, stores raw payloads, writes normalized ticks, fetches settlements, and records a heartbeat.
  - [x] 4.4 Reuse the existing live-fixture state when trustworthy and define an explicit fallback for markets whose venue state and fixture state disagree.
  - [x] 4.5 Implement separate pre-match and in-play polling schedules using the configuration chosen in task 1.6.
  - [x] 4.6 Isolate each venue with independent timeouts, bounded exponential backoff plus jitter, and error accounting so one venue cannot stop the other.
  - [x] 4.7 Make discovery, capture, raw writes, settlement retries, and worker restarts idempotent using the keys defined in task 1.10.
  - [x] 4.8 Revisit closed-but-unsettled markets until they settle or become void/cancelled; expose aged exceptions instead of retrying silently forever.
  - [x] 4.9 Write one heartbeat per worker/venue cycle with intended cadence, markets seen, success/error counts, retry/rate-limit counts, and cycle duration.
  - [x] 4.10 Add graceful shutdown and restart behavior that finishes or safely abandons an in-flight transaction without corrupting capture state.
  - [x] 4.11 Implement `pipeline.report_capture_health` to report discovered markets, intended versus observed ticks, heartbeat gaps, adapter errors, rate limits, raw-payload failures, and settlement exceptions by venue/time range.
  - [x] 4.12 Add structured logs with venue, venue key, cycle, retry, and error category while redacting credentials and authorization headers.
  - [x] 4.13 Add deterministic worker tests for success, partial venue failure, total failure, malformed data, duplicate delivery, restart, backoff, raw-store outage, and settlement correction.
  - [x] 4.14 Add a worker Dockerfile/process command and local run instructions; do not provision or deploy the paid worker in this task.

- [ ] 5.0 Validate P0 on a full soccer weekend and complete the guarded production cutover
  - [x] 5.1 Run the new migration and worker against a disposable PostgreSQL instance using recorded venue fixtures, then confirm all five tables and raw objects are populated as designed.
  - [x] 5.2 Run a short read-only live API smoke capture for both venues and verify discovery counts, pagination, full-book shapes, clock/in-play states, and settlement states against saved evidence.
  - [ ] 5.3 Run the capture worker through one full weekend of listed soccer fixtures with the legacy market-intel workflow operating in parallel.
    - Prepared `docs/experiments/2026-07-31-p0-weekend-shadow/PLAN.md` with a verified three-market Polymarket fixture, exact bounded configuration, isolated local runtime, and scheduled start/review follow-ups. Kalshi exact match keys remain intentionally unset until listed.
  - [ ] 5.4 Produce the P0 coverage report with achieved cadence, gaps, errors, rate limits, markets discovered, unresolved markets, raw-store failures, and settlement exceptions.
  - [ ] 5.5 Investigate every unexplained heartbeat/tick gap and repeat the acceptance window if the report cannot distinguish a venue outage from a worker failure.
  - [x] 5.6 Force one adapter to fail during a controlled test and verify the other venue continues capturing and heartbeats describe the degraded state.
  - [ ] 5.7 Verify every market closed during the window is settled, void/cancelled, or present in an actionable dated exception report.
  - [ ] 5.8 Measure normalized database growth, raw-payload growth, API calls, CPU, memory, and projected monthly cost; confirm it remains inside the approved budget.
  - [x] 5.9 Run focused tests, the full Python suite, and `make test`; fix regressions without changing the old intel panel's contract.
  - [x] 5.10 Prepare migration-only draft PR #197 and show the additive schema diff plus rollback plan; stop for explicit approval before merging, running `refresh.yml`, or touching production.
  - [ ] 5.11 After approval, merge/apply the migration and verify the five new tables exist before deploying code that uses them.
  - [ ] 5.12 Show the worker service definition, actual monthly cost, secrets/configuration plan, and acceptance evidence; stop for explicit approval before provisioning/deploying the paid worker.
  - [ ] 5.13 After approval, deploy the worker, verify production heartbeats/ticks/raw payloads from both venues, and confirm the existing `market_odds_snapshots` intel panel still works.
  - [ ] 5.14 Record final evidence for OQ-1, OQ-3, configured cadences, and P0 acceptance in the runbook.

- [ ] 6.0 Publish the reproducible P1 World Cup venue-calibration audit
  - [x] 6.1 Re-run the existing 104-match WC26 experiment from frozen inputs and reconcile every number with the source design before building the page.
  - [x] 6.2 Create one deterministic command that regenerates the audit's tables and page-data artifact, including fixed seeds for bootstrap output.
  - [x] 6.3 Include favourite hit rate, log loss, Brier score, paired deltas and CI95, venue divergence distribution, favourite disagreements, and naive consensus results.
  - [x] 6.4 Include sample/overlap rules, de-vigging, grading, snapshot fidelity, post-hoc timing limitations, and the boundary between measured pre-match 1X2 and unmeasured in-play/derived markets.
  - [x] 6.5 State plainly that the model was credibly behind Kalshi pre-kickoff and did not credibly beat Polymarket; do not frame consensus as an accuracy improvement.
  - [x] 6.6 Generate or update a repository evidence card that links the exact command, inputs, outputs, environment, and limitations.
  - [x] 6.7 Build the public venue-calibration page with accessible tables/charts, definitions of the scoring metrics, evidence links, and information-only language.
  - [x] 6.8 Add data-generator and frontend tests that lock the published headline values and required caveats.
  - [x] 6.9 Run the reproducibility command from a clean environment and compare the generated artifact byte-for-byte or field-for-field with the committed page data.
  - [x] 6.10 Run frontend typecheck, lint, tests, and production build; manually check mobile layout and all evidence links.
  - [ ] 6.11 Prepare the public-page diff and stop for approval before merge/deploy; after approval, publish and verify the live page.
  - [ ] 6.12 Record distribution date, channels, visits/referrals, and meaningful responses so the plan's “complete silence” stop condition can be evaluated.

- [ ] 7.0 Build the P2 canonical entity resolver and retroactively resolve captured markets
  - [x] 7.1 Inventory canonical teams, competitions, fixtures, venue source keys, aliases, and outcome patterns already encoded in `market_names.py`, `team_mapping.py`, and their tests.
  - [x] 7.2 Seed canonical team/competition entities and exact verified source mappings with provenance and `verified_at`; do not convert unreviewed fuzzy aliases into verified mappings.
  - [x] 7.3 Implement the resolver contract returning exactly `mapped`, `unmapped`, or `ambiguous`, with canonical event and outcome only for `mapped` results.
  - [x] 7.4 Resolve fixture orientation and contract outcome separately so home/away reversals, draws, spreads, first-half, correct-score, BTTS, and totals cannot be confused with team identity.
  - [x] 7.5 Permit similarity suggestions only in an operator-review path; prevent suggestions from writing production mappings automatically.
  - [x] 7.6 Store ambiguous candidate context and unmapped raw titles/source keys so each state is explainable and actionable.
  - [x] 7.7 Implement an idempotent reconciliation command that re-resolves all or filtered historical `venue_market` rows without rewriting `venue_price_tick` rows.
  - [x] 7.8 Make mapping corrections auditable and re-run affected history while preserving the previous verification/correction record.
  - [x] 7.9 Block unresolved, ambiguous, unsupported, or outcome-incomplete markets from reaching a served fair value.
  - [x] 7.10 Add tests for exact mappings, source-key uniqueness, reversed fixtures, ambiguous candidates, unsupported market types, the Fair Play Award regression, retroactive resolution, and mapping correction.
  - [ ] 7.11 Run reconciliation over P0 data and report mapped/unmapped/ambiguous counts without treating capture coverage as mapping coverage.
  - [x] 7.12 Investigate and document the model's supported competition universe for OQ-4; do not expand the model universe without its own held-out gate.

- [ ] 8.0 Build the P2 coverage dashboard and safely retire duplicate legacy name-mapping logic
  - [x] 8.1 Define coverage calculations for registry discovery, intended/observed capture windows, mapping status, raw-payload integrity, and settlement completeness.
  - [x] 8.2 Add fail-closed internal API/report queries for coverage by venue, competition, market type, status, and time range.
  - [x] 8.3 Add unresolved-market drill-down with raw title, source key, first/last seen, candidate context, and a safe link or command for operator review.
  - [x] 8.4 Choose an internal dashboard access method that never ships `RECOMPUTE_TOKEN` or another operations secret to browser JavaScript; document the decision.
  - [x] 8.5 N/A — CLI and server-to-server internal API selected; no browser dashboard or browser-held operations secret.
  - [x] 8.6 Add API/report and optional frontend tests for filters, zero denominators, UTC boundaries, gaps spanning partitions, stale heartbeats, and unresolved drill-down.
  - [ ] 8.7 Convert existing required mappings into new resolver fixtures and run parity comparisons against legacy `market_names.py` and `team_mapping.py` behavior.
  - [ ] 8.8 Resolve every parity difference explicitly as a desired correction, unsupported legacy guess, or missing verified mapping.
  - [ ] 8.9 Remove legacy mapping logic from the new capture/resolution path only after parity and zero-silent-skip tests pass; keep compatibility wrappers if other live paths still import it.
  - [ ] 8.10 Run the P2 acceptance report: every registry market has one resolution state, coverage is queryable, retroactive mapping works, and a seeded ambiguity cannot be served.
  - [x] 8.11 Update the runbook with mapping verification, correction, reconciliation, dashboard access, and gap-triage procedures.

- [ ] 9.0 Add and validate the P2b venue-streaming transport with reconnect, recovery, and polling fallback
  - [x] 9.1 Confirm and document which venues provide supported market-data streams, authentication needs, subscription limits, sequence/cursor semantics, and history/backfill endpoints.
  - [x] 9.2 Define a transport-neutral stream interface whose updates enter the same raw-store and normalized-tick write path as polling.
  - [ ] 9.3 Implement venue stream authentication/subscription only where supported; keep unsupported venues explicitly on polling.
  - [x] 9.4 Tag every tick as polling, streaming, or recovery/backfill and preserve venue sequence/cursor metadata when available.
  - [ ] 9.5 Implement connection health, application heartbeats, bounded reconnect backoff, clean shutdown, and resubscription to the current discovered market set.
  - [x] 9.6 Deduplicate replayed updates, detect out-of-order events and sequence gaps, and prevent stale events from replacing newer logical state.
  - [x] 9.7 Backfill reconnect gaps through a supported venue endpoint; otherwise record an explicit permanent gap with its cause and interval.
  - [x] 9.8 Fall back to venue-safe polling after a stream failure and avoid double-counting simultaneous stream/poll observations.
  - [ ] 9.9 Add deterministic stream tests using recorded message sequences for disconnect, reconnect, resubscribe, duplicate, out-of-order, missing sequence, backfill, and polling fallback.
  - [x] 9.10 Build the parallel-control report comparing stream updates with polling coverage, timestamps, missing updates, and latency.
  - [ ] 9.11 Run streaming beside polling for a full matchday and force at least one controlled disconnect/reconnect.
  - [ ] 9.12 Record P2b acceptance evidence: unattended operation, recovery outcome, unexplained gaps, observed per-update resolution, and latency.
  - [x] 9.13 If P2b threatens P3 delivery, leave polling as the supported transport, document the remaining gap, and prioritize task 10.

- [ ] 10.0 Build and run the P3 in-play benchmark by venue, market type, and match horizon
  - [x] 10.1 Define the benchmark population, held-out cutoff, match-state alignment rule, precommitted exclusions, minimum data-quality checks, and deterministic bootstrap seed before examining results.
  - [x] 10.2 Build query/loader code that joins settled venue markets and ticks to verified canonical fixtures/outcomes and the corresponding pure-model ledger entries.
  - [x] 10.3 Reject materially mismatched observations, including different score/card states, stale quotes, unsupported outcomes, unresolved mappings, and post-settlement ticks; report each exclusion count.
  - [x] 10.4 Assign comparable observations to the PRD horizon buckets, with explicit boundary tests for 15, 30, 45, halftime, 60, 75, and 90 minutes.
  - [x] 10.5 Keep Kalshi and Polymarket results separate and keep 1X2, spread, first-half, correct-score, BTTS, and totals separate unless a precommitted transformation makes them directly comparable.
  - [x] 10.6 Calculate model and venue log loss, Brier score, calibration diagnostics, paired model-minus-venue loss, per-match win rate, sample matches, paired ticks, and coverage.
  - [x] 10.7 Implement bootstrap confidence intervals by resampling matches and carrying all selected ticks from each sampled match together; never resample ticks as independent units.
  - [x] 10.8 Add tests using synthetic correlated ticks that would falsely appear significant under tick bootstrap but remain honest under match-clustered bootstrap.
  - [x] 10.9 Add tests for state alignment, horizon boundaries, venue/market separation, score outcomes, binary outcomes, exclusions, deterministic output, and empty/insufficient samples.
  - [x] 10.10 Create a CLI that emits a human-readable report, machine-readable results, exclusion/coverage tables, and an evidence-card skeleton from one command.
  - [ ] 10.11 Run the benchmark on accrued held-out data and generate an evidence card under `docs/experiments/<date>-inplay-market-benchmark/`.
  - [x] 10.12 Report insufficient samples as insufficient rather than pooling incompatible data or changing the precommitted buckets after seeing results.
  - [ ] 10.13 Answer OQ-2 with observed liquidity/spread/coverage by derived market type and OQ-4 with honest model-coverage limits.
  - [ ] 10.14 Peer-check or independently reproduce the evidence card's sample, metrics, CI95, exclusions, and command before P4.

- [ ] 11.0 Run and publish the P4 evidence gate, preserve the pure-model ledger, and select the P5 branch
  - [ ] 11.1 Freeze the held-out dataset identifier, comparison venue(s), primary market type/horizon claim, code revision, and gate rule before the final run.
  - [ ] 11.2 Run the P4 command from a clean environment and classify the result as `beating` only if the paired model-minus-market log-loss CI95 is entirely below zero.
  - [ ] 11.3 Classify a CI touching/crossing zero as `inconclusive` and a CI entirely above zero as `beaten`; route both to P5A.
  - [ ] 11.4 Record the result, including a loss or inconclusive result, in `docs/MODEL-EXPERIMENTS.md` and link the immutable evidence card.
  - [ ] 11.5 Publish the same sample, metrics, intervals, exclusions, and caveats regardless of which verdict is returned.
  - [x] 11.6 Remove `W_ODDS_CAP = 0.5` and validate blend weights across the full inclusive `[0,1]` range while rejecting values outside it.
  - [x] 11.7 Extend the held-out blend search to `[0,1]`; keep promotion blocked until the shadow ledger beats production on log loss over at least 30 scored pairs.
  - [x] 11.8 Add/extend tests proving pure-model rows remain unblended, blended shadow/served rows are separately identified, and no public reader mistakes one ledger for the other.
  - [ ] 11.9 If a blend is eligible, prepare its exact parameter diff, shadow record, and rollback; stop for approval before using `--ship`, merging, or deploying it.
  - [ ] 11.10 Create a dated branch-decision record naming `P5A` or `P5B`, the gate evidence, and any early-refutation condition that affected the choice.
  - [ ] 11.11 Mark the unselected P5 parent task `N/A — P4 selected <branch>` and do not implement its sub-tasks.

- [ ] 12.0 If the no-edge branch is selected, build and validate the P5A trader analytics and CLV product
  - [ ] 12.1 Confirm the P4 record selects P5A before beginning; otherwise mark this parent `N/A — P4 selected P5B`.
  - [ ] 12.2 Define the generic CSV contract for venue, venue market key, side/outcome, execution time, execution price, and size, including timezone, numeric, duplicate, and row-error rules.
  - [ ] 12.3 Add additive private fill/import models keyed to `AppUser`, with original row provenance, resolution status, and derived fields separated from user-supplied values.
  - [ ] 12.4 Implement a streaming/bounded CSV parser that validates every row, reports row-specific errors, and never silently drops or partially guesses a fill.
  - [ ] 12.5 Resolve fills only through exact venue keys and verified canonical outcomes; leave unmatched or ambiguous fills visible and excluded from aggregates.
  - [ ] 12.6 Define pre-close reference selection and settlement reference rules, including missing/stale reference behavior and venue correction handling.
  - [ ] 12.7 Implement side-aware CLV calculations for yes/no and multi-outcome contracts and verify them against hand-calculated fixtures.
  - [ ] 12.8 Implement authenticated APIs for import preview, confirmed import, fill history, unresolved rows, aggregate CLV filters, and settlement results.
  - [ ] 12.9 Enforce row ownership on every read/write and ensure one user's fills cannot enter another user's response, cache key, aggregate, log, or public evidence.
  - [ ] 12.10 Implement leak summaries by venue, competition, market type, side, phase, and time period with displayed samples and a precommitted minimum before labeling a segment meaningful.
  - [ ] 12.11 Build the private import and analytics UI with preview/errors, unresolved states, filterable history, labeled reference prices, CLV definitions, and information-only language.
  - [ ] 12.12 Add backend, parser, privacy, and frontend tests for valid/invalid imports, duplicates, ownership, exact resolution, missing references, side direction, filters, noisy small samples, and empty states.
  - [ ] 12.13 Run the P5A acceptance fixture: valid rows import, invalid rows are reported, unresolved rows remain actionable, and aggregate results match hand calculations.
  - [ ] 12.14 Complete privacy/security review and manual multi-user testing before any production rollout.

- [ ] 13.0 If the model-beating branch is selected, build and validate the P5B sharp in-play intelligence product
  - [ ] 13.1 Confirm the P4 record selects P5B before beginning; otherwise mark this parent `N/A — P4 selected P5A`.
  - [ ] 13.2 Define supported venue/competition/market combinations from verified mappings, compatible model outputs, liquidity context, and the held-out evidence scope.
  - [ ] 13.3 Build a read model joining the latest fresh venue tick, pure-model ledger value, promoted served blend, canonical fixture/outcome, match state, and evidence version without mutating source ledgers.
  - [ ] 13.4 Calculate and label model-versus-venue and blend-versus-venue gaps; expose venue, capture transport, quote time, model-state time, and traceable source identifiers.
  - [ ] 13.5 Add configurable freshness limits and suppress fair values/edges for stale model state, stale venue quotes, disconnected feeds without a fresh fallback, unresolved mappings, or unsupported outcomes.
  - [ ] 13.6 Include bid/ask spread, top-of-book depth, and available sizes; never label a midpoint or displayed gap as a guaranteed executable price.
  - [ ] 13.7 Add authenticated user alert preferences for supported markets, threshold, and reset/hysteresis settings; keep alerts in-product only.
  - [ ] 13.8 Deduplicate alerts until an edge resets below its threshold or materially changes; persist enough state to avoid duplicate alerts across process restarts.
  - [ ] 13.9 Build read APIs for supported live fixtures/markets and authenticated APIs for alert preferences/history with explicit unsupported, stale, unmapped, ambiguous, closed, and settled states.
  - [ ] 13.10 Build responsive live-list and market-detail surfaces showing venue price, pure model, served blend, gaps, clock, freshness, book context, and applicable benchmark evidence.
  - [ ] 13.11 Add backend and frontend tests for ledger joins, support rules, freshness boundaries, stale suppression, provenance, book context, threshold/reset, deduplication, restart, and every required UI state.
  - [ ] 13.12 Run a full live-fixture acceptance test and trace each displayed probability back to its venue tick, raw payload, model ledger entry, blend version, and match state.
  - [ ] 13.13 Verify the product cannot place orders, store trading credentials, or send outbound alerts, and that copy does not promise returns or financial advice.

- [ ] 14.0 Complete cross-phase security, reliability, documentation, test, and release verification
  - [x] 14.1 Review secrets, structured logs, raw payloads, internal APIs, P5 user data, cache keys, and public artifacts for credential or private-data leakage.
  - [x] 14.2 Verify every public/internal endpoint has the intended auth, cache-control, rate-limit, CORS/origin, and error behavior; internal endpoints must fail closed when their secret/config is absent.
  - [x] 14.3 Verify `market_odds_snapshots`, the existing intel panel, `/v1`, and `/embed` remain compatible unless a separately approved shadow cutover has passed.
  - [ ] 14.4 Review tick partitioning, query plans, indexes, raw-object growth, worker CPU/memory, API calls, and actual monthly cost using production-like volumes.
  - [ ] 14.5 Exercise worker crash/restart, venue outage, database outage, raw-store outage, stream disconnect, missed sequence, settlement correction, and rollback runbooks in a non-production environment.
  - [x] 14.6 Update `docs/PREDICTION-MARKET-RUNBOOK.md`, `docs/RELIABILITY.md`, architecture/data-flow documentation, configuration examples, and evidence links to match the shipped branch.
  - [x] 14.7 Run all focused adapter, worker, resolver, API, benchmark, and frontend tests.
  - [x] 14.8 Run `.venv/bin/python -m pytest`, frontend typecheck/lint/tests/build, and `make test`; record exact pass/fail output and resolve all in-scope failures.
  - [ ] 14.9 Perform manual QA for the selected P5 branch at mobile and desktop widths, including fresh, loading, empty, degraded, stale, unmapped, ambiguous, closed, and settled states.
  - [x] 14.10 Re-run the relevant phase acceptance report/evidence command from a clean environment and verify committed/generated artifacts are reproducible.
  - [ ] 14.11 Prepare the final PR with phase scope, migrations, cost impact, evidence, security notes, test output, rollback, and any deferred open questions; watch CI to green.
  - [ ] 14.12 Stop for explicit owner approval before merging to `main`, applying any remaining production migration, provisioning paid services, or deploying.
  - [ ] 14.13 After approval, complete the guarded merge/deploy sequence, verify `/api/health`, worker heartbeats, capture freshness, selected P5 behavior, and existing consumer/API/embed behavior in production.
  - [x] 14.14 Update this task file immediately with completed boxes; P5 selection and production verification remain explicitly deferred because the held-out window has not begun and no deployment approval exists.
