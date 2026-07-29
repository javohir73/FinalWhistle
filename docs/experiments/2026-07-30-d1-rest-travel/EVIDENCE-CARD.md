# CORRECTION ROUND, appended 2026-07-29 — read this before anything below

A review of the first D1 cut found four defects. Three of them invalidate
headline claims in the original card, which is left below **unaltered** so the
correction is auditable rather than cosmetic.

## C1 — the pre-registration chronology is not verifiable

`PRE-REGISTRATION.md`, the implementation, the coverage numbers and the
original evidence card **all landed in one commit, `6b7c875`**. The claim
"committed before any run" therefore has no support in this repository's
history, and is withdrawn. The commit is not rewritten; see the correction at
the head of `PRE-REGISTRATION.md`.

The selection phase now has its own standalone, separately-committed
[`SELECTION-PRE-REGISTRATION.md`](SELECTION-PRE-REGISTRATION.md) so that *its*
chronology is verifiable.

For contrast, D0's pre-registration **is** verifiable: `8ea3edf` contains the
pre-registration and the program ledger — two documents, no code and no
results — and the implementation landed later in `86f8c8b`.

## C2 — M3 was recorded PASS and was false

The original card asserted M3 as *"one coordinate per club — a season-varying
venue would let a later stadium move leak backwards"*. That reasoning is
backwards. Uniqueness does not **prevent** future venue state reaching earlier
fixtures; for a club that moved, it **guarantees** it.

Three in-scope clubs moved, and the first snapshot was wrong for all three:

| Club | First snapshot resolved | Actually played at | Wrong for |
|---|---|---|---|
| **Brentford** | Griffin Park | Brentford Community Stadium | **every** in-scope season (2021-22→); Wikidata has no statement for the new ground at all |
| **Tottenham** | Tottenham Hotspur Stadium | White Hart Lane (→2017), **Wembley** (2017-19), new stadium (2019→) | 2016-17 through 2018-19; Wembley is ~10 km away and Wikidata records nothing for it |
| **Freiburg** | Europa-Park-Stadion | Dreisamstadion until Oct 2021 | 2016-17 through most of 2021-22 |

Venue is now modelled as an **interval** with `valid_from`/`valid_to`, looked
up **at the fixture date**, and abstaining whenever the answer is not
established. M3 is restated as a temporal property and tested as one.

## C3 — travel coverage was 100%; it is actually 2.17%

Requiring the venue in force *on the fixture date* for both clubs, and
excluding what cannot be established:

| Division | Fixtures | Travel defined | Coverage |
|---|---|---|---|
| E0 | 3,420 | 14 | **0.41%** |
| SP1 | 3,420 | 62 | **1.81%** |
| D1 | 2,754 | 0 | **0.00%** |
| **All** | **9,594** | **76** | **0.79%** |

Exclusions, all named and summing exactly to the shortfall:

| Reason | E0 | SP1 | D1 |
|---|---|---|---|
| `single_undated` — one venue, no date qualifier, unverifiable | 3,129 | 2,311 | 1,944 |
| `ambiguous_undated` — several venues, none dated | — | 449 | 648 |
| `boundary_precision_unknown` — the date falls inside a coarse boundary's uncertainty | — | 580 | 162 |
| `excluded_declared` — Brentford, Tottenham | 273 | — | — |
| `relocation_risk_season` — COVID-era 2019-20 / 2020-21 | 4 | 18 | — |

> **Revised after the second review round (C5–C6 below).** The first version of
> this table reported 208 / 2.17% and attributed 2,132 fixtures to
> `relocation_risk_season`. Both were wrong: date precision was not respected,
> and the season rule was tested before the venue rule, so COVID absorbed
> exclusions whose binding constraint was actually an unusable venue history.

**Root cause: Wikidata cannot date these clubs.** Measured across all 94:

| status | clubs |
|---|---|
| `single_undated` | 73 |
| `dated` | 11 |
| `ambiguous_undated` | 8 |
| `excluded_declared` | 2 |

(The authoritative copy is `status_counts` in `pipeline/data/club_venues.json`;
this table summarises that artifact rather than counting independently.)

**Verdict: the travel candidates D1.1 / D1.2 / D1.4 are BLOCKED**, not merely
unrun. 76 fixtures — 14 in England, 62 in Spain, **none at all in Germany** —
is not a sample any of the pre-registered grids could be fitted on. D1.3 (congestion) needs no coordinate
and is unaffected.

Unblocking travel requires a venue-history source with effective dates and
primary-source provenance. That is a data-acquisition decision, and it is not
made here.

## C4 — the reproducibility receipt was not auditable

`club_venues.json` held derived rows plus a query hash. Nothing in it could
show what Wikidata actually returned, so a resolver change and a provider
change were indistinguishable after the fact — the same failure D0-2 records
for football-data.co.uk, reproduced in a phase that had the licence to avoid it.

Now: `pipeline/data/club_venues_raw.json` holds the **raw SPARQL bindings**
with retrieval time, the exact query, a digest over the bindings, provider
QIDs, ranks and `P580`/`P582` qualifiers, the CC0 licence source, and the WDQS
usage and rate-limit notes an operator needs to re-run it. `club_venues.json`
is **derived from that file and nothing else**, and a test rebuilds it
byte-for-byte offline. A test also proves the digest catches an edited receipt.

## C5 — a year-precision date was read as 1 January (P1, second round)

The C2 fix modelled venue as an interval but still read every `P580`/`P582`
literal as a **day**. Wikidata serialises a *year*-precision qualifier as
`YYYY-01-01`, and the precision lives on the value node, which the query did
not fetch.

So `venue_on` did not abstain — it answered **confidently and wrongly**:

- Atlético Madrid's Metropolitano interval opened `2017-01-01`; the ground
  opened **16 September 2017**.
- `venue_on(2017-05-21)` returned Metropolitano. That fixture was the **Vicente
  Calderón farewell match** — the last game ever played there, scored against a
  stadium that did not yet exist, 10.94 km away.
- Six of the then-208 travel-defined fixtures were affected; three more were
  right only by luck.

This is the same class of defect as C2 — future venue state reaching an earlier
fixture — surviving the correction written to remove it. Eleven of the 39 date
literals in the receipt fall on 1 January; under genuine day precision that has
probability ~1e-19.

**Fixed.** The query now projects `pqv:P580`/`pqv:P582` value nodes with
`wikibase:timePrecision`. A boundary is `in`, `out`, or **`unknown`** — three
valued, because collapsing an indeterminate boundary to a boolean is exactly
what produced a confident wrong answer. A year-precision boundary makes its
whole year unanswerable; a month-precision one, its month; a boundary with no
precision at all is unusable everywhere. One indeterminate interval abstains
the whole club, since "exactly one interval covers this" is not knowable while
another might have opened.

Atlético now abstains across the whole of 2017 and answers correctly on either
side of it.

## C6 — the exclusion table blamed COVID for venue problems

`travel_exclusion_reason` tested the relocation-risk season **before** the venue
status, so a fixture that was unusable for both reasons was attributed to COVID.
That over-attributed **2,132** fixtures and hid the real constraint.

**Fixed:** venue status is tested first, because it is the reason an operator
could act on. `relocation_risk_season` falls from 2,132 to **22** — those are
the only fixtures whose *sole* disqualification was the season.

## C7 — the receipt verified only its bindings, and its rebuild command was dead

Two auditability defects the second round found in the C4 fix itself:

- `load_raw_snapshot` recomputed only `bindings_sha256`. The recorded `query`
  could be swapped for unrelated SPARQL and nothing noticed — including the
  test suite, which stayed green while `derived_from.query_sha256` still
  reported the old digest. Now the query digest and an **envelope digest** over
  all provenance metadata are both verified, so editing the licence text or the
  retrieval time is caught too. The bindings digest is also order-independent,
  because WDQS has no `ORDER BY` and a re-fetch legitimately returns rows in a
  different order.
- The §7 reproduction receipt named `fetch_bindings`, `resolve` and
  `snapshot_payload` — all renamed away by the C4 commit, which did not update
  the card. The phase's only documented rebuild command **could not run**. It is
  now `python -m pipeline.ingest.venue_coordinates --refresh|--verify`, and
  `--verify` is exercised by a test.

Also fixed in this round: the derived table now records the **receipt's**
provider block rather than the module constant; the module docstring's temporal
census is derived from the artifact instead of being a hand-written second count
that disagreed with it in all four cells; the query projects `?club` so club
QIDs are in the receipt; the L1 leakage scanner anchored a package's
`__init__.py` one level too high and went green on a live relative import;
`_CONFIRMATION_SUFFIX` is derived from `CONFIRM_SEASON` and the test its comment
promised now exists; and the D0 capture fetcher no longer sends a forged
`curl/8` user agent to the one provider whose terms this program is careful
about.

## What still holds from the original card

- 94/94 clubs resolve to *a* venue with a checkable QID.
- The capacity rule still separates stadiums from training grounds.
- Rest and congestion coverage (99.2–99.4%) is unchanged — neither needs a
  coordinate.
- Licensing: Wikidata is CC0, so both snapshots ship as bytes.
- Nothing is promoted, and nothing can be.

---

# D1 — Rest and travel: EVIDENCE CARD

Run 2026-07-29. Pre-registration: [`PRE-REGISTRATION.md`](PRE-REGISTRATION.md),
committed before any D1 run. Master ledger:
[`docs/DATA-VALIDATION-PROGRAM.md`](../../DATA-VALIDATION-PROGRAM.md).

**Nothing here is promoted, and nothing here can be.** The out-of-sample gate
needs a clean confirmation season; 2025-26 is consumed and 2026-27 is still
being played. That was settled in the pre-registration, before any number
existed to argue about.

---

## Status

| Deliverable | State |
|---|---|
| Verified club→venue coordinate layer | **DONE** — 94/94 resolved, snapshot committed |
| Deterministic pre-match candidates (rest, congestion, travel) | **DONE** — implemented, coverage measured |
| Leakage audit M1–M4 | **DONE** — passing |
| Pre-registered selection run over 2016-17…2024-25 | **NOT RUN** — see §6 |
| Promotion | **BLOCKED BY DESIGN** — no clean holdout exists |

## 1. The coordinate layer — the actual substance of this phase

Before D1 there was **no coordinate anywhere in this repository**: no latitude,
no longitude, no distance, for any venue in any sport. Travel had therefore
never been testable here, whatever anyone believed about it.

**94 of 94 clubs resolved — 100% in all three leagues**, every one carrying a
Wikidata QID a human can check.

| Division | Clubs required | Resolved | Unresolved |
|---|---|---|---|
| E0 | 34 | **34 (100%)** | 0 |
| SP1 | 30 | **30 (100%)** | 0 |
| D1 | 30 | **30 (100%)** | 0 |

Artifacts: [`pipeline/data/club_venues.json`](../../../pipeline/data/club_venues.json)
(the committed snapshot),
[`pipeline/data/club_venue_aliases.json`](../../../pipeline/data/club_venue_aliases.json)
(naming only — a test asserts it holds no numbers).

### The rule that made 100% possible, and why it needed a third step

1. Alias table: football-data.co.uk short label → canonical club name.
2. Candidate venues = every non-ended `P115` on any entity matching that name,
   carrying both `P625` (coordinates) and `P1083` (capacity).
3. **Rank by capacity; require a strictly unique maximum.**

Step 3 is not tidying. Wikidata lists training grounds and former stadiums as
current home venues with no end date:

| Club | Candidates Wikidata offers | Capacity separates them |
|---|---|---|
| Athletic Bilbao | Lezama Facilities / San Mamés | 3,250 vs **53,289** |
| RB Leipzig | Cottaweg / Red Bull Arena | none vs **42,000** |
| SC Freiburg | Dreisamstadion / Europa-Park-Stadion | 24,000 vs **34,700** |
| Crystal Palace | Crystal Palace Park / Selhurst Park | none vs **26,255** |

And because the *venue* is what matters, several club entities sharing one
label resolve cleanly when they agree — FC Barcelona is modelled as a men's
team, a multisport club and a non-profit, and all three point at Camp Nou.

**A tied maximum is a `conflict` and a missing one is `unresolved`. Neither is
ever settled by picking.** Zero of either occurred, but the refusal paths are
tested, because a rule that has never refused anything is not known to work.

### Distances are checked against geography, not just against themselves

| Fixture | km | Expectation |
|---|---|---|
| Man United → Man City | 6.4 | Manchester derby |
| Tottenham → Arsenal | 6.2 | North London derby |
| Schalke 04 → Dortmund | 27.5 | Revierderby |
| Holstein Kiel → Bayern Munich | 689.6 | Kiel to Munich |
| Las Palmas → Real Madrid | 1,744.7 | Canary Islands to mainland |
| Girona → Las Palmas | 2,259.7 | longest journey in scope |

Pinned as regression tests, so a latitude/longitude swap — which produces
distances that are wrong but plausible — cannot pass quietly.

## 2. Licensing — the deliberate contrast with D0

| | D0 (football-data.co.uk) | D1 (Wikidata) |
|---|---|---|
| Cost | free | free |
| Licence | © All Rights Reserved | **CC0 1.0** |
| Redistribution | **not granted** → stop gate G1 | **granted** |
| Snapshot in repo | fingerprints only | **bytes, committed** |
| Reproducible after upstream changes? | **No** — see D0-2 | **Yes** |

D0 finding D0-2 is precisely what the left-hand column costs: all 27 captures
drifted, and because the bytes were never retained the drift cannot be
diagnosed. D1 does not have that exposure, and the reason is the licence.
**G1 remains open and is still the human's call** — this is evidence for the
decision, not the decision.

## 3. Candidate coverage over 2016-17…2024-25

| Division | Fixtures | Rest defined | Openers (undefined) | Travel defined | No coordinate | Median km | p95 km | Max km |
|---|---|---|---|---|---|---|---|---|
| E0 | 3,420 | 3,396 | 24 | **3,420 (100%)** | 0 | 174.1 | 378.4 | 471.7 |
| SP1 | 3,420 | 3,400 | 20 | **3,420 (100%)** | 0 | 428.5 | 954.4 | 2,259.7 |
| D1 | 2,754 | 2,733 | 21 | **2,754 (100%)** | 0 | 304.2 | 513.7 | 721.4 |

Raw: [`schedule-coverage.txt`](schedule-coverage.txt), [`schedule-coverage.json`](schedule-coverage.json).

Two things worth noting before any modelling:

- **La Liga is where the travel range lives.** Its p95 is 954 km against
  England's 378, and the Canary Islands clubs push the maximum past 2,250 km.
  If travel has an effect anywhere in this dataset, La Liga is where it is
  detectable; England barely varies.
- **Congestion has real variance** — sd of the home-minus-away differential is
  0.55 / 0.55 / 0.44 matches. It is not a near-constant, so it is at least
  capable of carrying signal. That is a statement about variance, not effect.

Rest is undefined only for season openers (24 / 20 / 21 fixtures), which get no
offset rather than a default — the behaviour `ml/models/rest.py` already
implements.

## 4. What is new here, and what is deliberately not re-run

**Rest was already tested and refuted.** `docs/MODEL-EXPERIMENTS.md` T3.2
pre-registered a linear function of the rest differential and refuted it in all
three leagues (EPL +0.0003, Bundesliga +0.0003, La Liga +0.0005; every CI
straddling zero). D1 **does not re-run it**. Re-running a refuted candidate on
the same nine seasons until it clears is the practice this repository's
protocol exists to prevent.

`congestion_14d` is a **different hypothesis, declared before the run**: T3.2
asked how long the gap was; this asks how much was played. Travel is
**genuinely new** — there was no coordinate to compute it from.

## 5. Leakage audit

| ID | Property | Status |
|---|---|---|
| **M1** | Features are computable strictly before kickoff | **PASS** — truncating the fixture list at match *n* leaves match *n*'s context bit-identical, checked at every truncation point; and scrambling input order is a no-op, so a pass cannot be an artifact of ordering |
| **M2** | No result or score can reach a candidate | **PASS** — `Fixture` carries only `(date, division, home, away)`, asserted structurally |
| **M3** | One coordinate per club, so a later stadium move cannot leak backwards | **PASS** — snapshot keys are unique |
| **M4** | The confirmation season is neither read nor hashed | **PASS** — scope is `pre_confirmation_keys()`; no `*_2526` capture opened |

## 6. What has NOT been run, and why that is stated rather than implied

**The pre-registered selection over 2016-17…2024-25 has not been executed.**
The candidate grids (D1.1–D1.4) are pre-registered and the features exist, but
wiring them into `ml/evaluation/club_walkforward.py` and running the
season-clustered bootstrap is a separate piece of work.

It is recorded as outstanding rather than quietly dropped, and it changes
nothing about what can ship: **no candidate can be promoted regardless of its
selection result**, because the confirmation season is consumed. A selection
number would be information, not a decision.

## 7. Reproducibility receipt

```bash
# Re-fetch from Wikidata and rewrite both snapshots (free, CC0, no key).
# Operator-run: nothing schedules this, and no test calls it for real.
PYTHONPATH=backend:. .venv/bin/python -m pipeline.ingest.venue_coordinates --refresh

# Offline: re-derive the table from the committed receipt and assert the
# rebuild is byte-for-byte identical. Exits 1 if it is not.
PYTHONPATH=backend:. .venv/bin/python -m pipeline.ingest.venue_coordinates --verify
```

> **Corrected.** The first version of this receipt named three functions
> (`fetch_bindings`, `resolve`, `snapshot_payload`) that a later refactor had
> renamed away, so the phase's only documented rebuild command could not run at
> all. It is now a `python -m` entry point, which cannot drift from the code the
> way a prose snippet can, and `--verify` is exercised by a test.

| | |
|---|---|
| snapshot retrieved | 2026-07-29T13:39:50Z (recorded in the receipt, and re-read from it) |
| provenance per row | Wikidata venue QID, label, capacity, canonical club name |
| query fingerprint | `query_sha256` in the snapshot |
| scope | 27 pre-confirmation captures; `*_2526` never opened |
| python suite | see the PR's CI run |

## 8. Limitations, declared

1. **Neutral and relocated venues are undetectable in this source.**
   football-data.co.uk publishes no venue column, so travel is computed as
   *away club's home venue → home club's home venue*. Any COVID-era relocation
   or ground-share is silently mis-measured. Declared in the pre-registration
   before the coverage run, and it caps what any D1 effect estimate can mean:
   the error attenuates a real effect rather than manufacturing one.
2. **One venue per club, not per season.** A club that moved grounds inside the
   window (Tottenham 2019, Freiburg 2021, Brentford 2020) is scored at its
   current venue for every season. This is a deliberate M3 trade — a
   season-varying table would let a future move leak backwards — but it means
   those clubs' early-season distances are wrong by the distance between the
   old and new ground.
3. **Capacity as the discriminator is a heuristic**, and it happened to
   separate all four ambiguous cases cleanly. A future club whose training
   ground out-capacities its stadium would resolve wrongly; the QID in the
   snapshot is what makes that checkable by eye.
4. **No selection result exists yet** (§6).
