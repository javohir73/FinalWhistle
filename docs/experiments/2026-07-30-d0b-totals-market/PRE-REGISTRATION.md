# D0-B — Totals market validation: PRE-REGISTRATION

**Written 2026-07-30, before any benchmark run.** Committed alone, pushed, and
only then run. That discipline exists because D1's first pre-registration
landed in the same commit as its own results, which made its ordering claim
unverifiable and forced a withdrawal; D1 then re-registered in a commit of its
own. Both commits live on the `claude/finalwhistle-d1-rest-travel` branch and
are **not reachable from `main`** — see the note below. Appended to afterwards;
never edited in place.

**Base.** This phase branches from `main` at `87e69eb`, the squash-merge of D0
(#213). It depends only on D0's loader and benchmark code, which is in `main`.
It has no dependency on D1.

> **Branch-state note, recorded because it affects what a reader can verify.**
> PR #214 (D1) reports `MERGED`, but it was merged into
> `claude/finalwhistle-data-validation-2b6db1` — the D0 *branch* — at
> 00:51:36Z, six minutes after #213 had already squash-merged that branch into
> `main` at 00:45:32Z. D1's commits therefore reach no branch that feeds
> `main`, and none of its files (`pipeline/ingest/venue_coordinates.py`,
> `ml/features/schedule_context.py`, `pipeline/data/club_venues.json`) are
> present in `main`. This is stated as an observation for the human to resolve.
> D0-B neither depends on nor repairs it.

Master ledger: [`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

**Odds are a BENCHMARK ONLY.** No part of D0-B lets a price become a training
feature, a label, or a served number. That is a structural constraint, tested
(§8), not a promise.

**This phase selects nothing.** It is a measurement. §12 states the
no-promotion rule, and there is no path around it.

---

## 1. Why this phase exists

D0 established that the #202 club program never computed a market comparator,
and supplied one — **for 1X2 only**. The correction it appended to
`docs/MODEL-EXPERIMENTS.md` says why the odds were unavailable at all:

> No de-vigged closing-line comparator was computed at any point in the
> original program — the club CSV cache was built with
> `usecols=[Date,HomeTeam,AwayTeam,FTHG,FTAG]`, so the odds columns never
> reached disk.

That `usecols` list excluded the over/under columns exactly as it excluded the
1X2 ones. D0 recovered the 1X2 market. **The totals market has still never been
computed in this repository.**

This is not a cosmetic gap. `base` is the *only* engine parameter ever gated on
a totals metric (`docs/MODEL-EXPERIMENTS.md`, "Metric → Parameters gated on
it": **O/U totals log loss → `base`**). Both of its shipped per-league
overrides were justified against a **constant**, and the production code says
so in its own comments:

- [`pipeline/leagues.py:98-101`](../../../pipeline/leagues.py) — EPL `base`
  1.20 → 1.30: *"Defect-fix bar: the served internationals base left EPL's O/U
  2.5 book LOSING to a constant (LL 0.6955 vs 0.6893)."*
- [`pipeline/leagues.py:144-147`](../../../pipeline/leagues.py) — Bundesliga
  `base` 1.20 → 1.44: *"a -16.7% totals bias that left the O/U book losing to a
  constant (LL 0.7001 vs 0.6738)."*

A constant is a floor, not a yardstick. "Better than a constant" and "closer to
the market" are different claims, and only the second one says whether the
totals book is any good. Bundesliga's `base` refit confirmed on held-out data
at −0.0447 O/U LL — against a constant. Whether it *closed the gap to the
closing line* or merely cleared a floor is, as of this writing, unknown.

Two further facts, both established before this document was written and both
recorded here so the run cannot be accused of finding what it went looking for:

- **The model side already exists and is uncalibrated.**
  [`ml/models/poisson.py:107`](../../../ml/models/poisson.py) `goal_markets()`
  returns `total.over_2_5`, marginalized from the *normalized Dixon–Coles
  grid*. The 1X2 triple in `predict_from_lambdas` then passes through
  `calibrate()` (segmented vector scaling); `goal_markets` does not. The served
  totals number is therefore uncalibrated where the served 1X2 number is
  calibrated. This is a fact about the code, recorded now, not a finding.
- **The engine has no per-team tempo channel.**
  [`ml/models/poisson.py:64-65`](../../../ml/models/poisson.py) sets
  `lam_home = base·exp(β·diff)` and `lam_away = base·exp(−β·diff)`, so
  `lam_home · lam_away ≡ base²` identically and the expected total is
  `2·base·cosh(β·diff)` — a function of the rating gap alone. The optional
  attack/defence offsets that could break that symmetry are `"team_offsets":
  null` in [`ml/models/model_params.json`](../../../ml/models/model_params.json)
  and their store is absent from disk, so they contribute exactly zero in the
  served configuration. Whether this costs anything measurable against the
  market is the question §2 asks; it is **not** assumed here.

## 2. Measurable objective

For each of the three activated leagues, and pooled, compute and record:

**O1.** The paired per-match difference in binary log loss between the served
model's `P(over 2.5)` and the de-vigged closing over/under 2.5 line, over every
match where both exist.

**O2.** The same quantity for a **constant-rate** predictor, so the existing
recorded constant-relative numbers are reproduced on this exact sample and the
new market-relative number can be read against them on one scale.

**O3.** The **totals information budget**: market LL minus constant LL. This is
how much a perfectly-informed public predictor knows about totals beyond the
base rate. O1 divided by O3 is the share of available totals information the
served model captures — the number that makes the totals gap comparable to
D0's 1X2 gap.

**O4.** Per-league, whether the shipped `base` override moved the model toward
or away from the market on totals, computed by scoring the *same* matches under
`base = 1.20` (the pre-override global) and under the shipped per-league value.
This is a **descriptive re-measurement of an already-shipped decision**, not a
new selection; see §12.

**O5.** Coverage and every exclusion, attributed by reason and summing exactly
to the shortfall.

## 3. Baselines

Three, all reported, none optional:

| Baseline | Definition |
|---|---|
| **Constant rate** | `P(over) = r` for a fixed `r`, where `r` is the over-2.5 rate of the **training portion only** (§4 split), never the pooled rate of the scored sample. An in-sample base rate would flatter the constant and understate the model. |
| **Market** | De-vigged closing O/U 2.5 (§10). The yardstick. |
| **Served model** | `goal_markets(...)['total']['over_2_5']` under `club_params_for(code)` — the exact per-league configuration in production today, including the `base` overrides. |

## 4. Scope, and the exact split

**Files in scope: 18 of the 27 pre-confirmation captures.** The nine excluded
are excluded *structurally* — football-data.co.uk published no over/under
columns for them at all:

`E0_1617`, `E0_1718`, `E0_1819`, `SP1_1617`, `SP1_1718`, `SP1_1819`,
`D1_1617`, `D1_1718`, `D1_1819`

The remaining 18 are the six seasons `1920, 2021, 2122, 2223, 2324, 2425`
across `E0`, `SP1`, `D1`. Measured usable rows (both sides priced, non-NaN,
both > 1.0), recorded here before the run:

| League | 1920 | 2021 | 2122 | 2223 | 2324 | 2425 | total | over rate | iso-week clusters |
|---|---|---|---|---|---|---|---|---|---|
| D1 (Bundesliga) | 305 | 306 | 306 | 306 | 306 | 306 | **1,835** | 0.6082 | 195 |
| E0 (EPL) | 380 | 380 | 380 | 380 | 380 | 380 | **2,280** | 0.5500 | 212 |
| SP1 (La Liga) | 380 | 380 | 380 | 380 | 380 | 380 | **2,280** | 0.4605 | 210 |
| **pooled** | | | | | | | **6,395** | 0.5348 | |

6,395 of a possible 6,396 — one 2019-20 Bundesliga row carries no `AvgC` price.
Coverage on the in-scope files is **99.98%**. This is a materially different
situation from D0's 1X2 case and is stated plainly so no later phase mistakes
it for one: the totals gap is *whole seasons absent*, not *matches missing*.

**Confirmation-season quarantine.** `CONFIRM_SEASON` (`2526`) is not on disk
and is not in scope. Every in-scope file is pre-confirmation. The quarantine
cannot be violated by this phase, and a test asserts the scored file list
contains no confirmation-season key.

**Split.** Because the constant baseline needs a rate fitted somewhere, and a
rate fitted on the scored sample is circular:

- `1920`–`2223` (four seasons) fit the constant rate.
- `2324`–`2425` (two seasons) are scored.
- The **model and market are scored on the same two seasons**, so all three
  predictors face an identical sample.
- The pooled all-six-season numbers are **also** reported, clearly labelled
  in-sample-for-the-constant, because the recorded #202 numbers are
  all-seasons and a reader must be able to line them up.

No parameter is chosen on either portion. This split exists to keep the
constant honest, not to select anything.

## 5. Acceptance criteria

This phase "succeeds" if it produces trustworthy numbers, **not** if the
numbers are favourable. Concretely, all of:

- **A1.** Every scored match traces to a file SHA-256 recorded in the receipt.
- **A2.** Usable + every named drop reason = total rows, exactly, per file.
- **A3.** The market side is labelled with its actual basis and column family;
  a pre-closing family is never reported as closing (D0's A3 defect).
- **A4.** The constant-rate LL recomputed here reproduces the recorded #202
  scoping numbers to within rounding on the comparable sample, or the
  discrepancy is diagnosed and recorded.
- **A5.** The leakage tests in §8 pass.
- **A6.** The run is reproducible offline from committed fingerprints and a
  fixed seed, and the receipt states the exact command.
- **A7.** A null or unfavourable result is recorded with the same prominence as
  a favourable one.

## 6. Data fingerprint

The CSV bytes are **not** committed — stop gate **G1** is open and unresolved
(`docs/DATA-VALIDATION-PROGRAM.md`). D0 already measured the cost of that: all
27 pinned captures have drifted and the #202 numbers cannot be reproduced
byte-for-byte. D0-B inherits the same limitation and does not re-litigate it.

What is committed: per-file SHA-256, byte size, row count, header column list
restricted to the O/U and identity columns, retrieval date, and the manifest
drift status at run time. A number without this receipt is an anecdote.

## 7. Missingness policy

- A match missing either O/U price on the selected family is **dropped and
  counted**, never imputed, never given the base rate.
- A file missing the O/U columns entirely is **excluded as a file**, named in
  §4, and its match count reported — not silently absent from a denominator.
- Every drop carries a reason from a closed set: `no_ou_columns`,
  `blank_price`, `non_positive_price`, `unparseable_date`, `unjoined`.
- Reasons sum exactly to the shortfall. A run where they do not is a failed
  run, not a run with a footnote.

## 8. Leakage audit

The totals benchmark introduces a leakage risk the 1X2 one did not: the O/U
price is a direct read on expected total goals, which is the quantity `base`
controls. A path from the price into `base` would be self-fulfilling.

- **L1.** `pipeline/market_leakage_test.py` must show no import path — direct,
  relative, dynamic, or transitive — from any odds-carrying module into
  `ml/ratings`, `ml/features`, or `ml/simulate`. The new totals module is added
  to `_BENCHMARK_MODULES`; a new module that reads odds and is *not* registered
  fails the test.
- **L2.** The de-vigged market probability must not appear in any argument to
  `goal_markets`, `expected_goals_from_elo`, `score_matrix`, or
  `club_params_for`. Asserted by test, not by inspection.
- **L3.** Truncation invariance: scoring match *n* with the fixture list
  truncated at *n* gives the same model probability as scoring it with the full
  season present. Elo is path-dependent and pre-match ratings must stay
  pre-match.
- **L4.** The constant rate is fitted on `1920`–`2223` only. A test asserts the
  fitting sample and the scoring sample are disjoint.
- **L5.** The existing deliberate exception is unchanged and still default-off:
  `ml/models/odds_blend.py` with `w_odds` / `use_odds`
  (`"use_odds": false` in `model_params.json`). D0-B does not touch it, enable
  it, or benchmark it.

## 9. Timestamp and closing-line rules

- Only the **`C`-suffixed** families are closing. `AvgC>2.5` / `AvgC<2.5` is
  primary, matching D0's 1X2 choice so the two gaps are measured against the
  same book. `MaxC`, `PC`, `B365C` are reported as a **sensitivity axis only**.
- `Avg>2.5` / `Avg<2.5` (no `C`) is **pre-closing** and is never the primary.
  If it is ever scored it is labelled `pre_closing` in the output.
- A family is selected per file from the header, and the selection is recorded
  per file. Silent fallback from closing to pre-closing — D0's finding — must
  not recur here, and a test pins it.

## 10. De-vigging

Two-way proportional: `p_over = (1/o_over) / (1/o_over + 1/o_under)`. This is
[`ml/evaluation/market_benchmark.py::devig2`](../../../ml/evaluation/market_benchmark.py),
which already exists and is already tested; D0-B is its first caller.

Proportional is the primary and stays the primary — D0 measured the three-way
de-vig sensitivity at ≤ 0.0007 nats and a two-way market has strictly less room
for the method to matter, having one fewer degree of freedom in the overround
split. A **Shin two-way sensitivity is nonetheless computed and reported**, so
the headline cannot be said to rest on an arbitrary normalization. No method is
ever selected because it flatters the model.

The measured booksum per family is reported. An underround family (booksum
< 1) falls back to proportional explicitly and is labelled, never silently.

## 11. Uncertainty, and what the sample can actually resolve

**Primary interval: iso-week-clustered paired bootstrap**, 2,000 resamples,
seed 26. Resampling unit is the calendar week, following the repo's own
precedent and its stated reason (`docs/MODEL-EXPERIMENTS.md`): a week respects
the short-range correlation between matches sharing a rating snapshot. Six
seasons give 195–212 week-clusters per league.

**Sensitivity: season-clustered**, same seed, reported alongside — with the
explicit caveat that **six clusters under-covers** and its interval is not the
one to quote. Declaring both here, with the primary named, is what stops the
narrower one from being picked afterwards.

**Resolution, pre-committed.** The naive minimum detectable effect at 80% power,
two-sided α = 0.05, is `MDE = 2.80 · sd / √n` where `sd` is the **realized**
paired per-match log-loss difference. That formula is fixed now; `sd` is not
known yet and will be reported. The clustered CI half-width is reported
alongside it and is the honest resolution, since clustering inflates it.

D0's power finding applies directly and is restated so it cannot be forgotten:
on the 1X2 paired sd of ≈0.167, resolving 0.003 nats needs ≈24,000 matches.
**If the realized totals CI half-width exceeds the observed effect, the result
is "unresolved at this sample size" — which is a finding, not a failure, and is
recorded as such.**

**Multiplicity.** Three leagues are reported. No family-wise claim is made and
no candidate is selected, so no Bonferroni correction is applied — instead,
each league's interval is explicitly labelled as one of three, and **no
sentence in the write-up may claim "the model beats the market on totals" on
the strength of one league clearing while two do not.**

## 12. No-promotion rule

**Nothing in this phase may change a served parameter, and no result here is a
licence to change one.**

Specifically, and without exception:

- O4 re-measures the already-shipped `base` overrides against the market. If
  that re-measurement is unfavourable — if `base` 1.44 turns out to have moved
  Bundesliga *away* from the closing line while moving it toward a constant —
  the correct output is **a recorded finding and a stop**, handed to the human.
  It is not a revert, and it is emphatically not a re-tune.
- If the market-relative totals gap is large, the correct output is a recorded
  measurement. Any candidate that then proposes to close it needs its own
  pre-registration, its own clean holdout, and the existing out-of-sample gate.
- The next clean holdout is the live **2026-27** season. `2526` is consumed. A
  phase that cannot reach a clean holdout **does not ship** — standing rule 2.
- No `base`, `beta`, `rho`, calibrator, or `leagues.py` override is edited on
  this branch. A test asserts `pipeline/leagues.py` and
  `ml/models/model_params.json` are byte-identical to `main` at the merge base.

## 13. Stop gates for D0-B

| Gate | Status entering the phase | Fires if |
|---|---|---|
| **G1** — redistribution of football-data.co.uk bytes | **OPEN, deferred** | D0-B commits fingerprints only, exactly as D0 did. It does not vendor bytes and does not reopen the question. |
| **G2** — paid data | not reached | No paid call. The already-on-disk CSVs are the only source. |
| **G3** — enabling capture | not reached | No capture, no schedule, no credential. |
| **G4** — production write / migration | not reached | No schema, no served number, no parameter change (§12). |
| **G5** — *new* — unfavourable re-measurement of a shipped decision | not reached | If O4 shows a shipped `base` override is market-negative, the run **stops and reports**. The agent does not decide what to do about a production parameter. |

## 14. Explicitly NOT in D0-B

- Any change to a served parameter, artifact, or league override (§12).
- Any totals **candidate** — per-team tempo, bivariate Poisson, a totals
  calibrator, market-anchored lambdas. The structural observation in §1 is
  recorded as a fact about the code; acting on it needs its own
  pre-registration.
- Asian handicap. The columns are on disk in the same 18 files and are
  deliberately left for a later phase, so this one stays cheap and falsifiable.
- Enabling, benchmarking, or touching `odds_blend` / `w_odds` / `use_odds`.
- Any file owned by the scope guards: PR #203's paths, the T1.6 calibrator
  area, or `pipeline/run_calibrator_benchmark.py` and the frozen q3 baseline.
- D1's venue and travel work. Unrelated; separate branch, separate PR.
