# Surface the availability twin — internal availability-record endpoint — design spec

**Date:** 2026-07-04
**Status:** Approved (scope: internal endpoint only; no migration, no promotion)
**Feature branch:** `feat/availability-record-endpoint`

## Problem

The availability twin (`AVAILABILITY_MODEL_VERSION`) writes a live shadow prediction for
every match where both sides have availability signal, but its evidence is never surfaced.
The automated scoring path (`pipeline/learning_loop.py::evaluate_finished_shadow_predictions`)
scores **only** the odds twin — it dedupes by `match_id` alone and `_frozen_prediction(shadow=True)`
hardcodes `SHADOW_MODEL_VERSION`, and `prediction_results` is uniquely constrained to one shadow
row per match (`uq_prediction_result_match_shadow` on `(match_id, is_shadow)`). A dedicated
scorer exists — `ml/evaluation/availability_benchmark.py` + `pipeline/run_availability_benchmark.py`
— but it's a manual CLI, so the availability evidence silently accumulates and rots.

**Availability is inherently live-only** — announced XIs don't exist for historical matches, so
unlike `wdl_blend` / `calibrator` / `team_offsets` (which have powered backtest gates in
`pipeline/experiment_model_eval.py`), the live twin is its **only** evidence path. That makes
surfacing it the one real gap.

## Constraints & decisions

- **Dedicated-runner path, not `prediction_results`.** Score the twin via the existing pure
  `benchmark_availability`, reading frozen `Prediction` rows + final scores. `prediction_results`
  stays odds-only. **No schema migration, no constraint widening.**
- **Compute-on-read.** The sample is tiny (dozens of matches) and inputs are frozen (predictions
  are append-only, frozen at kickoff), so the endpoint recomputes on each request — deterministic,
  auditable, no persistence.
- **Internal-only.** Mirrors `/api/internal/shadow-record`: token-gated via `RECOMPUTE_TOKEN`
  (fail-closed), never public. Comparison numbers stay private until a manual promotion decision
  (FR-4.6/4.8). Nothing here auto-promotes.
- **Reuse, don't redesign.** `benchmark_availability` (the pure scorer) is unchanged, including its
  IID bootstrap; the CI is wide on a small sample — honest, surfaced as-is.
- **Endpoint only.** No frontend page (the endpoint *is* the surface, like shadow-record). No
  pipeline log line.

## Design

### 1. Reusable scorer: `availability_record(db) -> dict`

Extract the DB-gathering currently inlined in `run_availability_benchmark.main()` into
`availability_record(db)` (in `pipeline/run_availability_benchmark.py`):

- For each finished match (`status == "finished"`, scores present), take the latest published
  prediction (`is_shadow=False`) and the latest availability twin
  (`model_version == AVAILABILITY_MODEL_VERSION`) via the existing `_latest` helper.
- Skip matches missing either row — inherently like-for-like: only matches with **both** count.
- Label by final score (H/D/A), call `benchmark_availability(prod_probs, avail_probs, labels)`.
- Fold in the `verdict` string (currently computed in `main()`), machine-readable:
  `"availability_beats_published"` (CI hi < 0), `"published_beats_availability"` (CI lo > 0),
  else `"no_credible_difference"`.
- Return the benchmark dict + verdict; return an **honest-empty** dict when no match carries both
  rows: `{"n_matches": 0, "verdict": "insufficient", "production": None, "availability": None,
  "diff_log_loss": None, "diff_ci95": None, "availability_win_rate": None}`.
- `main()` becomes a thin printer over `availability_record(db)` (DRY; preserves current CLI
  output). This also makes the gathering logic unit-testable for the first time.

### 2. Endpoint: `GET /api/internal/availability-record`

In `backend/app/api/internal.py`, mirroring `shadow_record`:

- Signature: `db: Session = Depends(get_db)`, `x_recompute_token: str | None = Header(default=None)`.
- `_require_token(x_recompute_token)` first (fail-closed 503 if `RECOMPUTE_TOKEN` unset, 401 on
  mismatch, constant-time compare — reuse the module helper).
- Lazy-import `availability_record` from `pipeline.run_availability_benchmark` (matches the
  module's existing lazy-import-from-`pipeline` pattern; avoids the app→pipeline cycle at load).
- Return `availability_record(db)`.

### Response shape

```json
{
  "n_matches": 12,
  "production":   {"log_loss": 0.98, "brier": 0.59, "accuracy": 0.5, "n": 12},
  "availability": {"log_loss": 0.97, "brier": 0.58, "accuracy": 0.5, "n": 12},
  "diff_log_loss": -0.01,
  "diff_ci95": [-0.06, 0.03],
  "availability_win_rate": 0.58,
  "verdict": "no_credible_difference"
}
```

`production` / `availability` come straight from `compute_metrics`; `diff_log_loss` is
`availability LL − production LL` (negative = availability better). Null fields on the
honest-empty response.

## Testing

- Unit test on `availability_record(db)` with a seeded session:
  - both rows on ≥1 finished match → numbers match a direct `benchmark_availability` call; verdict
    matches the CI.
  - no match carries both rows → honest-empty (`n_matches == 0`, `verdict == "insufficient"`).
  - a match missing the twin is excluded (like-for-like).
- Endpoint tests cloned from `test_shadow_record_api.py`:
  - no token configured → 503; bad token → 401.
  - valid token + seeded data → 200 with the paired comparison.
  - valid token + empty → 200 honest-empty.

## Non-goals

- No schema migration; `prediction_results` unchanged (odds-only).
- No change to `benchmark_availability`'s math or bootstrap.
- No frontend page, no public exposure, no auto-promotion.
- No pipeline log line (the endpoint is the surface).
