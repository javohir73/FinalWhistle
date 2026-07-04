# Club-league xG method validation — design spec

**Date:** 2026-07-04
**Status:** SHELVED 2026-07-04 — the Task-0 depth-probe gate returned STOP. API-Football's `expected_goals` exists only from the 2023 club season (~1447 matches / 4 cells, below the pre-registered 3000-match / 6-cell gate), and a direct international probe found **no World Cup 2022 xG**, no friendlies, no qualifiers — only Euro/Copa 2024. No viable production xG source for WC26 teams. The provider-agnostic method (parametrized fitter goal-source + re-anchor/κ-blend) is banked for if coverage ever deepens.
_(original: Approved — offline method validation; hard gate on the WC xG-offset spec)_
**Feature branch:** `feat/xg-method-validation`
**Gates:** `docs/superpowers/specs/2026-07-04-xg-team-offsets-design.md`

## Purpose

The WC xG-offset feature rests on an unproven premise: that nudging goals-based attack/defence
offsets toward xG improves calibration. WC data can't test it — xG covers ≤2 past editions, too
few clusters to exclude zero. This spec **proves or kills the method on dense club-league data**,
using the **same xG provider (API-Football)** we'd deploy, so a positive result transfers to
production. It is a **hard gate**: the WC feature does not build unless this passes.

Entirely offline and read-only — reads API-Football, caches to disk, prints a report. No database
writes, no served-model change, no migration; nothing here touches the stop gate.

## Constraints & decisions

- **Same xG source as production.** API-Football `/fixtures/statistics` (`expected_goals`), so
  the validated signal *is* the deployed signal — not a different vendor's xG model. **Phase 0
  is a depth probe** and a fork gate: if API-Football club xG history is too shallow to power the
  test, fall back to Understat/FBref depth plus an API-Football overlap check for transfer.
- **Spine from API-Football fixtures, not CSVs.** We already spend Pro quota on per-fixture xG;
  pulling `/fixtures` per league-season alongside makes xG **`fixture_id`-keyed with no fuzzy
  join**, dodging the club-name-matching trap (`run_club_benchmark` deliberately skips the
  national mapper for club names). Club Elo comes from `replay_with_prematch` on those results —
  the same leak-free replay the existing club harness uses. Cost: more quota, and we drop the
  market/odds yardstick (the A/B/C-vs-outcomes test doesn't need it).
- **This spec builds the SHARED method.** The parametrized `fit_offsets` goal-source, the
  re-anchor, and the κ-blend are built and unit-tested here, then consumed verbatim by the WC
  spec. So is the xG fetcher/parser (`fetch_fixture_statistics` + `parse_team_xg`).
- **Pass criterion: directional + consistent** (see Verdict). The xG-nudge is capped at ±7.8%, so
  the true effect may be real but small; the bar requires a consistent point-estimate improvement
  across leagues/seasons rather than a CI that excludes zero.

## The shared method (ML core — authoritative home)

For each team `t`: `ĝ_t` = goals-fit offset, `x̂_t` = xG-fit offset, both from the **same**
`fit_offsets` (already shrunk `√(n_eff/30)`, clamped to `OFFSET_CAP = 0.075` log-λ ≈ 7.8%).
`S` = teams with xG coverage.

1. **Goals fit** — `fit_offsets` over all matches (goal source = actual goals) → `ĝ_t`.
2. **xG fit** — the **same** `fit_offsets` over xG-covered matches (goal source = `xg`) → `x̂_t`.
   *Refactor: parametrize the goal-source arrays so one function serves both; MLE/decay/shrink
   logic unchanged.*
3. **Re-anchor** — the two fits centre on different populations, so their zero points differ by a
   scalar. Shift the xG fit onto the goals frame:
   `δ̂ = Σ_{t∈S} n_eff_xg,t·(ĝ_t − x̂_t) / Σ_{t∈S} n_eff_xg,t`, `x̂′_t = x̂_t + δ̂`. `n_eff_xg`
   weighting leans on the least-shrunk teams, isolating the frame shift from shrinkage.
4. **κ-blend** — `κ_t = min(1, √(n_eff_xg,t / 30))`;
   `offset_t = ĝ_t + κ_t·(x̂′_t − ĝ_t)`. Residual mean-zero over `S` by construction (no
   κ-correlated level shift); `κ=0` → identical to the goals fit; convex, so within the cap.

## The test harness (A/B/C)

Per league, walk-forward over seasons (leak-free: fit on prior seasons only, exclusive cutoff):

- **A** no offsets (Elo→Poisson), **B** goals-offsets, **C** xG-nudged offsets.
- For each held-out season, fit on all prior seasons, predict that season's matches under each
  config, score **Brier** and **log-loss** on W/D/L.
- Aggregate across leagues × seasons; **clustered bootstrap (cluster = league-season)** for CIs
  and per-cell deltas.

## Verdict — directional + consistent

**PASS** (unblocks the WC spec) requires all of:

- C beats B in **point estimate on both Brier and log-loss**, aggregated.
- **Consistent sign**: C ≤ B in the large majority of league-season cells, with **no league where
  C is clearly worse** than B. The exact cell fraction (e.g. ≥⅔) is **pre-registered in the
  implementation plan before Phase 5 produces any numbers** — never chosen after seeing the
  results, so the threshold judges the data instead of drifting to fit it.
- CIs are reported (not required to exclude zero) and per-cell deltas printed so consistency is
  visible, not asserted.

**FAIL** → the WC feature is shelved / reconsidered, **not** built. A B-beats-A-but-C-≈-B result
means "the offsets help but xG adds nothing" — goals-offsets could then be promoted on their own
(separate decision), but the xG machinery isn't worth building. That goals-offsets promotion is
**not** cleared by this test: its directional-and-consistent bar was calibrated for the
small-capped xG question, not as a general green light. It still routes through the existing
champion/challenger gate (`pipeline/experiment_model_eval.py`, CI-excludes-zero), like any other
served-model change.

## Risks

- **Underpowered club xG (primary).** Mitigated by the Phase-0 depth probe as a fork gate;
  fallback to Understat/FBref depth + API-Football overlap check for transfer.
- **Quota.** Per-fixture statistics calls across many league-seasons — disk-cached and resumable
  so a run picks up where it stopped; idempotent.
- **Population transfer.** Club ≠ international (different strength dispersion, no neutral venues),
  so a club PASS is *necessary* evidence the method works, **not** a guarantee for WC — which is
  exactly why the WC spec keeps its own sanity backtest + live shadow twin. Stated, not hidden.

## Non-goals

- No production DB writes, no served-model change, no shadow rows — offline research only.
- No market/odds comparison (dropped with the API-Football spine).
- Not the WC feature; that's the gated downstream spec.

## Phasing (TDD)

0. **Depth probe** — how far back does `/fixtures/statistics` carry `expected_goals` per candidate
   league; total powered match count. **Fork gate:** proceed on API-Football, or fall back to
   Understat depth + overlap check.
1. **Shared fetcher/parser** — `fetch_fixture_statistics` + `parse_team_xg`, disk-cached for quota.
2. **Club spine + Elo** — pull `/fixtures` per league-season; `replay_with_prematch` for club Elo.
3. **Club xG backfill** — `/fixtures/statistics` per fixture, `fixture_id`-keyed, cached.
4. **Shared offset method** — parametrize goal source; add re-anchor + κ-blend (the module both
   specs consume).
5. **A/B/C harness + CIs** — walk-forward, Brier/log-loss, clustered bootstrap, per-cell deltas.
6. **Verdict report + `make test`** — apply the directional+consistent criterion; PASS unblocks
   the WC spec, FAIL shelves it.

## Testing

- **Shared method** (lives here): re-anchor makes the covered-set residual mean-zero; `κ=0`
  reproduces the goals fit bit-for-bit; blend never exceeds `OFFSET_CAP`; a synthetic clinical
  finisher (goals ≫ xG) is pulled down, a wasteful side (xG ≫ goals) pulled up.
- **Parser**: `expected_goals` present / absent / malformed → correct `xg` / `None`.
- **Harness**: the walk-forward cutoff is leak-free (a held-out season never enters its own fit);
  A/B/C configs isolated; bootstrap clusters by league-season.
- **Cache**: idempotent resume — a re-run makes no duplicate calls and yields identical rows.
