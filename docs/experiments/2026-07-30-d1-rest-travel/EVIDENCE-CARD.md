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
# Rebuild the coordinate snapshot from Wikidata (free, CC0, no key).
# Operator-run: nothing schedules this, and no test calls it for real.
PYTHONPATH=backend:. .venv/bin/python -c "
import hashlib, json
from datetime import datetime, timezone
from pipeline.ingest.venue_coordinates import *
al = load_aliases(); names = [al[d][c] for d, c in required_clubs(al)]
r, p = resolve(fetch_bindings(names), al)
SNAPSHOT_PATH.write_text(json.dumps(snapshot_payload(
    r, p, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    hashlib.sha256(build_query(sorted(names)).encode()).hexdigest()),
    ensure_ascii=False, indent=2) + '\n')
print(format_coverage(json.loads(SNAPSHOT_PATH.read_text())))"
```

| | |
|---|---|
| snapshot retrieved | 2026-07-29T12:09:44Z (recorded in the snapshot itself) |
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
