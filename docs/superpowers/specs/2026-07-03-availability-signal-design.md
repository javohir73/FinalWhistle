# Availability signal — design spec

**Date:** 2026-07-03
**Status:** Approved (scope: v1 = announced-XI only)
**Feature branch:** `feat/availability-signal`

## Problem

The published forecast is pure team-level Elo → Poisson. It is blind to who is
actually on the pitch: a star striker rested or injured does not move the number.
The methodology page states this openly as a limitation. We want the forecast to
*account for* individual availability — without breaking the walk-forward discipline
that makes the predictions credible in the first place ("through the gate or not at all").

## Constraints & decisions

- **Shadow-first.** The availability-adjusted forecast is logged as a shadow twin for
  measurement. It does **not** change the published champion number until it earns
  promotion through the existing gate.
- **Explanation-only surfacing.** Users see **one** published probability (the official
  one) plus an availability *note* — who is out and the directional impact — **not** a
  competing set of percentages.
- **Free path only (v1).** Signal = announced XI (`/fixtures/lineups`, already ingested)
  + player form (`Player` table, already ingested). No paid injuries feed.
- **Migration-free.** No schema change. The twin reuses `is_shadow=True`, distinguished
  by `model_version`.
- **Champion untouched, WC26 routes additive.** No change to group/knockout sims; no
  change to existing endpoints' existing fields.

## The adjustment (ML core)

New module `ml/models/availability.py` — pure functions, no I/O.

Reuse `goalscorers.player_rate(player)` (shrunk goals-per-90 with position priors) as
each player's **attacking weight** `w_p`.

- `attack_capacity(eleven) = Σ w_p` over the eleven named players.
- **Reference XI** = the squad's top eleven by total minutes (`club_minutes + wc_minutes`)
  — the team's usual starters.
  *(Default. Alternative considered: a fixed formation-position baseline. Minutes-based
  chosen — simpler, self-calibrating, no formation assumptions.)*
- `ratio = attack_capacity(announced XI) / attack_capacity(reference XI)`.
- `attack_offset = clamp(ln(ratio), LO, HI)` with **`LO = −0.25`, `HI = +0.10`**
  (≈ −22% / +10% on that team's expected goals). Deliberately asymmetric and tight: a
  missing player almost always subtracts, and the clamp guarantees a garbled/empty XI can
  never wreck a forecast.
- Applied through the attack/defence offset hook **already in `poisson.py`**
  (`lambda_home *= exp(atk_home + def_away)`): v1 adds `attack_offset` to `atk_home`
  (home) / `atk_away` (away) **only**. `def_*` is untouched — form data is goals-based,
  so a defensive/GK adjustment would be guesswork (explicit non-goal). The offset is
  **additive on top of** any fitted `fit_attack_defence` offset (exp-space multiply).

Returns `(atk_offset_home, atk_offset_away, explanation)`, where `explanation` names the
missing high-weight players (reference starters absent from the announced XI, sorted by
weight) and the resulting per-team %.

### Edge cases
- **No announced XI** for a match → no adjustment, no shadow row, no note. Partial
  coverage is expected and honest — XIs land only ~T-60.
- **Announced player lacks form data** → `player_rate` already shrinks to the position
  prior; handled.
- **`ratio > 1`** (stronger-than-usual XI, e.g. a rested star returns) → small positive
  offset, capped at `HI`.
- **Reference capacity ≈ 0** (no minutes data for a squad) → skip (guard the divide);
  no adjustment.

## Persistence (migration-free)

When the announced XI is available (~T-60, still pre-kickoff), the pipeline computes the
adjusted prediction and writes it as a **shadow row**: `is_shadow=True`,
`model_version="poisson-elo-v0.1+avail"` — distinguished from the odds-anchored shadow by
its version string. No new column, no migration, no `refresh.yml` stop-gate. Being
pre-kickoff, it is a valid immutable-log entry. Coverage is partial by nature. This row
exists for **measurement only** — its adjusted probabilities are never surfaced as a
user-facing number (see Serving + UI).

## Serving + UI

- **API:** additive `availability` block on the match prediction payload:
  `{ has_lineup: bool, per_team: [{ side, players_out: [{name, weight}], attack_delta_pct, note }] }`,
  where `attack_delta_pct = exp(attack_offset) − 1`. Carries the **note and directional %,
  not a second probability set.** WC26 routes untouched; new field only.
- **Frontend:** one availability line under the existing prediction on the match page,
  clearly labelled *"context — not reflected in the number above; logged for evaluation."*
- **Methodology page:** replace the limitation line *"individual player form and injuries
  aren't factored in"* with the honest new state — team-level published number, with
  announced-XI availability surfaced as context and logged as an experimental adjusted
  forecast pending the gate.

## Measurement / promotion gate

Extend the existing benchmark harness to score the `+avail` twin vs the official
prediction vs outcome (log-loss / Brier) over matches with a non-trivial adjustment.
Promotion of the twin to champion uses the existing gate language: **ship only if the
out-of-sample CI on the improvement excludes zero.** This half is mostly future/manual
(needs match results to accumulate); the harness ships now so the data is ready to
evaluate when they do.

## Non-goals (v1)

No paid injuries feed. No schema migration. No change to the published number. No
defensive/GK availability. No change to group/knockout simulations.

## Deferred / next step

**Free injuries feed.** Research a way to obtain injury/availability data at no cost
(alternative free APIs, official team-news sources, community feeds). If found, extend the
same bounded adjustment to injuries — which are known days ahead, so they would inform the
day-ahead forecast, not only the near-kickoff one. Same shadow-first, same gate. Not in v1.

## Testing

- **Unit** (`availability.py`, TDD): capacity math, clamp bounds, `ratio > 1`,
  missing-XI / empty-squad guards, explanation content.
- **Integration:** pipeline writes exactly one `+avail` shadow row when an XI exists, zero
  when it does not; champion row unchanged.
- **Serializer:** `availability` block present/absent correctly; existing fields unchanged
  when no XI is present.
- Full suite green (`make test`) before PR.
