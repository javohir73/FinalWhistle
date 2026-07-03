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

- [ ] **Repo goes private / re-license.** Apache 2.0 + public repo means the entire engine is free to every prospect. Blocker for any commercial path.
- [ ] **Closing-odds benchmark harness** (`pipeline/run_market_benchmark.py`, `ml/evaluation/market_benchmark.py`): model probabilities vs de-vigged closing-odds implied probabilities. Log-loss, Brier, accuracy, per-match paired diffs, bootstrap CI. Two modes:
  - historical CSV (WC 2018/2022 odds),
  - live DB (WC26 `Odds` snapshots vs stored `Prediction` rows).
- [ ] **Immutable prediction log.** Every prediction timestamped pre-kickoff next to the market snapshot. The WC26 window (ends Jul 19, 2026) is a once-in-4-years verified record — page one of the track record forever.
- [ ] Publish the benchmark result on the methodology page, whatever it says.

**Exit criterion:** a reproducible number for "model vs market" on ≥100 matches.

## Phase 1 — Generalize to club football (months 0–3)

*Goal: from 104 matches every 4 years to thousands per year.*

- [ ] Entity layer: extend `team_mapping` to clubs + leagues (source-agnostic canonical IDs).
- [ ] Ingestion: club fixtures/results via existing API-Football path; historical club results + closing odds via football-data.co.uk CSVs (already half-supported in `pipeline/ingest/football_data_odds.py`).
- [ ] Ratings: club Elo replay (promotion/relegation, cross-league priors); reuse `replay_with_prematch`.
- [ ] Launch with 2–3 leagues for the 2026-27 season (kicks off mid-August — natural deadline).
- [ ] Benchmark harness runs weekly per league; results logged, never edited.

**Exit criterion:** daily automated predictions + market benchmark for ≥2 leagues.

## Phase 2 — Market surface (months 3–9)

*Goal: price what B2B buyers actually consume.*

- [ ] Derived markets from the existing scoreline grid (near-free): totals O/U (all lines), BTTS, Asian handicap, correct score, double chance.
- [ ] Calibration + benchmark per market, not just 1X2 (`Odds` already captures OU 2.5).
- [ ] Player props (goalscorer likelihoods — extends `ml/models/goalscorers.py`): needs lineup/minutes modeling. Higher effort, high B2B value.
- [ ] Versioned public API: `/v1/markets/{match}` with model version, probabilities, explanation payload, calibration metadata.

**Exit criterion:** ≥5 market types benchmarked vs market prices for a full half-season.

## Phase 3 — In-play engine (months 6–12)

*Goal: the hardest moat. Live pricing is where B2B willingness-to-pay concentrates.*

- [ ] Upgrade `live_winprob` to a full in-play scoreline model (time-decayed Poisson re-pricing on score/red-card/minute state; later xG-flow features).
- [ ] Latency budget: state change → new price in < 5s. Measure and publish.
- [ ] Reliability engineering: uptime SLOs, feed-failure fallbacks (self-healing live state already exists — formalize it).
- [ ] Benchmark vs in-play market snapshots where obtainable.

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

1. Take the GitHub repo private.
2. Run `pipeline/run_market_benchmark.py --live` after each WC26 match day; archive the output.
3. Source WC 2018/2022 closing-odds CSVs and run the historical benchmark.
4. Pick the first two club leagues for Phase 1.
