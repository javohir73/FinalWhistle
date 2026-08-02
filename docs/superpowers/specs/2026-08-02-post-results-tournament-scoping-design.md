# Post-results tournament scoping

## Problem

The post-results chain calls `generate_predictions()` without a tournament
boundary. In a database containing World Cup groups and the newly activated
Champions League group, the tournament simulator merges every `Group` row.
The empty pre-draw Champions League group reaches the World Cup simulator,
which assumes a third-placed team exists and raises `IndexError` at
`order[2]`.

Render confirms the chain catches the exception and leaves data consistent,
but the success watermark cannot advance, so the job retries and football
predictions remain stale.

## Design

The post-results chain will regenerate each database tournament independently.
Every call to `generate_predictions` receives an explicit `tournament_id`, so
groups, matches, standings, and the bracket simulation cannot cross competition
boundaries. Registered club competitions use the same per-league model params,
historical Elo map, baseline policy, and standings advancement count as the
daily league pipeline. An unregistered tournament uses the caller's existing
model version and default model parameters, preserving the World Cup path.

The individual summaries are aggregated back into the existing
`matches_predicted`, `groups_simulated`, and `tournament_teams` shape, with a
new `tournaments_simulated` count for observability. This keeps existing API
and health consumers compatible.

As defense in depth, `_simulate_tournament` will run the World Cup bracket only
when its explicitly scoped tournament contains exactly 12 groups with at least
four teams each. Incomplete structures return zero simulated teams instead of
entering the bracket engine.

## Error handling

Failures still propagate to `run_tracked_post_results_chain`, which rolls back
uncommitted work, records the exception, and leaves the chain pending for its
existing retry path. No exception is hidden inside prediction generation.

## Testing

An integration regression seeds the valid 12-group World Cup plus an empty UCL
group, finishes a UCL qualifying match, and runs the real post-results chain.
Before the fix it raises the production `IndexError`; after the fix it completes
and reports both tournaments separately. A focused simulation test verifies an
explicitly scoped 12-group tournament with an incomplete group skips cleanly.
The complete Python suite remains the final gate.

## Non-goals

- No schema or migration changes.
- No change to live-score ingestion or the NRL result display.
- No redesign of rating-state storage.
- No silent fallback to mixed-tournament simulation.
