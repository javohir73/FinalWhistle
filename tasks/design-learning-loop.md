# Design: Match-Result Learning Loop (working notes)

Status: DRAFT — audit-independent core locked first; integration points filled in
after the 6-reader audit completes. Branch: `feat/match-result-learning-loop`.

## Non-negotiable constraints (from the brief)

1. **No overfitting to 1–2 games.** Updates are conservative, capped, and decay-aware.
2. **No blind rewrites.** The base model (Elo + Poisson + Monte-Carlo over 49,000
   internationals) stays the foundation; tournament evidence *adjusts* it, never
   replaces it.
3. **Explainable.** Every changed probability must be decomposable into:
   base model + Elo delta from results + capped form adjustment.

## 1. Per-match prediction snapshot (the "receipt")

Freeze the pre-kickoff prediction so it can never be silently rewritten by a
recompute — this is also what makes marketing claims auditable.

`prediction_snapshots` (one row per match, written at kickoff or first
recompute that sees the match as scheduled; immutable once the match goes
in_play):

| column | type | notes |
| --- | --- | --- |
| match_id | FK, unique | |
| p_home, p_draw, p_away | float | pre-kickoff probabilities |
| pred_home_goals, pred_away_goals | int | modal scoreline |
| elo_home, elo_away | float | ratings at snapshot time |
| model_version | str | e.g. poisson-elo-v0.2 |
| snapshot_at | datetime | |

After full time, an evaluation row is computed (same table or
`prediction_results`):

| column | notes |
| --- | --- |
| winner_correct | argmax(p) side == actual side |
| exact_score_correct | modal scoreline == actual |
| brier | multiclass: Σ(pᵢ − oᵢ)² over {home, draw, away} |
| log_loss | −ln(p[actual outcome]), clamped p ≥ 1e-12 |
| goal_error | |pred_home−act_home| + |pred_away−act_away| |
| evaluated_at | |

Calibration error is an aggregate (not per-match): reliability buckets over all
evaluated matches, reported by the evaluation endpoint.

## 2. Conservative Elo update (after each FT)

Standard Elo with World-Cup-tuned damping:

```
E_home = 1 / (1 + 10^((R_away − R_home_adj) / 400))   # R_home_adj includes host bonus if applicable
S      = 1 / 0.5 / 0 for win/draw/loss (home perspective)
K_eff  = K_base × G(goal_diff) × stage_weight
ΔR     = K_eff × (S − E_home);  R_home += ΔR;  R_away −= ΔR
```

- **K_base = 20** (tournament football; vs ~32 for qualifiers in common Elo variants —
  deliberately low: one match moves a top side ≤ ~15 points ≈ ~2% win-prob shift
  vs an equal opponent).
- **G(goal_diff)**: 1.0 (≤1), 1.5 (=2), 1.75 + (gd−3)/8 (≥3) — the classic
  World Football Elo multiplier, sublinear so a 5–0 isn't 5× a 1–0.
- **stage_weight**: 1.0 group, 1.1 R32/R16, 1.2 QF+, capped.
- **Opponent strength** is inherent to Elo (expected score E). No extra term.
- Updates are **idempotent per match**: applied exactly once, recorded
  (e.g. `elo_applied_at` on the match/snapshot row), so re-runs never double-apply.

Anti-overreaction math check: an 81%-favorite losing 0–2 moves ~K·1.5·0.81 ≈ 24
points ≈ 3.4 pp win-prob vs an equal side. An upset *informs*; it cannot flip a
bracket.

## 3. Capped tournament-form layer

A transparent additive layer on top of Elo, recomputed from ALL tournament
matches played so far (never incremental, so it can't drift):

```
xg_diff_t   = (goals_for − expected_goals_for) per match t  (expectation = model's pre-match Poisson means)
attack_adj  = clamp(mean(xg_diff) × λ_a, −cap_g, +cap_g)     # goals added to team's Poisson attack mean
defense_adj = clamp(mean(conceded_diff) × λ_d, −cap_g, +cap_g)
```

- λ small (≈0.3) and **cap_g ≈ 0.25 goals** on the Poisson means, which empirically
  maps to **≤ ~6 pp on win probability** for an even match — inside the brief's
  ±5–8% ceiling. The cap is enforced in code AND asserted in tests.
- Requires **≥1 played match**, weight grows with √(n_matches) up to n=4 then flat —
  so 1 match has ~half the influence of 4.
- Injuries/suspensions: **not modeled** — no data source exists; the layer must not
  fake it (documented limitation).
- Form adjustments are stored per team per recompute with their inputs, so the
  UI/docs can show "why" (explainability requirement).

## 4. Recompute flow (after results ingest)

```
finished match detected (status -> finished)
  → evaluate snapshot (metrics)                 [idempotent]
  → apply Elo update                            [idempotent]
  → recompute form layer (all teams, from scratch)
  → re-run remaining-match predictions (Poisson w/ adjusted ratings+form)
  → re-run group qualification + tournament Monte-Carlo (finished = facts, as today)
  → persist predictions; bump model_version metadata timestamp
  → rescore leaderboard
  → clear response caches (scoped)
```

Triggers: (a) scheduled refresh workflow after live-results stage; (b) manual
internal endpoint (token-guarded, same family as the existing recompute).
Guard: recompute only fires when the set of finished matches actually changed.

## 5. Evaluation endpoint (public, cacheable)

`GET /api/model/record` → { evaluated_matches, winner_accuracy, exact_score_hits,
avg_brier, avg_log_loss, calibration: [bucketed reliability], best_calls[],
biggest_misses[], last_updated, model_version }.
Public + honest: powers both the in-app "AI record" and marketing claims.

## 6. Frontend

- Match page + cards (finished): "AI predicted: Mexico 2–0 (81%)" vs "Final: 2–0"
  + existing ✓ badge extended with winner-correct state.
- Global: "Predictions updated after Matchday N results · {timestamp}" note.
- New: small "AI record" strip (from /api/model/record).

## Open questions for the audit to answer

- Where ratings live today (file? DB table? recompute artifact) → decides where
  ΔElo persists without forking the source of truth.
- Exact recompute entrypoint + runtime budget (GitHub Actions timeout?).
- Whether `predicted_score`/probabilities already snapshot pre-kickoff or get
  overwritten by recompute (if overwritten, snapshots are urgent).
- Leaderboard scoring trigger location.
- What the methodology page promises (must stay truthful).

---

## POST-AUDIT RESOLUTIONS (locked 2026-06-13)

1. **Snapshot table NOT needed.** Predictions are append-only and only generated for
   `status='scheduled'` — the latest Prediction row per match is already an immutable
   pre-kickoff snapshot. We add `prediction_results` (evaluation) + `team_tournament_state`
   (learning state) only. One migration.
2. **Elo: replay-from-base, not incremental.** `teams.elo_rating` stays the historical
   base (rewritten daily by `compute_and_store_elo`). The learning loop replays ALL
   finished WC matches chronologically from that base each run, producing per-team
   `elo_delta` — idempotent by construction, survives daily base rewrites, no
   double-apply flags needed. **Double-count guard:** any WC match already present in
   `historical_matches` (martj42 may add WC2026 rows mid-tournament) is skipped.
3. **Conservative K:** `K_eff = k_factor('FIFA World Cup')(=60) × LIVE_DAMPING(0.5) ×
   stage_weight (group 1.0 / R32+R16 1.1 / QF+SF+F 1.2)` → group K_eff = 30.
   Rationale: half the historical convention between full recomputes; an 81%-favorite
   upset moves ≤ ~36 pts ≈ ~5pp — informative, not bracket-flipping.
4. **Form layer folds into effective Elo** (single integration surface; simulators and
   match predictions stay consistent with zero simulator changes):
   `effective_elo = elo_rating + elo_delta + form_adj`.
   `form_adj = clamp(40 × (mean_gf_residual − mean_ga_residual) × min(1, √(n/4)), ±35)`
   where residuals are actual vs pre-match Poisson λ (from the replay's pre-match
   effective ratings). ±35 Elo ≈ ±5pp win prob (within the ±5–8% ceiling; asserted in
   tests). Attack/defense residual components stored for explainability.
5. **Scope: group stage only** for prediction generation + evaluation (knockout
   `fullTime` from football-data may include ET — outcome ambiguity; documented
   limitation, revisit at R32).
6. **Triggers:** (a) `run_pipeline` new step after elo/team_stats, before predictions;
   (b) `/api/internal/recompute` upgraded to run the full chain (learn → predict →
   rescore → cache.clear); (c) live path: `update_live_scores` summary gains a
   `finished` transition count; `maybe_refresh_live` fires the chain in the background
   when > 0 — the event-driven trigger.
7. **Evaluation reuses** `ml/evaluation/match_metrics.py` (built, 9 tests green) +
   `reliability_curve` for the calibration summary.
8. **Endpoint: public `GET /api/model/record`** (cacheable, key `model:record`) — the
   frontend AI-record strip and marketing claims read the same source of truth.
9. **Frontend reuses `predictionVerdict()`** (exists; MatchCard + MatchScoreboard
   already render badges). Adds: ModelRecord type + fetcher, AI-record line on the
   match-page footer + country hub AI outlook, verdict badge in UserPredictionCard for
   finished matches.
10. **Model version stays `poisson-elo-v0.1`** — the loop adds state, not new params;
    `last_learned_at` comes from the state/evaluation tables. CDN may lag ≤60s+SWR
    after cache.clear (documented).
