# D1 — SELECTION pre-registration

**This file is committed alone, in its own commit, before any selection run or
effect measurement exists.** That is the entire reason it is a separate file
rather than a section of `PRE-REGISTRATION.md`: that document landed in the
same commit as the results it governed (`6b7c875`), so its chronology could not
be checked. This one can be.

**No selection has been run at the time of this commit.** If a later commit
adds results, the chronology is verifiable from `git log` alone.

Supersedes `PRE-REGISTRATION.md` §5–§6 for selection purposes. Master ledger:
[`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

---

## 0. Preconditions — none of this runs until all four hold

1. This commit exists and is pushed. ✅ (that is what this file is)
2. The venue-time corrections (interval lookup, abstention, named exclusions,
   raw-snapshot receipt) have passed an independent adversarial review.
3. The full test suite and CI are green.
4. The candidate is not blocked by §2.

## 1. What can and cannot be run

The correction round measured travel coverage at **2.17%** — 208 of 9,594
fixtures — because Wikidata carries a `P115` date qualifier for only 11 of 94
clubs. That is a sample problem, not a tuning problem.

| ID | Candidate | Status | Why |
|---|---|---|---|
| **D1.1** | Travel distance (raw km) | **BLOCKED** | 208 usable fixtures across three leagues, 14 of them in E0 and 14 in D1. No grid can be fitted on that, and a walk-forward needs the sample *per training block*, which is smaller still |
| **D1.2** | Travel, `log1p(km)` | **BLOCKED** | same sample |
| **D1.4** | Travel × short rest | **BLOCKED** | strictly smaller sample than D1.1 |
| **D1.3** | **Congestion differential** | **ELIGIBLE** | needs no coordinate; 100% of fixtures have a defined value |

**Only D1.3 is eligible.** Blocked candidates are not re-scoped, re-shaped or
re-fitted on a subset to make them runnable — that would be selecting a
candidate on the basis of which data happened to survive.

## 2. Stop conditions — declared before the run

Selection halts and reports, rather than continuing, if any of these fire:

- **S1 — sample floor.** Any scored season with fewer than **250 fixtures** for
  a league, or fewer than **6 scored seasons** for that league, is not scored.
  A league that cannot reach both is dropped and named.
- **S2 — coverage floor.** A candidate whose feature is defined for **< 90%** of
  the fixtures in a training block is not fitted on that block.
- **S3 — degenerate response.** If the fitted coefficient sits on a grid
  boundary for a majority of blocks, the grid was mis-specified; the result is
  recorded as inconclusive rather than reported as a pick.
- **S4 — vacuity.** If a parameter provably has no effect on output (the trap
  T1.4 fell into, where `temperature` was a no-op under the served calibrator),
  the candidate is recorded as vacuous and not reported as a null result.
- **S5 — any need to widen the family, change a grid, or add a candidate after
  seeing a number.** Such a change requires a new, explicitly post-hoc file.

## 3. Candidate specification — exact and frozen

### D1.3 — congestion differential

- **Feature.** `congestion_diff = matches_played_by_home_in_trailing_14d −
  matches_played_by_away_in_trailing_14d`, counted from **prior fixture dates
  only**, window inclusive at the far edge (a match exactly 14 days earlier
  counts). Implemented in `ml/features/schedule_context.py`.
- **Application.** A symmetric bounded log-λ offset, the same shape
  `ml/models/rest.py::rest_offsets` already uses: `x = clamp(coef ×
  congestion_diff, −cap, +cap)`, applied as `(+x/2, −x/2)` so the total-goals
  level is preserved and only the balance moves.
- **Grid, frozen.** `coef ∈ {0.000, 0.005, 0.010, 0.015, 0.020, 0.025, 0.030,
  0.035, 0.040, 0.045, 0.050, 0.055, 0.060}` × `cap ∈ {0.05, 0.10}`.
  **26 points.** No other value is evaluated.
- **Control.** Served parameters with the offset disabled (`coef = 0`), which
  is inside the grid so the candidate must beat its own null.

**This is not T3.2.** T3.2 tested *gap length* — days since the last match,
clipped to a 2–8 day window — and was refuted in all three leagues. D1.3 tests
*load* — how many matches were played in a fixed window. A side on its third
match in fourteen days is congested even when its last gap was four days, and
the two features are not monotone transforms of one another. T3.2 is **not**
re-run, and no result below may be cited as revisiting it.

## 4. Temporal split — fixed before the run

- **Selection:** walk-forward over **2016-17 … 2024-25**. Each scored season is
  fitted only on seasons **strictly before** it. The first season can never be
  scored — nothing precedes it.
- **Confirmation:** **none is available.** 2025-26 is the consumed #202
  holdout; 2026-27 is in progress. The confirmation slot is left empty on
  purpose rather than filled with a season that has already been used.
- **The 2025-26 captures are neither read nor hashed.** Scope is
  `pipeline.club_data_manifest.pre_confirmation_keys()` (27 files).

## 5. Metric

- **Primary:** 1X2 **log loss against realized outcomes**, paired per match
  against the control.
- **Reported alongside, never as the gate:** the de-vigged closing-line
  benchmark from D0, on the same matches, as context only. Odds are a
  benchmark; no candidate reads them.
- **Secondary, reported for completeness:** ECE. A candidate that improves log
  loss while degrading calibration is reported as such — the failure #202's
  `base` change produced and only the post-merge audit caught.

## 6. Uncertainty and multiplicity

- **Resampling unit: the season.** Matches inside a season share a rating
  snapshot, so the season is the honest cluster. Season-clustered bootstrap,
  **2,000 resamples**, seed fixed at **26** (the repository's convention).
- **Multiplicity.** One eligible candidate over three leagues = **3 tests**.
  CIs are reported **nominal and Bonferroni-corrected at k = 3**. The corrected
  interval is the one a ship decision would have to clear.
- **No pooling across leagues.** Each league is scored separately.

## 7. Missingness

- Openers have no rest and no prior fixtures; congestion is **0**, which is a
  real count, not a fill.
- A fixture whose feature is undefined is **excluded and counted**, never
  imputed.
- Travel is **not** used, so its 2.17% coverage does not enter here.
- Exclusion counts are reported per league with denominators; the reasons must
  sum exactly to the shortfall.

## 8. Decision rule — and there is only one outcome available

**Nothing is promoted, whatever the result.** Promotion requires clearing the
out-of-sample gate on a clean confirmation season, and none exists. A candidate
whose Bonferroni-corrected CI excludes zero in its favour is recorded as
**"selected, awaiting the 2026-27 holdout"** — not shipped, not enabled behind
a flag, not defaulted on.

This is a hard constraint, not a preference. Stating it before the run removes
the incentive to argue toward a favourable number: there is nothing to win.

## 9. What is recorded

Every outcome, including a null. The selection result, the per-season deltas,
the coverage tables with named exclusions, and the reproduction command land in
`SELECTION-RESULT.md` in this directory. If a stop condition fires, that is the
result and it is recorded as one.
