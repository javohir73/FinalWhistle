# Venue-market → fixture resolution

**Status: OPERATOR-RUN ONLY. Dry-run by default, `--apply` gate, nothing
schedules it, no env var turns it on.**

Deterministically links `venue_market` rows to our `matches` rows, in entity
space, with the whole decision recorded. `pipeline/entities/` holds the code;
`pipeline/run_market_resolution.py` is the only entry point.

## The rule

**A mapping is written only when every dimension agrees; anything short of
that abstains out loud.** Five dimensions must be positively consistent:

| Dimension | Check |
|---|---|
| participants | both venue keys resolve through verified `entity_source_map` rows |
| orientation | descriptor home **is** fixture home, away is away — a reversed pairing is a *different fixture* (the other leg) |
| competition | market's competition key resolves to the fixture's competition entity |
| kickoff | within a bounded window (36h) of the fixture kickoff |
| season | declared-and-equal when the descriptor carries one; otherwise **kickoff-within-window plus competition IS the season gate**, and the evidence records exactly that (`gated_by_kickoff_and_competition`) rather than pretending a fifth check ran |

**And consistency is necessary, not sufficient.** The descriptor's *facts* —
orientation, kickoff, competition — must themselves be verified by a named
person before anything maps. A grammar-derived descriptor caps at `proposed`
however consistent it is.

The canonical season token is the tournament's **starting year**, four digits
(`Tournament.year`): a 2026-27 season is `"2026"`, January fixtures included.
Metadata seasons in any other format are refused at extraction.

Missing metadata is not consistency — it caps the outcome at `proposed`. Two
fixtures surviving every constraint is `ambiguous`, never a coin flip. The
original #203 resolver matched `{home, away}` as an unordered set with none of
the other four dimensions, which conflates two-legged ties, reverse fixtures,
cup-vs-league meetings and adjacent seasons. All of those are now adversarial
tests.

## Statuses

| `mapping_status` | Meaning | Canonical columns |
|---|---|---|
| `mapped` | fully consistent, or operator-verified | set |
| `proposed` | ONE near-miss with ONE explainable failure (reversed orientation, out-of-window kickoff, missing competition/kickoff declaration, postponed fixture, season mismatch) — a review candidate with its story attached | **NULL** |
| `ambiguous` | several survivors, or several different near-misses, or an ambiguous ticker split | NULL |
| `unmapped` | unverified keys, no pairing, unsupported market type, no structured metadata | NULL |

Migration `c2d3e4f5a6b7` adds `proposed` to the check constraint. Verified on
Postgres **with a populated `proposed` row**: the downgrade folds it back to
`unmapped` before the old constraint returns, evidence intact (see the
migration note under Known data gaps).

## No similarity, anywhere

Names never touch the resolution path. Participants come from **verified
exact keys**: `entity_source_map` rows written by `link-entity` with a named
`verified_by`. The internal side is just another source — `("internal",
"team:<id>")`, `("internal", "tournament:<id>")` — so the resolver compares
entity ids only. An unverified key fails closed naming exactly the row to add.

**Kalshi ticker parsing is a review-hint generator, never a mapping.**
Kalshi's own documentation ([ticker conventions](https://docs.kalshi.com/getting_started/terms))
says tickers have occasional exceptions and explicitly advises against parsing
ticker strings to infer relationships. So the ticker grammar
(`KXEPLGAME-26AUG01ARSCHE-ARS`) produces an **unverified** descriptor: the
team block splits only where both halves are already verified keys, a block
that splits two ways abstains at extraction — and even full five-dimension
consistency caps at `proposed`, with the grammar and its usual-convention
reading (home listed first) recorded in the evidence. **Mapping requires
operator-verified metadata or a manual correction.** Reversed-orientation
candidates are likewise `proposed`, which also covers neutral-venue listings.

**Operator metadata is an assertion, and an assertion needs an asserter.**
Every `--venue-metadata` record must carry `verified_by` (a named person) and
`note` (the evidence source); both persist into `resolution_context` and the
history. Anonymous metadata fails closed — verifying the entity keys does not
verify the orientation someone typed into a file — and metadata can never
touch a manually-corrected row, which stays `locked` under replay.

## Evidence

`resolution_context` records the CURRENT decision: resolver version,
timestamp, extractor grammar, verification (who signed the facts), every
candidate with every check, rejections by name, the proposal target, missing
keys.

`mapping_history` is append-only, records **transitions** (`resolution`,
`manual_correction`, `conflict_detected`) — and each entry carries the
evidence itself, because `resolution_context` is replaced on the next
transition and history is where provenance must survive:

- `resolution` entries embed the full context snapshot (`evidence`);
- `conflict_detected` entries embed the replay's full evidence
  (`replay_evidence`, timestamp-free so an identical conflict still records
  once);
- `manual_correction` entries embed the context they replaced
  (`previous_context`) — a correction never destroys the resolver's original
  evidence.

Replay with unchanged inputs appends nothing. A verification is only usable
when both `by` and `note` are non-blank — `{}`, a missing note, or whitespace
is verification theater and caps at `proposed` **in the resolver core**, so
no direct caller can bypass it.

## Dry runs touch nothing

`resolve`, `correct` and `link-entity` without `--apply` neither commit nor
roll back, and read under `no_autoflush` — a dry run in a shared session
leaves the caller's unrelated pending work exactly where it was. (The first
revision called `db.rollback()`, which silently destroyed it; a sentinel test
now pins the fixed behavior on every dry-run and idempotent path.)

## Protection

- **Verified rows are untouchable.** A mapping carrying
  `resolution_context.verified` is skipped by replay (`locked`), whatever the
  resolver now believes.
- **No silent remap.** A mapped row that re-resolves elsewhere keeps its
  mapping; the disagreement lands in `resolution_context.conflict` plus one
  audited history entry, and a human decides via `correct`.
- **One market → one fixture.** `correct` validates the target match exists;
  `--clear` rolls back with history retained; every correction names a person
  and a note.
- **`link-entity` refuses implicit remaps** — a source key already pointing at
  a different entity is an error, not an upsert.

## Commands

```bash
# read-only report (default); prints decisions, counts, AND data gaps
# (every owed link-entity row), sorted deterministically
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_market_resolution resolve

# write decisions
... resolve --apply

# verify keys (the only way keys become trusted)
... link-entity --kind team --name "Arsenal" --source kalshi --key ARS \
    --verified-by "pete" --apply

# audited manual correction / rollback
... correct --venue kalshi --venue-key <ticker> --match-id 41 --outcome home \
    --verified-by "pete" --note "checked venue listing" --apply
... correct --venue kalshi --venue-key <ticker> --clear \
    --verified-by "pete" --note "wrong market" --apply
```

## Known data gaps

1. **No venue delivers auto-mappable structure today.** Polymarket's stored
   rows carry an opaque `conditionId` and a display question; Kalshi's ticker
   is parseable but its own docs bar treating that parse as authoritative.
   **Every mapping therefore passes through a named human** — verified
   metadata or a correction — until capture persists venue-structured
   participant fields with verified semantics.
2. **Stopped fixtures are invisible after ingestion.** `league_structure._STATUS`
   and `live_scores._STATUS_MAP` normalize SUSP/PST/CANC/ABD to internal
   `"scheduled"`, so the resolver's postponed/cancelled guard — while tested
   as a core contract — **cannot fire on production data**. A through-ingest
   test documents this; closing it needs a provider-status column carried
   through ingestion.
3. **Fixtures missing internal entity mappings** cannot be candidates; the
   reconcile report's `data_gaps` names each owed `link-entity` row instead
   of letting the fixture vanish silently.

Migration note: downgrading `c2d3e4f5a6b7` folds `proposed` rows back to
`unmapped` (canonical columns are NULL by construction; evidence in
`resolution_context`/`mapping_history` is untouched) — verified against a
populated table, not an empty one.
