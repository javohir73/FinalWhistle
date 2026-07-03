# xG-nudged team attack/defence offsets — design spec

**Date:** 2026-07-04
**Status:** Approved (scope: offline build + backtest + live shadow twin; **no promotion**)
**Feature branch:** `feat/xg-team-offsets`

## Problem

The served forecast maps a single Elo scalar per team into both lambdas
(`ml/models/poisson.py::expected_goals_from_elo`): `λ_home = base·exp(β·diff)`,
`λ_away = base·exp(−β·diff)`. It therefore **cannot represent a team's style** — a
grind-it-out defensive side and a free-scoring side with equal Elo get identical goal
expectations. There is no notion that one team wins 1–0 and another wins 3–2.

The machinery to fix this **already exists and is dormant**: `pipeline/fit_attack_defence.py`
fits per-team attack/defence offsets, `ml/models/team_offsets.py` shrinks/caps them, and
`generate_predictions.py::_offsets_by_team_id` routes them through the match card and both
Monte-Carlo simulators behind one flag (`model_params.json` `"team_offsets": null` → no-op).
But the fitter learns from **raw goals** (`score_a`/`score_b`), a low-count, high-variance
signal (~1.4 goals/team/match).

**xG is a denser, lower-variance estimate of the same attack/defence strength.** This spec
feeds the offset fit from xG where xG exists, degrading provably to the goals fit where it
doesn't — and ships it shadow-first for measurement, changing nothing users see.

## Constraints & decisions

- **Shadow-first, no promotion.** The served model is untouched: `params.team_offsets`
  stays `null`. The xG-nudged store is loaded **only** by a new shadow-twin writer, exactly
  as the availability twin scales λ without enabling anything on the published path.
  Promotion (flipping `team_offsets` on) is a separate, gated decision with its own evidence
  — out of scope here. (Precedent: availability and odds twins both ship this way; live
  window is only ~15 knockout matches, no room to recover from a bad mid-tournament flip.)
- **Goals prior + xG nudge, re-anchored.** Two independent fits (goals over full history,
  xG over the covered subset), blended per team by a coverage ramp, with a **re-anchor step**
  that removes the two fits' zero-point mismatch (see ML core). No xG for a team → the blend
  is **bit-identical to today's goals fit**.
- **Pro plan.** xG comes from `/fixtures/statistics` (`expected_goals`), reachable on the
  Pro key. **Phase 0 is a coverage probe** and a hard go/no-go gate: if xG is sparse for our
  teams, κ collapses toward 0 everywhere and the feature degrades to goals-offsets — we stop
  and reconsider rather than ship a no-op.
- **Backfill scope: WC26-team matches within ~5 years.** The fitter's 3-year half-life makes
  older matches near-weightless (`0.5^(5/3) ≈ 0.30`) and those are exactly the ones without
  xG, so backfilling further buys nothing. Bounds API calls and fixture-matching to a
  tractable set.
- **Migration required.** New nullable `xg_a`/`xg_b` columns on `historical_matches`
  (mirrors the injuries-column precedent). Schema reaches prod via `refresh.yml`
  (`alembic upgrade head`) **before** any code that selects the columns — the stop-gate
  sequencing rule.
- **Follows the availability twin pattern, not the odds-shadow pattern.** Since availability
  landed there are already two `is_shadow=True` rows per match, and `_frozen_prediction`
  disambiguates by `model_version` (`learning_loop.py:104`); the `prediction_results` table is
  uniquely constrained to one shadow row per match. So the xG twin is scored by its **own
  benchmark runner** reading its tagged rows (clone of `run_availability_benchmark.py`), not
  through `evaluate_finished_shadow_predictions`.

## The fit (ML core)

Notation: for each team `t`, `ĝ_t` = goals-fit offset (attack; defence identical), `x̂_t` =
xG-fit offset. Both come out of the **same** `fit_offsets`, already shrunk to
`√(n_eff/30)` and clamped to `OFFSET_CAP = 0.075` log-λ (`exp(0.075)−1 ≈ 7.8%` on expected
goals). Let `S` = teams with any xG coverage (`n_eff_xg,t > 0`).

1. **Goals fit (the prior).** Run `fit_offsets` unchanged over the full ~49k-row history →
   `{t: ĝ_t}`. This is today's fitter output.
2. **xG fit.** Run the **same** `fit_offsets` over only xG-covered rows, reading `xg_a`/`xg_b`
   as the goal source → `{t∈S: x̂_t}`. (Small refactor: parametrize the goal-source arrays so
   one function serves both; no change to the MLE/decay/shrink logic.)
3. **Re-anchor (removes the zero-point mismatch).** `fit_offsets` centres offsets to a
   `n_eff`-weighted mean over *whatever population it is handed* (`fit_attack_defence.py:145`).
   The goals fit is centred on the full population, the xG fit on the (plausibly stronger,
   better-covered) subset `S`, so their zero points differ by a scalar `δ`. Left uncorrected,
   the blend shifts every high-κ team by `κ·δ` — a **systematic bias** for well-covered teams,
   not noise. Fix: shift the xG fit onto the goals frame using the shared set,
   `δ̂ = Σ_{t∈S} n_eff_xg,t·(ĝ_t − x̂_t) / Σ_{t∈S} n_eff_xg,t`, then `x̂′_t = x̂_t + δ̂`.
4. **Blend by coverage.** `κ_t = min(1, √(n_eff_xg,t / 30))` (reuses the offset layer's
   full-weight count; tunable). Final offset:

   ```
   offset_t = (1−κ_t)·ĝ_t + κ_t·x̂′_t  =  ĝ_t + κ_t·(x̂′_t − ĝ_t)
   ```

   i.e. **goals prior plus a coverage-weighted "scores-vs-xG" residual.** The residual is
   mean-zero over `S` by construction (step 3), so no κ-correlated level shift. `κ_t = 0`
   (no xG) → `offset_t = ĝ_t`, identical to today. Convexity of already-capped inputs keeps
   `|offset_t| ≤ 0.075` for free. Note a low-coverage team is shrunk **twice** — once inside
   `fit_offsets` on `x̂_t`, again by `κ_t` in the blend — a deliberate compounding consistent
   with the conservative choice: thin xG barely moves a team off its goals prior.
5. **Write** `ml/models/team_offsets_xg.json`, same `{team_name: {atk, def, n_matches}}` shape
   the loader already reads.

## Data — ingestion & backfill

- **Fetch.** New `fetch_fixture_statistics(api_key, fixture_id)` in
  `pipeline/ingest/api_football.py` → `GET /fixtures/statistics?fixture=`, same
  `x-apisports-key` / 200-with-`errors` handling as the existing fetchers. Pure parser
  `parse_team_xg(response) -> {side: xg}` reading the `expected_goals` statistic per team
  (returns `None` per side when the field is absent — never fabricate).
- **Fixture matching.** Map each in-scope `historical_matches` row to its api-football fixture
  by `(date, normalized home, normalized away)`, reusing `pipeline/team_mapping.normalize_team_name`.
  Unmatched or xG-absent rows are left `NULL` (no coverage) — expected and honest.
- **Backfill script** (`pipeline/backfill_xg.py`, offline/CLI, best-effort, never raises):
  iterate in-scope rows (WC26-team matches, date ≥ ref − ~5y), fetch stats, write `xg_a`/`xg_b`.
  Idempotent (skips rows already populated) so it can resume within the Pro daily quota.

## Persistence — the shadow twin

- New constant `OFFSETS_MODEL_VERSION = "poisson-elo-v0.3+xg"` in `generate_predictions.py`.
- New `write_offsets_prediction(db, match, payload, strengths, params)`, mirroring
  `write_availability_prediction`: load `team_offsets_xg.json` **directly** (independent of
  `params.team_offsets`), get `(atk,def)` per side, scale the production lambdas
  `λ_home *= exp(atk_home + def_away)` / mirrored, rebuild via `predict_from_lambdas`, and
  append an `is_shadow=True` row tagged `OFFSETS_MODEL_VERSION`. No offsets for either team →
  no row (clean null test; partial coverage expected). Called in the `generate_predictions`
  loop beside the existing two twins.
- **Match-level only.** Like the availability twin, no shadow *simulations* — the served sims
  stay offset-free. If promoted later, `_offsets_by_team_id` already carries offsets into both
  simulators; that's the promotion step, not this spec.

## Evidence — walk-forward backtest

`pipeline/backtest_xg_offsets.py` (offline) compares three configs on held-out past WC
editions using the existing walk-forward harness (`build_enriched_rows`, exclusive `ref_date`
so no edition leaks into its own fit):

- **A** no offsets (today's served model), **B** goals-offsets, **C** xG-nudged offsets.
- Predict each held-out edition's matches under each config; score **Brier** and **log-loss**
  on W/D/L.
- **Honest caveat:** xG only exists in the training windows of recent editions (2018, 2022),
  so C vs B is only discriminating there; for older editions C ≈ B by construction. The report
  states per-edition coverage so a null result isn't mistaken for "xG doesn't help."

The backtest is the primary evidence; the live twin (~15 matches) is on-pattern confirmation,
not sufficient on its own.

## Edge cases

- **xG absent for a match / a side** → `NULL`, treated as no-coverage; contributes nothing to
  the xG fit.
- **Team with no xG at all** → `κ=0`, pure goals offset (unchanged behaviour).
- **Empty `S`** (coverage probe was wrong) → `δ̂` undefined → skip the xG fit entirely, write
  the goals store; loudly log a no-op (this is the kill-switch firing).
- **Hand-edited store past the cap** → `offsets_for` re-clamps at read time (defence in depth,
  already there).
- **Fixture-match ambiguity** (double-header dates, renamed teams) → no confident match → leave
  `NULL`; never guess an xG onto the wrong game.

## Risks

- **Coverage too thin (primary).** Mitigated by the Phase-0 probe as a go/no-go gate.
- **Zero-point mismatch.** Handled by the re-anchor (step 3); the backtest is the residual
  detector, now un-confounded.
- **Migration sequencing.** `xg_a`/`xg_b` must reach prod via `refresh.yml` before any code
  selecting them serves — standard stop-gate discipline.
- **Twin never scored.** Avoided by the dedicated benchmark runner (not the
  `SHADOW_MODEL_VERSION`-only learning-loop path).

## Non-goals

- No change to the published prediction, champion odds, or any served field.
- No shadow simulations (match-level twin only).
- No promotion / `model_params.json` flip.
- No player-level xG (that's a separate availability-weighting upgrade).

## Phasing (TDD, mirrors the injuries feature)

0. **Coverage probe** (throwaway script) — sample `/fixtures/statistics` on recent
   internationals; confirm `expected_goals` populated for our teams. **Go/no-go gate.**
1. **Migration** — nullable `xg_a`/`xg_b` on `historical_matches`; dispatch `refresh.yml`.
2. **Fetch/parse** — `fetch_fixture_statistics` + `parse_team_xg`.
3. **Backfill** — `pipeline/backfill_xg.py` over the in-scope window (idempotent).
4. **Fitter blend** — parametrize goal source, add re-anchor + κ-blend, write
   `team_offsets_xg.json`.
5. **Shadow twin + benchmark runner** — `OFFSETS_MODEL_VERSION`, `write_offsets_prediction`,
   benchmark runner.
6. **Backtest + whole-branch verify** — A/B/C walk-forward report; full `make test`.

## Testing

- Fitter: re-anchor makes the covered-set residual mean-zero; `κ=0` reproduces the goals fit
  bit-for-bit; blend never exceeds `OFFSET_CAP`; a synthetic "clinical finisher" (goals ≫ xG)
  gets pulled down and a "wasteful" side (xG ≫ goals) pulled up.
- Parser: `expected_goals` present / absent / malformed → correct `xg` / `None`.
- Twin: null-test (no offsets → no row); with a store, λ scaled by `exp(atk+def)` and tagged
  `OFFSETS_MODEL_VERSION`; production row and the other two twins unaffected.
- Backfill: idempotent skip; unmatched fixture → `NULL`.
