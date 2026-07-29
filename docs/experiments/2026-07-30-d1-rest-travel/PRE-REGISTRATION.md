# CORRECTION, appended 2026-07-29 — read this first

**Everything below was committed in a single commit, `6b7c875`, together with
the implementation, the measured coverage and the evidence card.**

So the claim in the original header — *"Written 2026-07-29, before any D1
run"* — is **not verifiable from this repository**, and must not be relied on.
A pre-registration whose commit also contains the results it governs provides
no chronological guarantee at all: nothing in the history distinguishes
"written first" from "written afterwards to match".

The original text is left below **unaltered**, and the commit is not rewritten.
Correcting the record by editing it would destroy the very evidence this
correction is about.

Two further corrections to the content below, both from the same review:

1. **M3 was recorded PASS and was not.** The original design resolved one
   *current* venue per club and applied it backwards across nine seasons.
   Uniqueness of a club's coordinate does not prevent future venue state
   reaching an earlier fixture — it guarantees it, for any club that moved.
   Three in-scope clubs did: Tottenham, Brentford and Freiburg. See the
   evidence card's "Correction round" section.
2. **The travel candidates are blocked, not merely unrun.** Once venue must be
   established *on the fixture date*, coverage is **2.17%** (208 of 9,594),
   not the 100% originally reported. D1.1 / D1.2 / D1.4 have no usable sample.

**For the selection phase, this document is superseded** by
[`SELECTION-PRE-REGISTRATION.md`](SELECTION-PRE-REGISTRATION.md), which is
committed on its own, before any selection or effect measurement, precisely so
that its chronology *is* verifiable.

---

# D1 — Rest and travel: PRE-REGISTRATION

**Written 2026-07-29, before any D1 run.** Appended to afterwards; not edited in
place. Master ledger: [`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

---

## 0. The constraint that shapes this whole phase

**D1 cannot ship anything, and that is settled before the first run rather than
discovered after a favourable result.**

The repository's out-of-sample gate needs a clean confirmation season.
`docs/MODEL-EXPERIMENTS.md` records that 2025-26 is **consumed** — burnt by the
#202 confirmation phase — and names the live 2026-27 season as the next clean
holdout. 2026-27 is in progress and cannot confirm anything yet.

So D1 runs **selection only**, and the ship decision is deferred. The standing
rule is not negotiable: *nothing joins the served model without clearing the
existing out-of-sample gate*. A candidate that looks good in selection is
recorded as looking good in selection.

Declaring this first also removes the incentive that makes selection-only work
dangerous — there is no ship to argue for, so there is nothing to argue toward.

## 1. Baseline: rest was already tested, and refuted

This is the single most important input to D1, and it is easy to miss.

`docs/MODEL-EXPERIMENTS.md` pre-registered **T3.2 `rest_days`** — grid
`coef 0.000–0.020 step 0.002 × cap {0.05, 0.075, 0.10}` — and ran it. Result:

| League | Final pick | Mean Δ | CI95 | Verdict |
|---|---|---|---|---|
| EPL | (0.002, 0.05) | +0.0003 | [−0.0002, +0.0009] | **REFUTED** |
| Bundesliga | (0.000, 0.05) | +0.0003 | [−0.0002, +0.0010] | **REFUTED** |
| La Liga | (0.020, 0.05) | +0.0005 | [−0.0006, +0.0018] | **REFUTED** |

The machinery already exists and is wired: `ml/models/rest.py`
(`rest_offsets`, `DEFAULT_REST`), `ml/evaluation/club_walkforward.py`
(`rest_deltas`, `rest_coef`, `rest_cap`).

**Therefore D1 does not re-run T3.2.** Re-running a refuted candidate on the
same nine seasons until it clears is the definition of the practice this
repository's protocol exists to prevent.

What D1 may legitimately do with rest:

- **Re-specify it**, with the reason stated *before* the run. T3.2 tested a
  linear function of the rest *differential*, clipped to a 2–8 day window. A
  differently-shaped hypothesis (congestion load rather than gap length) is a
  new hypothesis, not a second attempt at the old one.
- **Use it as an interaction term** with travel, which was never tested at all.

Every rest candidate below is labelled with which of those it is.

## 2. What is genuinely new: travel

**Travel has never been tested in this repository.** No coordinate exists
anywhere in the codebase — verified by search across `pipeline/`, `ml/` and
`backend/app/`. There is no latitude, no longitude, no distance, for any venue
in any sport. D1 introduces the first one.

That makes the data layer, not the model result, the substance of this phase.

## 3. Measurable objective

For the three club leagues over 2016-17…2024-25:

- **O1** — build a deterministic, verifiable **club → home-venue coordinate**
  table with per-club provenance, and report resolution coverage with
  denominators. A club that does not resolve is **named, never guessed**.
- **O2** — derive pre-match travel and congestion candidates from **prior
  fixture dates and coordinates only**, with a leakage audit proving no
  match-day or post-match input can reach them.
- **O3** — run the pre-registered selection over 2016-17…2024-25 and record the
  result, including a null result.

## 4. Data source and licensing — deliberately unlike D0

| | |
|---|---|
| Source | **Wikidata** SPARQL (`query.wikidata.org`), properties `P115` (home venue) and `P625` (coordinate location) |
| Cost | free — no key, no account, no quota tier |
| Licence | **CC0 1.0** — Wikidata data is public domain by policy |
| Redistribution | **GRANTED.** Unlike football-data.co.uk (stop gate G1), CC0 explicitly permits redistribution |

**So the resolved coordinate table IS committed, bytes and all**, with each row
carrying its Wikidata QID, the label it resolved from, and the retrieval date.
That is the whole difference G1 is about: when redistribution is granted, the
snapshot can be committed and the result stays reproducible forever. D0's
finding D0-2 is what happens when it is not.

Feasibility probed 2026-07-29 before writing this: the endpoint returns real
coordinates for current top-flight clubs in all three leagues. Coverage of
*relegated* clubs across nine seasons is unknown and is exactly what O1 measures.

## 5. Candidate family — pre-registered, and small on purpose

Four candidates. The family is deliberately small: 27 gates at nominal 95%
already cost #202 roughly 1.35 expected false positives, and this phase cannot
afford a wide net it has no holdout to check.

| ID | Candidate | Kind | Grid |
|---|---|---|---|
| **D1.1** | **Away-team travel distance** — great-circle km from the away club's home venue to the match venue, as a bounded symmetric log-λ offset like `rest_offsets` | **NEW** | coef per 1000 km 0.00–0.10 step 0.01 × cap {0.05, 0.10} |
| **D1.2** | **Travel, log-scaled** — `log1p(km)` instead of raw km. A 400 km trip is not twice the burden of a 200 km one | **NEW** | coef 0.00–0.06 step 0.005 × cap {0.05, 0.10} |
| **D1.3** | **Congestion differential** — matches played in the trailing 14 days, home minus away | **RE-SPECIFIED** rest. T3.2 tested *gap length*; this tests *load*. A team playing its third match in 14 days is congested even if its last gap was 4 days | coef 0.00–0.06 step 0.005 × cap {0.05, 0.10} |
| **D1.4** | **Travel × short rest** — D1.1's distance applied only when the away side's rest is below the median | **NEW interaction** | coef as D1.1, threshold = training-block median |

**Not pre-registered, and not to be added later without a new explicitly
post-hoc row:** timezone deltas (all three leagues sit within one or two zones),
altitude, and any per-club fixed effect.

## 6. Acceptance criteria

| ID | Criterion |
|---|---|
| **B1** | Coordinate coverage reported per league with denominators: clubs resolved / clubs required, and every unresolved club named. |
| **B2** | Every coordinate row carries provenance: Wikidata QID, matched label, `P625` value, retrieval date, and the query's own fingerprint. A coordinate with no QID does not enter the table. |
| **B3** | Distances are reproducible offline from the committed table — no network at scoring time, and a test proves it. |
| **B4** | Leakage audit M1–M4 (§8) all pass. |
| **B5** | Selection runs walk-forward over 2016-17…2024-25 only; the 2025-26 captures are neither opened nor hashed (`pre_confirmation_keys()`). |
| **B6** | CIs reported **nominal and Bonferroni-corrected at k=4** over the family. |
| **B7** | The result is recorded whatever it is, and **nothing is promoted**. A cleared candidate is recorded as *awaiting the 2026-27 holdout*. |

## 7. Missingness policy

- **A club with no verified coordinate is not given one.** No city-centroid
  fallback, no nearest-neighbour, no "close enough". It is named in the report.
- **A match involving an unresolved club is excluded from the travel
  candidates and counted**, never scored with an imputed distance.
- **Neutral and relocated venues:** football-data.co.uk publishes **no venue
  column**. Travel is therefore computed as *away club's home venue → home
  club's home venue*, which is **wrong for any relocated or neutral-venue
  match, and this source cannot detect one*. Declared here, before the run,
  because it caps what any D1 result can mean. Known affected population: the
  2019-20 and 2020-21 COVID-era relocations. If a candidate clears, this
  limitation is a reason the effect estimate is attenuated, not a reason to go
  looking for a better number.
- **Openers have no prior fixture**, so rest and congestion are undefined for
  the first match of a club's season. Those matches get **no offset**
  (`rest_offsets` already returns `None`), never a default value.

## 8. Leakage audit

| ID | Property | How it is proven |
|---|---|---|
| **M1** | Every candidate is computable **strictly before kickoff**: inputs are prior fixture dates and static coordinates, nothing else. | Test feeding a fixture list truncated at match *n* and asserting the feature for match *n* is bit-identical to its value computed from the full season. |
| **M2** | **No result, score, or post-match quantity** reaches a candidate. | Test that tampers with every match's scores and asserts the derived features are unchanged. |
| **M3** | Coordinates are **static per club**, not per season, so no future-season stadium move can leak backwards — and where a club genuinely moved (e.g. Tottenham 2019), the table records one venue and the limitation is declared rather than silently time-varying. | Test asserting a single coordinate per club and a documented list of known movers. |
| **M4** | The confirmation season is neither read nor hashed. | Poison test in the D0/T1.6 style. |

## 9. Reproducibility receipt

The Wikidata response is snapshotted to a committed JSON artifact with its own
sha256, and the resolved table is derived from that snapshot — not from a live
query — so a re-run scores the same coordinates even if Wikidata changes. The
live query is an operator-run refresh, and a drift between snapshot and live is
reported, **never silently re-pinned** (the D0-2 rule, applied in advance).

## 10. Stop gates for D1

D1 halts and reports at any of:

1. Any proposal to **promote** a candidate to the served model. There is no
   clean holdout; promotion is not available at any effect size.
2. Coordinate resolution below the level at which the coverage report is
   honest — if a large share of clubs cannot be verified, D1 reports a blocked
   phase rather than a thinner dataset.
3. Any need to use a paid geocoder, an API key, or API-Football quota.
4. Any temptation to re-run T3.2 as-is, or to widen the candidate family after
   seeing a result.
5. Any point at which a coordinate would have to be guessed to make progress.

## 11. Explicitly NOT in D1

- No confirmation run. No promotion. No `model_params.json` change.
- No re-run of T3.2.
- No timezone, altitude, or weather input (weather is D4, and gated behind it).
- No database table, no migration, no serving change.
- No touching the D0 change set's conclusions, the T1.6 calibrator area, or #203.
