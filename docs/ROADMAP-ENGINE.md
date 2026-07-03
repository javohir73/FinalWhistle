# FinalWhistle → Prediction Engine: Phased Technical Roadmap

> Strategy: stop being a World Cup app, become a football prediction engine.
> The single question that decides this product's value: **do we beat the closing line?**
> Everything below is sequenced to answer that question with verifiable evidence,
> while building the assets that are valuable *either way* (track record, coverage,
> explainability, in-play).

## The fork (decision framework)

| Outcome after ~1 season of verified data | Path |
|---|---|
| Model ≥ market on held-out log-loss vs de-vigged closing odds | **Edge path**: trading syndicates, quant partnerships, acquisition. Do not license the edge cheaply. |
| Model < market (expected default) | **Product path**: explainable prediction & engagement layer — B2B API for affiliates, free-to-play, white-label platforms. Sell transparency, coverage, reliability — not alpha. |

Both paths are funded by the same roadmap. The fork is taken at Phase 4, not before.

---

## Phase 0 — Protect & measure (now)

*Goal: stop leaking value; make the market the benchmark.*

- [x] **Repo goes private / re-license.** Apache 2.0 + public repo means the entire engine is free to every prospect. Blocker for any commercial path.
- [x] **Closing-odds benchmark harness** (`pipeline/run_market_benchmark.py`, `ml/evaluation/market_benchmark.py`): model probabilities vs de-vigged closing-odds implied probabilities. Log-loss, Brier, accuracy, per-match paired diffs, bootstrap CI. Two modes:
  - historical CSV (WC 2018/2022 odds),
  - live DB (WC26 `Odds` snapshots vs stored `Prediction` rows).
- [x] **Immutable prediction log.** Every prediction timestamped pre-kickoff next to the market snapshot — the writer is append-only and frozen at kickoff (a guard refuses any post-kickoff append; regression-tested). The WC26 window (ends Jul 19, 2026) is a once-in-4-years verified record — page one of the track record forever.
- [ ] Publish the benchmark result on the methodology page, whatever it says. *(Publish surface shipped — methodology-page section + reproducible `--emit-json` path; renders a "pending" state until the first `--live`/`--csv` run produces a number.)*

**Exit criterion:** a reproducible number for "model vs market" on ≥100 matches.

## Phase 1 — Generalize to club football (months 0–3)

*Goal: from 104 matches every 4 years to thousands per year.*

- [ ] Entity layer: extend `team_mapping` to clubs + leagues (source-agnostic canonical IDs).
- [ ] Ingestion: club fixtures/results via existing API-Football path; historical club results + closing odds via football-data.co.uk CSVs. *(Historical CSV ingestion shipped — `pipeline/ingest/football_data.py`, prefers CLOSING-odds columns; live API-Football club path deferred.)*
- [x] Ratings: club Elo replay via `replay_with_prematch` (leak-free, replayed oldest-first); promotion/relegation + cross-league priors deferred to Phase 2.
- [ ] Launch with 2–3 leagues for the 2026-27 season (kicks off mid-August — natural deadline).
- [x] Benchmark harness runs per league; results logged, never edited. *(Offline runner shipped — `pipeline/run_club_benchmark.py` + `--emit-json`, reuses the Phase-0 closing-line benchmark; weekly live automation deferred to the 2026-27 season.)*

**Exit criterion:** daily automated predictions + market benchmark for ≥2 leagues.

## Phase 2 — Market surface (months 3–9)

*Goal: price what B2B buyers actually consume.*

- [x] Derived markets from the existing scoreline grid (near-free): totals O/U (all lines), BTTS, Asian handicap, correct score, double chance. *(Shipped — `ml/models/markets.py`, pure grid math with push/half/quarter Asian-handicap handling.)*
- [ ] Calibration + benchmark per market, not just 1X2 (`Odds` already captures OU 2.5). *(2-way benchmark infra shipped — `benchmark_binary`/`devig2`/`ou25_label`; per-market calibration fitting + live numbers deferred until matched O/U closing odds accumulate.)*
- [ ] Player props (goalscorer likelihoods — extends `ml/models/goalscorers.py`): needs lineup/minutes modeling. Higher effort, high B2B value. *(Deferred: needs lineup/minutes data.)*
- [x] Versioned public API: `/v1/markets/{match}` with model version, probabilities, explanation payload, calibration metadata. *(Shipped — reads the frozen prediction; additive, WC26 routes untouched.)*

**Exit criterion:** ≥5 market types benchmarked vs market prices for a full half-season.

## Phase 3 — In-play engine (months 6–12)

*Goal: the hardest moat. Live pricing is where B2B willingness-to-pay concentrates.*

- [x] Upgrade `live_winprob` to a full in-play scoreline model (time-decayed Poisson re-pricing on score/red-card/minute state; later xG-flow features). *(Shipped — `ml/models/live_grid.py` + `live_markets.py`; the live 1X2 bar reads the same shared grid, proven bit-identical. xG-flow features deferred.)*
- [x] Latency budget: state change → new price in < 5s. Measure and publish. *(Measured 0.19 ms mean / 0.36 ms worst per re-price — `test_live_latency.py`; documented in `docs/RELIABILITY.md`.)*
- [x] Reliability engineering: uptime SLOs, feed-failure fallbacks (self-healing live state already exists — formalize it). *(Formalized in `docs/RELIABILITY.md`: SLOs + the existing freshness guard / minute estimation / chain retry / cache invalidation.)*
- [ ] Benchmark vs in-play market snapshots where obtainable. *(Blocked: no in-play odds feed on free/available tiers — see `docs/RELIABILITY.md`; closing-line benchmark stands in until a live feed is licensed.)*

**Exit criterion:** live 1X2 + totals repricing across a full match day without manual intervention.

## Phase 4 — ML ceiling + the fork (months 9–18)

*Goal: raise accuracy to its ceiling, then decide the business.*

- [ ] Feature-rich challengers via the existing gated-challenger framework (`experiment_model_eval`): gradient boosting on xG, lineups/availability, schedule congestion, market-derived features. Ship only on beating champion on held-out log-loss (keep the gate).
- [ ] A full season of immutable model-vs-close records across leagues and markets.
- [ ] **Take the fork** (see table above) with evidence, not opinion.
- [ ] Product-path prep in parallel: white-label widget kit (the "why this prediction" layer is the differentiator no feed vendor offers), sandbox API keys, pricing tiers, B2B licensing review (UKGC/MGA where required; content/F2P deals typically exempt — get counsel).

**Exit criterion:** signed pilot (product path) or verified positive CLV/log-loss edge (edge path).

---

## Standing rules

1. **The market is the only baseline that matters.** Favorite-rate baselines stay in CI, but every model change reports vs closing line.
2. **The prediction log is append-only.** No retro-edits, ever. Credibility is the product.
3. **Challengers ship through the gate or not at all** — beating the champion on held-out data, never in-sample.
4. **Explainability is a first-class output**, maintained for every new market and model. It survives both forks.

## Immediate next actions

1. Take the GitHub repo private. — **done** (private as of 2026-07-03).
2. Run `pipeline/run_market_benchmark.py --live` after each WC26 match day; archive the output.
3. Source WC 2018/2022 closing-odds CSVs and run the historical benchmark.
4. Pick the first two club leagues for Phase 1.
