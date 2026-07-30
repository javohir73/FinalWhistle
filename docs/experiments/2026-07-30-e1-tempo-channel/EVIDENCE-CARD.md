# E1.1 — per-team tempo channel: EVIDENCE CARD

**Run 2026-07-30**, after the pre-registration was committed alone (`3989145`)
and corrected (`758963a`), both pushed before any E1 code existed. Appended to;
never edited in place.

```bash
PYTHONPATH=backend:. python -m pipeline.run_e1_tempo \
    --csv-dir data/raw/club --emit-json /tmp/e1.json
```

Scored `1819`–`2425`; `1617`/`1718` are burn-in; nine seasons replayed per
league; `2526` never opened. Intervals: season-clustered paired bootstrap,
2,000 resamples, **seed 26**, Bonferroni **k=3** → 98.3%.

---

## Result: NEGATIVE. Two stop conditions fired.

**The per-team tempo channel does not clear its bar on club data.**

| League | O/U 2.5 (PRIMARY) | 98.3% CI | verdict | paired sd | MDE₈₀ |
|---|---|---|---|---|---|
| Bundesliga | **−0.0013** | [−0.0030, +0.0004] | **UNRESOLVED** | 0.0517 | 0.0031 |
| EPL | **+0.0004** | [−0.0031, +0.0036] | **UNRESOLVED** | 0.0897 | 0.0049 |
| La Liga | **−0.0053** | [−0.0111, +0.0009] | **UNRESOLVED** | 0.0977 | 0.0053 |

Negative = candidate better. Every interval straddles zero.

**S1 fired** — unresolved in all three leagues. Per §10 the grid is **not**
widened and the candidate is **not** re-specified.

**S4 fired** — offsets are cap-saturated for **28.1% of EPL** and **65.4% of
La Liga** club-seasons, against a 20% ceiling. §S4: *"that is a fitting defect,
not a result, and reporting a number from it would be reporting an artifact."*

Per §10 the phase **stops without proceeding**. The Italy/France transfer test
pre-registered in §9 was therefore **not run and those captures were not
downloaded** — there is no selected candidate to transfer.

## The guardrail

| League | 1X2 delta | 98.3% CI | verdict |
|---|---|---|---|
| Bundesliga | +0.0016 | [−0.0004, +0.0042] | UNRESOLVED |
| EPL | +0.0006 | [−0.0033, +0.0043] | UNRESOLVED |
| La Liga | +0.0019 | [−0.0002, +0.0039] | UNRESOLVED |

§6's guardrail is non-inferiority, and it **passes**: no league is credibly
worse on 1X2. But all three point estimates are positive, and La Liga's
interval barely contains zero. The candidate is, if anything, slightly
1X2-negative — consistent with the scoping note that a single strength scalar
beat attack/defence by ~0.0020 on the ratio. **S3 did not fire.**

## What S4 actually means, and why it is not a fixable nuisance

The fitted tempo range hits **exactly ±0.1500** in La Liga — which is 2 × the
±0.075 policy cap, i.e. the extreme clubs are pinned at the bound on both
components. The fit *wants* larger offsets than FR-5's policy allows.

That cap is not arbitrary and it is not a bug: `ml/models/team_offsets.py`
derives it from the form layer's ±35 Elo through the served β
(0.0021 × 35 ≈ 0.0735 → 0.075), for **international** football. Club football
has 34–38 matches per team per season instead of 3–7, so a per-team offset is
far better identified and the international-calibrated ceiling binds.

**This does not license raising the cap.** §4 froze the cap deliberately —
*"moving it would be a second candidate wearing the first one's name"* — and
§10 S1 forbids re-specifying after a null. The cap sensitivity was
pre-registered precisely so this question could be *looked at* without being
*acted on*:

| League | cap 0.05 | cap 0.10 | cap 0.15 |
|---|---|---|---|
| Bundesliga | −0.0016 [−0.0049, +0.0014] | −0.0008 [−0.0060, +0.0035] | +0.0002 [−0.0053, +0.0053] |
| EPL | −0.0008 [−0.0035, +0.0016] | +0.0013 [−0.0038, +0.0065] | +0.0039 [−0.0040, +0.0120] |
| La Liga | **−0.0045 [−0.0088, −0.0002]** | −0.0055 [−0.0125, +0.0018] | −0.0053 [−0.0136, +0.0030] |

**Loosening the cap does not help.** In every league the point estimate is flat
or *worse* as the cap widens — the opposite of what "the fit is constrained"
would predict if the constraint were costing accuracy.

One cell is credible: La Liga at cap 0.05. **It should not be believed.** Its
point estimate (−0.0045) is *smaller in magnitude* than the same league's
unresolved 0.10 and 0.15 cells (−0.0055, −0.0053); what differs is the interval
width, because a tighter cap mechanically reduces variance. That is an
interval-width artifact, not a cap effect. It is also 1 credible cell out of 9
at α = 0.0167, which is roughly what noise produces. §4 already declared these
points **never eligible to win**, and this is why.

## Diagnostics

| League | club-seasons fitted | zeroed (<10 prior) | cap-saturated | tempo sd | tempo range |
|---|---|---|---|---|---|
| Bundesliga | 191 | 0.0% | **0.0%** | 0.0498 | [−0.1047, +0.1290] |
| EPL | 224 | 0.0% | **28.1%** | 0.0584 | [−0.1477, +0.1500] |
| La Liga | 214 | 0.0% | **65.4%** | 0.0549 | [−0.1500, +0.1500] |

**Bundesliga's null is clean** — nothing saturated, a well-identified fit, and
the effect (−0.0013) is less than half its own half-width (0.0017) and well
under its MDE₈₀ (0.0031). That is the one league where E1 can say something
positive: *the tempo channel was measured properly and is not there at a size
worth having.*

EPL's and La Liga's numbers are **not interpretable** under §S4. They are
reported for completeness and should not be quoted as evidence either way.

Zero clubs fell below the 10-prior-match floor, because every scored season is
preceded by at least two full seasons of history. §8's floor never bound; it
remains correct policy for a shorter window.

## What this does and does not say

**Does:** the specific FR-5 offset parameterisation, refit per league on club
data with a walk-forward selected half-life and shrinkage, does not produce a
resolvable totals improvement at n ≈ 2,100–2,700 per league.

**Does not:**

- It does **not** show that a tempo channel is worthless. It shows that *this*
  channel, under *this* policy cap, at *this* sample size, is not resolvable.
  D0-B's structural finding — `λ_h·λ_a ≡ base²`, Bundesliga never pricing an
  under — is unaffected and still true.
- It does **not** vindicate FR-5's original refutation. That was a different
  population, metric and sample size (§3). Both are now null, for different
  reasons, on different data.
- It does **not** license a cap search, a wider grid, a new metric, or a
  re-specified candidate. §10 S1 is explicit, and #202 accumulated 27
  underpowered gates by doing exactly that.

## Power — what would have been needed

The realized candidate-vs-control paired sd is **0.052–0.098**, far below the
0.147–0.194 D0-B measured for model-vs-market. §7 anticipated this ("the two
models are highly correlated"), and it is why MDE₈₀ here is 0.0031–0.0053
rather than ~0.017.

So the sample was **not** the limiting factor for Bundesliga: its effect
(0.0013) is below its own detection floor (0.0031) by a factor of 2.4, and
resolving it would need ~13,600 matches — but there is no reason to want to,
because §7's practical floor is 0.005 and Bundesliga's effect is a quarter of
that. **Even a perfectly resolved −0.0013 would have been recorded as "real but
not worth serving" under S2.**

La Liga is the only league where the point estimate (−0.0053) exceeds the
practical floor, and it is exactly the league whose fit is 65% cap-saturated.

## Reproducibility

Per-file SHA-256 for all 27 captures is in the emitted JSON. As with D0 and
D0-B, the CSV **bytes are not committed** — G1 is open and deferred — and the
manifest is known to have drifted from disk, so the fingerprints in this run's
receipt are the run's own, not the manifest's.

Deterministic: no RNG in the fitter (iterative proportional scaling), and the
one bootstrap is seeded at 26.

## Pre-registration compliance

| Promised | Delivered |
|---|---|
| §4 grid frozen at 9 selectable points | 9 points; cap sensitivity kept in a separate tuple a selection loop cannot reach; test pins the disjointness |
| §5 walk-forward, per-season refit, strictly prior | 9 points × 9 seasons × 3 leagues = 243 fits; test asserts the fitter never sees the season it fits for |
| §6 O/U primary, 1X2 non-inferiority guardrail | both reported; guardrail scores the **same** selected point, not a re-selection |
| §7 seed 26, k=3, UNRESOLVED rule, practical floor | all four; a zero-width interval now prints DEGENERATE rather than credible |
| §8 <10 prior matches → exactly 0.0 | implemented; 0 clubs bound |
| §9 I/F transfer test | **not run** — S1/S4 fired first and §10 says stop without proceeding. Captures not downloaded. |
| §10 stop conditions | S1 and S4 fired, applied mechanically by `stop_conditions()` rather than narrated |
| §11 no promotion | nothing changed; git-diff test on `leagues.py` and `model_params.json`; `"team_offsets"` still `null` |
| §12 four traps | all four covered by tests: `GridConfig` untouched and still hashable, offsets keyword-only, per-season refit, no network fallback |
| Appendix A1 additive seam | `policy` defaults to `shrink_and_cap`; bit-identity test for existing callers; exact-equivalence test at shipped constants; both constants pinned |
| Appendix A2 market reporting deferred | deferred; D0-B's harness is on an unmerged branch |

`2659 passed`
