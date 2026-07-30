# FinalWhistle vNext architecture

Status: experimental, shadow-only. The served `poisson-elo-v0.5` engine remains
the champion until a separately versioned challenger passes the gates below.

## Objective

vNext turns a match forecast into two independent latent coordinates:

- **strength**: `log(lambda_home / lambda_away)`, which controls the share of
  expected goals assigned to each side;
- **tempo**: `log(lambda_home + lambda_away)`, which controls the expected total
  goals in the match.

They are converted into one normalized Dixon-Coles score grid. W/D/L, exact
scores, totals, team goals and BTTS are all marginals of that grid. A component
may not publish a separate probability triple that disagrees with it.

## Non-negotiable invariants

1. Production is unchanged when `vnext_shadow_spec=None`.
2. Every feature has both an effective time and a known-at time. Both must be at
   or before the forecast cutoff.
3. A result is incorporated only after its forecast is frozen.
4. Strength changes cannot alter expected total goals. Tempo changes cannot
   alter the home/away goal share.
5. Every persisted challenger has a content-addressed model tag of at most 40
   characters.
6. vNext rows are `is_shadow=True` and are never selected by public APIs.
7. Market-free and market-informed forecasts keep separate ledgers.
8. A candidate is promoted only on paired, pre-declared, out-of-sample gates.

## Flow

```text
as-of observations
        |
        v
hierarchical team state ------> strength coordinate
xG / lineup / context --------> bounded latent corrections
market 1X2 -------------------> optional strength evidence
team/league tempo + O/U ------> tempo coordinate
        |
        v
one Dixon-Coles score distribution
        |
        +--> W/D/L
        +--> exact scores
        +--> O/U and team-goal markets
        +--> BTTS
        +--> simulation sampler
```

## Twelve-step implementation map

| Step | Status | Current implementation |
|---|---|---|
| 1. Immutable time-aware data | Foundation implemented | `ml/features/as_of.py`; database-backed observation storage remains future work. |
| 2. Dynamic hierarchical strength | Experimental primitive | `ml/ratings/dynamic_strength.py`; needs fitted historical artifacts before live use. |
| 3. Separate strength and tempo | Implemented | `LatentMatchState` in `ml/models/vnext.py`. |
| 4. Coherent score distribution | Implemented | One normalized grid supplies every market. |
| 5. Player/lineup model | Existing inputs only | Current availability code remains shadow data; historical player value and lineup backfill are still required. |
| 6. xG state updates | Partial data foundation | Existing StatsBomb aggregate backfill can feed the as-of layer; event-level coverage is not yet broad enough. |
| 7. Residual ML expert | Not promoted | Existing W/D/L booster must be replaced by bounded corrections to strength/tempo and re-gated. |
| 8. Latent-space market blend | Math implemented | `ml/models/vnext_market.py`; live weights remain off until freshness/liquidity and historical gates exist. |
| 9. Distribution calibration | Primitive implemented | Outcome-class raking changes the grid itself and records calibrator provenance. |
| 10. Uncertainty-aware simulation | Contract only | Approximate online variances are not a fitted posterior and must not drive public simulations. |
| 11. Learned live model | Not implemented | Requires historical event, substitution and post-shot-xG feeds. |
| 12. Validation and monitoring | Foundation implemented | Coherent replay metrics, paired challenger gates, and exact-parent shadow receipts. Every receipt stores the candidate O/U 2.5 probability plus a hash of its complete score grid, so the pure-tempo primary metric is measurable from the append-only ledger. Automatic promotion remains disabled. |

## Challenger sequence

Candidates are deliberately isolated so a win has a clear cause:

1. **Parity canary** — current lambdas and headline numbers represented through
   the vNext contract. This validates plumbing, not accuracy.
2. **Pure tempo** — preserve the production strength ratio and change only total
   expected goals.
3. **Dynamic strength residual** — preserve total expected goals and change only
   relative strength.
4. **Combined fundamental model** — evaluated only if steps 2 and 3 survive
   independent confirmation.
5. **Market-informed model** — blends 1X2 and O/U evidence in latent space and
   always keeps a parallel market-free ledger.

## Promotion evidence

Every challenger is paired to the exact earlier production row named by its
receipt fingerprint; independently selecting two "latest" rows is forbidden.
The receipt also validates the full 64-character artifact identity behind the
40-character database tag, its information cutoff, predictor type, payload mode,
score-grid hash and candidate O/U 2.5 probability. Missing, stale or tampered
receipts are rejected by the benchmark and repaired by the coverage sweep.
World Cup, international and club families are never pooled for promotion.

Minimum general gate:

- primary metric confidence interval favours the challenger;
- at least 500 paired matches, 90% coverage and four independent clusters for
  an initial offline gate (production gates should use at least 20 meaningful
  time/competition clusters where available);
- no mean Brier or accuracy regression;
- a frozen confirmation holdout not used for tuning.

Candidate-specific metrics:

- pure tempo: O/U log loss primary; 1X2 log loss non-inferiority;
- strength residual: 1X2 log loss primary; totals non-inferiority;
- combined model: score-grid negative log likelihood plus both guardrails;
- market blend: report pure and blended records separately.

The 72-match WC26 group-stage record is useful evidence but is too small to establish a
one- or two-percentage-point accuracy improvement by itself.

## First replay result (unfitted defaults)

The local replay runner was exercised on the public international-results file
for three World Cups. The file does not identify score-at-90, so the runner now
uses only the chronologically known group-stage boundary (48 matches in 2018 and
2022; 72 in 2026). Knockout rows are removed before they can train Elo or the
dynamic model. These remain architecture diagnostics, not promotion-grade
claims: every prediction is frozen before applying its result, but the current
legacy parameters were not reconstructed as historical as-of artifacts for the
older tournaments.

| World Cup | Matches | Candidate | W/D/L log loss | W/D/L Brier | Winner accuracy | O/U 2.5 Brier |
|---|---:|---|---:|---:|---:|---:|
| 2018 | 48 | legacy | **0.9859** | **0.5888** | 56.25% | 0.2577 |
| 2018 | 48 | Elo strength + dynamic tempo | 0.9896 | 0.5918 | 56.25% | **0.2559** |
| 2022 | 48 | legacy | 1.1214 | 0.6498 | 52.08% | 0.2507 |
| 2022 | 48 | Elo strength + dynamic tempo | **1.1135** | **0.6489** | 52.08% | **0.2459** |
| 2026 | 72 | legacy | 0.9161 | 0.5469 | 59.72% | 0.2577 |
| 2026 | 72 | Elo strength + dynamic tempo | **0.8886** | **0.5329** | 59.72% | **0.2459** |

The result supports the staged design rather than a wholesale replacement. The
orthogonal tempo candidate preserved winner accuracy in all three samples. It
was slightly worse on 2018 W/D/L, then descriptively improved 2022 and 2026; its
2026 changes were about 3.0% lower W/D/L log loss, 2.6% lower W/D/L Brier and
4.6% lower O/U Brier. Across all 168 diagnostic rows, the corresponding
descriptive reductions were about 1.3%, 0.9% and 2.7%, but that pooled summary is
not used as a gate. Every paired confidence interval for the orthogonal
component still crossed zero. The full dynamic strength-and-tempo default lost
substantial winner accuracy in 2018 and 2022 and remains research-only. No
vNext candidate passes the stated 500-match/four-cluster gate.

Reproduce a single tournament locally with:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_vnext_backtest \
  --csv /path/to/results.csv --year 2026 --bootstrap-samples 2000
```

## Production migration

The migration is additive:

1. Keep the current engine and APIs unchanged.
2. Generate content-addressed vNext rows with `is_shadow=True`.
3. Replay and compare exact model versions on identical cutoffs.
4. Promote one component at a time only after its gate passes.
5. Retain the old engine as a fallback for at least one full evaluation cycle.

No current vNext component is authorized to merge to `main`, run a production
database migration, or change served forecasts without a separate reviewed
promotion decision.
