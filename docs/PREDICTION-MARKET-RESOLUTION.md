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
| season | declared-and-equal, or implied by the kickoff window |

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

Migration `c2d3e4f5a6b7` adds `proposed` to the check constraint (empty table,
verified round-trip on Postgres).

## No similarity, anywhere

Names never touch the resolution path. Participants come from **verified
exact keys**: `entity_source_map` rows written by `link-entity` with a named
`verified_by`. The internal side is just another source — `("internal",
"team:<id>")`, `("internal", "tournament:<id>")` — so the resolver compares
entity ids only. An unverified key fails closed naming exactly the row to add.

Kalshi descriptors parse the ticker grammar
(`KXEPLGAME-26AUG01ARSCHE-ARS`): the team block splits **only where both
halves are already verified keys** — the registry disambiguates, not string
heuristics — and a block that splits validly two ways abstains. The grammar's
one assumption (home side listed first) is recorded on every descriptor so a
venue convention change is auditable, and any reversed-orientation candidate
is `proposed`, never auto-linked, which also covers neutral-venue listings.

## Evidence

`resolution_context` records: resolver version, decision timestamp, extractor
grammar and its raw fields, every candidate with every check and its result,
rejections by name, the proposal target, missing keys. `mapping_history` is
append-only and records **transitions** (`resolution`, `manual_correction`,
`conflict_detected`) — replay with unchanged inputs appends nothing.

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
# read-only report (default)
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

## Known data gap

Polymarket's stored rows carry an opaque `conditionId` and a display question
only — the structured slug lives in the raw discovery payload, not the
database. Polymarket resolution therefore requires operator-supplied
`--venue-metadata` (asserted venue facts, recorded verbatim in the evidence)
until capture persists structured participants. Kalshi resolves fully from
stored rows.
