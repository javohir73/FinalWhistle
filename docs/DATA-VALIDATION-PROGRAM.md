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

## E1 — a tempo channel for the club engine (2026-07-30) — NEGATIVE

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

**Answer: no, and two stop conditions fired.**

| League | O/U 2.5 delta | 98.3% CI | verdict | cap-saturated |
|---|---|---|---|---|
| Bundesliga | −0.0013 | [−0.0030, +0.0004] | UNRESOLVED | 0.0% |
| EPL | +0.0004 | [−0.0031, +0.0036] | UNRESOLVED | 28.1% |
| La Liga | −0.0053 | [−0.0111, +0.0009] | UNRESOLVED | 65.4% |

- **S1** — unresolved everywhere. Grid **not** widened, candidate **not**
  re-specified.
- **S4** — EPL and La Liga are cap-saturated past the 20% ceiling, so their
  numbers are a fitting artifact and are **not interpretable**.
- The §9 Italy/France transfer test was **not run** and those captures were
  **not downloaded**: §10 stops the phase without proceeding, and there is no
  selected candidate to transfer.

### Findings worth not rediscovering

- **E1-1.** Bundesliga's null is **clean** — nothing saturated, effect 2.4×
  below its own MDE₈₀, and a quarter of §7's 0.005-nat practical floor. Even
  perfectly resolved it would have been "real but not worth serving" under S2.
  That is the one league where the channel was measured properly and is simply
  not there at a useful size.
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
  [−0.0088, −0.0002]) and **must not be cited**. Its point estimate is
  *smaller* than the same league's unresolved 0.10 and 0.15 cells; only the
  interval is narrower, because a tighter cap mechanically reduces variance.
  One credible cell out of nine at α=0.0167 is what noise produces. §4 declared
  these points never eligible to win, in advance, for exactly this reason.
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
