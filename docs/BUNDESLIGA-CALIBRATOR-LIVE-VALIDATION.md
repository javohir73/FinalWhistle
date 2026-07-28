# Bundesliga q3 calibrator — live 2026-27 validation plan

**Status: DESIGN, shadow-only. Nothing enabled, nothing promoted, no migration.**

T1.6 (`docs/MODEL-EXPERIMENTS.md`) found one candidate that survives multiplicity
correction: the **Bundesliga q3 recalibrator**, −0.0104 nats vs the production
calibrator with Bonferroni CI [−0.0188, −0.0036], halving ECE from 0.0645 to
0.0340 at the shipped `base=1.44`. The 2025-26 holdout is consumed. This
document is the plan for earning that on live data.

EPL and La Liga do **not** qualify and are out of scope. xG/GBM stays paused.

---

## 1. Audit — can the existing `+baseline` twin score q3?

**No. Two independent blockers, both verified by execution.**

**Blocker A — `calibrate()` silently discards the q3 blob.** Its dispatch
recognises `vector_scaling` and `vector_scaling_segmented`; anything else falls
through to `apply_temperature`. Measured:

```
calibrate(p, q3_blob, 1.0, eff_gap=10.0)  == apply_temperature(p, 1.0)   -> True
calibrate(p, {"method": "totally_made_up"}, ...) == apply_temperature(...) -> True
```

A q3 twin wired naively would have logged the **identity** and looked perfectly
healthy. This fallthrough is a deliberate, tested contract
(`test_calibrate_unknown_method_falls_back_to_temperature`), so it is *not*
changed here — it is fenced instead (§2).

**Blocker B — one alternative config only.** `generate_predictions` accepts a
single `baseline_params`, so it cannot log the v0.1 baseline *and* the q3
candidate at once. The four-way comparison needs both.

**Not a blocker — storage.** No migration is required:

| Comparator | Where it already lives |
|---|---|
| Production calibration | `Prediction`, `is_shadow=False` |
| Old baseline (v0.1 params) | `Prediction` `+baseline` twin (shipped in #202) |
| q3 candidate | `Prediction` `+cal_q3` twin (this design) |
| De-vigged closing odds | `Odds.implied_prob_{home,draw,away}`, `snapshot_phase='closing'` |

`Odds` already stores **margin-free** implied probabilities and a five-band
phase schedule (`opening/t24/t6/t1/closing`, `pipeline/ingest/odds_phases.py`),
captured pre-kickoff by the hourly `odds-snapshots.yml`. `Prediction` stores
`lambda_home/away` and `rho`, from which every grid-derived market is exactly
reconstructible. Nothing new is needed.

---

## 2. Design — smallest opt-in shadow twin

**`shadow_variants: dict[str, ModelParams] | None = None`** on
`generate_predictions`. `None` (the default) writes nothing.

- One extra `is_shadow=True` row per match per variant, tagged
  `{production_version}+{name}` via `variant_model_version_for` — the same
  family-scoping convention as `+avail` / `+rest` / `+bans` / `+baseline`, so a
  club variant can never pool into a WC26 ledger.
- **Fail-closed:** `write_variant_prediction` calls
  `assert_servable_calibrator` first. A calibrator `calibrate()` cannot
  genuinely serve raises, and that variant is dropped with a logged exception —
  it never aborts the pass and never touches the production row. This is the
  fence around Blocker A.
- `calibrate()` additionally learns `vector_scaling_segmented_edges`, which
  carries bucket **edges inside the blob** so a recut fitted for club gap
  distributions is expressible without mutating the module-level `_GAP_EDGES`
  every other caller buckets on. Purely additive.

### What a calibrator swap can and cannot change

| Output | Affected? | Why |
|---|---|---|
| W/D/L triple | **yes** — the point | calibration acts on it |
| Totals, BTTS, correct-score probabilities | **no, provably** | `goal_markets()` is a pure function of `(λ_h, λ_a, ρ)` |
| λ, ρ | **no** | untouched by calibration |
| **Headline scoreline shown to users** | **YES** | `predict_from_lambdas` picks it via `abs(p_home − p_away) <= DRAW_HEADLINE_BAND` on the **calibrated** triple |

That last row is a finding, not a footnote: promoting a calibrator **is a
user-visible change** even though it cannot move a single market probability.
Both properties are pinned by tests.

---

## 3. Pre-registered gates

Fixed before any live data accrues.

### Primary — paired 1X2 log loss, q3 vs production

Season-clustered where ≥2 seasons exist, otherwise matchweek-clustered
bootstrap, 2,000 resamples, on frozen pre-kickoff rows for **finished
Bundesliga matches only**.

### Minimum sample — derived from power, not optimism

Per-match SD of the q3−production log-loss delta, measured on the T1.6 scored
seasons: **0.1465**, against a mean effect of **−0.0104**. A 14:1 noise-to-
signal ratio per match. Required n for a 95% CI to exclude zero:

| Intra-matchweek ρ | Design effect | n required | ≈ Bundesliga seasons |
|---|---|---|---|
| 0.00 (iid, optimistic) | 1.00 | 759 | 2.5 |
| 0.05 | 1.40 | 1,062 | 3.5 |
| 0.10 | 1.80 | 1,366 | 4.5 |

**A single 2026-27 season (306 matches) cannot confirm this candidate.** At
n=306 the 95% half-width is 0.0164–0.0220 against an effect of 0.0104. Anyone
reading a one-season null as a refutation would be misreading an underpowered
window.

So the season-one window is pre-registered as a **monitoring** window, not a
decision window:

| Gate | Threshold | Decision |
|---|---|---|
| **Confirm** | n ≥ 759 finished Bundesliga matches **and** primary CI upper bound < 0 | Eligible for promotion review. Not automatic |
| **Rollback / abandon** | primary point estimate ≥ +0.020 at any n ≥ 306 | Disable the variant, record the refutation |
| **Continue** | anything else | Keep accruing, publish no verdict |

The +0.020 rollback trigger is deliberately set where one season *is* powered:
a half-width of ~0.0164 at n=306 detects harm of that size, even though it
cannot resolve a benefit of 0.0104.

### Secondary — reported every window, never sufficient alone

Paired multiclass **Brier** and **RPS**; **ECE + reliability curve** (T1.6's
largest effect: 0.0645 → 0.0340); **sharpness**; **market benchmark** —
de-vigged closing odds where captured, as a reference only.

### Regression checks

- Totals / BTTS / correct-score: **assert exact equality** vs production. Any
  inequality is a bug in the variant mechanism, not a result.
- Headline scoreline: report the **flip rate** vs production. Expected non-zero;
  a rate above ~15% is a promotion-blocking product concern.

### Data validity — BOTH sides are time-filtered

**Predictions.** Production and variant rows must each carry a non-null
`created_at` **strictly before** `kickoff_utc`; the latest admissible row on
each side is used, and if either side has none the pair is **omitted**.

This is not belt-and-braces. The writer guards only on `status == 'scheduled'`,
and a delayed status refresh leaves a finished match in that state — so a row
appended after kickoff is possible, and since selection is newest-first it
would have been the one chosen. Found in independent diff review; the earlier
cut filtered odds by time but not predictions.

**Odds.** Only `snapshot_phase='closing'` with `captured_at < kickoff_utc`.
`Odds.captured_at` is nullable, so the null guard does real work there; on
`Prediction` the column is `NOT NULL`, so the equivalent guard is defensive
only — a test documents that distinction so it is not "simplified" away.

Nothing is clamped or repaired. An inadmissible row is dropped and the
comparison shrinks. A missing comparison is honest; a post-kickoff one is not.
The run output states the filter on every report.

**The consumed 2025-26 holdout is never read.** T1.6's 27-file manifest scope
(`pre_confirmation_keys()`) applies to any offline re-fit.

---

## 4. Rollback

The variant is `is_shadow=True` and never served, so rollback is removing a
keyword argument — no deploy semantics, no data repair, no user impact.

1. Drop `shadow_variants` from the league call site.
2. Variant rows stay in place; they are historical evidence, and the ledger is
   append-only.
3. Record the outcome in `docs/MODEL-EXPERIMENTS.md`, win or loss.

A **production** rollback is not in scope because nothing production changes.

---

## 5. Operational activation — stated honestly

### Merging this changes nothing that accrues data

`PIPELINE_TARGET` is `wc26`. The league branch of `run_pipeline` — the only
place `club_shadow_variants_for` is called — **does not execute in production**.
So merging this infrastructure, with or without the flag set, accrues **zero
Bundesliga pairs**. `/api/health` confirms production serves
`poisson-elo-v0.5` against the 104-match WC26 ledger.

Data accrual needs, in order: (1) `PIPELINE_TARGET` flipped to the league path
— its own stop-gated decision, not requested here; (2) the flag set; (3) the
2026-27 season to actually play. Item (3) alone is 2.5–4.5 seasons at the
required n. **This branch buys readiness, not evidence.**

### The flag

`CLUB_SHADOW_VARIANTS`, comma-separated `league:variant`. Unset = off, the
shipped default.

```
CLUB_SHADOW_VARIANTS=bundesliga:cal_q3
```

Enablement is filtered through `AVAILABLE_SHADOW_VARIANTS`, which contains
**only** `bundesliga: {cal_q3}`. EPL and La Liga are excluded *structurally*,
not by configuration — no env value can name a variant that does not exist, and
neither league has a reviewed artifact because neither cleared T1.6's
multiplicity-corrected gate. WC26 is untouchable for a second, independent
reason: it runs the other pipeline branch entirely. Four tests pin this.

### The artifact

`ml/models/calibrators/bundesliga_q3.json`, fitted **once** on exactly the 27
manifest-verified 2016-17…2024-25 captures via
`pipeline/fit_club_calibrator.py`. Edges `[69.9, 167.3]`, occupancy
919/918/917, no thin buckets, `n_train=2754`. Provenance records the seasons,
the excluded holdout, the engine it was fitted against, a digest over the 27
manifest hashes, and the reproduction command. If upstream revises a season
file the digest moves and a test fails — the artifact is then stale, not merely
old. T1.6's archived nested results are **not** restated; they refit per outer
season and are a different object.

### Failure isolation

Each variant write runs inside a **SAVEPOINT** (`db.begin_nested()`). A plain
try/except is insufficient: a database-level failure leaves the *session*
unusable, so production rows added earlier in the same transaction would fail
to commit — the shadow would take serving down with it. A test forces a real
`IntegrityError` inside the variant write and asserts production still commits
byte-identically and the session stays usable.

## 5b. Operator runbook

**Enable** (single environment, still shadow-only, still no data unless
`PIPELINE_TARGET` is on the league path):

```bash
CLUB_SHADOW_VARIANTS=bundesliga:cal_q3
```

**Verify after the first league pipeline run:**

1. `SELECT model_version, is_shadow, count(*) FROM predictions GROUP BY 1,2;`
   — expect `poisson-elo-club-v0.2+cal_q3`, `is_shadow=true`, count equal to
   the Bundesliga production row count.
2. Production row count and probabilities unchanged from the prior run.
3. At least one match where the `+cal_q3` triple differs from production. If
   none differ the calibrator was discarded — stop and investigate.
4. `GET /api/health` unchanged.

**Read the benchmark** (safe to run any time; honest-empty until pairs exist):

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_calibrator_benchmark --variant cal_q3
```

It reports paired log loss / Brier / RPS / ECE / sharpness, headline flip rate,
grid-equality status, the closing-market benchmark, and the pre-registered
verdict: `insufficient` · `continue_underpowered` · `continue` ·
`confirm_eligible` · `rollback`.

**On alarm** — `grid equality: VIOLATED` (a mechanism bug, not a result),
variant row count ≠ production count, or identical triples — unset the flag,
then investigate. A quiet shadow is worse than no shadow.

## 6. Out of scope

Promotion of any calibrator · EPL and La Liga · xG / GBM · `PIPELINE_TARGET` ·
schema migrations · flipping `PIPELINE_TARGET` · activating the flag.

**Resolved since the first draft:** `calibrate()`'s unknown-method
fallthrough is no longer fenced at the shadow writer — it now **raises**
globally. Validating only at the writer was insufficient, because a later
*promotion* of a mis-specified calibrator would have silently de-calibrated
production with nothing to detect it. `calibrator=None` remains the valid
scalar-temperature path; the old contract test is updated in place.
