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
