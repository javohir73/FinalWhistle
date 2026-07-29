# D0 — Independent market validation: PRE-REGISTRATION

**Written 2026-07-29, before any audit run.** Appended to afterwards; not
edited in place. Master ledger: [`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

**Odds are a BENCHMARK ONLY.** No phase of D0 lets a price become a training
feature, a label, or a served number. That is a structural constraint, tested
(§Leakage audit L1), not a promise.

---

## 1. Why this phase exists, and why it is first

`docs/MODEL-EXPERIMENTS.md` "Finding 1 (P1) — the market baseline was never
computed" records that the entire #202 club program — 27 gates, 9 candidate
families, two shipped parameter changes — scored **against realized outcomes
only**. The closing-line comparator the program was chartered on was never run,
because the CSV cache was built with
`usecols=[Date, HomeTeam, AwayTeam, FTHG, FTAG]` and the odds columns never
reached disk.

The audit then computed it retrospectively and reported the model is **behind
the closing line in all three leagues**, on "~70% of matches with odds".

That number is the yardstick every later phase (D1–D4) will be measured
against. Before another phase leans on it, D0 asks: **is it a closing line at
all, and is 70% the right denominator?**

Two facts already give grounds for doubt, both established before this
pre-registration was written and both recorded here so the audit cannot be
accused of finding what it went looking for:

- **`pipeline/ingest/football_data.py::_ODDS_CHAIN` falls back from closing to
  pre-closing columns silently.** Its chain is `AvgC → PSC → B365C → MaxC →
  Avg → B365`. The last two carry no `C`. football-data.co.uk's own notes
  state plainly: *"The following key to betting odds data is described below.
  These are for pre-closing odds. For the closing odds, as below but with an
  additional 'C' character."* Selection is per **file**, from the header, so a
  season file that has no `C` columns at all yields **pre-closing odds labelled
  and reported as a closing-line benchmark**. The module's own docstring says
  it "always prefers the CLOSING odds columns — the sharpest public predictor,
  and the only fair yardstick".
- **The manifest's own byte sizes suggest the earliest seasons have no closing
  columns.** In `pipeline/data/club_data_manifest.json`, `D1_1617/1718/1819`
  are 77–80 KB and every later D1 file is 139–168 KB; `E0_1617/1718/1819` are
  98–103 KB against 176–209 KB later. Three of ten seasons per division is
  exactly 70% — the audit's reported odds coverage, to the digit.

If both hold, "~70% of matches carry odds" is not a missingness rate. It is
**three whole seasons missing the closing line**, and the remaining seven
carrying it — a materially different fact, with a materially different fix.

**Neither is established yet.** Both are hypotheses this audit will confirm or
refute against the bytes, and a refutation is recorded as loudly as a
confirmation (§7).

## 2. Measurable objective

For every in-scope `(division, season)` file, determine and record:

- **O1** — which 1X2 odds column families are present, and for each, the
  per-match non-null rate.
- **O2** — whether a **true closing** (`*C*`) family is available at all.
- **O3** — the exact basis the current code path would select, and whether that
  basis is closing or pre-closing.
- **O4** — the join rate between parsed odds rows and the model's match rows,
  with every drop attributed to a named reason.

Success is a **census**, not a verdict on the model. D0 changes no parameter,
fits nothing, and ships no model change.

## 3. Baseline

The current path, unchanged, is the baseline:

| Component | File |
|---|---|
| CSV parse + odds-column selection | `pipeline/ingest/football_data.py` |
| Proportional de-vig, join, paired benchmark | `ml/evaluation/market_benchmark.py` |
| Offline club runner | `pipeline/run_club_benchmark.py` |
| Input fingerprint | `pipeline/club_data_manifest.py` + `pipeline/data/club_data_manifest.json` |

Baseline behaviour to beat: odds basis is a bare string (`"AvgC"`), carried
nowhere; coverage is reported as one pooled percentage with no denominators;
there is no licence or provider provenance in any output; no test asserts that
a closing-labelled benchmark actually used closing prices.

## 4. Scope

**Divisions** — `E0` (Premier League), `SP1` (La Liga), `D1` (Bundesliga): the
three leagues in `pipeline/leagues.py`. No pooling across them, ever.

**Seasons — default scope is the 27 PRE-CONFIRMATION files**
(2016-17…2024-25), via `pipeline.club_data_manifest.pre_confirmation_keys()`.

The 2025-26 (`2526`) captures are **not opened by default**. Auditing a file
means reading its bytes, and T1.6 already established in this repository that
hashing a capture is itself a holdout read
(`docs/MODEL-EXPERIMENTS.md`, "Manifest scope — the holdout is never opened").
D0 inherits that scope discipline rather than re-litigating it. An explicit
`--include-confirmation` flag exists for the #202-reproduction scope; using it
is recorded in the evidence card with a reason.

## 5. Acceptance criteria

Pre-committed and falsifiable. D0 ships when all seven hold; any that fails is
recorded as failed.

| ID | Criterion |
|---|---|
| **A1** | A per-`(division, season)` census exists covering O1–O3, emitted as JSON and rendered into the evidence card. |
| **A2** | The loader can no longer return pre-closing odds from a closing-labelled request. Either it declares `odds_basis` explicitly on every record and the caller selects, or it refuses. Pinned by a test built on a fixture with **no `C` columns**. |
| **A3** | Provenance travels end-to-end into benchmark output: provider, source URL, licence statement, capture date, per-file sha256, odds column family, `odds_basis`, de-vig method. A benchmark result that cannot state its provenance does not serialize. |
| **A4** | No coverage number is reported without its denominators: `n_eligible`, `n_matched`, `coverage_rate`, and a per-reason drop breakdown that sums exactly to `n_eligible − n_matched`. |
| **A5** | Leakage audit L1–L4 (§8) all pass. |
| **A6** | Every new test is hermetic — no network, no DB, no credential. Fetching lives behind an operator-run CLI that tests never call for real. |
| **A7** | A cold-clone reproduction receipt exists: exact command, input fingerprints, code revision, and the drift verdict against `club_data_manifest.json`. |

## 6. Data fingerprint, and what "immutable snapshot" means here

football-data.co.uk **revises published season files in place**
(`pipeline/club_data_manifest.py`). The existing manifest already pins
sha256/size/rows for 30 files captured 2026-07-28. D0 extends the receipt, it
does not replace it:

- The existing 30-file manifest is **not re-pinned**. Drift against it is a
  finding to record, never something to paper over — that rule is inherited,
  not invented here.
- D0 adds a **column-level census** keyed by the same `{DIV}_{SEASON}` names,
  so a future run can tell "the publisher revised the file" from "the publisher
  added an odds column" — which the byte hash alone cannot distinguish.
- **The snapshot descriptor is committed. The bytes are not.** See §Licensing.
  Raw captures stay in a gitignored working directory.

## 7. Missingness policy

- Missing is **reported, never imputed**. No forward-fill, no cross-season
  substitution, no borrowing another bookmaker's price to stand in for a
  missing one.
- A match with no usable odds triple is **excluded from the market comparison
  and counted**, never scored against a guessed price.
- A season file with no closing family is **abstained from a closing-line
  benchmark entirely**, and named in the report. It is not silently pooled
  with seasons that have one.
- **Pre-closing odds are a separate, separately-labelled series.** They may be
  reported side by side with closing odds for contrast. They may never be
  merged into one "market" column.
- Every refutation, including of the two §1 hypotheses, is recorded.

## 8. Leakage audit

| ID | Property | How it is proven |
|---|---|---|
| **L1** | No odds value reaches any fit, feature, or rating path. | Structural test over the ratings/feature modules: the market benchmark is imported by evaluation and runners only. |
| **L2** | The odds→match join is **exact** on `(date, home, away)`; no fuzzy or nearest-date matching is introduced. Orientation swap is permitted only where it already exists, and flips the H/A probabilities. | Test with a near-miss fixture (same clubs, adjacent date) asserting it does **not** join. |
| **L3** | Closing prices are post-hoc information relative to any pre-match model input, so they may only ever be a **comparator**. A closing price must never be attached to a row that a model later trains on. | Enforced by L1 plus A3's explicit `odds_basis` — a benchmark row is a distinct type from a training row. |
| **L4** | Under default scope, the three `*_2526` captures are never opened. | Poison test in the T1.6 style: replace each confirmation capture with a directory so any `read_bytes()` raises, prove the 27-file path completes, then prove the poison is real by showing the unscoped call still raises. |

## 9. Timestamp and closing-line rules

football-data.co.uk publishes **one row per finished match**, not a timestamped
price series. That means:

- There is **no capture timestamp** per price, and D0 must not manufacture one.
  The only honest provenance is: publisher, file, capture date of *the file*,
  and the column family's documented meaning.
- "Closing" is therefore **a column-family claim by the publisher**, not an
  observation this repo made. It is recorded as such. `odds_basis` takes the
  value `closing` or `pre_closing` on the publisher's documented definition of
  the `C` suffix, and nothing stronger is asserted.
- The strictly-pre-kickoff rule that governs live capture
  (`docs/VALIDATION-DATA-SOURCES.md`) **cannot be checked here** — there is no
  per-price timestamp to check it against. That limitation is declared in the
  evidence card rather than glossed.

## 10. De-vigging

Current behaviour is proportional normalization (`raw_i / Σ raw`), applied in
two places with duplicated logic (`ml/evaluation/market_benchmark.py::devig`,
`pipeline/ingest/football_data_odds.py::implied_probabilities`).

D0 makes the method **explicit and selectable**, and reports which was used:

| Method | Note |
|---|---|
| `proportional` | **Default. Unchanged.** Every number already in `docs/MODEL-EXPERIMENTS.md` used it; changing the default silently would invalidate them. |
| `shin` | Balanced-book model with insider trading; standard in the literature for 1X2. Offered as a sensitivity check. |
| `power` | Log-odds/power normalization; the third common choice. |

**The de-vig method is a reported field, not an implementation detail.** A
sensitivity table across the three is a D0 deliverable, because the audit's
headline claim ("the model is behind the closing line") should not rest on an
arbitrary normalization. It is not a tuning knob: no method is selected on the
basis of which makes the model look better, and the default does not move.

## 11. Cost and licensing limits

**Cost: zero.** football-data.co.uk CSVs are free HTTP downloads, no key, no
account, no quota. D0 makes **no paid call**, adds **no credential**, enables
**no capture**, and writes **no production**.

**Licensing — stop gate G1, open.** Verified on the publisher's own pages
2026-07-29:

- "Simply download for free the available files" — free download is granted.
- "© Football-Data. Liability Disclaimer. All Rights Reserved." — **no
  redistribution grant appears anywhere on the site.**

Free-to-download is not free-to-redistribute. D0 therefore commits a
**fingerprint descriptor** (hashes, row counts, column presence, non-null
rates) and **not the CSV bytes**, which keeps the receipt verifiable without
republishing the publisher's dataset. Whether to vendor the raw files into the
repository is a licensing decision for the human, recorded as **G1** in the
master ledger and **not decided by the agent**.

Attribution is carried in the provenance record on every output (A3).

## 12. Stop gates for D0

D0 halts and reports, rather than proceeding, at any of:

1. **G1** — any proposal to commit, publish, or otherwise redistribute
   football-data.co.uk bytes.
2. A finding that would change a number already published in
   `docs/MODEL-EXPERIMENTS.md`. D0 **appends a correction**; it does not edit a
   recorded result.
3. Any need to touch the scope-guard files in the master ledger.
4. Any temptation to re-pin `club_data_manifest.json` because a file drifted.
   Drift is a finding. Re-pinning destroys the evidence that it drifted.
5. Any point at which odds would need to enter a fit path to make progress.

## 13. Explicitly NOT in D0

- No model parameter is fitted, tuned, or shipped.
- No live/2026-27 data, no capture, no scheduling.
- No change to the frozen q3 baseline or the API-Football `odds` table.
- No new database table, no migration.
- No re-run of the #202 gates.
- No artifact published to any research surface.
