# D0 — Independent market validation: EVIDENCE CARD

Run 2026-07-29. Pre-registration: [`PRE-REGISTRATION.md`](PRE-REGISTRATION.md)
(committed at `8ea3edf`, **before** any audit run). Master ledger:
[`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

**Nothing here changes a model parameter, a served number, or a recorded
result.** One correction is *appended* to `docs/MODEL-EXPERIMENTS.md`; nothing
in that file is edited.

---

## Headline

`docs/MODEL-EXPERIMENTS.md` "Finding 1 (P1)" computed the club market baseline
on "**~70% of matches [that] carry odds**" (EPL n=2,660 · La Liga n=2,660 ·
Bundesliga n=2,142).

**That 70% is not a data-availability limit. It is the consequence of pinning
one column family.** Across the 27 pre-confirmation captures, **100% of matches
carry a closing line** — 3,420/3,420 (E0), 3,419/3,420 (SP1), 2,753/2,754 (D1).
Only 66.7% carry the *market-average* closing family (`AvgC*`). The other third
carry **Pinnacle closing** (`PSC*`), which football-data.co.uk has published in
every season file in the window.

**1,140 + 1,139 + 917 = 3,196 priced matches were discarded by a column
choice**, not missing from the source.

## Both pre-registered hypotheses were refuted

The pre-registration named two suspicions and committed to reporting a
refutation as loudly as a confirmation. Both were refuted.

| # | Hypothesis as written | Outcome |
|---|---|---|
| H1 | The loader's `AvgC → … → Avg → B365` chain **is** silently substituting pre-closing odds into a closing-line benchmark | **REFUTED for these captures.** No capture falls through to `Avg`/`B365`: every one of the 27 lands on a `C`-suffixed family. The fallback is a **latent** defect, never an observed one. |
| H2 | "~70%" means three seasons per division have **no closing line** | **REFUTED as stated.** The three earliest seasons per division have no `AvgC*` but do have `PSC*`. They were never short of a closing line. |

H1's refutation matters for how the fix is described. The silent-substitution
path is real and still reachable — a future capture with no `C` family would
return pre-closing prices under a closing-line label — but **it did not fire
here**, and this card does not claim it did.

## Findings

### D0-1 (P1) — the market baseline used 7 of 10 seasons, and the discarded ones are sharper

`AvgC*` first appears in the 2019-20 files. Finding 1's n figures are exactly
`7 × 380` and `7 × 306` — the `AvgC` era, to the match.

Where both families exist, they are the same predictor: over 18 overlapping
captures the mean log-loss difference is **0.0004 nats**, the maximum absolute
difference is **0.0025 nats**, and Pinnacle is ahead in 11 of 18. Raw table:
[`avgc-vs-psc.txt`](avgc-vs-psc.txt).

So `PSC` is a valid stand-in where `AvgC` is absent, and using it recovers the
three earliest seasons per division. **This is not a free win for the model.**
The recovered seasons carry a *sharper* market in England and Spain (E0
0.8907–0.9405, SP1 0.8997–1.0017, against 0.90–1.00 in the `AvgC` era), so a
best-available-closing benchmark sets a **harder** bar than the one already
recorded, not an easier one.

**What this does not say.** No model-vs-market number is recomputed here. D0
audits the yardstick; re-running the paired benchmark on the wider base is D0's
recommendation, not its result.

### D0-2 (P1) — all 27 pinned captures have drifted, and the drift is undiagnosable

`pipeline/data/club_data_manifest.json` pins sha256 for 30 season files captured
2026-07-28. Re-downloaded 2026-07-29: **27 of 27 in-scope files mismatch.** Row
counts are unchanged (380/380/306, exactly as pinned); every file is smaller,
by 1,463–11,968 bytes.

**Nothing was re-pinned.** Per the manifest module's own rule, drift is a
finding.

The diagnosis stops there, and that is the point: **the manifest pins hashes but
the bytes were never retained**, so "the publisher revised a price" and "the
publisher trimmed padding" are indistinguishable after the fact. A byte hash can
say *that* a file moved and never *what* moved.

The byte deltas are consistent with removal of ~7–12 trailing padding commas per
line, and no capture now carries an `Unnamed:` column — but that is a
**hypothesis, not a finding**, and it cannot be tested without the 2026-07-28
bytes. The census artifact
([`coverage-census.json`](coverage-census.json)) now records per-file column
counts, per-family presence, usable counts and per-family market log loss, so
**the next drift will be diagnosable** even though this one is not.

Consequence, stated plainly: **the #202 market numbers cannot currently be
reproduced byte-for-byte from a live download.** Whether to vendor the raw
captures so they can be is stop gate **G1** — a licensing decision, below.

### D0-3 (P2) — the loader could substitute a different market under the same label

`_ODDS_CHAIN` ended `… → Avg → B365`, neither of which is a closing line. The
publisher's `notes.txt` is explicit: the documented abbreviations *"are for
pre-closing odds. For the closing odds, as below but with an additional 'C'
character."* The module's own docstring claimed it "always prefers the CLOSING
odds columns — the sharpest public predictor, and the only fair yardstick".

Latent, not fired (see H1). Fixed anyway: the loader now refuses a
closing-labelled request it cannot honour, every record carries `odds_basis`
and its bookmaker, and pre-closing prices are reachable only by asking for them.
The test that previously **pinned the fallback as correct behaviour**
(`test_falls_back_when_no_closing_columns`) is replaced by one that pins the
refusal.

## Negative results

Recorded because they cost the same to find as a positive one.

- **The headline does not rest on the de-vig choice.** Market log loss over the
  27 captures, best-available closing family:

  | method | E0 | SP1 | D1 |
  |---|---|---|---|
  | proportional | 0.9415 | 0.9644 | 0.9809 |
  | shin | 0.9413 | 0.9641 | 0.9813 |
  | power | 0.9412 | 0.9640 | 0.9816 |

  Spread ≤ 0.0007 nats — two orders of magnitude below the ~0.03 nat gap
  between model and market in Finding 1. **The de-vig method is not where the
  answer lives.** Proportional stays the default.

- **No leak was found.** L1–L4 all pass, and none of them found an existing
  defect to fix. They are regression guards, not repairs.

- **Coverage is not the model's problem.** The audit began from a suspicion that
  missing odds were degrading the benchmark. They are not missing. The
  benchmark's weakness was a column choice and an unretained snapshot.

## Acceptance criteria

| ID | Verdict | Evidence |
|---|---|---|
| A1 census exists | **MET** | [`coverage-census.json`](coverage-census.json), [`coverage-report.txt`](coverage-report.txt) |
| A2 no silent substitution | **MET** | `test_refuses_pre_closing_odds_by_default`, `test_pre_closing_odds_available_only_on_explicit_opt_in` |
| A3 provenance end-to-end | **MET** | `PROVIDER` on every census; `odds_basis`/`odds_bookmaker` on every record; `test_provenance_travels_on_the_census` |
| A4 denominators always | **MET** | `test_drop_reasons_are_exhaustive_and_sum_to_rows` proves `usable + Σdrops == rows` |
| A5 leakage L1–L4 | **MET** | `pipeline/market_leakage_test.py`, `test_join_is_exact_and_a_near_miss_does_not_match`, `test_default_scope_never_opens_a_confirmation_capture` |
| A6 hermetic tests | **MET** | `test_census_makes_no_network_call`; `fetch_captures` is operator-only and never called for real |
| A7 reproduction receipt | **MET, with a declared limitation** | below — the receipt is exact, but D0-2 means it reproduces *today's* publisher bytes, not 2026-07-28's |

## Reproduction receipt

```bash
# 1. fetch the free public captures (no key, no account, no cost)
PYTHONPATH=backend:. .venv/bin/python -m pipeline.market_coverage \
    --dir data/raw/club --fetch

# 2. census + de-vig sensitivity + drift check
PYTHONPATH=backend:. .venv/bin/python -m pipeline.market_coverage \
    --dir data/raw/club --sensitivity \
    --emit-json docs/experiments/2026-07-29-d0-market-validation/coverage-census.json
```

| | |
|---|---|
| code revision | `86f8c8b` (branch `claude/finalwhistle-data-validation-2b6db1`, from `main` at `eebff2c`) |
| python / pandas | 3.12.1 / 3.0.3 |
| scope | 27 pre-confirmation captures (`pre_confirmation_keys()`); the three `*_2526` captures were **never fetched and never opened** |
| input fingerprints | per-file sha256 in [`coverage-census.json`](coverage-census.json) |
| drift verdict | **27/27 drifted** vs `pipeline/data/club_data_manifest.json`; manifest byte-identical to `main` |
| python suite | 2,577 passed |

## Limitations, declared

1. **No per-price timestamp exists.** These files are one row per finished
   match. "Closing" is a **publisher claim about a column family**, not a
   capture time this repo observed. The strictly-pre-kickoff rule that governs
   live capture cannot be checked here at all.
2. **`Time` (kickoff) only exists from 2019-20.** The nine earliest captures
   have no kickoff time. D1 (rest/travel) and D4 (weather) both need it — plan
   around its absence rather than discovering it later.
3. **The confirmation season was not examined.** 2025-26 is consumed; opening a
   capture is a holdout read. Any statement here covers 2016-17…2024-25 only.
4. **D0-2 is not diagnosed, only detected.**
5. **No model-vs-market number was recomputed.** D0 audited the yardstick.

## Stop gates

**G1 — redistribution of football-data.co.uk bytes. OPEN, human decision.**

The publisher grants free download ("Simply download for free the available
files") and reserves all rights ("© Football-Data. Liability Disclaimer. All
Rights Reserved."). **No redistribution grant appears on the site.**

D0 therefore committed a fingerprint descriptor and left the CSVs in a
gitignored working directory. D0-2 is the cost of that choice: without retained
bytes, drift cannot be diagnosed and the #202 numbers cannot be reproduced
exactly. Vendoring the 27 captures (~3.6 MB) into this private repository would
fix that permanently — **and it is a licensing call for the human, not the
agent.** Recorded, not decided.

No other gate was reached: zero spend, no credential, no capture enabled, no
production write, no migration, no published artifact.

## Recommendation for the next phase

Not done here, and deliberately so — each is a separate decision:

1. **Re-run the club market benchmark on best-available closing**, reporting
   `AvgC`-only and best-available side by side. It widens the evidence base by
   ~43% and raises the bar.
2. **Decide G1.** Everything about reproducibility downstream depends on it.
3. **Carry `odds_basis` into any future benchmark output**, so no published
   number is ever again ambiguous about which market it scored.
