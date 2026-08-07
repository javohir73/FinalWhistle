# E2 — a club-derived offset cap: SELECTION PRE-REGISTRATION

**Written 2026-07-31. Committed alone, pushed, before any E2 run.** Appended to
afterwards; never edited in place.

Continues on the E1 branch and PR
[#216](https://github.com/javohir73/FinalWhistle/pull/216) rather than opening a
stack: E2 depends directly on E1's `club_tempo.py` and runner, and stacking a
phase on an unmerged branch is what orphaned D1.

Master ledger: [`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

**This document runs nothing.** §9 is a no-promotion rule with no path around it.

---

## 0. Why E2 exists, and the one thing it must not become

E1 asked whether a per-team tempo channel helps club totals. It could not
answer: FR-5's ±0.075 policy cap — derived for **international** football from
the form layer's ±35 Elo through β — bound on **69.9% / 78.4% / 89.2%** of
club-seasons, so §S4 fired everywhere and no number was interpretable.

E2 re-asks the same question with a cap derived from **club** data.

**The obvious way to corrupt this is to pick the cap that makes the candidate
win.** E1 has already been run; its saturation profile and its cap-sensitivity
numbers exist. Choosing a cap by looking at those is selection on the outcome,
and it would make E2 worthless. §1 therefore fixes the cap by a stated
principle, measured on data E1 **never scored**, and records the measurement
here before any E2 run.

## 1. The cap, derived and frozen

### The principle

`ml/models/team_offsets.py` states what a cap is *for*:

> a few-match team gets a near-zero adjustment no matter how extreme its raw fit

That is **tail control**. The `√(n_eff/n0)` ramp already handles small samples;
the cap exists to stop a degenerate fit from producing an absurd offset. A cap
that binds on the majority of clubs is not doing that job — it is compressing
the whole distribution, which is what E1 measured.

So the cap must be set where a per-team offset stops being *physically
plausible*, not where it stops being convenient.

### The measurement (burn-in seasons only, `1617`–`1718`)

Observed dispersion of club scoring rates — a fact about football, independent
of the model, computed as the sd of `log(team rate / league mean)` per
team-season with ≥20 matches:

| League | team-seasons | sd log(GF/mean) | sd log(GA/mean) |
|---|---|---|---|
| Bundesliga | 36 | 0.2944 | 0.2263 |
| EPL | 40 | 0.3537 | 0.2870 |
| La Liga | 40 | 0.3460 | 0.3056 |
| **pooled** | **232 values** | **0.3068** | |

### The frozen value

> **`CLUB_OFFSET_CAP = 0.30`** — one standard deviation of observed club
> team-season log scoring dispersion, rounded from 0.3068.

In plain terms: *a per-team offset may move a club's expected goals by up to
one standard deviation of what club scoring rates actually vary by.*
`exp(0.30) ≈ 1.35`.

The cap is **fixed, not on the grid, and not tuned.** E1's §4 reasoning stands
unchanged: moving it during a run would be a second candidate wearing the
first one's name.

### The honest disclosure

For the same fit, cap-binding rates measured on the burn-in window:

| cap | Bundesliga | EPL | La Liga | pooled |
|---|---|---|---|---|
| 0.075 (FR-5) | 65.0% | 100.0% | 87.0% | **84.0%** |
| 0.150 | 45.0% | 65.2% | 60.9% | 57.0% |
| 0.200 | 15.0% | 30.4% | 34.8% | 26.7% |
| 0.250 | 5.0% | 21.7% | 21.7% | 16.2% |
| **0.300** | 5.0% | 8.7% | 17.4% | **10.4%** |
| 0.400 | 5.0% | 4.3% | 4.3% | 4.6% |

**0.30 also happens to clear §7's 20% saturation ceiling, and I am stating that
rather than letting a reader discover it.** The derivation above does not
reference that ceiling and was written from the dispersion measurement, but the
two are not independent facts about the world, and a reader is entitled to
weigh the coincidence. Two things constrain the choice against being
outcome-driven:

- The value comes from a **scoring-dispersion** statistic, not from the
  saturation table and not from any effect size. Had 1 sd landed at 0.22, this
  document would say 0.22 and E2 would likely fail §S4 immediately.
- Both measurements use **burn-in seasons only** (`1617`–`1718`), which E1 never
  scored. No E2 or E1 effect size was consulted in setting it.

## 2. The prior, stated before the run: E2 is expected to FAIL

E1's pre-registered cap sensitivity already looked at looser caps, and it did
not improve:

| League | cap 0.05 | cap 0.10 | cap 0.15 |
|---|---|---|---|
| Bundesliga | −0.0016 | −0.0008 | +0.0002 |
| EPL | −0.0008 | +0.0013 | +0.0039 |
| La Liga | −0.0045 | −0.0055 | −0.0053 |

Point estimates are **flat or worse** as the cap widens in two of three
leagues. That is the opposite of what a binding-constraint story predicts.

**So the honest prior is that E2 finds nothing, or finds the candidate
credibly worse.** E2 is worth running anyway, because those sensitivity points
were a single grid point (`hl365`, `n0=30`) at caps that were *still* binding
on 57–84% of clubs — none of them was an unconstrained test. But a favourable
E2 result would be surprising, and §8 pre-commits to treating it as such.

## 3. Candidate — identical to E1.1 except the cap

`λ_home = μ_home(Elo)·exp(a_home + d_away)`, `λ_away = μ_away(Elo)·exp(a_away + d_home)`,
positive `d` = leaky. Per E1's Appendix B3, corrected:

```
log λ_h + log λ_a  =  base + (a_h + d_h) + (a_a + d_a)   -> TOTALS: (a+d) is TEMPO
log λ_h − log λ_a  =  base + (a_h − d_h) − (a_a − d_a)   -> 1X2:    (a−d) is STRENGTH
```

**Selectable grid — 9 points, frozen, unchanged from E1:**

| Parameter | Values |
|---|---|
| half-life (days) | `180`, `365`, `730` |
| shrinkage `n0` in `√(n_eff/n0)` | `10`, `30`, `60` |

Cap fixed at `0.30` throughout. **`n0` is now load-bearing in a way it was not
in E1** — with the cap no longer compressing the distribution, the ramp is the
only remaining regularizer, so a shrinkage failure will show up as
overfitting rather than being masked.

**Cap sensitivity reported, never eligible to win:** `0.20`, `0.30`, `0.45` at
`hl365`/`n0=30`. Chosen to bracket the frozen value symmetrically in
saturation terms (26.7% / 10.4% / ~3%), not by effect.

## 4. Data, split, and the quarantine

Unchanged from E1: nine pre-confirmation seasons replayed per league,
`1819`–`2425` scored, `1617`–`1718` burn-in, `2526` **never opened** — it is
consumed and `walk_forward_tempo` raises on it.

Offsets are refit **per scored season** on matches strictly before that
season's first kickoff.

## 5. Metric and guardrail

**PRIMARY (the gate):** O/U 2.5 log loss vs realized outcomes, per league,
per-match paired delta against the served control. Same metric T1.1 was gated
on.

**GUARDRAIL (non-inferiority, not a second gate):** 1X2 log loss vs outcomes,
scoring the **same** selected point. Fails only if credibly *worse*.

The guardrail matters more in E2 than it did in E1: a 4× looser cap gives the
fit far more room to overfit, and `(a−d)` moves the ratio. E1's guardrail point
estimates were already positive in all three leagues.

## 6. Uncertainty — E1's lessons, carried forward as requirements

**Interval: ISO-WEEK-clustered** paired bootstrap, 2,000 resamples, **seed 26**,
passed explicitly. E1 pre-registered iso-week and shipped season (7 clusters)
undisclosed; that is not repeated.

**Anything under 20 clusters is labelled `NOT AN INTERVAL` and may not exclude
zero.** Already enforced in `_interval`.

**Season-clustered reported as a sensitivity**, flagged as not-an-interval at 7
clusters.

**Multiplicity:** one family × one primary metric × three leagues, **k = 3**,
Bonferroni → **98.3%** intervals.

**The UNRESOLVED rule.** Every comparison carries a paired interval from
per-match deltas; none is a difference of two levels. If
`|mean| ≤ half-width`, the verdict is **UNRESOLVED at this sample size** —
never a direction. A zero-width interval prints **DEGENERATE**.

**Practical floor: 0.005 nats.** A resolved gain below it is recorded as *"real
but not worth serving"* and stops.

**Saturation is measured on the RAW pre-policy fit.** E1's detector compared
the post-ramp value to the cap and could not fire; that is fixed and tested,
and E2 inherits the fix.

## 7. Stop conditions

The phase stops and reports, without proceeding, if any fire:

- **S1** — primary UNRESOLVED in all three leagues. Negative result. The grid
  is **not** widened, the cap is **not** moved, the candidate is **not**
  re-specified.
- **S2** — resolved but below the 0.005 practical floor. *"Real but not worth
  serving."*
- **S3** — the 1X2 guardrail is credibly worse in any league.
- **S4** — raw-fit cap saturation above **20%** in any league. Given §1's
  measurement this is not expected; if it fires anyway, the dispersion-derived
  cap is also wrong and **E2 records that and stops** rather than trying a
  third value.
- **S5** — any §6 requirement is found violated after a run. The run is
  **discarded**, not corrected and reported.
- **S6** — anything touching production, cost, capture, credentials, or `2526`.

## 8. Decision rule

E2 may be recorded as a **selection winner** only if: resolved at 98.3% in ≥2
of 3 leagues; point estimate ≥ 0.005 nats there; guardrail not credibly worse
anywhere; saturation under 20% everywhere; and the result survives an
adversarial review.

**Because §2 declares a pessimistic prior, a favourable result gets an extra
requirement:** it must be shown not to be an artifact of the looser cap
permitting overfitting — specifically, the fitted offsets' out-of-sample
tempo correlation must be reported alongside the in-sample one, and the
guardrail must not degrade monotonically with cap across the §3 sensitivity.

**And even then nothing ships.** `2526` is consumed; the next clean holdout is
the live **2026-27** season, and standing rule 3 requires the existing
out-of-sample gate. A selection winner is written to the ledger and waits.

**No served parameter, artifact, or league override is edited.** Tests git-diff
`pipeline/leagues.py`, `ml/models/model_params.json`,
`pipeline/fit_attack_defence.py` and `ml/models/team_offsets.py` against the
merge base; `"team_offsets"` stays `null`.

## 9. Explicitly NOT in E2

- Any change to a served parameter or artifact.
- Moving the cap after the run, for any reason, including S4 firing.
- A third cap value, a widened grid, a new metric, or a re-specified candidate.
- The Italy/France transfer test — it stays unrun and undownloaded until a
  candidate actually clears §8. E1 did not, and a cap change does not
  retroactively give it one.
- `odds_blend` / `w_odds` / `use_odds`.
- Reading or fingerprinting `*_2526`.
- Vendoring football-data.co.uk bytes; G1 remains open and deferred.
- Re-landing D1, or repairing PR #214's orphaning.
