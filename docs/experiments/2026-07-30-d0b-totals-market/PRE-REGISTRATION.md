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

---

# APPENDIX A — corrections and additions, appended before any run

**Written 2026-07-30, after a structured recon of the integration seams and
before the first benchmark run.** Appended, not edited in place, per the
standing rule. Everything above stands as written; this section says where it
was wrong and what it missed. The commit that added this appendix contains no
results either.

## A1. §4 is wrong about the nine excluded files — CORRECTION

§4 says football-data.co.uk *"published no over/under columns for them at
all."* **That is false**, and it was false when written. Verified by reading
the headers:

```
E0_1617, SP1_1718, D1_1819  ->  BbMx>2.5  BbAv>2.5  BbMx<2.5  BbAv<2.5
```

All nine 2016-17…2018-19 captures carry a **Betbrain** over/under pair — a
market maximum and a market average. What they do not carry is a **closing**
totals family: there is no `C`-suffixed totals column in any of them.

The nine files stay excluded, and the row counts, the 6,395 total, and the
99.98% in §4 are all unaffected — but the *reason* changes, and it changes from
a weaker claim to a stronger one. They are excluded by §9's closing-line rule,
which is a rule this program chose, not by an absence in the source data.

That distinction is load-bearing, because it converts a fact into a
temptation. Betbrain totals would widen the sample from 6,395 to roughly
9,590 — a ~50% increase — and every one of those added rows would be
**pre-closing**. Taking them would reproduce D0's founding defect exactly: a
pre-closing market reported as a closing-line benchmark. So:

- `BbMx` and `BbAv` are **never** added to the closing totals families.
- A test asserts all nine captures raise `ClosingTotalsUnavailable`, so
  including them later requires a visible code change and cannot happen by
  drifting a default.
- If a future phase wants them, it scores them in a separate, separately
  labelled `pre_closing` column and never pools the two.

## A2. The model column is IN-SAMPLE, and §4's split does not fix it

§4 splits the seasons so the **constant** baseline is fitted out-of-sample.
That is necessary and it is not sufficient, because it says nothing about the
model.

T1.1 selected `base` on **O/U 2.5 log loss** — this phase's exact metric —
over seasons **1718–2425**. D0-B scores **1920–2425**, a strict subset.
Therefore EPL's `base = 1.30` and Bundesliga's `base = 1.44` were *chosen on
the data they are about to be scored on*, on the same metric. The 1X2 benchmark
had no such alignment; this one does.

Consequences, pre-registered now:

- **A model-beats-market totals result is inflated by construction** and may
  not be read as an edge. Any write-up that omits this sentence is wrong.
- O4 already scores `base = 1.20` alongside the shipped value. Its status is
  hereby upgraded from "descriptive re-measurement" to **the primary control**:
  `pipeline.leagues.club_baseline_params_for(code)` is out-of-sample with
  respect to T1.1, the shipped column is not, and **the difference between the
  two columns is a measurement of the in-sample advantage, not of skill.**
- The only clean holdout for totals is 2026-27. `2526` is consumed. This phase
  therefore yields **information, not a decision** — which §12 already required
  for other reasons, and now requires for this one too.

## A3. Dixon–Coles ρ is exactly vacuous on this market — measured, pre-run

τ touches only the cells (0,0), (0,1), (1,0), (1,1), every one of which has a
total ≤ 2, and τ is mass-preserving, so it moves neither the numerator nor the
denominator of P(total ≥ 3). Measured across ρ ∈ {0, −0.06, −0.20}:

| λ pair | max |Δ P(over 2.5)| |
|---|---|
| (1.80, 1.20) | `0.000e+00` |
| (2.40, 0.70) | `0.000e+00` |
| (1.44, 1.44) | `0.000e+00` |
| (1.05, 2.05) | `0.000e+00` |

Not "negligible" — **exactly zero**, bit-for-bit. The served `rho = −0.06`
cannot affect any number this phase reports. A ρ-invariance test is added so a
future ρ change cannot silently move a recorded totals number, and so this
claim is checked rather than trusted.

## A4. `λ_h · λ_a ≡ base²` — measured at every served base

Confirmed to 10 decimal places at `base` ∈ {1.20, 1.30, 1.44} and rating gaps
{−300, 0, +150, +400}. The instructive part is the **sums**:

| base | total at parity | total at a 400-pt gap |
|---|---|---|
| 1.20 (La Liga) | 2.400 | 3.298 |
| 1.30 (EPL) | 2.600 | 3.573 |
| 1.44 (Bundesliga) | 2.880 | 3.957 |

The engine can only predict a high-scoring match by predicting a **mismatch**.
Two evenly-matched high-scoring teams receive the league floor. Recorded here
as a measured property of the served code, before any market comparison — so
that if the totals gap turns out large, this is a pre-existing observation
rather than a story assembled to explain it. It remains **out of scope** (§14):
no tempo channel is built in this phase.

## A5. `pipeline/run_club_benchmark.py` scores a model nobody serves

[`pipeline/run_club_benchmark.py:98`](../../../pipeline/run_club_benchmark.py)
calls `model_probs(rep["pre_home"], rep["pre_away"], False)` — three positional
arguments, every keyword left at its default. Those defaults
([`ml/evaluation/backtest.py:22-26`](../../../ml/evaluation/backtest.py)) are
`base = 1.35`, `beta = 0.0019`, `home_adv = HOME_ADVANTAGE`, `rho = 0.0`,
`temperature = 1.0`, **and no calibrator**.

Production serves `base` 1.30 / 1.20 / 1.44, `beta = 0.0021`, `rho = −0.06`,
`home_adv` 60 / 80 / 60, and a segmented vector-scaling calibrator. The two
configurations share no parameter except `home_adv`, and only for two leagues.

D0-B therefore **does not reuse that call site**. It builds its model column
from `pipeline.leagues.club_params_for(code)` and
`LEAGUES[code]["home_advantage"]`, and writes the resolved parameters into the
receipt so the scored configuration is stated rather than assumed.

Whether the 1X2 closing-line gaps recorded in `docs/MODEL-EXPERIMENTS.md`
(+0.0312 / +0.0279 / +0.0326) came from this runner or from the separate audit
harness is **not yet established**, and D0-B does not assume it. It is logged
as an open question for the human; if they did come from here, those three
numbers describe an unserved model and need restating. D0-B neither fixes that
runner nor edits those numbers — out of scope, and not this phase's call.

## A6. Two traps that would silently corrupt the run

**A6.1 — a corrupt price that the guard catches.** `D1_1920.csv` line 261,
`01/06/2020 FC Koln 2–4 RB Leipzig` (six goals, an Over), carries
`AvgC>2.5 = 0.42`. A decimal price below 1.0 is not a price. Without the
existing `min(...) <= 1.0` guard the proportional de-vig gives
`p_over ≈ 0.871` on a match that was over — scoring as one of the market's
best predictions of the decade. This is D0's NaN finding (P1) arriving through
a different door, and it is the single row missing from §4's 6,396.

Note `PC>2.5 = 1.47` on the same row: the match **is** recoverable from
Pinnacle. It will not be recovered. Per-file family selection is fixed by §9;
switching family per row would compose the market series out of whichever book
happened to be clean, which is a selection effect concentrated on exactly the
rows the publisher got wrong. The row is dropped and counted.

**A6.2 — a loader that would fetch the burnt holdout.**
`pipeline/experiment_club_eval.py::load_matches` iterates `SEASON_CODES`, which
includes `"2526"`, and **falls back to a live network download when the cached
file is absent**. The three `*_2526` captures are not on disk. Pointing that
loader at `data/raw/club` would download the consumed confirmation season.

D0-B does not reuse it. It uses a scoped loader over `pre_confirmation_keys()`
with **no network fallback**, and a test monkeypatches `urlopen` to fail the
test if any fetch is attempted.

## A7. Interval choice — restated, because the recon disagreed with it

The recon recommended season-clustered as primary. §11 declared
**iso-week-clustered** as primary, with season-clustered reported alongside.

§11 stands. Six season-clusters per league under-covers badly, and the repo's
own precedent chose the calendar week for exactly this reason
(`docs/MODEL-EXPERIMENTS.md`: *"one held-out season is a single season-cluster,
so a season bootstrap would resample the same cluster every draw and return a
zero-width CI"*). Changing the primary after seeing an argument for the other
one — with no result yet in hand — is still the shape of post-hoc selection,
and both intervals are reported either way. This paragraph exists so the
disagreement is on the record rather than resolved silently.
