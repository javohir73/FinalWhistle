# NRL prediction evaluation harness

This harness evaluates the complete pre-match NRL engine without changing the
model, public routes, or production data. It measures winner probabilities,
margin, total points, and both team scores with chronological walk-forward
folds and independent promotion gates.

## Phase 0 inventory

The production snapshot inspected before implementation contained:

- 2,008 NRL fixtures across 2017–2026: 1,958 finished and 50 scheduled.
- 639 held-out finished matches across 2023–2025 in 93 `(season, round)`
  bootstrap clusters.
- Complete kickoff, round, venue, team, and final-score fields for the finished
  history.
- Five drawn matches. Official final scores include golden point.
- One historical team identity split: `Tigers` (2017–2018) and
  `Wests Tigers` (2019 onward). The loader maps the old team ID to the current
  team ID in memory; it never changes the database.
- No licensed historical NRL moneyline, spread, or total archive. Market
  comparisons therefore remain unavailable and do not affect internal gates.

The production prediction store is append-only and currently covers recent
fixtures rather than the full historical evaluation period. The harness
therefore generates its own versioned, local prediction artifact from the
same winner and score-model inference paths.

## Run

Use a read-only production connection or a read-only database snapshot:

```bash
PYTHONPATH=backend:. DATABASE_URL="$PROD_READ_DATABASE_URL" \
python -m pipeline.sports.nrl_evaluate \
  --from-season 2023 \
  --to-season 2025 \
  --model-version nrl-score-v0.1-shadow
```

Add `--require-gates` when the command should return exit code 2 unless every
independent gate passes. A failed gate is a measurement result, not a runtime
failure.

PostgreSQL runs inside a repeatable-read, read-only transaction. Evaluation
artifacts are written under the ignored `artifacts/nrl_backtests/` directory;
the harness never writes results to PostgreSQL.

## Walk-forward protocol

For held-out season `T`:

1. Winner-model training data ends at `T-2`.
2. `T-1` is used only by the existing winner parameter tuner.
3. Model and baseline states are replayed through all fixtures before `T`.
4. Each fixture in `T` is predicted before its result updates state.
5. Fixtures sharing a kickoff timestamp are predicted as one batch before any
   result in that batch updates state.

Rows after the final evaluated season are excluded from both the run and its
dataset fingerprint. Licensed external observations are accepted only when
`captured_at < kickoff_utc`. Partial market archives are reported as a blocker
and cannot alter the internal model gates.

## Metrics and gates

- Winner: log loss (headline), Brier, RPS, accuracy, and calibration/ECE.
  Promotion requires better log loss than the Elo-favourite baseline in most
  seasons and an overall paired 95% interval whose upper bound is not above
  zero.
- Margin: MAE (headline), RMSE, bias, winner-sign accuracy, and errors within 6
  and 12 points. Promotion requires at least 5% lower MAE than Elo margin,
  improvement in most seasons, and a paired interval not crossing above zero.
- Total: MAE (headline), RMSE, bias, and errors within 6 and 12 points.
  Promotion requires at least 5% lower MAE than the leak-free rolling league
  mean, improvement in most seasons, and a paired interval not crossing above
  zero. The historical 47.09 constant is reported only as a diagnostic.
- Scoreline: home, away, and combined team-score MAE, exact hit rate, and both
  scores within 6 points. Promotion requires at least 5% lower combined MAE
  than rolling home/away means, improvement in most seasons, and no material
  regression in margin or total.

All paired intervals use 10,000 deterministic bootstrap samples, clustered by
`(season, round)`, with seed `2026`. Market metrics appear only if each held-out
season reaches 70% verified, licensed, pre-kickoff coverage. They never control
an internal promotion gate.

## Artifacts

Each run writes a deterministic directory keyed by model version, seasons, and
dataset fingerprint:

- `manifest.json`: model version, parameters, dataset fingerprint, code commit,
  seed, timestamp, source inventory, and artifact hashes.
- `predictions.jsonl`: one shared fixture row containing model and every
  benchmark prediction.
- `results.json`: aggregate, seasonal, calibration, benchmark, confidence
  interval, market-coverage, and gate results.
- `leakage_audit.json`: strict-prior-state and external-signal assertions plus
  canonical team aliases.
- `report.html`: human-readable tables, reliability plot, seasonal breakdown,
  market blocker, and statistical noise-floor statement.

Champion selection remains separate and manual. The harness reports evidence;
it never promotes a model automatically.
