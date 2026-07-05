# Market comparison (model vs closing line) — design spec

**Date:** 2026-07-05
**Status:** Approved — a live `GET /api/model/market-record` endpoint that surfaces the
model-vs-market comparison on the existing `/methodology` section, computed on read from
captured odds; honesty-first, framed as the "final pre-kickoff consensus we captured."
**Feature branch:** `feat/market-record`

## Problem

Beating naive baselines is the entry bar; the **market's closing line** is the real one —
it's the roadmap's Phase-0 fork criterion (`docs/ROADMAP-ENGINE.md`). Almost all of this
already exists:

- **Odds capture** (`pipeline/ingest/odds.py::refresh_odds`) fetches 1X2 from API-Football,
  takes the **median consensus across bookmakers**, strips the margin to implied
  probabilities, and stores one `Odds` row per match with `captured_at`. Best-effort, never
  raises. It is wired into `run_pipeline` *before* predictions — but gated behind
  `if settings.api_football_api_key:` (`run_pipeline.py:71`), which is unset in prod, so it
  is **skipped** and prod captures **zero** snapshots.
- **The benchmark** (`pipeline/run_market_benchmark.py::run_live`) already joins, for each
  finished match, the **last odds snapshot before kickoff** (the closing line) to the
  pre-kickoff production prediction and computes model-vs-market log-loss / Brier, a paired
  diff + CI, win rate, and a verdict (`ml/evaluation/market_benchmark.py::benchmark` /
  `result_to_json`).
- **The frontend** already renders it — the `/methodology` "How does it compare to the
  market?" section reads `frontend/lib/market-benchmark-data.json` and shows a full table +
  `VerdictBadge` when its `status` flips to `"ready"` (currently `"pending"`).

The gaps are only: (1) odds capture is off in prod; (2) the comparison is published as a
**static committed JSON** that updates only via a commit + redeploy; (3) the daily-window
snapshot is a *late pre-kickoff* line, not the literal closing tick.

## Constraints & decisions

- **Live compute-on-read, not static JSON.** Add `GET /api/model/market-record` computing
  the comparison from the `Odds` + `Prediction` tables on read (mirrors the audited
  `GET /api/model/record`). The `/methodology` section fetches it server-side instead of
  static-importing the JSON. Auto-updates as matches finish; no commit/deploy per refresh.
- **Reuse the existing benchmark core.** Extract the DB-benchmark body of `run_live` into a
  reusable `market_record(db) -> dict` returning the page-ready `result_to_json` payload
  (`status, n_matches, updated_at, model, market, diff_log_loss, diff_ci95, model_win_rate,
  mean_edge, verdict`), or an honest-empty payload (`status` not `"ready"`, nulls) when
  nothing is benchmarkable. `run_live` becomes a thin CLI over it (the CLI keeps working).
  No change to the `benchmark` math, `result_to_json`, or the `Odds` schema.
- **Honest label — "final pre-kickoff consensus we captured," not "closing line."** The
  join uses the last snapshot with `captured_at <= kickoff_utc`; with the daily 48h-window
  capture that is a late pre-kickoff consensus, not the literal closing tick. The page says
  exactly that. A near-kickoff capture is a **future refinement, out of scope here.**
- **Enablement is a stop-gate, and carries no secret in code.** Adding
  `API_FOOTBALL_API_KEY` to `render.yaml` (`sync: false`) and `refresh.yml`
  (`${{ secrets.API_FOOTBALL_API_KEY }}`) only *references* a secret; the value is set by
  the human in the Render dashboard + GitHub secrets, using a **freshly rotated** key (the
  earlier key was pasted in plaintext). Turning it on spends external API quota → it goes
  through the stop gate at execution.
- **No overclaim.** Framing is transparency — "here's where we match the market and where we
  don't," never "we beat the market." The section already carries the honest copy; wording
  is adjusted to match what is actually captured. Evidence is forward-only (cannot
  reconstruct closing odds for the 90 already-finished matches) and thin near-term (~6 WC26
  matches left) — this is infrastructure for future tournaments.

## Out of scope (explicit)

- Naming or comparing specific platforms (Polymarket, Kalshi) — this is model-vs-closing-line
  only.
- A near-kickoff / true-closing odds capture upgrade.
- Any change to the odds-ingestion math or the `Odds` schema.
- Surfacing the comparison anywhere other than the existing `/methodology` section (the
  `/record` page stays model-only).

## Backend

- **`pipeline/run_market_benchmark.py`** — add `market_record(db) -> dict` holding the
  current `run_live` DB logic (it needs the ORM, so it lives with the pipeline runner,
  mirroring `pipeline/run_availability_benchmark.py::availability_record`): iterate finished
  matches, take the closing `Odds` snapshot (`captured_at <= kickoff_utc`, latest) and the
  pre-kickoff non-shadow `Prediction`, build `MatchedMatch`es, call `benchmark(...)`, and
  return `result_to_json(result, title, now_iso)`; return an honest-empty payload
  (`{"status": "pending", "n_matches": 0, "model": null, "market": null, …}` matching the
  frontend `MarketBenchmark` shape) when zero matches are benchmarkable. Pure of HTTP.
  `run_live` is reduced to: call `market_record(db)`, log the report, and (in `--emit-json`
  mode) write the JSON — same CLI behavior.
- **`backend/app/api/market_record.py`** (new router, prefix `/api/model`, mounted in
  `backend/app/main.py` next to the `model_record` router) — add `GET /api/model/market-record`
  (public, cached like `/record`) that **lazy-imports** `market_record` from
  `pipeline.run_market_benchmark` (avoids the app→pipeline import cycle, exactly as
  `/api/internal/availability-record` does) and returns it.

## Frontend

- **`frontend/lib/api.ts`** — add `getMarketRecordServer()` = `getServer<MarketBenchmark>(
  "/api/model/market-record", …)`. Move the `MarketBenchmark` type into `lib/types.ts`.
- **`frontend/app/methodology/page.tsx`** — becomes an async server component; fetch the
  market record instead of static-importing `market-benchmark-data.json`. The existing
  `pending`/`ready` branch, table, `VerdictBadge`, and paired-CI copy are unchanged. Adjust
  the "closing line" wording to "final pre-kickoff consensus we captured."
- The static `market-benchmark-data.json` is no longer imported (may be deleted or kept as a
  local dev fixture — deletion preferred to avoid a stale second source of truth).

## States & errors

- **Nothing benchmarkable** (no odds captured yet, or no finished match with both a snapshot
  and a pre-kickoff prediction) → honest-empty payload (`status` not `"ready"`) → the
  section renders its existing "results publish here after the first benchmarked match day"
  copy.
- **Endpoint fetch failure** → the section falls back to the same pending state; the rest of
  `/methodology` still renders.

## Testing

- **Backend:** `market_record(db)` unit test — in-memory SQLite seeded with a finished
  `Match`, a pre-kickoff non-shadow `Prediction`, and an `Odds` snapshot
  (`captured_at <= kickoff_utc`) → asserts a `ready` payload with the expected `n_matches`
  and a well-formed `diff_ci95`; a second case with no `Odds` → honest-empty (`status`
  not `"ready"`, nulls). Endpoint test mirroring `test_model_record_api.py`.
- **Frontend:** the methodology section renders the `pending` state from an empty payload and
  the `ready` table + verdict from a populated payload.

## Non-goals recap

Turn on the existing odds capture (config, human-set secret), expose the existing benchmark
as a live audited endpoint, and repoint the existing methodology section at it — honestly
labeled. No new comparison math, no competitor naming, no schema change, no near-kickoff
capture.
