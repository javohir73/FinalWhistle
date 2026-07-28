# PRD: Prediction-Market Intelligence Layer

**Status:** Draft for owner review  
**Date:** 2026-07-26  
**Owner:** pete@degail.com  
**Source design:**
[`docs/superpowers/specs/2026-07-25-prediction-market-intelligence-layer-design.md`](../docs/superpowers/specs/2026-07-25-prediction-market-intelligence-layer-design.md)  
**Scope:** P0–P5, from permanent market-data capture through the evidence-gated
product fork  
**Target reader:** A junior developer working in this repository

---

## 1. Introduction / Overview

FinalWhistle will become an **intelligence layer over football event-contract
markets**: a venue-independent product that captures market prices, explains how
they move, audits their accuracy, and compares them with an independently maintained
football model.

The product will not operate an exchange. It will not hold funds, match orders,
resolve contracts, or initially provide a monetisation rail. Its first commercial
hypothesis is that prosumer and sharp football traders value an auditable in-play
fair price and the evidence behind it.

This direction is based on three measured facts:

1. FinalWhistle's model did not beat Kalshi or Polymarket before kickoff on the
   measured 2026 World Cup sample.
2. Liquid pre-match 1X2 prices on the two venues were too close for a useful
   cross-venue arbitrage product.
3. The repository already contains a fast live scoreline-pricing engine, but it has
   never been benchmarked against a captured in-play market history.

The immediate problem is therefore **missing data, not missing model code**. Every
uncaptured market update is permanently lost. P0 must begin capturing all soccer
markets without waiting for perfect entity mapping. Later phases add reliable
mapping, higher-resolution streaming, an in-play benchmark, and a published gate.

The final product is deliberately conditional on the evidence:

- If the model credibly beats the in-play market, FinalWhistle ships a sharp tier
  with in-play fair values and edge context.
- If it does not, FinalWhistle ships a trader analytics/closing-line-value product
  that helps users audit their own decisions without claiming a model edge.

**Goal:** By the end of Q4 2026, own a permanent and auditable football market-price
history, publish the pre-match venue audit, and produce a statistically honest
answer about the model's in-play performance. In Q1 2027, use that answer to build
the correct P5 product branch.

---

## 2. Definitions

- **Venue:** An external event-contract market, initially Kalshi or Polymarket.
- **Venue market:** One contract listed by a venue, identified by the venue's own
  stable key.
- **Canonical entity:** FinalWhistle's internal identity for a team or competition.
- **Canonical event:** FinalWhistle's internal identity for a fixture or other
  event to which a venue market may map.
- **Tick:** One timestamped observation of a venue market's price and order book.
- **Settlement:** The venue's final outcome for a closed contract.
- **Pure-model price:** A probability generated only from FinalWhistle's model.
- **Venue price:** A probability implied by a captured market quote.
- **Served fair value:** A fitted blend of the pure model and venue price. The blend
  weight is selected on held-out data and may range from 0 to 1.
- **Evidence card:** A reproducible experiment report stored under
  `docs/experiments/<date>-<topic>/EVIDENCE-CARD.md`.
- **Coverage:** The measured proportion of expected markets or capture windows for
  which usable data exists. Coverage must be reported, never assumed.
- **CLV:** Closing-line value, or the difference between a user's execution price and
  a defined later reference price such as the pre-close market price.

---

## 3. Goals

1. Capture every soccer market discovered on Kalshi and Polymarket from the P0
   cutover onward, subject to documented venue availability and rate limits.
2. Retain normalized ticks permanently and retain lossless raw order-book payloads
   in object storage so future analyses can be reproduced.
3. Make capture gaps, adapter errors, settlement gaps, and entity-mapping coverage
   measurable by venue, competition, and time window.
4. Publish a reproducible pre-match calibration audit using the existing 2026 World
   Cup sample.
5. Replace name guessing with an explicit, auditable entity-resolution system that
   permits `mapped`, `unmapped`, and `ambiguous` states and supports retroactive
   resolution.
6. Upgrade in-play capture from polling to venue-supported streaming without
   changing downstream storage or analysis contracts.
7. Benchmark the pure model against each venue by in-play match phase using paired
   scoring and match-clustered uncertainty estimates.
8. Preserve a permanent, unblended pure-model ledger regardless of which served
   blend is promoted.
9. Publish the in-play result whether it is positive, negative, or inconclusive.
10. Build exactly one evidence-selected P5 product branch: sharp in-play
    intelligence if the model wins, or trader/CLV analytics if it does not.
11. Keep the system operable by one owner working approximately 10–15 hours per
    week and within a $100–500/month infrastructure budget.

---

## 4. User Stories

### 4.1 Prosumer or sharp football trader

- As a trader, I want to see the current market price, pure-model price, served fair
  value, and their gaps so I can understand rather than blindly trust a number.
- As a trader, I want prices labeled with venue, market, match state, and freshness
  so I know whether the comparison is still actionable.
- As a trader, I want evidence showing how the model performed against each venue at
  comparable in-play moments so I can judge its credibility.
- As a trader, if the model has no demonstrated edge, I want to import my fills and
  measure my own closing-line value and recurring mistakes.
- As a trader, if the model has a demonstrated edge, I want timely in-product alerts
  when the market and fair value diverge by a configured amount.

### 4.2 Research reader

- As a reader, I want a public venue-calibration audit with clear methods, sample
  sizes, limitations, and reproducible commands so I can verify its claims.
- As a reader, I want positive and negative model experiments published under the
  same rules so I can trust that weak results were not hidden.

### 4.3 Operator

- As the operator, I want new soccer catalogues and competitions discovered without
  code changes so coverage is not dependent on a hardcoded league list.
- As the operator, I want one venue's timeout or rate limit to leave the other venue
  running.
- As the operator, I want heartbeats and coverage reports to expose missing windows
  before they become unrecoverable data loss.
- As the operator, I want unmapped markets stored for later review rather than
  silently discarded.
- As the operator, I want a newly verified mapping to re-resolve historical captures
  without refetching market data.

### 4.4 B2B media consumer

- As a media partner, I want existing `/v1` and `/embed` surfaces to reuse the same
  audited pricing engine without requiring a bespoke feed.

---

## 5. Functional Requirements

### 5.1 Cross-phase requirements

1. **FR-001 — Venue independence:** The system must preserve venue-specific keys,
   timestamps, raw titles, quotes, and settlements. It must not overwrite one
   venue's observation with another venue's observation.
2. **FR-002 — Independent ledgers:** The system must keep the pure-model ledger
   separate from market-derived and blended prices. A served blend must never be
   written back as a pure-model prediction.
3. **FR-003 — UTC timestamps:** All persisted observation, venue, fixture, and
   settlement times must use UTC. User-facing surfaces may localize them.
4. **FR-004 — Provenance:** Every displayed or analyzed price must be traceable to a
   venue market, capture time, capture transport, and raw source payload.
5. **FR-005 — No silent skips:** A discovered market that cannot be parsed, mapped,
   or priced must produce a stored state or an observable error. It must not vanish
   silently.
6. **FR-006 — Configurable cadence:** Polling cadences, retry limits, backoff rules,
   and order-book depth must be configuration rather than hardcoded business logic.
   Safe defaults must be chosen through venue rate-limit and data-volume testing in
   P0.
7. **FR-007 — Venue isolation:** Failure, throttling, or malformed data from one
   venue must not stop capture from any other venue.
8. **FR-008 — Idempotency:** Reprocessing the same discovery, capture, settlement,
   or resolution input must not create duplicate logical records.
9. **FR-009 — Evidence discipline:** Any accuracy claim must report its sample,
   metric, comparator, uncertainty interval, and reproducible command.
10. **FR-010 — Information only:** User-facing language must describe analytics and
    probabilities, not promise returns or present the product as financial advice.

### 5.2 P0 — Stop the bleeding

**Target window:** 2026-07-26 through 2026-08-21  
**Purpose:** Begin permanent, discovery-driven market capture before more live data
is lost.

11. **FR-011 — Stop tick deletion:** The capture path must no longer delete market
    history through the current 14-day retention rule in
    `pipeline/market_intel.py`. New `venue_price_tick` records must be append-only.
12. **FR-012 — Preserve the old path:** P0 must not migrate, rename, truncate, or
    delete `market_odds_snapshots`. The existing intel panel must continue to read
    it until a later, separately verified cutover.
13. **FR-013 — Discover soccer catalogues:** Each venue adapter must enumerate every
    soccer series, tag, event, and market exposed by the venue instead of relying on
    World Cup, EPL, or NRL constants.
14. **FR-014 — Store the market registry:** Every discovered market must be upserted
    into `venue_market` with its venue key, market type, raw title, venue status,
    open/close times when available, first/last seen times, and mapping status.
15. **FR-015 — Default unresolved state:** A market must default to `unmapped` unless
    an exact, verified mapping exists. P0 must not require the P2 entity resolver in
    order to capture it.
16. **FR-016 — Fetch full books:** Venue adapters must return the order-book payload
    already obtained from the venue rather than reducing it to a single midpoint.
17. **FR-017 — Retain raw payloads:** The worker must store a lossless raw venue
    payload in object storage, identified by venue, venue key, and capture time.
18. **FR-018 — Normalize useful quote fields:** Each tick must persist yes bid, yes
    ask, last price, computed midpoint, bid/ask sizes, configured top-of-book depth,
    in-play state, and clock state when provided or derivable. Unavailable fields
    must be stored as null rather than invented.
19. **FR-019 — Price validation:** Normalized probabilities must remain within valid
    bounds; crossed books, stale timestamps, malformed levels, and impossible values
    must be rejected or flagged while preserving the raw payload for diagnosis.
20. **FR-020 — Capture worker:** A long-lived worker must perform discovery, quote
    capture, and settlement capture. It must not perform entity resolution, model
    pricing, benchmarking, or user-facing serving.
21. **FR-021 — Match-state cadence:** The worker must use separate configurable
    cadences for pre-match and in-play markets and reuse the repository's existing
    live-fixture detection where possible.
22. **FR-022 — Backoff:** The worker must honor venue rate-limit responses, retry
    transient failures with bounded exponential backoff and jitter, and record the
    final outcome of each attempt.
23. **FR-023 — Heartbeats:** Each capture cycle must write a `capture_heartbeat` per
    worker and venue containing its time, markets seen, success/error counts, and
    enough detail to calculate missed windows.
24. **FR-024 — Restarts:** After a crash or deployment, the worker must resume from
    persisted state without duplicating ticks or requiring manual cleanup.
25. **FR-025 — Settlement discovery:** The worker must revisit closed markets until
    a settlement is recorded or the venue explicitly marks the market void/cancelled.
26. **FR-026 — Settlement provenance:** Settled time, settled outcome, and source must
    be persisted. A later venue correction must be auditable rather than silently
    replacing the prior value.
27. **FR-027 — Operational report:** P0 must provide a documented query or internal
    report showing markets discovered, ticks captured, heartbeat gaps, errors, and
    unsettled closed markets by venue and time range.
28. **FR-028 — Verify venue assumptions:** During P0 week one, the operator must
    record whether either venue offers per-match EPL contracts and whether
    Polymarket maintains usable liquidity after kickoff.
29. **FR-029 — Additive migrations:** The five new tables must be introduced through
    additive Alembic migrations. Production migrations must run before code that
    depends on them is deployed.

**P0 acceptance criteria**

- One complete weekend of listed soccer fixtures is captured from both venues.
- Every market returned by discovery appears in `venue_market`, including markets
  that are unmapped or malformed.
- Ticks appear at the configured pre-match and in-play cadences, with the measured
  achieved cadence reported by venue.
- Heartbeats show no unexplained capture gaps for the acceptance weekend.
- Every market that closes during the acceptance window is settled, explicitly
  voided/cancelled, or listed in an actionable exception report.
- A forced adapter failure demonstrates that the other venue continues capturing.
- OQ-1 and OQ-3 have dated evidence, even if either answer is negative.

### 5.3 P1 — Publish the venue audit

**Target window:** 2026-08-22 through 2026-09-30  
**Purpose:** Establish credibility and test distribution before building a paid
surface.

30. **FR-030 — Public audit:** The product must publish the 2026 World Cup venue
    calibration study described in the source design as a public, readable page.
31. **FR-031 — Reproducibility:** The audit must name one command that regenerates
    every published table and metric from repository-controlled inputs.
32. **FR-032 — Method disclosure:** The audit must state sample sizes, overlap rules,
    de-vigging method, scoring rules, snapshot limitations, and the difference
    between simultaneous and post-hoc observations.
33. **FR-033 — Required results:** The audit must report at least favourite hit rate,
    average log loss, average Brier score, paired model-versus-venue deltas, CI95,
    cross-venue divergence, favourite disagreements, and the naive consensus result.
34. **FR-034 — Honest framing:** The audit must clearly say that the measured model
    was credibly behind Kalshi pre-kickoff and that the results do not answer the
    in-play or derived-market questions.
35. **FR-035 — Evidence card:** The audit's underlying experiment must have an
    evidence card under `docs/experiments/`.

**P1 acceptance criteria**

- A stranger can read the published audit without repository knowledge.
- A fresh local run of the documented command regenerates the displayed values.
- All claims link to their method and data limitations.
- Basic distribution response is recorded so a complete lack of attention can
  trigger the plan's stated stop condition.

### 5.4 P2 — Entity layer

**Target window:** 2026-09-01 through 2026-10-15  
**Purpose:** Make identity resolution explicit, safe, measurable, and retroactive.

36. **FR-036 — Canonical entities:** The system must maintain canonical team and
    competition identities independently of any venue's names.
37. **FR-037 — Exact source keys:** `entity_source_map` must enforce one mapping per
    `(source, source_key)`. A source key may map to exactly one canonical entity or
    remain unresolved.
38. **FR-038 — Resolution contract:** Resolving a venue market must return exactly
    one status from `mapped`, `unmapped`, or `ambiguous`, plus a canonical event and
    outcome only when the result is `mapped`.
39. **FR-039 — No fuzzy production mapping:** String similarity may assist an
    operator's review, but the production resolver must not automatically map a
    market through fuzzy matching or an unverified guess.
40. **FR-040 — Recorded verification:** Creating or changing a source mapping must
    record who or what verified it and when.
41. **FR-041 — Retroactive resolution:** The resolver must be able to reprocess all
    historical `venue_market` rows after a mapping is added or corrected without
    changing the underlying captured ticks.
42. **FR-042 — Outcome mapping:** Resolution must identify both the canonical event
    and the contract outcome. Team identity alone is insufficient for markets such
    as 1X2, spread, first half, correct score, BTTS, and team totals.
43. **FR-043 — Ambiguity handling:** When more than one exact candidate remains, the
    system must store `ambiguous` and expose it for review. It must not choose the
    first candidate.
44. **FR-044 — Coverage dashboard:** An internal view must show mapped, unmapped, and
    ambiguous counts and percentages by venue, competition, market type, and time
    range, plus capture and settlement gaps.
45. **FR-045 — Drill-down:** The operator must be able to list the raw titles and
    source keys behind each unresolved count so mappings can be corrected.
46. **FR-046 — Legacy retirement:** `pipeline/ingest/market_names.py` and duplicate
    logic in `pipeline/team_mapping.py` may be retired only after parity tests show
    that required existing mappings are represented in the new entity layer.

**P2 acceptance criteria**

- Coverage counts are queryable and visible per venue and competition.
- Every captured market has exactly one current resolution status.
- A new mapping successfully re-resolves older P0 markets without rewriting ticks.
- A deliberately ambiguous fixture remains ambiguous and cannot reach a served
  price.
- There are zero silent skips in the capture-to-registry path.

### 5.5 P2b — Streaming upgrade

**Target window:** 2026-10-15 through 2026-11-30  
**Purpose:** Increase in-play resolution while preserving the P0 storage contract.

47. **FR-047 — Streaming transport:** For each venue that offers a suitable stream,
    the adapter must subscribe to market updates and write through the same
    normalized tick path used by polling.
48. **FR-048 — Transport tag:** Every tick must identify whether it came from
    polling, streaming, or a recovery/backfill operation.
49. **FR-049 — Connection lifecycle:** Streaming adapters must authenticate when
    required, subscribe, resubscribe, send/receive heartbeats, reconnect after
    interruption, and stop cleanly.
50. **FR-050 — Ordering and duplication:** The adapter must use venue sequence
    numbers when available. Duplicate events must be idempotent, and out-of-order or
    missing events must be flagged for recovery.
51. **FR-051 — Recovery:** After reconnecting, the worker must backfill the missing
    interval through a supported venue mechanism or record an explicit permanent
    gap when no backfill is possible.
52. **FR-052 — Polling fallback:** A streaming failure must fall back to the proven
    polling path where rate limits permit, without mixing two observations into one
    logical tick.
53. **FR-053 — Parallel control:** Acceptance testing must run streaming beside a
    polling control so missing updates and timing differences can be measured.

**P2b acceptance criteria**

- Streaming runs unattended for a full matchday on at least one venue and one live
  fixture.
- A forced disconnect demonstrates reconnect, resubscription, and recovery behavior.
- No unexplained tick gap appears relative to the polling control.
- Per-update resolution is demonstrated and its observed latency is reported.
- If capacity conflicts with P3, P3 retains priority and polling remains supported.

### 5.6 P3 — In-play benchmark

**Target window:** 2026-10-01 through 2026-11-30  
**Purpose:** Determine how the pure model compares with each available in-play venue
at comparable match states.

54. **FR-054 — Comparable observations:** The benchmark must pair model and venue
    probabilities using a documented time or match-state alignment rule. It must not
    compare observations from materially different game states.
55. **FR-055 — Horizon buckets:** Results must be reported separately for 0–15,
    15–30, 30–45, halftime, 45–60, 60–75, and 75–90 minute phases, or for a changed
    set of buckets documented before scoring.
56. **FR-056 — Match-level clustering:** Bootstrap resampling must use the match as
    the unit. It must not treat correlated ticks from the same match as independent.
57. **FR-057 — Per-venue comparison:** The benchmark must report paired model-minus-
    venue average log-loss deltas and CI95 separately for Kalshi and Polymarket when
    each venue has sufficient data.
58. **FR-058 — Supporting metrics:** Each report must include sample matches, paired
    ticks, coverage, average log loss, Brier score, and calibration diagnostics for
    both the model and comparator.
59. **FR-059 — Market-type separation:** Results for materially different contracts
    must not be pooled into one headline score. 1X2, spread, first half, correct
    score, BTTS, and totals must be separated or excluded with a stated reason.
60. **FR-060 — Data-quality exclusions:** Every exclusion rule must be defined before
    the scored run and the evidence card must report excluded counts and reasons.
61. **FR-061 — Competition coverage:** The benchmark must report which captured
    competitions the current club-Elo/model universe can price and must not present
    capture coverage as model coverage.
62. **FR-062 — Reproducible evidence:** Each benchmark run must create an evidence
    card using the repository's existing experiment format and a command that
    reproduces the reported values.

**P3 acceptance criteria**

- At least one evidence card reports paired in-play performance by horizon bucket.
- Confidence intervals are match-clustered and reproducible.
- Each venue and market type is reported separately or marked insufficient with its
  actual sample size.
- OQ-2 and OQ-4 are answered to the extent supported by accrued data.

### 5.7 P4 — The evidence gate

**Target window:** Approximately December 2026  
**Purpose:** Select the P5 branch using the precommitted statistical rule.

63. **FR-063 — Gate rule:** A model win requires the relevant paired
    model-minus-market log-loss CI95 to be entirely below zero on held-out in-play
    data. An interval that touches or crosses zero is not a win.
64. **FR-064 — Outcome classes:** The gate must record one of three research results:
    `beating`, `beaten`, or `inconclusive`. Both `beaten` and `inconclusive` select
    the no-edge P5 product branch.
65. **FR-065 — Record losses:** Gate results must be recorded in
    `docs/MODEL-EXPERIMENTS.md` even when the model loses or the sample is
    insufficient.
66. **FR-066 — Publish either answer:** The public result must include the same
    metrics, caveats, and evidence-card link regardless of outcome.
67. **FR-067 — Uncap market weight:** The fitted served blend must be allowed to
    search `w_odds` across the full `[0, 1]` interval. The current belief-based
    `W_ODDS_CAP = 0.5` restriction must not remain.
68. **FR-068 — Preserve promotion gate:** A new blend weight may replace production
    only when the existing shadow ledger beats production on log loss over at least
    30 scored pairs.
69. **FR-069 — Show both legs:** Any later user-facing fair-value surface must show
    the pure-model probability, venue input, served blend, and gaps rather than
    presenting the blend as an independent model output.
70. **FR-070 — Branch record:** The gate artifact must state which P5 branch is
    selected and why. A branch must not be selected from a point estimate alone.

**P4 acceptance criteria**

- The held-out gate produces a reproducible evidence card and a recorded result.
- The result is published even if it refutes the in-play edge thesis.
- The pure-model ledger remains unblended and queryable.
- The selected P5 branch follows FR-063–FR-064 without discretionary relabeling.

### 5.8 P5A — Trader analytics / CLV branch

**Condition:** Selected when P4 is `beaten` or `inconclusive`, or earlier if no
venue offers per-match markets for a competition the model can rate.  
**Target window:** Q1 2027  
**Purpose:** Help traders measure and improve their own process without claiming a
FinalWhistle model edge.

71. **FR-071 — Fill import:** An authenticated user must be able to import a
    documented fill format containing venue, venue market key, side/outcome,
    execution time, execution price, and size. Invalid rows must be rejected with
    row-specific reasons.
72. **FR-072 — Exact fill resolution:** A fill must link through venue keys and the
    verified entity layer. An unresolved fill must remain visible as unresolved and
    must not be guessed from its title.
73. **FR-073 — Reference prices:** The system must calculate each resolved fill's
    result against clearly labeled reference points, including an available
    pre-close price and final settlement. It must not substitute a missing reference
    silently.
74. **FR-074 — CLV calculation:** The product must show the signed difference between
    the user's execution probability and each selected reference probability, with
    direction handled correctly for the traded side.
75. **FR-075 — User history:** Users must be able to review fills and aggregate CLV
    by venue, competition, market type, side, match phase, and time period.
76. **FR-076 — Leak detection:** The system must identify recurring segments where a
    user's CLV is worse than their own baseline, show the sample size, and avoid
    ranking small noisy segments as confident findings.
77. **FR-077 — No edge claim:** The analytics branch must not market the pure model
    as market-beating. Model comparisons may appear only with the published P4
    result and appropriate limitations.
78. **FR-078 — Data isolation:** One user's imported fills and derived analytics must
    not be visible to another user or included in public evidence without explicit
    consent.

**P5A acceptance criteria**

- A fixture CSV imports valid rows, reports invalid rows, and never silently drops a
  row.
- Resolved fills display correct side-aware CLV and settlement results.
- Unresolved fills remain actionable without corrupting aggregates.
- Filters and recurring-leak summaries agree with hand-calculated fixtures.

### 5.9 P5B — Sharp in-play intelligence branch

**Condition:** Selected only when P4 is `beating`.  
**Target window:** Q1 2027  
**Purpose:** Serve auditable in-play fair values and execution context to prosumer
football traders.

79. **FR-079 — Live market view:** For each supported live fixture and market, the
    surface must display the latest venue quote, pure-model price, served fair value,
    model-versus-venue gap, match clock/state, and time since last update.
80. **FR-080 — Supported scope:** Only venue markets with verified entity/outcome
    mappings and a compatible model output may receive a fair value. Other markets
    must show an explicit unsupported or unresolved state.
81. **FR-081 — Staleness guard:** A fair value or edge must be visually suppressed
    when its model state or venue quote exceeds a configured freshness limit.
82. **FR-082 — In-product alerts:** A user must be able to configure an in-product
    edge threshold for supported markets. An alert must state the venue, contract,
    side, market price, fair value, gap, timestamp, and freshness state.
83. **FR-083 — Alert deduplication:** The system must avoid repeating the same alert
    until the edge crosses back below the reset threshold or materially changes.
84. **FR-084 — Execution context:** The surface must include top-of-book depth and
    spread so a probability gap is not presented without available-liquidity
    context.
85. **FR-085 — Evidence link:** Every model-supported surface must link to or
    summarize the applicable held-out benchmark, sample, and last evaluation date.
86. **FR-086 — No execution:** The product must not place orders, hold venue
    credentials for trading, or represent displayed prices as guaranteed executable
    prices.

**P5B acceptance criteria**

- A full live fixture displays synchronized market, model, blend, state, freshness,
  and book context for supported contracts.
- Stale or unresolved data cannot create an active alert.
- Alert threshold, reset, and deduplication behavior pass deterministic tests.
- Displayed probabilities can be traced to captured ticks and model-ledger entries.

### 5.10 Existing and B2B surfaces

87. **FR-087 — Existing application:** P0–P4 must not require a redesign of the
    existing consumer application. It remains a marketing and credibility layer.
88. **FR-088 — Existing interfaces:** Existing `/v1` and `/embed` capabilities may
    expose supported intelligence from the same engine, but this PRD does not add a
    bespoke partner feed or service-level agreement.
89. **FR-089 — Cutover protection:** Any later replacement of the existing intel
    panel's data source must run as a shadow path first and demonstrate equivalent or
    better correctness and availability before cutover.

---

## 6. Non-Goals / Out of Scope

- Running an exchange, matching orders, custodying funds, resolving contracts, or
  holding user trading credentials.
- Cross-venue arbitrage alerts for headline 1X2 markets.
- Trading FinalWhistle's model as a fund or promising returns.
- Treating a naive multi-venue consensus as an accuracy improvement.
- US-facing monetisation at launch. Affiliate, revenue-share, subscription, and
  payment-processing work remain blocked on jurisdiction-specific legal advice.
- Politics, economics, culture, or other event-contract categories.
- New sport models such as NFL, NBA, or MLB.
- A licensed in-play odds feed within the current $100–500/month budget.
- Migrating or deleting `market_odds_snapshots` as part of P0–P4.
- Automatic fuzzy entity matching in production.
- Building P5A and P5B in parallel. Only the branch selected by evidence is in scope.
- Bespoke B2B feeds, partner-specific calculations, or an SLA.
- Outbound email, SMS, push, or chat alerts in this version. P5B alerts are
  in-product until a separate notification scope is approved.
- Implementing billing or monetisation mechanics. P5 defines product capability,
  not a payment rail.

---

## 7. Design Considerations

### 7.1 Product principles

1. **Show provenance:** Prices must always show venue and timestamp.
2. **Show uncertainty:** Evidence pages must show samples and confidence intervals,
   not only point estimates.
3. **Show both legs:** A blended fair value must not hide its model and venue inputs.
4. **Make missingness visible:** `unmapped`, `ambiguous`, `unsupported`, and `stale`
   are designed states, not generic errors.
5. **Do not imply execution:** Market cards must distinguish observed quotes from
   guaranteed fill prices.

### 7.2 Required states for P5 surfaces

- Loading
- Live and fresh
- Pre-match
- Halftime or paused
- Stale model state
- Stale venue quote
- Venue disconnected with polling fallback
- Unsupported market type
- Unmapped market
- Ambiguous mapping
- Closed and awaiting settlement
- Settled

### 7.3 Accessibility and clarity

- Do not rely on green/red alone to communicate positive or negative gaps.
- Show probability values numerically in addition to charts.
- Define log loss, Brier score, CI95, fair value, and CLV in plain language near
  their first user-facing use.
- Freshness must be readable as a time duration, not only an icon.

No new consumer UI is required before P5 except the public P1 audit and internal P2
coverage dashboard.

---

## 8. Technical Considerations

### 8.1 Existing integration points

- Venue adapters: `pipeline/ingest/kalshi.py` and
  `pipeline/ingest/polymarket.py`.
- Legacy name logic to replace in P2: `pipeline/ingest/market_names.py` and
  `pipeline/team_mapping.py`.
- Current capture orchestration and destructive retention rule:
  `pipeline/market_intel.py`.
- Existing live-state detection: `backend/app/live_refresh.py`.
- Existing live pricing: `ml/models/live_grid.py` and
  `ml/models/live_markets.py`.
- Existing benchmark code: `ml/evaluation/market_benchmark.py` and related pipeline
  experiment runners.
- Current blend promotion restriction: `pipeline/promote_blend.py`.
- Existing intel table and API: `market_odds_snapshots` and
  `backend/app/api/intel.py`.
- Migrations: `backend/alembic/versions/`.

These paths are guidance based on the current repository. A developer may refactor
within the component contracts, but must preserve the behavioral requirements and
migration sequencing.

### 8.2 Component contracts

```python
discover_markets(sport: str) -> list[VenueMarket]
fetch_quote(venue_key: str) -> Quote
fetch_settlement(venue_key: str) -> Settlement | None

resolve(venue_market: VenueMarket) -> Resolution
# Resolution.status is mapped, unmapped, or ambiguous.

price(match_state: MatchState) -> Probabilities
```

The capture worker writes market observations and heartbeats only. Entity
resolution, model pricing, benchmarking, and serving must remain separate jobs or
components so capture can continue when downstream code fails.

### 8.3 Required data model

The implementation must add five logical tables without modifying the current live
odds table:

1. `canonical_entity`
   - `id`, `sport`, `kind`, `canonical_name`
   - `kind` initially supports `team` and `competition`.
2. `entity_source_map`
   - `entity_id`, `source`, `source_key`, `confidence`, `verified_at`
   - Unique constraint on `(source, source_key)`.
3. `venue_market`
   - Venue identity, raw title, market type, optional canonical event/outcome,
     mapping status, venue lifecycle, settlement, and first/last-seen fields.
   - Unique constraint on `(venue, venue_key)`.
4. `venue_price_tick`
   - Market foreign key, observation time, normalized quote fields, order-book
     depth, in-play/clock state, transport, and raw-payload reference.
   - Append-only and partitioned by month in production.
5. `capture_heartbeat`
   - Worker, venue, time, markets seen, successes/errors, and cycle metadata.

The exact physical schema may add audit, sequence, and integrity fields required by
FR-001–FR-026. Migrations must remain additive.

### 8.4 Storage

- Keep the narrow normalized tick table queryable in PostgreSQL.
- Partition ticks monthly before volume requires an emergency migration.
- Store raw order-book payloads in object storage; do not force large venue payloads
  into hot relational rows.
- Do not introduce an automatic deletion policy for normalized ticks.
- Measure storage growth and forecast monthly cost before P3.

### 8.5 Reliability and observability

- Log structured venue, market-key, cycle, retry, and error fields without secrets.
- Alerting mechanism selection is implementation work, but missing heartbeat windows
  must be queryable from persisted data even if alert delivery fails.
- Adapter tests must use stored fixtures and remain network-free.
- Capture acceptance tests must cover rate limits, malformed payloads, partial venue
  failure, duplicate delivery, restart, and settlement correction.
- Streaming tests must cover disconnect, resubscription, event duplication,
  out-of-order delivery, and unrecoverable gaps.

### 8.6 Security and legal constraints

- Never expose venue API credentials, raw auth headers, or user fill data in public
  pages or logs.
- Imported P5A files must be treated as private user data and validated before use.
- Provisioning paid PostgreSQL or a worker (estimated $25–35/month) requires a
  plain-English cost summary and explicit owner approval.
- Any payment, affiliate, revenue-share, or US-facing monetisation work requires
  legal review before implementation.

### 8.7 Testing and release gates

- Run the repository's real test suite (`make test`) before claiming a phase is
  complete.
- Model changes must use held-out data and the existing challenger gate.
- Positive and negative experiments must both be recorded.
- Production migrations must be applied through `refresh.yml` before dependent code
  deploys. Migration dispatch and production deployment require the repository stop
  gate.
- P0 must run in shadow with the old intel path; no dependent consumer cutover is
  implied by successful capture.

---

## 9. Delivery Sequence and Dependencies

| Phase | Target | Depends on | Exit artifact |
|---|---|---|---|
| P0 — Stop the bleeding | By 2026-08-21 | Paid infrastructure approval for production operation | Permanent capture plus weekend coverage report |
| P1 — Venue audit | Aug–Sep 2026 | Existing WC26 experiment data | Public audit and reproducible evidence card |
| P2 — Entity layer | Sep–mid-Oct 2026 | P0 registry and raw titles | Resolver plus coverage dashboard |
| P2b — Streaming | Mid-Oct–Nov 2026 | Stable P0 write path; P2 identifiers preferred | Matchday streaming comparison report |
| P3 — In-play benchmark | Oct–Nov 2026 | Sufficient P0 capture; existing live model | In-play evidence card by horizon and venue |
| P4 — Gate | Around Dec 2026 | Held-out P3 result | Published result and recorded branch decision |
| P5A or P5B | Q1 2027 | P4 branch decision, or earlier refutation condition | One validated trader product branch |

P2b and P3 may run in parallel. If solo capacity cannot support both, P3 takes
priority and continues on polling data.

---

## 10. Success Metrics

### 10.1 End-of-Q4 outcome metrics

1. **Matchday capture:** From the accepted P0 cutover onward, 100% of discovered
   soccer markets are represented in the registry. Any missing ticks are quantified
   as explicit gaps rather than treated as absent markets.
2. **Permanent history:** Queryable, append-only pre-match and in-play ticks exist
   with raw-payload provenance and settlement outcomes.
3. **Settlements:** 100% of closed markets are either settled, explicitly
   void/cancelled, or present in a dated exception queue.
4. **Mapping visibility:** 100% of registry markets have one of the three resolution
   states; mapped/unmapped/ambiguous rates are visible by venue and competition.
5. **Public audit:** The P1 venue audit is live and reproducible from one documented
   command.
6. **In-play answer:** At least one held-out, match-clustered evidence card reports
   paired model-versus-venue performance by match phase.
7. **Honest gate:** The P4 result and selected P5 branch are public and recorded,
   including when the result is negative or inconclusive.

### 10.2 Operational metrics to report, not silently assume

- Discovered markets per venue/day.
- Successful tick observations divided by intended observations per venue and match
  phase.
- Median, p90, and p99 observation delay from venue/source time.
- Heartbeat gaps and longest gap per venue/week.
- Adapter errors and rate-limit responses per 1,000 attempts.
- Closed markets awaiting settlement and their age.
- Mapping rates by venue, competition, and market type.
- Tick and raw-payload storage growth per month.
- Streaming updates missed relative to polling control during P2b acceptance.

No universal numeric latency or cadence SLO is invented in this PRD. P0 must measure
venue limits and publish the safe configured values; P2b must publish the improved
streaming resolution.

### 10.3 P5 product metrics

For P5A:

- Valid fill-import success rate and row-level rejection rate.
- Percentage of fills resolved to a verified market/outcome.
- Percentage of resolved fills with an available reference close and settlement.
- Returning users who add new fills in a later week.

For P5B:

- Percentage of supported live minutes with fresh model and venue inputs.
- Median and p95 end-to-end quote-to-surface delay.
- Alerts suppressed because of stale, unresolved, or illiquid inputs.
- Returning users who view supported live fixtures in a later week.

Commercial conversion targets are intentionally deferred until distribution and
legal posture are clearer.

---

## 11. Risks and Required Responses

| Risk | Severity | Required response |
|---|---|---|
| The model is behind in-play too | High | Publish the result and select P5A; do not build the sharp tier. |
| Neither venue lists match markets for competitions the model can rate | High | Use captured coverage evidence, stop the in-play thesis, and select P5A early. |
| Capture cannot operate within the budget or venue limits | High | Re-cost the data thesis before P2; do not quietly add a licensed feed. |
| Distribution remains negligible after P1 | High | Pause product expansion until distribution has an owner and testable plan. |
| Solo capacity is insufficient | High | Keep P0 thin; prioritize P3 over P2b; do not combine both P5 branches. |
| Entity mapping produces a wrong price | Medium | Require exact verified mappings and block ambiguous/unmapped markets from serving. |
| Capture gaps go unnoticed | Medium | Persist heartbeats and expose coverage/gap reports before relying on the dataset. |
| Tick storage exceeds budget | Medium | Use monthly partitions and raw object storage; review measured growth before P3. |
| Venue APIs change or throttle | Medium | Maintain fixture-tested adapters, venue isolation, backoff, and polling fallback. |
| Users mistake analytics for guaranteed execution or advice | Medium | Show provenance, freshness, book depth, and information-only language. |

---

## 12. Open Questions

These questions do not block writing the PRD. Each has a named resolution phase and
must be answered with evidence rather than assumption.

1. **OQ-1 — EPL availability (P0 week one):** Do Kalshi or Polymarket list per-match
   EPL markets once the season begins?
2. **OQ-2 — Derived-market opportunity (P3):** Which spread, first-half, correct
   score, BTTS, and team-total markets have enough liquidity and model support for a
   fair benchmark?
3. **OQ-3 — Polymarket in-play continuity (P0):** Does useful liquidity persist after
   kickoff?
4. **OQ-4 — Model competition coverage (P2/P3):** Which captured club competitions
   can the current club-Elo universe rate honestly, and what expansion is required?
5. **OQ-5 — Legal posture (before P5 monetisation):** Which jurisdictions and
   product language are permissible for subscription or affiliate rails?
6. **OQ-6 — Distribution (ongoing):** Which repeatable channel can reach the initial
   prosumer/sharp audience?
7. **OQ-7 — Safe polling configuration (P0):** What pre-match cadence, in-play
   cadence, book depth, concurrency, and backoff stay within each venue's limits?
8. **OQ-8 — Raw storage choice (before production P0):** Which object store meets
   durability, access-control, and budget needs?
9. **OQ-9 — P5A import scope (after branch selection):** Which venue export formats
   are common enough to support in addition to the documented generic CSV?
10. **OQ-10 — P5 launch access (after branch selection):** Is the selected product
    invite-only, free research preview, or legally approved paid access?

---

## 13. Assumptions Recorded for This PRD

1. The owner selected a single PRD covering all phases, not a P0-only PRD.
2. Exact polling intervals were not selected. They remain configurable and must be
   established through P0 rate-limit and coverage tests.
3. P0 operational health may begin as documented queries or an internal report; P2
   must add an internal coverage dashboard.
4. The existing app remains unchanged through P0–P4 except for the public P1 audit.
5. The paid PostgreSQL/worker budget is not presumed approved merely because it is
   described here. Provisioning remains behind the repository stop gate.
6. P5 product functionality is specified, but payment and outbound notification
   rails are not authorized.

---

## 14. Definition of Done

This PRD is complete only when P0–P4 have produced their required evidence and one,
and only one, P5 branch has met its acceptance criteria. Completing infrastructure
without publishing the gate is not done; publishing the gate without selecting the
corresponding branch is not done; and building the sharp tier without a P4 win is a
failure of the requirements.

