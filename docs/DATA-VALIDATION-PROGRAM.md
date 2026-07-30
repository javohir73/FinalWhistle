# Data & Independent Validation program — MASTER LEDGER

**Status: RESEARCH. Nothing here serves. No production write, no paid call, no
capture enabled, no credential added.**

This file is the durable state of a sequenced, five-phase data program. It
exists **because GitHub Issues:write is unavailable to the agent running it** —
without a repo-backed ledger every run restarts from zero, re-audits settled
questions, and re-derives findings that were already paid for. Read this file
first. Append to it; do not rewrite history in it.

Phases run **one at a time**, in order. Each gets its own pre-registration, its
own experiment directory under `docs/experiments/`, and its own focused draft
PR. A phase does not begin until the previous phase's PR is open and CI is
green.

## Phase state

| Phase | Subject | State | Ledger | PR |
|---|---|---|---|---|
| **D0** | Independent market validation (football-data.co.uk closing odds) | **COMPLETE — draft PR open, G1 awaiting decision** | [`2026-07-29-d0-market-validation/`](experiments/2026-07-29-d0-market-validation/) | draft |
| D1 | Rest and travel | NOT STARTED | — | — |
| D2 | Lineups, player minutes, injuries | NOT STARTED | — | — |
| D3 | xG (StatsBomb Open Data) | NOT STARTED | — | — |
| D4 | Weather | NOT STARTED | — | — |

Ordering is deliberate: market validation first, because until the yardstick is
trustworthy every other number in the program is uninterpretable. Weather last,
because it is the lowest-value and the most leak-prone join in the set.

## Standing rules for every phase

1. **Pre-register before implementing.** Objective, baseline, acceptance
   criteria, coverage/cost/licensing limits, data fingerprint, missingness
   policy, reproducibility receipt, leakage audit, stop gates. Written before
   the first run, appended to afterwards, never edited in place.
2. **Never reuse a confirmation season during candidate selection.** 2025-26
   (`2526`) is **consumed** — burnt by the #202 confirmation phase
   (`docs/MODEL-EXPERIMENTS.md`). The next clean holdout is the live 2026-27
   season. A phase that cannot reach a clean holdout **does not ship**; it
   records a selection result and defers.
3. **Nothing joins the served model without clearing the existing
   out-of-sample gate.** Not "looks promising", not "shipped on principle".
4. **Record negative results.** A refuted hypothesis costs the same to
   discover as a confirmed one and is worth as much to the next run.
5. **Mock the network in tests.** Every test in this program is hermetic.
6. **One focused draft PR per phase.** Wait for green CI. Never merge.

## Scope guards — DO NOT TOUCH

Two other work streams are live in this repository. Overlapping them corrupts
their evidence, and theirs corrupts this program's.

| Off-limits | Why |
|---|---|
| PR **#203** `feat/prediction-market-intelligence` | Superseded but unmerged; owns `venue_market` / `entity_source_map` and an entity resolver. A second writer with different confidence semantics collides. Do not touch, do not duplicate, do not "helpfully" rebase. |
| **T1.6 calibrator-integrity task** — `pipeline/fit_club_calibrator.py`, `ml/evaluation/club_calibration.py`, `docs/BUNDESLIGA-CALIBRATOR-LIVE-VALIDATION.md`, `docs/experiments/2026-07-28-t16-calibrator-recut/`, branch `feat/bundesliga-cal-shadow-twin` | Separate active task. It is mid-flight on the same three leagues and the same nine pre-confirmation seasons. This program reads its published results; it changes none of its files. |
| `pipeline/run_calibrator_benchmark.py` and the API-Football `odds` table | The frozen q3 confirmation baseline (`docs/VALIDATION-DATA-SOURCES.md`). Frozen means frozen. |

## Stop-gate register

The repository stop gate (`CLAUDE.md`) fires on spend, production, destructive
ops and outward sends. This program adds four data-specific gates. Each is
**recorded here when reached and handed to the human** — the agent does not
decide them.

| Gate | Status | Detail |
|---|---|---|
| **G1 — redistribution of football-data.co.uk bytes** | **OPEN — human decision required** | See D0 pre-registration §Licensing. The site states "Simply download for free the available files" and "© Football-Data. Liability Disclaimer. All Rights Reserved." Free download is granted; **redistribution is not granted anywhere on the site.** D0 therefore commits a *fingerprint descriptor*, never the CSV bytes. Committing the raw files — even to a private repo — is a licensing decision for the human. **D0 measured the cost of leaving this open:** all 27 pinned captures have since drifted, and because the bytes were never retained the drift cannot be diagnosed and the #202 market numbers cannot be reproduced byte-for-byte (finding D0-2). Vendoring ~3.6 MB would fix it permanently. |
| G2 — paid data | not reached | No paid call is made by any phase. The Odds API historical endpoint, Betfair Basic→Advanced upgrades, and any API-Football quota increase are all out of scope. |
| G3 — enabling capture | not reached | No phase enables live capture, schedules a job, or adds a credential. |
| G4 — production write / migration | not reached | No phase writes production. Any schema work lands default-off and behind `refresh.yml` sequencing (`CLAUDE.md` § Database migrations). |

## Reproducibility receipts

Every phase emits a receipt sufficient to re-run it from a cold clone: the
exact command, the input fingerprints, the code revision, and the environment.
Receipts live in the phase's experiment directory. A number without a receipt
is not a result — it is an anecdote.

---

## E1 — a tempo channel for the club engine (2026-07-30) — INCONCLUSIVE

Engine work, not a D-series data phase. It descends from D0-B's finding and is
recorded here because this is where the program's state lives.

Pre-registered alone in `3989145`, corrected in `758963a`, both pushed before
any code. Evidence:
[`2026-07-30-e1-tempo-channel/EVIDENCE-CARD.md`](experiments/2026-07-30-e1-tempo-channel/EVIDENCE-CARD.md).

**Question.** D0-B showed the served engine has no per-team tempo parameter —
`λ_h·λ_a ≡ base²`, so the expected total is a function of the rating gap alone
and Bundesliga priced P(over 2.5) below 0.5 zero times in 612 matches. E1 asked
whether FR-5's per-team attack/defence offsets, refit per league on club data,
close that. `(aᵢ + dᵢ)` moves the ratio; `(aᵢ − dᵢ)` moves the total.

**Answer: the question was never actually put.** The first cut recorded a clean
null; a 28-agent adversarial review (23 confirmed findings, 7 invalidating)
established that was an instrument failure, and the conclusion was withdrawn.

Corrected, on §7's pre-registered **iso-week** clustering (227–247 clusters):

| League | O/U 2.5 delta | 98.3% CI | verdict | cap-saturated |
|---|---|---|---|---|
| Bundesliga | −0.0013 | [−0.0040, +0.0015] | UNRESOLVED | **69.9%** |
| EPL | +0.0004 | [−0.0037, +0.0044] | UNRESOLVED | **78.4%** |
| La Liga | −0.0053 | [−0.0098, −0.0004] | credible | **89.2%** |

- **S4 fires in ALL THREE leagues.** §S4: a cap-saturated fit is "a fitting
  defect, not a result". §11's decision rule requires offsets that are not
  saturated; that fails everywhere. **No league is interpretable**, La Liga's
  credible −0.0053 included.
- The §9 Italy/France transfer test was **not run** and those captures were
  **not downloaded**: §10 stops the phase without proceeding.
- **The cap may not be raised and the run repeated.** §4 froze it ("moving it
  would be a second candidate wearing the first one's name"); §10 forbids
  re-specifying after a stop. Answering this needs a fresh pre-registration
  with a club-appropriate cap argued from club data before any run — a
  different phase, and the human's call whether it is worth one.

### Findings worth not rediscovering

- **E1-1 — WITHDRAWN.** The first cut called Bundesliga's null "clean, nothing
  saturated". Its true saturation is **69.9%**. The detector compared the
  **post-ramp** offset to the cap, but the policy clamps to ±cap and *then*
  multiplies by `min(1, √(n_eff/n0))`, so a pinned component returns `cap×ramp`
  and can never equal `cap`. At Bundesliga's selected point (`n0=60`) the ramp
  tops out at 0.87, so **not one of 191 club-seasons could match** — the rate
  was arithmetically pinned to 0.0%. **A detector that cannot fire is worse
  than no detector**, because it certifies exactly the thing it fails to check.
- **E1-1b.** The card's own numbers had already contradicted it: Bundesliga's
  reported `tempo_max = +0.1290` is Augsburg at raw (+0.0794, −0.0948) — both
  past ±0.075 — and 2 × 0.075 × 0.8603 = 0.1290 exactly.
- **E1-2.** The candidate-vs-control paired sd is **0.052–0.098**, against
  0.147–0.194 for model-vs-market. Two correlated models differ far less
  match-to-match than a model and the market do, so MDE₈₀ here is 0.003–0.005.
  **Use ~0.05–0.10 as the sd prior for any future candidate-vs-control club
  gate, not the market figure** — it changes required-n by ~9×.
- **E1-3.** FR-5's ±0.075 cap, derived for internationals from the form
  layer's ±35 Elo through β, **binds hard on club data** — the La Liga fit sits
  at exactly ±0.1500 (2 × the cap) for its extreme clubs. Club teams play 34–38
  matches a season, not 3–7, so the offsets are far better identified and the
  international ceiling is the wrong size. **This is not a licence to raise
  it**: the pre-registered cap sensitivity shows the effect is flat or *worse*
  as the cap widens, which is the opposite of a binding-constraint signature.
- **E1-4 (trap).** La Liga at cap 0.05 reads "credible" (−0.0045
  [−0.0078, −0.0011]) and **must not be cited**. Its point estimate is
  *smaller* than the same league's unresolved 0.10 and 0.15 cells; only the
  interval is narrower, because a tighter cap mechanically reduces variance.
  One credible cell out of nine at α=0.0167 is what noise produces. §4 declared
  these points never eligible to win, in advance, for exactly this reason.
- **E1-6.** §7 pre-registered **iso-week** clustering; the first cut shipped
  **season** (7 clusters) and did not disclose the substitution. On the correct
  clustering La Liga's primary flips from unresolved to credible. D0-B's own
  code treats <20 clusters as *not an interval*; `_interval` now enforces that
  and refuses to let such a figure exclude zero.
- **E1-7.** Tempo is **(a+d)**, not (a−d) — with positive `def` = leaky, the
  log-SUM moves with (a+d) and the log-RATIO with (a−d). §4's prose and the
  diagnostics had them swapped. Against realized goals-per-match, (a+d)
  correlates **+0.53/+0.63/+0.71** and (a−d) **−0.18/−0.13/−0.28**, so **the
  fitter genuinely learns tempo** — E1 failed to test it, not to find it.
- **E1-8.** "0.0% zeroed" measured coverage over the *fit dictionary*, where an
  unmodelled club is missing from numerator and denominator alike. Against
  clubs that actually played a scored season: **7.9% / 7.9% / 5.0%** had no
  offset at all.
- **E1-5.** A season-clustered bootstrap over **identical** clusters returns a
  zero-width interval that reads as certainty. E1's `_interval` now prints
  `DEGENERATE` instead; `season_clustered_ci`'s docstring had already warned
  about this and nothing enforced it. Found by E1's own test, not in review.

### What E1 does NOT say

It does not show a tempo channel is worthless — only that *this* channel, under
*this* cap, at *this* sample size, is not resolvable. D0-B's structural finding
stands. It also does not vindicate FR-5's original refutation, which was a
different population, metric and sample size. Both are now null for different
reasons on different data.

**Nothing was promoted.** `"team_offsets"` is still `null`; `pipeline/leagues.py`
and `ml/models/model_params.json` are byte-identical to the merge base, enforced
by test. The only edits to the FR-5 path are the two additive, default-preserving
changes Appendix A1 permits, both covered by bit-identity tests.

---

## E2 — a club-derived offset cap (2026-07-31) — REFUTED on the guardrail

Pre-registered alone in `8bb0d72`, pushed before any E2 code. Evidence:
[`2026-07-31-e2-club-cap/EVIDENCE-CARD.md`](experiments/2026-07-31-e2-club-cap/EVIDENCE-CARD.md).

E1 could not answer its question because FR-5's ±0.075 cap, derived for
international football, bound on 69.9–89.2% of club-seasons. E2 re-ran the same
candidate at **`CLUB_OFFSET_CAP = 0.30`** — one standard deviation of observed
club team-season log scoring dispersion (pooled sd 0.3068, burn-in seasons
only), fixed by that principle before any run.

**The cap fix worked, and the candidate is refuted anyway.**

| League | O/U 2.5 | 98.3% CI | 1X2 guardrail | 98.3% CI | saturation |
|---|---|---|---|---|---|
| Bundesliga | −0.0006 | [−0.0058, +0.0048] | **+0.0049** | **[+0.0007, +0.0090]** | 11.0% |
| EPL | +0.0021 | [−0.0032, +0.0075] | +0.0041 | [−0.0010, +0.0088] | 19.6% |
| La Liga | **−0.0080** | **[−0.0148, −0.0007]** | +0.0043 | [−0.0000, +0.0083] | 13.9% |

**S3 fired** — the guardrail is credibly worse in Bundesliga. §8 requires it not
credibly worse anywhere. La Liga's credible −0.0080 does not survive that, and
reporting it alone would be picking one league of three on a phase whose stated
prior was that none would clear.

### Findings worth not rediscovering

- **E2-1 — the parameterisation couples tempo to strength, and that is the
  refutation.** The 1X2 cost is **+0.0049 / +0.0041 / +0.0043** — positive in
  all three leagues and tightly clustered — while totals is −0.0006 / +0.0021 /
  −0.0080, inconsistent. The candidate reliably pays ~0.0044 nats on the ratio
  to inconsistently maybe gain on the sum. Because `(a+d)` and `(a−d)` are both
  free, fitting tempo perturbs strength; strength spread rose to sd 0.074–0.088
  once the cap stopped compressing it. Elo already captures 64–84% of the 1X2
  budget (D0-B), so that perturbation is close to pure added noise. **No cap
  value fixes this — it is the parameterisation.**
- **E2-2.** The cap really was the wrong size: saturation fell **84% → ~15%**,
  and no club-season is now pinned on both components. E1's complaint was
  valid; it just was not what was hiding an effect.
- **E2-3.** Across E1's 0.05–0.15 bracket and E2's 0.20–0.45 bracket the totals
  effect is **flat over a 9× span of cap values**. That retires the cap as an
  explanation, permanently. Do not re-open it.
- **E2-4.** With the cap no longer binding, the walk-forward collapses onto
  short half-life and weak shrinkage (`hl180`, `n0` 30–60) in every league.
- **E2-5 (method).** §2 declared "E2 is expected to fail" before the run, from
  E1's cap-sensitivity signal. It did. Writing the prior down first is what
  makes the result cheap to interpret rather than a surprise to explain away.

### The next candidate — and it needs its own pre-registration

Constrain **`(a−d) = 0`** so only `(a+d)` is free: a pure tempo channel with no
strength side-effect, aimed squarely at the coupling E2 identified. §9 forbids
re-specifying inside E2 and §7 S3 forbids searching for a configuration that
satisfies both, so this is a new phase. **Whether it is worth one is the
human's call** — D0-B bracketed the totals headroom widely, and E1 plus E2 have
now spent two phases on the tempo question without a promotable result.

**Nothing was promoted.** `"team_offsets"` is still `null`; all four §8-guarded
files are byte-identical to the merge base, enforced by test. The Italy/France
transfer test remains unrun and those captures undownloaded — no candidate has
cleared §8, and a cap change does not retroactively give one.
