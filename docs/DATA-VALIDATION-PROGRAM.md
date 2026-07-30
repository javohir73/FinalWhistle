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
| **D0** | Independent market validation (football-data.co.uk closing odds) | **COMPLETE — merged to `main` as #213, G1 still awaiting decision** | [`2026-07-29-d0-market-validation/`](experiments/2026-07-29-d0-market-validation/) | #213 (merged) |
| **D0-B** | Totals market validation (closing over/under 2.5) | **COMPLETE — result recorded, nothing promoted** | [`2026-07-30-d0b-totals-market/`](experiments/2026-07-30-d0b-totals-market/) | draft |
| D1 | Rest and travel | **DONE BUT ORPHANED — see below** | [`2026-07-30-d1-rest-travel/`](experiments/2026-07-30-d1-rest-travel/) | #214 (merged to a dead branch) |
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

## D0-B — totals market validation (2026-07-30)

Pre-registered alone in `aa7a445`, corrected in `1e207a6`, both pushed before
any code existed. Evidence:
[`2026-07-30-d0b-totals-market/EVIDENCE-CARD.md`](experiments/2026-07-30-d0b-totals-market/EVIDENCE-CARD.md).

**Why it was run.** D0 recovered the 1X2 closing line but not the totals one.
`base` is the only engine parameter ever gated on a totals metric, and both of
its shipped per-league overrides were justified against a **constant** —
`pipeline/leagues.py` says so in its own comments. A constant is a floor, not a
yardstick.

**Result — the model is credibly behind the closing over/under line in all
three leagues**, and unlike #202's 0.000–0.003 nat candidates, this is
*resolved* at the available sample size:

| League | model − market | iso-week CI95 | 1X2 share | **O/U share** |
|---|---|---|---|---|
| Bundesliga | +0.0328 | [+0.0215, +0.0438] | 63.8% | **−6.7%** |
| EPL | +0.0216 | [+0.0081, +0.0350] | 74.4% | **+7.9%** |
| La Liga | +0.0245 | [+0.0123, +0.0371] | 83.8% | **+29.5%** |

Measured on the same matches, book, window and served parameters. The gaps in
nats are similar on both markets (0.020–0.042); the totals *budget* is
0.024–0.035 against 1X2's 0.116–0.133, so the same-sized error consumes the
whole of it. **The engine captures roughly three quarters of what the market
knows about who wins and approximately none of what it knows about how many
goals.**

### Findings worth not rediscovering

- **D0B-1.** Bundesliga's model assigned P(over 2.5) below 0.5 **zero times in
  612 matches** (range 0.549–0.847). Arithmetic, not tuning:
  `λ_h·λ_a ≡ base²`, so the expected total is `2·base·cosh(β·diff)`, minimised
  at parity, and `base = 1.44` puts the floor at 2.88 goals. The Bundesliga
  book cannot price a low-scoring match.
- **D0B-2.** Both shipped `base` overrides **did** move the model toward the
  market (Bundesliga −0.0336, EPL −0.0187; La Liga exactly +0.0000, having no
  override — the wiring check). #202's totals work was right. It moved the
  model from *much worse than a constant* to *level with a constant*, while the
  market sits 0.023–0.035 better than that constant. **G5 does not fire.**
- **D0B-3.** Under a fairly-fitted constant, the model is still beaten by a
  constant on O/U in **EPL and Bundesliga** — the same defect T1.1 was
  pre-registered to fix. EPL's apparent 0.0018 win over the pre-registered
  constant is an artifact of an 8.5-point regime shift between the fit window
  (over-rate 0.5217) and the scored window (0.6066); an oracle constant scores
  0.6703 against the model's 0.6830.
- **D0B-4 (negative).** De-vig method moves the market LL by ≤ 0.0011 nats and
  book choice (AvgC/PC/B365C/MaxC) by ≤ 0.0015. The headline rests on neither.
- **D0B-5 (negative).** Dixon–Coles `rho` is **exactly** vacuous on this market
  — τ touches only cells with total ≤ 2 and is mass-preserving, so it moves
  neither numerator nor denominator of P(total ≥ 3). Pinned by test. `rho`
  earns its keep on exact-score and BTTS, nowhere else measured here.
- **D0B-6.** The nine 2016-17…2018-19 captures **do** carry over/under columns
  (Betbrain `BbMx`/`BbAv`) — they lack a *closing* family. The earlier claim
  that they had none was wrong and is corrected in the pre-registration
  appendix. Admitting them would widen the sample ~50% with pre-closing rows
  reported as a closing benchmark; two tests pin the abstention.
- **D0B-7.** `pipeline/run_club_benchmark.py:98` calls `model_probs` with all
  defaults — `base = 1.35`, `beta = 0.0019`, `rho = 0.0`, no calibrator — a
  configuration production serves nowhere. **Open question for the human:**
  whether the recorded 1X2 gaps (+0.0312/+0.0279/+0.0326) came from that
  runner. D0-B computed 1X2 independently on served params over `2324`–`2425`
  and got +0.0420/+0.0340/+0.0203 — different window, so not a contradiction,
  but the two cannot both be called "the model's 1X2 gap" without saying which
  model and which seasons. Not fixed here.

### What D0-B did not do

Nothing was promoted. No served parameter, artifact or league override was
touched — enforced by a test that git-diffs `pipeline/leagues.py` and
`ml/models/model_params.json` against the merge base. No totals candidate was
proposed: the `λ_h·λ_a ≡ base²` observation is recorded as a measured property
of the code, not as a design. The only clean holdout remains **2026-27**.

## Branch-state anomaly — D1 is merged into a dead branch

**PR #214 (D1) reports `MERGED`, but its work is not in `main`.** It was merged
into `claude/finalwhistle-data-validation-2b6db1` — the D0 *branch* — at
`00:51:36Z`, six minutes after #213 had already squash-merged that same branch
into `main` at `00:45:32Z`. The D1 commits therefore reach no branch that feeds
`main`, and none of D1's files are present there:

- `pipeline/ingest/venue_coordinates.py`
- `ml/features/schedule_context.py`
- `pipeline/data/club_venues.json`, `club_venues_raw.json`, `club_venue_aliases.json`
- `docs/experiments/2026-07-30-d1-rest-travel/`

They are intact on `claude/finalwhistle-d1-rest-travel` at `21bc00d`. Recovering
them means opening a fresh PR from that branch against current `main`.
**Recorded as an observation for the human; no agent should quietly re-do D1's
work, and no agent should rewrite that history to "fix" it.**
