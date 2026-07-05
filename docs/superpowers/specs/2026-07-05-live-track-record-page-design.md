# Live Track Record page — design spec

**Date:** 2026-07-05
**Status:** Approved — a dedicated `/record` page that illustrates the live, audited
model record honesty-first (every headline rate shown with its 95% CI and sample size).
**Feature branch:** `feat/track-record-page`

## Problem

The model's live tournament performance is already fully computed and audited by
`GET /api/model/record` (`backend/app/api/model_record.py`): it aggregates only
production (`is_shadow=False`) `PredictionResult` rows into winner accuracy, exact-score
hits, avg Brier / log-loss, a live calibration curve, best calls, biggest misses, and the
sample size (`evaluated_matches`) — with an honest-empty branch and a "not betting advice"
disclaimer. It is the documented source of truth: *"anything stated publicly must be
reproducible from this endpoint."*

But the **frontend collapses all of that to a single line** on the home page —
`"AI record so far: N/M winners · K exact scores"` (`HomeExperience.tsx`). None of the
richer signal is illustrated. The visuals that do exist on `/methodology`
(`CalibrationChart`, metrics-vs-baselines tables) are fed by **static historical backtests**
(2014 / 2018 / 2022 from `lib/methodology-data.json`), **not** the live record.

This spec adds a dedicated, illustrated **live** Track Record page that surfaces the
existing audited record — with every headline rate shown next to its 95% confidence
interval and sample size, so a number can never read as more certain than it is.

## Constraints & decisions

- **Reuse the audited endpoint as the single source of truth.** The page consumes
  `GET /api/model/record`; it does not compute its own metrics. This preserves the
  endpoint's mandate that public claims be reproducible from it.
- **Honesty is server-side and always visible.** Add a **Wilson 95% CI** for the two rates
  (winner accuracy, exact-score rate) to the endpoint payload so the interval is
  reproducible from the same source as the point estimate. The page always renders
  `rate · 95% CI · n` — never a bare percentage. **No gating on small `n`** (the interval
  carries the caution); a light "small sample" note appears when `n` is low.
- **Production record only.** Shadow twins (odds / availability / xG) stay behind
  `/api/internal/*`. This page is the audited *public* record.
- **Reuse existing UI.** Glass cards, the `Stat` component pattern, and the existing
  `CalibrationChart` — no new charting dependency; matches the `/methodology` visual language.
- **No overclaim.** Surfaces misses (`biggest_misses`) alongside wins; keeps the
  "analytics / entertainment only — not betting advice" disclaimer; links to `/methodology`
  for the historical backtests and limitations.

## Out of scope (explicit)

- Market / competitor comparison (Polymarket, Kalshi, closing line) — a separate step,
  blocked on prod odds capture.
- Any metric the endpoint does not already compute (accuracy-over-time trend, per-stage or
  per-confidence breakdowns).
- Any change to how the record is *computed* or to learning-loop scoring. This is
  presentation plus one CI helper.

## Backend — the one addition

`backend/app/api/model_record.py`:

- Add a pure helper `wilson_ci95(successes: int, n: int) -> tuple[float, float] | None`
  (returns `None` when `n == 0`).
- Populate three new payload fields: `winner_accuracy_ci95`, `exact_score_rate`,
  `exact_score_ci95` — all `null` in the honest-empty (`n == 0`) branch.
- No change to the aggregation, the `is_shadow=False` filter, caching, or existing fields.

## Frontend — the page

New route `frontend/app/record/page.tsx`, server-fetched via the existing
`getServer<ModelRecord>("/api/model/record", …)` (same pattern as `/methodology`). The
`ModelRecord` type (`lib/types.ts`) gains the three new fields. Add a top-nav link
("Track record"); the home-page one-liner in `HomeExperience.tsx` becomes a link to
`/record`.

Sections, top to bottom:

1. **Hero honesty row** — Winner accuracy and Exact scores as two headline stats, each
   rendered inline as `rate · 95% CI [lo–hi] · n=…`. The CI *is* the honesty — no dials.
2. **Sharpness** — avg log-loss + avg Brier, each with a one-line plain-English gloss and a
   "lower is better" hint (reusing the methodology glossary tone).
3. **Calibration** — the live reliability curve via `CalibrationChart`, with per-bin counts
   and a "based on N calls" caption; explicitly labeled noisy on small samples.
4. **Best calls / biggest misses** — the endpoint's `best_calls` / `biggest_misses` as small
   cards (match label, predicted score, prob assigned, ✓/✗). Surfacing misses is part of the
   honesty.
5. **Footer** — `last_updated`, `model_version`, the disclaimer, and a link to
   `/methodology`.

## States & errors

- **`n = 0`** → an honest empty state ("No matches scored yet — this fills in as WC26
  fixtures finish"); no fake zeros, no CI shown.
- **low `n`** (`n < 30`) → the CI renders naturally wide, plus a light "small sample —
  treat with caution" note. (30 is a display-only threshold for the note; it never gates
  the number itself.)
- **fetch failure** → a graceful "record unavailable" card; the page still renders.
  Server-fetch honors the existing cache TTL.

## Testing

- **Backend:** `wilson_ci95` unit tests (known-value checks + `n = 0` → `None`); the endpoint
  payload includes the three new fields and they are `null` in the empty branch.
- **Frontend:** the page renders correctly for a **populated** record, an **empty** record
  (empty state, no CI), and a **low-`n`** record (wide CI + small-sample note); the nav link
  and the `/methodology` link are present.

## Non-goals recap

Presentation of existing audited data plus a CI helper — no new signal, no competitor
comparison, no scoring changes, no new charting library.
