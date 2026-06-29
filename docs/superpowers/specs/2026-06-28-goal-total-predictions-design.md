# Goal-total / over-under predictions (Phase 1)

Status: APPROVED
Date: 2026-06-28
Author: pete@degail.com
Scope: Phase 1 only. Phase 2 (individual goalscorer predictions — needs new player
data + model) is explicitly deferred and not designed here.

## Problem / Goal

Match predictions currently show W/D/L probabilities and a single most-likely
score. Users want goal-total markets too: "how many + goals" — e.g. *Argentina
4+ goals vs Cape Verde*. These are a natural, exact extension of the existing
Poisson model and should appear on the match prediction card.

## Key enabling fact

The `Prediction` row already persists `lambda_home`, `lambda_away`, and `rho`
(the per-team expected-goal rates + Dixon-Coles correlation), and they are
already in the served payload. Goal-total probabilities are a deterministic
function of those three numbers. Therefore this feature needs **no DB migration
and no pipeline rerun** — it is computed on read and lights up on every existing
prediction the moment it deploys.

## Markets

- **Per-team goal bands** (headline): for each team, `P(scores ≥1)`, `≥2`, `≥3`,
  `≥4`. Display rule: show "to score" (≥1), "2+", "3+" always; show "4+" only
  when `P(≥4) ≥ 0.10` (so mismatches like Argentina/Cape Verde surface it, but
  even contests stay uncluttered).
- **Match total over/under**: the helper returns Over 1.5 / 2.5 / 3.5; the card
  shows **Over 2.5** and **Over 3.5**.
- **Both teams to score (BTTS)**: single probability.
- **Not included**: clean sheet — it is the inverse of the opponent's "to score"
  band, so it would be redundant.

## The math (one source of truth)

Build the Dixon-Coles-adjusted score matrix `M[h][a] = P(home=h, away=a)` once
from `(lambda_home, lambda_away, rho)` via the existing
`score_matrix(lam_home, lam_away, rho=rho)` in `ml/models/poisson.py`. That
function returns an **un-normalized** grid (the DC tau factor and the `MAX_GOALS`
truncation mean it doesn't sum to 1), so **normalize by total mass first** —
exactly as `score_cdf` and `outcome_probabilities` already do. This is the
**same distribution** that yields the predicted score (its argmax cell) and the
W/D/L triple, so every number on the card is internally consistent. Then
marginalize the normalized matrix:

- `P(home ≥ N)  = Σ_{h≥N, all a} M[h][a]`
- `P(away ≥ N)  = Σ_{a≥N, all h} M[h][a]`
- `P(total ≥ M) = Σ_{h+a≥M} M[h][a]`  → Over 1.5 = `P(total≥2)`, Over 2.5 =
  `P(total≥3)`, Over 3.5 = `P(total≥4)`
- `BTTS = Σ_{h≥1, a≥1} M[h][a]`

No new model, no calibration to tune. (The W/D/L booster blend, when on, only
adjusts the W/D/L triple, never the scoreline distribution — goal markets come
from the scoreline distribution, matching `predicted_score`.)

## Architecture

### Backend (compute on read, serializer-side)

- **`goal_markets(lambda_home, lambda_away, rho) -> dict | None`** — new pure
  function in `ml/models/poisson.py`. Returns `None` only when `lambda_home` or
  `lambda_away` is `None`; a missing `rho` is treated as `0` (plain Poisson, no
  low-score correction) rather than nullifying the whole card.
  Calls `score_matrix(lam_home, lam_away, rho=rho)`, normalizes by total mass,
  then marginalizes (no new matrix code needed). Returns:
  ```
  {
    "home": {"to_score": p, "p2": p, "p3": p, "p4": p},
    "away": {"to_score": p, "p2": p, "p3": p, "p4": p},
    "total": {"over_1_5": p, "over_2_5": p, "over_3_5": p},
    "btts": p,
  }
  ```
  All probabilities rounded to 4 dp.
- **Serializer**: `serializers.prediction_to_out` calls `goal_markets(...)` from
  the stored `Prediction.lambda_home/lambda_away/rho` and attaches the result to
  `PredictionOut`.
- **Schema**: add nullable `goal_markets: GoalMarketsOut | None` to
  `PredictionOut`, with nested out-models (`GoalMarketsOut`, per-team band model,
  totals model). Null when `lambda_home`/`lambda_away` are absent (legacy rows);
  a missing `rho` defaults to `0`.
- **No** change to `build_payload`, the `Prediction` model, or any migration —
  markets are derived at serve time, not stored.

### Frontend

- Add `goal_markets` (nullable) + supporting types to the `Prediction` TS type.
- New **`GoalMarkets`** component (`frontend/components/GoalMarkets.tsx`):
  a compact "Goals" section — two per-team band columns (team name + the band
  chips), then a totals/BTTS row.
- Rendered on the match page (`/match/[id]`) overview, after the predicted-score
  / "Why" content. **Hidden entirely when `goal_markets` is null.**

## Display rules

- Per team: `To score {pct}`, `2+ {pct}`, `3+ {pct}`, and `4+ {pct}` only when
  `p4 ≥ 0.10`.
- Totals: `Over 2.5 {pct}`, `Over 3.5 {pct}`.
- BTTS: `Both teams to score {pct}`.
- Use the existing `pct()` formatter.

## Testing

- **ml** (`ml/models/poisson_test.py` or similar): `goal_markets` —
  - probabilities all in `[0, 1]`;
  - per-team bands monotonic non-increasing (`to_score ≥ p2 ≥ p3 ≥ p4`);
  - totals monotonic (`over_1_5 ≥ over_2_5 ≥ over_3_5`);
  - BTTS ≤ each team's `to_score`;
  - a known-λ fixture (e.g. λ_home=2.0, λ_away=0.5, ρ=0) with hand-checkable
    numbers;
  - `None` input → `None`.
- **backend** (serializer test): `goal_markets` populated when `lambda_*` present;
  `null` when `lambda_*` is `None`.
- **frontend** (`GoalMarkets` render test): bands render; "4+" hidden when its
  probability is low and shown when high; the whole section is absent when
  `goal_markets` is null.

## Out of scope

- Individual goalscorer predictions (Phase 2 — separate spec; needs a new
  player-stats data source + model).
- Persisting markets in the DB (computed on read by design).
- Surfacing markets in bracket / list / summary views (match-detail card only).

## Rollout

Backend (serializer + schema) and frontend ship together; no migration, no
pipeline rerun. Every existing prediction gains goal markets immediately on
deploy.
