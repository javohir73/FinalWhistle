# The match-result learning loop

How FinalWhistle learns from World Cup 2026 matches as they finish — in a
controlled, explainable, anti-overfitting way. (Design history:
`tasks/design-learning-loop.md`.)

## What happens after a final whistle

```
live refresh detects a scheduled/in_play → finished transition
  1. EVALUATE  — the frozen pre-kickoff prediction is scored against the
                 result → prediction_results (winner hit, exact-score hit,
                 Brier, log loss, goal error). Append-only; never rewritten.
  2. LEARN     — team_tournament_state is recomputed by REPLAYING all
                 finished WC matches from the historical Elo base:
                 conservative Elo delta + capped form adjustment per team.
  3. RECOMPUTE — remaining group matches are re-predicted and both
                 Monte-Carlo simulations re-run (group qualification +
                 full-tournament odds) using the adjusted ratings.
  4. RESCORE   — bracket leaderboard points are recomputed.
  5. CACHES    — the response cache is cleared (CDN may lag ≤60s + SWR).
```

Triggers: the opportunistic live-refresh path (final-whistle transition), the
daily 06:00 UTC pipeline (`learning_loop` + `bracket_scores` steps), and the
manual token-guarded `POST /api/internal/recompute` (runs the same chain).

## What updates automatically — and what doesn't

| Updates | Does NOT update |
| --- | --- |
| Team strength (effective Elo = base + delta + form) | The historical Elo base (daily full-history replay owns it) |
| Future match probabilities + predicted scores | Past predictions (frozen, append-only — they're the audit trail) |
| Group qualification probabilities | Model parameters (BASE_GOALS, beta, temperature — gated by walk-forward backtests) |
| Tournament/bracket/title odds | The model version string |
| Live group standings (real results, as before) | Anything from in-play matches (only `finished` counts) |
| Leaderboard scores | |

## Anti-overfitting safeguards

1. **Damped K:** in-tournament updates use `K_eff = K_wc(60) × 0.5 ×
   stage_weight (group 1.0 → final 1.2)`. An 81%-favorite losing by two moves
   ~36 Elo ≈ ~5 pp — it informs the forecast, it cannot flip a bracket.
2. **Hard form cap:** the form layer (goal residuals vs the model's own
   pre-match expectations) is clamped to ±35 Elo ≈ ±5 pp win probability, with
   a √(n/4) ramp so one match carries half the weight of four. Both the cap
   and the ramp are asserted in tests (`ml/ratings/tournament_test.py`).
3. **Replay, not increments:** state is recomputed from scratch every run —
   idempotent, no drift, no double-apply. Verified by tests.
4. **Double-count guard:** if the upstream historical dataset starts including
   WC2026 results, those matches are skipped in the tournament replay (the
   daily base replay already counts them).
5. **Frozen evidence:** predictions are only generated for `scheduled`
   matches, so the latest row per match is an immutable pre-kickoff snapshot;
   evaluation joins it to the actual result exactly once.

## How marketing claims are verified

`GET /api/model/record` is the single source of truth: winner accuracy, exact
score hits, average Brier/log loss, calibration buckets (same
reliability-curve math as the methodology backtests), best calls, biggest
misses, and `last_updated`. Any public claim ("2/2 winners, 1 exact score")
must be reproducible from this endpoint — it is computed from the append-only
`prediction_results` table, never hand-maintained.

## What users see

- Match cards/pages: predicted score + probabilities before kickoff; after
  full time, the actual result with a ✓ Exact score / ✓ Result predicted /
  ✗ Missed badge (including the country-hub prediction cards).
- Match page footer: "AI record so far: X/Y winners · Z exact score" and a
  "Model updated" timestamp that reflects the last learning run.
- Country hub: the AI outlook card carries the current record line.

## Baseline (pinned 2026-07-02)

Production `/api/model/record` snapshot: **82 evaluated / 51 winners (62.2%) /
9 exact scores (11.0%)**. All before/after accuracy claims for the exact-score
maximization program (see `tasks/prd-exact-score-maximization.md`) compare
against production snapshots — never the local dev database, which is stale
and unmigrated. Offline context: the 1,843-match walk-forward holdout hits
~14.8% exact with the production pick rule, ≈13–14% when re-weighted to a
World-Cup-like Elo-gap mix — the honest expectation band for live results.

## Limitations (honest)

- **Knockout evaluation uses the feed's full-time score, which includes extra
  time** (shootout kicks never count; a shootout tie evaluates as a draw). The
  model predicts 90-minute scores, so a tie decided by an extra-time goal is
  scored at its after-ET scoreline — an accepted skew until the 90-minute
  capture ships (Phase 2 of the exact-score program).
- **No injuries/suspensions:** no reliable data source — the form layer does
  not pretend otherwise.
- Effective ratings feed probabilities; the human-readable "reasons" text
  still cites the base Elo gap (the record endpoint + state table carry the
  adjustment decomposition).
- The in-process cache is per-worker; the CDN may serve predictions up to
  ~60s (+ stale-while-revalidate) after a recompute.
- Sample sizes are tiny early in the tournament — the record endpoint reports
  raw counts, and the UI copy avoids implying statistical significance.
