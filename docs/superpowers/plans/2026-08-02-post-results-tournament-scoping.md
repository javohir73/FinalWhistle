# Post-results Tournament Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the post-results chain from mixing World Cup and club competition groups, eliminating the production `IndexError` while preserving correct per-league prediction settings.

**Architecture:** Add one tournament-scoped regeneration helper to `pipeline.learning_loop`. It resolves registered league settings from `pipeline.leagues`, invokes `generate_predictions` once per tournament, and aggregates the existing summary counters. Harden `_simulate_tournament` so incomplete World Cup structures never enter the bracket engine.

**Tech Stack:** Python 3, SQLAlchemy, pytest, existing prediction and simulation modules.

## Global Constraints

- Preserve the existing `run_post_results_chain` public signature and summary keys.
- Every `generate_predictions` invocation from the post-results chain must pass an explicit `tournament_id`.
- Registered leagues must use `club_params_for`, `club_baseline_params_for`, `club_elo_ratings`, and their configured `standings_advance_count`.
- Do not add a migration, dependency, API endpoint, or UI change.

---

### Task 1: Reproduce and fix mixed-tournament regeneration

**Files:**
- Modify: `pipeline/learning_loop.py`
- Modify: `pipeline/learning_loop_test.py`
- Modify: `pipeline/generate_predictions.py`
- Modify: `pipeline/generate_predictions_test.py`

**Interfaces:**
- Consumes: `generate_predictions(db, ..., tournament_id: int, params: ModelParams, ...) -> dict`
- Produces: `_regenerate_tournament_predictions(db, model_version: str, n_sims: int, tournament_sims: int) -> dict`

- [ ] **Step 1: Write the mixed WC/UCL regression test**

Seed the standard World Cup structure, add a second `Tournament` with an empty
`Group` and a finished qualifying match, then call `run_post_results_chain`.
Assert the call completes, reports two tournaments simulated, and writes no UCL
tournament bracket odds.

- [ ] **Step 2: Run the regression test to verify RED**

Run:

```bash
.venv/bin/python -m pytest pipeline/learning_loop_test.py::test_post_results_chain_scopes_mixed_world_cup_and_ucl_groups -q
```

Expected: failure with `IndexError: list index out of range` from
`ml/simulate/bracket.py`.

- [ ] **Step 3: Implement tournament-scoped regeneration**

Add `_regenerate_tournament_predictions` that iterates `Tournament` rows in ID
order. For a tournament whose name matches `pipeline.leagues.LEAGUES`, resolve
its code and pass that league's model params, baseline params, competition Elo
map, and advancement count. For other tournaments, pass the existing model
version and default params. Always pass `tournament_id=tournament.id`, and sum
the three established summary counters plus `tournaments_simulated`.

- [ ] **Step 4: Add and verify the incomplete-group guard**

Before calling `simulate_tournament`, require exactly 12 scoped groups and at
least four members in every group. Return `0` otherwise. Add a focused test
whose scoped tournament has 12 group rows but one empty group and assert the
bracket engine is not called.

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest pipeline/learning_loop_test.py pipeline/generate_predictions_test.py pipeline/generate_predictions_tournament_scoping_test.py -q
```

Expected: all tests pass with no failures.

- [ ] **Step 6: Run the complete verification gate**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: exit code 0 and no failures or errors.

- [ ] **Step 7: Commit the implementation**

```bash
git add docs/superpowers/specs/2026-08-02-post-results-tournament-scoping-design.md docs/superpowers/plans/2026-08-02-post-results-tournament-scoping.md pipeline/learning_loop.py pipeline/learning_loop_test.py pipeline/generate_predictions.py pipeline/generate_predictions_test.py
git commit -m "fix: scope post-results predictions by tournament"
```
