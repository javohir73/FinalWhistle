# WC26 Match Writeup + Signal Readiness — Design

**Date:** 2026-07-11
**Status:** Approved (design reviewed in session)
**Model version at time of writing:** `poisson-elo-v0.5` (with `w_odds=0.35` armed shadow-only)

## Context

The WC26 match page shows probabilities, a predicted score, rule-based reason
bullets, feature importance, odds comparison, and goal markets — but no narrative
that stitches them into a readable "here's the call" writeup. The NRL side already
has a deterministic 3-paragraph `preview_text` (`ml/models/nrl_preview.py` →
`SportPrediction.preview_text` → `OverviewSection`); WC26 has nothing equivalent.

Separately, two model signals are built but idle: the odds blend (`w_odds`, armed
at 0.35 for the shadow twin on 2026-07-10, null test running, evidence at 15/30
pairs) and availability (`use_availability=false`). Production serving code never
reads `w_odds`, so even a met gate cannot be promoted today.

## Decisions (made with owner)

1. **Deterministic template generation only.** No LLM, no API key, no per-refresh
   cost, zero hallucination risk. Every sentence is templated from a real model
   field.
2. **Fable-style structured sections**, not a single text blob: the writeup is a
   JSON object with `case_home`, `case_away`, `call`, `caveat`.

## Goals

- A per-match narrative writeup on the WC26 match page that presents the model's
  numbers as reasoned prose and **structurally cannot contradict them**.
- Make promotion of the odds/availability signals a one-command, evidence-gated
  decision: production serving paths exist behind inert flags, and gate status is
  reported automatically.

## Non-goals

- No LLM integration anywhere.
- No promotion flip in this work — evidence gate is 15/30; the flip happens later
  via `promote_blend --ship` through the stop gate.
- No changes to NRL surfaces, `reasons.py` output, or score-matrix persistence.

---

## Part 1 — "The Call": writeup generator, storage, API, frontend

### Generator — `ml/explain/writeup.py`

Pure, deterministic function (no clock, no randomness) alongside the existing
rule-based `reasons.py`. It consumes fields `build_payload()`
(`pipeline/generate_predictions.py`) already computes:

- W/D/L probabilities, lambdas, predicted exact score + probability
- Elo gap, recent form, head-to-head aggregates
- Availability deltas / players out (when present)
- Odds comparison (when present)
- Knockout block (`p_advance_*`, `p_extra_time`) for KO matches
- Confidence level ("High" / "Medium" / "Low")

Returns `dict | None`:

```json
{
  "case_home": "one paragraph, 2–4 sentences",
  "case_away": "one paragraph, 2–4 sentences",
  "call":      "one paragraph",
  "caveat":    "one paragraph"
}
```

All four keys are present whenever a writeup is returned. Returns `None` (and the
frontend hides the section) when inputs are too thin to say anything honest.
The builder never raises.

**Content rules (the constraint system):**

- `case_home` / `case_away`: sentence templates per signal, each with an inclusion
  condition — Elo/attack edge, last-5 form record, H2H lean, players out /
  attack-delta, host advantage, and "the market agrees/disagrees" when
  `odds_comparison.available`. Missing signal → sentence omitted. Reuse
  `reasons.py` thresholds where they exist rather than inventing new ones.
- `call`: the named winner is **always the argmax** of the three probabilities
  (if draw is argmax, phrase as "too close to call — the draw is the single most
  likely outcome"). Includes the most-likely scoreline and its probability. For
  knockouts, adds advance probability for the favored side and extra-time chance.
- `caveat`: draw probability in plain English ("a draw after 90 is live at
  roughly one in four"), an "open game" phrasing when the favorite is below ~45%,
  and a thin-data warning whenever confidence is "Low".
- Shared phrasing helper `prob to "roughly one in N"` (N = round(1/p));
  percentages rounded to whole numbers, matching what the page displays.

### Storage & pipeline

- New nullable JSON column `writeup` on `Prediction`
  (`backend/app/models/__init__.py`) + alembic migration.
- Populated in `build_payload()` / `_write_prediction()` on each refresh, for
  **production rows only** (`is_shadow=False`); shadow rows stay lean.
- Freezing needs no special handling: the writeup is a column on the prediction
  row, which already freezes pre-kickoff (`prediction_coverage` invariant
  unchanged).

### API

- `PredictionOut.writeup: WriteupOut | None` (typed sub-schema with the four
  string fields) in `backend/app/schemas/__init__.py`; passthrough in
  `prediction_to_out()` (`backend/app/serializers.py`). Current prediction only —
  not the history array (planner: verify history uses the slim path).

### Frontend

- `frontend/lib/types.ts`: `writeup` field on the prediction type.
- New `frontend/components/MatchWriteup.tsx`: renders four labeled subsections —
  "The case for {home}", "The case for {away}", "The call", "The honest caveat" —
  null-safe (renders nothing when `writeup` is absent), same idiom as the NRL
  `OverviewSection` paragraph rendering.
- Placement: `frontend/app/match/[id]/page.tsx`, below the scoreboard /
  probability bar, above the reasons list. Reasons bullets stay.

---

## Part 2 — Gated signals: ready-to-promote, not promoted

1. **Production odds serving path.** Add `use_odds: bool = False` to
   `ModelParams` (`ml/models/params.py`) and `model_params.json` (mirrors the
   `use_availability` idiom). `build_payload()` blends market odds into lambdas
   only when `use_odds and w_odds > 0` and odds exist — factor the blend out of
   `write_shadow_prediction()` (`pipeline/generate_predictions.py:501–523`) into
   a shared helper so production and shadow use identical math. With
   `use_odds=false`, production output is **bit-identical** to today (regression
   test asserts this) and the armed null test is untouched.
2. **Availability serving path.** Verify whether `build_payload()` honors
   `use_availability` for production; if not, implement it behind that existing
   flag in the same shape.
3. **`promote_blend.py`.** Add `--use-odds` (sets `use_odds=true`; validation:
   requires `w_odds > 0`), keeping the existing dry-run default, `--ship`
   behavior, version bump, and the 0.5 hard cap.
4. **Automated gate readout.** Add `avg_log_loss` to both blocks of the
   `shadow-record` endpoint (`backend/app/api/internal.py:219–259`;
   `PredictionResult.log_loss` already exists — the runbook gate criterion is
   log loss, the endpoint currently reports only Brier). Then extend
   `.github/workflows/shadow-record.yml` with a daily schedule (07:30 UTC, after
   the 06:00 refresh), keeping manual dispatch, that evaluates the gate and
   writes to the job summary: **GATE MET / NOT MET (n=X/30, Δ log-loss=Y)**.
   Read-only; no DB writes.
5. **Promotion procedure (unchanged, documented).** When the readout says GATE
   MET: `promote_blend --ship` in a PR → stop gate → merge → refresh. Update
   `docs/RUNBOOK-WC26-ENDGAME.md` to reference the automated readout and
   `--use-odds`.

---

## Part 3 — Rollout sequencing

Schema change forces the two-step from CLAUDE.md (migrations run via
`refresh.yml`, not on deploy):

1. **PR 1 — migration only** (adds the `writeup` column; no code reads it).
   Merge (stop gate) → dispatch `refresh.yml` (stop gate; applies
   `alembic upgrade head` to prod) → confirm success.
2. **PR 2 — everything else** (generator, pipeline, API, frontend, signal
   readiness, workflow). Merge (stop gate) → backend auto-deploys (Render),
   frontend deploys (Vercel).
3. **Verify:** `GET /api/health`, spot-check one upcoming match payload contains
   `writeup` with numbers matching its probabilities, and view the section on
   the live match page.

## Testing

- `ml/explain/writeup_test.py`: determinism; call names the argmax outcome;
  caveat states the actual draw probability; fraction phrasing; omission rules
  for missing signals; `None` on thin inputs; never raises on degenerate inputs.
- Pipeline: production rows get `writeup`, shadow rows don't; with
  `use_odds=false` payloads are bit-identical to pre-change (regression).
- Backend: serializer/API test includes `writeup`; `shadow-record` endpoint test
  covers `avg_log_loss`.
- Frontend: `MatchWriteup` component test with fixture payload + null case;
  `npm run typecheck && npm run lint && npm test`.
- Full gate before each PR: `make test`.

## Success criteria

- Live WC26 match page shows the four writeup sections, and every number in the
  prose matches the payload it rides with.
- `use_odds=false` / `use_availability=false` keep production predictions
  bit-identical (proven by regression test).
- The daily workflow summary states gate status without anyone running curls.
- When the gate is met, promotion is one reviewed command, not a build project.
