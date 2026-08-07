# E1 — a tempo channel for the club engine: SELECTION PRE-REGISTRATION

**Written 2026-07-30. Committed alone, pushed, before any E1 code or any E1
run exists.** Branched from `main` at `87e69eb`, not from the D0-B branch —
stacking a phase on an unmerged branch is what orphaned D1 (PR #214 reports
`MERGED` and reaches nothing that feeds `main`). Appended to afterwards; never
edited in place.

Master ledger: [`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

**This document selects nothing and runs nothing.** It fixes, in advance, what
will be run, on what data, against what bar, and what result would end the
phase. §11 is a no-promotion rule with no path around it.

---

## 0. Preconditions — none of E1 runs until all four hold

1. **This file is committed alone and pushed.** A pre-registration in the same
   commit as its results proves nothing about ordering; D1's first one did that
   and had to be withdrawn.
2. **D0-B's finding is on the record** — [PR #215](https://github.com/javohir73/FinalWhistle/pull/215),
   CI green. E1 exists because of it.
3. **No candidate is run before §12's implementation constraints are satisfied**,
   because two of them (the `GridConfig` hashability trap and the walk-forward
   positional-binding trap) would silently produce a wrong number rather than
   an error.
4. **The Italy/France captures are NOT downloaded until this file is pushed.**
   §9 pre-registers that download and what it is for. Downloading first and
   deciding afterwards is the same defect in a different costume.

## 1. Why this phase exists — the measured finding, not a hunch

D0-B measured that the served model is credibly behind the closing over/under
2.5 line in all three leagues, and — the part that matters — that the gap
consumes almost the whole of a much smaller budget:

| League | model − market (O/U) | CI95 | 1X2 share | O/U share |
|---|---|---|---|---|
| Bundesliga | +0.0328 | [+0.0222, +0.0429] | 63.8% | −6.7% [−65.4, +22.0] |
| EPL | +0.0216 | [+0.0089, +0.0349] | 74.4% | +7.9% [−77.2, +52.0] |
| La Liga | +0.0245 | [+0.0123, +0.0367] | 83.8% | +29.5% [+4.3, +51.8] |

The share intervals are wide and only La Liga's excludes zero — that is
recorded honestly and is *not* the basis for this phase. The basis is the
resolved part: **the totals budget is 0.024–0.035 nats against 1X2's
0.116–0.133, and the model's absolute error is similar on both.**

And the cause is structural, not a tuning miss. `ml/models/poisson.py:64-65`:

```
lam_home = base * exp( beta * diff)
lam_away = base * exp(-beta * diff)
```

so `λ_h · λ_a ≡ base²` identically and the expected total is
`2·base·cosh(β·diff)` — a function of the rating gap alone, minimised at
parity. **There is no per-team tempo parameter.** D0-B's sharpest single
observation follows directly: with `base = 1.44`, Bundesliga's floor is 2.88
goals, and the model assigned P(over 2.5) below 0.5 **zero times in 612
matches**.

Real team-seasons vary far more than that allows. Measured over the nine
pre-confirmation seasons: mean total goals per team-season E0 2.84 (sd 0.37,
p10 2.32, p90 3.32), SP1 2.61 (sd 0.41), D1 3.08 (sd 0.40). Roughly a full goal
from p10 to p90, and the engine can represent none of it except by asserting a
rating mismatch.

## 2. Exploratory scoping — IN-SAMPLE, NOT GATE RUNS

Following the convention `docs/MODEL-EXPERIMENTS.md` already established for
#202. Scratch measurements were run on 2026-07-30 **before** this
pre-registration, to decide which candidate was worth registering. **No ship
decision and no result in this phase may cite them.** They are recorded so the
choice of candidate is auditable rather than presented as inspiration:

- A direct time-decayed Poisson MLE landed roughly 0.005–0.012 nats better than
  the served Elo→λ map on 1X2.
- Adding shots-on-target to goals moved a strength estimate by about −0.011
  nats, apparently by permitting a shorter half-life rather than by adding a
  separate signal.
- A single strength scalar per team beat separate attack/defence by ~0.0020 on
  **1X2** — which is a fact about the ratio, and says nothing about the sum.
- Market blending is dead: the optimal model weight was negative in all three
  leagues.

These are unregistered, in-sample, single-run numbers with no intervals. They
justify §4's candidate and nothing else.

## 3. The honest relationship to FR-5, which was REFUTED

**`pipeline/fit_attack_defence.py` already exists**, and the offsets it fits
were **refuted on 2026-07-02** (`docs/MODEL-EXPERIMENTS.md`). Re-running a
refuted candidate under a new name would be the worst thing this phase could
do, so the differences are stated here, before the run, and the reader may
judge them:

| | FR-5 (refuted) | E1 |
|---|---|---|
| Population | **International**, 18 major-finals editions | **Club**, 3 leagues |
| n | **750 matches** | **9,594 matches** |
| Matches per team per period | 3–7 per tournament | 34–38 per season |
| Metric | top-1 modal pick, exact-score NLL, 1X2 LL | **O/U 2.5 log loss** |
| Half-life | 1095 d (international squad cycle) | grid, §4 |
| Fitted on | `historical_matches` DB, pooled | per league, from CSV, offline |
| Verdict | top1 −1.47pp, NLL +0.0020, LL +0.0028 → REFUTED | to be determined |

**FR-5 was never tested on a totals metric and never on club football.** Its
refutation was on the modal exact-score pick at n=750 — a regime with 3–7
matches per team, where per-team offsets cannot be estimated at all. That is a
genuinely different question, and D0-B supplied a specific reason to ask it.

It is also possible that FR-5's refutation generalises and E1 fails the same
way. §10 pre-commits to recording that outcome as loudly as a success, and §11
forbids re-running with a widened grid afterwards.

**E1 does not modify `pipeline/fit_attack_defence.py`, `ml/models/team_offsets.py`,
or `ml/models/model_params.json`.** It writes a club-scoped fitter beside them.
`"team_offsets"` stays `null`.

## 4. Candidate specification — exact and frozen

### The parameterisation, and why it is the right one to test

Fit per-team attack `a_i` and defence `d_i` as log-λ offsets on the served
Elo-derived rates, which is FR-5's form:

```
λ_home = μ_home(Elo) · exp(a_home + d_away)
λ_away = μ_away(Elo) · exp(a_away + d_home)
```

The two derived quantities are what make this targeted rather than hopeful:

```
log λ_h − log λ_a  =  (Elo term)  +  (a_h + d_h) − (a_a + d_a)     -> 1X2
log λ_h + log λ_a  =  2·log base  +  (a_h + a_a) + (d_h + d_a)     -> TOTALS
```

`(a_i + d_i)` is **strength** and moves the ratio, which Elo already handles
well (D0-B: 64–84% of the 1X2 budget captured). `(a_i − d_i)` is **tempo** and
moves the sum, which the served engine cannot express at all. E1 is a test of
whether the second channel is worth its complexity, not of whether the first
can be improved.

### E1.1 — PRIMARY, and the only gated candidate

Club-scoped, per-league, walk-forward refit of the attack/defence offsets.

**Grid — 12 points, frozen:**

| Parameter | Values |
|---|---|
| half-life (days) | `180`, `365`, `730` |
| shrinkage denominator `n0` in `√(n_eff / n0)` | `10`, `30`, `60` |

with the existing `±0.075` log-λ cap held **fixed** at its shipped value, and
the cap deliberately not on the grid: it is the form-layer-equivalent policy
bound, and moving it would be a second candidate wearing the first one's name.

3 × 3 = 9 points. Plus 3 more: half-life `365` × `n0` `30` with the cap at
`0.05`, `0.10`, `0.15` — declared as a **cap sensitivity reported alongside**,
never as extra grid points eligible to win. **The selectable grid is 9.**

Grid points are chosen **inside** the walk-forward (a point scores season S
only if it was chosen on seasons strictly before S), which is the existing
protocol and is why the grid does not enter the multiplicity correction.

### E1.2 — SECONDARY, runs only if E1.1 clears §11

E1.1 with shots-on-target as an auxiliary observation in the likelihood.
Shots are present and parseable in **9,593 of 9,594 rows (99.99%)** across all
27 captures — verified before this document was written. Exact form is **not**
frozen here because E1.2 is conditional; if E1.1 clears, E1.2 gets its own
pre-registration commit before it runs.

### E1.3 — DECLARED OUT OF SCOPE

A direct Poisson MLE replacing the Elo→λ map entirely. The scoping run in §2
suggests it is the larger prize, and that is exactly why it does not go in the
same phase as a cheaper candidate that tests the same diagnosis: if both ran
and something improved, neither would be attributable. E1.3 waits for E1.1's
answer.

## 5. Temporal split — fixed before the run

- **Replay window:** all nine pre-confirmation seasons, `1617`–`2425`, per
  league. Elo is path-dependent; truncating the replay changes every rating.
- **Offsets refit:** walk-forward. To score season S, offsets are fitted on
  matches strictly **before** S's first kickoff, and the grid point is the one
  that won on seasons strictly before S. Nothing that scores S was fitted on S.
- **Scored seasons:** `1819`–`2425` (seven). `1617`–`1718` are burn-in — the
  first seasons have too little prior history to fit an offset at all, and
  scoring them would measure cold-start behaviour rather than the candidate.
- **`2526` is never opened.** It is consumed. `walk_forward` raises without an
  explicit opt-in that E1 does not pass and does not add.

## 6. Metric, and the guardrail that is not a second gate

**PRIMARY (the gate): O/U 2.5 log loss vs realized outcomes**, per league,
per-match paired delta against the served control. This is `loss_totals`, the
metric T1.1 was gated on, so E1's number is comparable to the recorded one.

**GUARDRAIL (non-inferiority, not a gate): 1X2 log loss vs realized outcomes.**
A candidate that buys totals by giving up 1X2 has moved the problem, not solved
it. E1.1 fails if its 1X2 delta is **credibly worse** — i.e. the iso-week CI is
entirely above zero. A 1X2 CI straddling zero passes the guardrail; a
1X2 *improvement* is reported and claimed for nothing.

**REPORTED, never gating:** both metrics against the de-vigged closing line via
D0-B's harness, so E1's effect can be read against the budget rather than only
against the control. A market comparison cannot be a gate here because the
market is a benchmark (D0 L1), and because the totals share intervals are too
wide to gate on.

## 7. Uncertainty, multiplicity, and the rule D0-B violated

**Interval:** iso-week-clustered paired bootstrap, 2,000 resamples, **seed 26**.
Passed explicitly at every call — `season_clustered_ci` defaults to `12345`,
and D0-B's first cut reported intervals drawn with that unregistered default.

**Season-clustered reported as a sensitivity**, with its cluster count printed.
Below 20 clusters it is labelled *not an interval* and is not quoted.

**Multiplicity:** one candidate family × one primary metric × three leagues =
**k = 3**. Bonferroni: a league's result is credible only if its **98.3%**
interval excludes zero. The grid does not enter k — grid points are selected
inside the walk-forward, not tested against the gate.

**The UNRESOLVED rule, pre-committed, because D0-B broke it.** D0-B's evidence
card reported two sub-0.003-nat model-vs-constant claims as determinate while,
sixty lines later in the same file, dismissing #202's sub-0.003-nat candidates
as unresolvable. It had computed them as a difference of two log-loss *levels*
and never given them an interval. Therefore, in E1:

> **Every comparison this phase reports carries a paired interval, computed
> from per-match deltas.** No number is reported as a difference of two levels.
> If `|mean| ≤ clustered half-width`, the verdict printed is **UNRESOLVED at
> this sample size** — never "no effect", never a directional claim, and never
> a sentence that reads as one.

**Practical floor, declared in advance and separate from significance.** Even a
resolved improvement below **0.005 nats** on the primary metric does **not**
justify a per-team parameter store, a fitting job, and a serving seam. E1.1
clearing statistically but landing under 0.005 is recorded as
**"real but not worth serving"** and stops.

**Power.** Realized paired sd is reported per league, with
`MDE₈₀ = 2.80 · sd / √n` (2.80 = 1.96 + 0.84, an 80%-power threshold at
two-sided α = 0.05). This is **not** comparable to the 1.96σ half-width printed
beside it; both are shown, neither is called "the conservative one". D0-B
measured the totals paired sd at 0.147–0.194 for model-vs-market; a
candidate-vs-control sd is expected to be far smaller because the two models
are highly correlated, and the realized value is reported rather than assumed.

## 8. Missingness

- A club with **fewer than 10 prior matches** in the fitting window gets
  offsets of exactly `0.0` — i.e. it falls back to the served Elo behaviour.
  Not a guessed offset, not a league-average offset. Promoted clubs are the
  common case and must not be handed a number invented for them.
- The existing `√(n_eff / n0)` shrinkage handles the middle of the range; the
  hard floor above handles the tail where shrinkage still multiplies noise.
- The **one** D1 row with unparseable shot counts is irrelevant to E1.1 (goals
  only) and will be counted, not imputed, if E1.2 ever runs.
- Every match in the scored window is scored. There is no abstention path: an
  offset of 0.0 is a real prediction, not a missing one. Coverage is therefore
  100% by construction, and the report states the count of clubs that received
  a zero offset so "100%" cannot be read as "every club was modelled".

## 9. The confirmation problem, and what Italy/France can and cannot do

**There is no clean holdout available this year.** `2526` was consumed by
#202's confirmation phase. The next is the live **2026-27** season. This is a
hard constraint, not a scheduling inconvenience, and it determines the phase's
maximum possible output: **E1 can produce a selection result. It cannot produce
a confirmation.**

**Pre-registered surrogate: an out-of-league transfer test.** After this file
is pushed, and only then, download the free football-data.co.uk captures for
**I1 (Serie A)** and **F1 (Ligue 1)**, seasons `1617`–`2425` — roughly 6,800
matches, same provider, same URL template, **never touched by #202 or by any
phase of this program**.

Rules, fixed now:

- The candidate configuration taken to I1/F1 is **the one E1.1's walk-forward
  selected on E0/SP1/D1**. No re-selection, no per-league re-tuning, no grid.
  One number per league, twice.
- It is a **transfer** test: out-of-league, same era. It asks whether the
  advantage generalises across competitions. It does **not** ask whether it
  survives on unseen time, and it is **not** a substitute for the 2026-27
  holdout. Any write-up that calls it a confirmation is wrong.
- Both leagues are reported whatever they show. Picking the better one
  afterwards would make this a two-shot test reported as one.
- **G1 applies identically:** fingerprints committed, bytes never. I1/F1 CSVs
  are gitignored like the rest of `data/raw/`.
- The download is free, keyless, quota-free, from a provider already in use.
  It is **not** a G2 (paid) or G3 (capture) event. It is recorded in the ledger
  as a new-data event so a later reader knows when those files appeared.

## 10. Stop conditions — declared before the run

The phase stops and reports, without proceeding, if any fire:

- **S1.** E1.1's primary effect is **UNRESOLVED** (§7) in all three leagues.
  Recorded as a negative result. **The grid is not widened and the candidate is
  not re-specified** — that is how #202 accumulated 27 underpowered gates.
- **S2.** E1.1 is resolved but below the **0.005 nat** practical floor.
  Recorded as "real but not worth serving". Stops.
- **S3.** The 1X2 guardrail fails — the 1X2 delta is credibly worse.
  Recorded, stops, and specifically **does not** trigger a search for a
  configuration that satisfies both.
- **S4.** The offsets fit fails to converge, or produces a cap-saturated
  solution for more than 20% of clubs, in any league. That is a fitting defect,
  not a result, and reporting a number from it would be reporting an artifact.
- **S5.** Any implementation constraint in §12 is found to have been violated
  after a run. The run is **discarded**, not corrected and reported.
- **S6.** Anything that would touch production, cost money, enable capture,
  need a credential, or read `2526`. Handed to the human; the agent does not
  decide it.

## 11. Decision rule — and the only outcomes available

E1.1 may be recorded as a **selection winner** if and only if all hold:

1. Primary O/U effect resolved at the Bonferroni-corrected 98.3% interval, in
   **at least two of three leagues**;
2. point estimate ≥ **0.005 nats** in those leagues;
3. 1X2 guardrail not credibly worse in **any** league;
4. offsets converge and are not cap-saturated (§S4);
5. the I1/F1 transfer test (§9) is reported, whatever it shows.

**And even then, nothing ships.** A selection winner is written to the ledger
and **waits for the 2026-27 season** to face the existing out-of-sample gate.
Standing rule 3: *nothing joins the served model without clearing the existing
out-of-sample gate.* A transfer test is not that gate.

**No served parameter, artifact, or league override is edited in this phase.**
A test git-diffs `pipeline/leagues.py`, `ml/models/model_params.json`,
`pipeline/fit_attack_defence.py` and `ml/models/team_offsets.py` against the
merge base, as D0-B's does for the first two.

## 12. Implementation constraints that are part of this pre-registration

These are declared here, not left to implementation, because each would produce
a plausible wrong number rather than an error:

- **`GridConfig` is frozen and used as a dict key** for replay memoization in
  `walk_forward`. Per-team offsets are a mapping and are **unhashable**; putting
  them in `GridConfig` raises `TypeError` at grid-scan time, not at import. The
  offsets must be threaded to the loss function separately.
- **`walk_forward` calls losses positionally** as
  `loss(matches, replays[elo], elo, grid, rest_deltas=rest)`. `loss_totals`'s
  fifth positional is `line`. Any new parameter must be **keyword-only** or come
  after `rest_deltas`, or it binds silently to the wrong argument.
- **Offsets must be refit per scored season** from strictly-prior matches. A
  single fit over the whole window, applied backwards, is the same defect D1
  found in its venue table — a future state leaking into an earlier fixture.
- **Do not reuse `pipeline/experiment_club_eval.py::load_matches`**: it iterates
  `SEASON_CODES` including `"2526"` and falls back to a live download for any
  absent cache, so pointed at `data/raw/club` it would fetch the burnt holdout.
  Use a scoped loader with no network fallback, as D0-B does.
- **Do not reuse `pipeline/run_club_benchmark.py:98`'s `model_probs` call**: it
  passes all defaults (`base=1.35`, `beta=0.0019`, `rho=0`, no calibrator) and
  therefore scores a model production serves nowhere.
- **`rho` is vacuous on the totals metric to within one ulp** (D0-B B3). It
  must not be varied here, and any totals difference attributed to it is an
  artifact.
- **Network mocked in every test**; `urlopen` monkeypatched to fail.

## 13. What is recorded, win or lose

An evidence card in this directory containing: per-league primary effect with
its interval and cluster count, the 1X2 guardrail, realized paired sd and
MDE₈₀, the selected grid point per season, the count of clubs receiving a zero
offset, the cap-saturation rate, the cap sensitivity, the I1/F1 transfer
result, per-file SHA-256 fingerprints for every capture including the new
I1/F1 ones, the exact command, and the code revision.

A negative result gets the same card, the same detail, and the same prominence
in the ledger. §10's whole purpose is that S1 and S2 are ordinary outcomes.

## 14. Explicitly NOT in E1

- Any change to a served parameter, artifact, or league override (§11).
- Any modification of `pipeline/fit_attack_defence.py`, `ml/models/team_offsets.py`,
  or the FR-5 serving path. `"team_offsets"` stays `null`.
- E1.3, the direct MLE replacing the Elo→λ map (§4).
- Enabling, benchmarking or touching `odds_blend` / `w_odds` / `use_odds`.
- Asian handicap, BTTS, exact score, or any market other than O/U 2.5 and 1X2.
- Reading, fetching, or fingerprinting `*_2526`.
- Vendoring football-data.co.uk bytes — G1 remains open and deferred.
- Any file owned by the scope guards: PR #203's paths, the T1.6 calibrator
  area, `pipeline/run_calibrator_benchmark.py`, or the frozen q3 baseline.
- Re-landing D1. Its orphaning is recorded in the ledger and is the human's
  call, not a side errand of this phase.

---

# APPENDIX A — one constraint relaxed, before any run

**2026-07-30, appended before E1 code existed and before any candidate ran.**
Not edited in place.

## A1. §14's "no modification of `fit_attack_defence.py`" is narrowed

§14 forbids *any* modification of `pipeline/fit_attack_defence.py` and
`ml/models/team_offsets.py`. That was written to protect the FR-5 serving path,
and as written it forces E1 to duplicate the fitter — which defeats §3.

The grid in §4 varies the shrinkage denominator `n0 ∈ {10, 30, 60}` and reports
a cap sensitivity. Both live in `ml/models/team_offsets.py` as module
constants (`FULL_WEIGHT_EFF_MATCHES = 30.0`, `OFFSET_CAP = 0.075`), and
`fit_offsets` calls `shrink_and_cap` on them directly, with no seam.

Duplicating the fitter's iterative-scaling core to get that seam would mean E1
is no longer testing *FR-5's fitter on club data* — it would be testing a
60-line numerical lookalike that can silently diverge, and §3's entire
comparison table would stop being true. That is a worse outcome than relaxing
a constraint I wrote too tightly.

**Narrowed to:** E1 may make **additive, default-preserving** changes to those
two modules — specifically, one optional `policy` callable on `fit_offsets`
defaulting to the current `shrink_and_cap`, and one parameterized policy
factory beside it. E1 may **not** change any default, any existing signature's
meaning, any constant, or any serving behaviour.

**Enforced, not promised:**

- A test asserts `fit_offsets` called without `policy` is **bit-identical** to
  its pre-E1 behaviour on a fixed fixture.
- A test asserts the parameterized policy at `n0 = 30, cap = 0.075` returns
  **exactly** what `shrink_and_cap` returns, over a grid of raw inputs.
- `OFFSET_CAP` and `FULL_WEIGHT_EFF_MATCHES` keep their values; a test pins
  both.
- `"team_offsets"` stays `null` in `model_params.json`, and §11's git-diff test
  covers that file plus `pipeline/leagues.py`. It is **extended** to allow the
  two additive changes here while still failing on any served-parameter edit.

Everything else in §14 stands unchanged.

## A2. Market-relative reporting is deferred, with the reason

§6 says both metrics are **reported, never gating** against the de-vigged
closing line "via D0-B's harness". That harness is on the D0-B branch
([#215](https://github.com/javohir73/FinalWhistle/pull/215)), which is not
merged; E1 is branched from `main` precisely so it cannot be orphaned the way
D1 was.

E1 therefore **defers the market-relative reporting** rather than either
stacking on an unmerged branch or duplicating D0-B's loader. This costs
nothing that gates: §6 already declared the market comparison non-gating, and
the primary metric (`loss_totals`, O/U 2.5 vs realized outcomes) is on `main`
and unaffected.

Recorded so a reader does not mistake its absence for an omission. If D0-B
merges before E1's evidence card is written, the market columns are added and
the card says when.
