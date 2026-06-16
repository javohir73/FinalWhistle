# Unify the Monte-Carlo simulators on the Dixon-Coles engine (+ knockout fixes) — design

**Date:** 2026-06-16
**Status:** Approved (design)
**Source analysis:** multi-agent model audit (workflow `wf_da0a67c7-89d`), 2026-06-16.

## Problem

The product runs **two divergent goal engines**:

- **Match cards** ([generate_predictions.py:62](pipeline/generate_predictions.py)) use the tuned **Dixon-Coles** engine: `predict_match(base, beta, rho, temperature)` from `model_params.json`.
- **Tournament sims** ([group_sim.py](ml/simulate/group_sim.py), [bracket.py](ml/simulate/bracket.py)) import **hardcoded** `BASE_GOALS=1.35 / ELO_TO_GOALS_BETA=0.0019` and sample with **plain `rng.poisson()`** — no Dixon-Coles, no `rho`, and drifted from the tuned values (`base 1.20`, `beta 0.0021`). `generate_predictions` passes only `base/beta` to the sims ([:161](pipeline/generate_predictions.py), [:221](pipeline/generate_predictions.py)), never `rho`.

So headline tournament numbers (qualification %, win-title %, reach-*) come from an **un-tuned, plain-independent-Poisson** engine that bypasses the very low-score (draw / 1-0) correction Dixon-Coles exists for. Two adjacent knockout bugs compound it: a skill-biased penalty shootout (`PK_BETA=0.0025` → a 100-Elo favorite wins ~56%) and `home_adv=0.0` hardcoded for all knockout matches ([bracket.py:164](ml/simulate/bracket.py)) despite real hosts.

## Goal

One calibrated scoreline engine feeding **both** the cards and the sims, plus correct knockout shootout/host behavior. Success is proven by a **consistency test**: the sampler-implied W/D/L over many draws ≈ `predict_match`'s W/D/L for the same `(λ_home, λ_away, rho)`.

## Design

### 1. Shared scoreline sampler (explicit fast path)

In [ml/models/poisson.py](ml/models/poisson.py), next to `score_matrix`:

```python
def score_cdf(lam_home, lam_away, rho=0.0, max_goals=MAX_GOALS) -> "np.ndarray":
    """Flattened, normalized CDF over the (max_goals+1)^2 Dixon-Coles grid.
    Build ONCE per fixture; reuse across all sims."""

def sample_scoreline_from_cdf(rng, cdf) -> tuple[int, int]:
    """One rng.random() + searchsorted into a prebuilt CDF -> (home, away)."""

def sample_scoreline(rng, lam_home, lam_away, rho=0.0, max_goals=MAX_GOALS) -> tuple[int, int]:
    """Convenience wrapper = sample_scoreline_from_cdf(rng, score_cdf(...)). Do
    NOT call inside a per-sim loop (rebuilds the grid)."""
```

- **Truncation alignment:** `score_cdf` uses the **same `MAX_GOALS`** as `score_matrix`, so the sampler and the card are over the identical sample space — mathematically aligned.
- **Normalization + guard:** build the grid via `score_matrix` (already applies the Dixon-Coles τ), then **clamp any negative/NaN cell to 0** (defends against future weird params, e.g. an extreme `rho` making τ push a cell negative) and **renormalize to sum 1** before the cumulative sum. A zero/degenerate total raises rather than silently producing a bad CDF.
- **Index decode:** flat index → `(home=idx // (max_goals+1), away=idx % (max_goals+1))`.

### 2. Thread the engine through the simulators

- `group_sim.simulate_group(...)` and `bracket.simulate_tournament(...)` gain a **required `rho` parameter (no default)** — a missed call site must fail loudly, never silently fall back to `rho=0` (plain Poisson). `base`/`beta` continue to be passed explicitly from params; a test asserts `generate_predictions` passes the `model_params.json` values (not the constants) at both call sites.
- Each unplayed fixture's CDF is built **once via `score_cdf`, outside the `n_sims` loop** (lambdas are already precomputed there), then `sample_scoreline_from_cdf` is called per sim. Replaces `rng.poisson(lh)/poisson(la)` at [group_sim.py:86-87](ml/simulate/group_sim.py), [bracket.py:166](ml/simulate/bracket.py), [:185](ml/simulate/bracket.py).
- **Single source of truth:** sims no longer rely on hardcoded `BASE_GOALS/ELO_TO_GOALS_BETA` as live defaults; values flow from `model_params.json` through `generate_predictions`. (Constants remain only as the documented v0.1 fallback inside `load_params`.)

### 3. Penalty shootout (near coin-flip + shrunk fitted edge)

- Replace the `PK_BETA=0.0025` logistic with a **`pk_beta` loaded from `model_params.json`**, fit from historical penalty-decided knockouts (flag penalty-decided KOs in `historical_matches`).
- **Regularize/shrink toward 0:** shootout samples are thin and selection-biased, so shrink the fitted slope toward zero — `pk_beta = (n / (n + k)) * fit`, with a strong prior weight `k` (and **default `pk_beta = 0.0`, pure coin-flip, when data is insufficient**).
- **Hard cap:** clamp the per-match shootout win probability to a bounded band (e.g. `[0.45, 0.55]`) so no parameter drift can reintroduce a large skill bias.

### 4. Host advantage in knockouts (actual venue/team pairing)

- Apply host advantage in `bracket.play()` **only when a simulated team is the host nation of that knockout slot's venue** — not merely because a host nation is in the match. (A host playing a KO match in another country's venue gets **no** bump.)
- Mechanism: thread per-knockout-slot host info (the host nation, if any, owning that slot's venue — derived from the fixed WC26 KO schedule / `Match.host_team_id` where available) into `simulate_tournament`. During `play()`, resolve `home_adv` by the same rule as [`_host_adv`](pipeline/generate_predictions.py:24): `+params.home_adv` to the team that is the slot-venue's host nation, `0` if neither team is. Replaces the hardcoded `home_adv=0.0`.
- The exact per-slot venue→host-nation source is the implementation crux; the plan will pin it down. If a slot's host nation can't be resolved, default to **neutral (0)** — never guess.

## Out of scope (YAGNI)

- **Temperature** stays on the card path only — it scales a W/D/L triple, not a single sampled scoreline. The sampler does not apply it.
- No extra-time reduced-λ phase before shootouts.
- No new data sources, no bivariate-Poisson / attack-defense, no odds prior (those are later roadmap items).

## Testing (TDD)

- **Sampler distribution:** over many draws, `sample_scoreline` frequencies match `score_matrix(λ, ρ)` cell probabilities (chi-square / tolerance); draw rate is **higher than plain Poisson** when `rho < 0`.
- **CDF guard:** negative/NaN cells clamped; CDF sums to 1; degenerate input raises.
- **`rho` required:** calling `simulate_group`/`simulate_tournament` without `rho` raises `TypeError` (no silent default).
- **Params wired:** `generate_predictions` passes `model_params.json` `base/beta/rho` to both sim call sites (assert the values, not the constants).
- **Shootout:** equal teams ≈ 0.50; a **100-Elo favorite is bounded well below the old ~0.56** (assert ≤ 0.54); `pk_beta=0.0` ⇒ exactly coin-flip; thin-data fit falls back to 0.
- **Host KO:** a host nation at its own venue gets `+home_adv`; the same nation at a non-home venue gets `0`; neutral matchup gets `0`.
- **KEY consistency test:** for sampled `(λ_home, λ_away, rho)`, the sampler's empirical W/D/L over N draws ≈ `predict_match`'s W/D/L (within Monte-Carlo tolerance) — proving the sim and the card now speak one language.

## Re-baselining (expected, not a regression)

Every tournament output shifts: more draws/ties (Dixon-Coles), more penalty upsets (coin-flip), hosts stronger in KO. We will re-run a tournament sim, re-baseline cached leaderboard / tournament-odds outputs, and update any tests asserting fixed probabilities (with the shift explained).
