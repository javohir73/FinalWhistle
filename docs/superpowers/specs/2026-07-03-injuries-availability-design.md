# Injuries → day-ahead availability — design spec

**Date:** 2026-07-03
**Status:** Approved
**Feature branch:** `feat/injuries-availability`
**Builds on:** the merged availability signal (`docs/superpowers/specs/2026-07-03-availability-signal-design.md`).

## Problem

The availability signal (v1) is **announced-XI only**, and XIs land ~1 hour before
kickoff — too late to inform the day-ahead forecast. api-sports `/injuries` (already
included in the existing **Pro** plan, verified: 69 WC26 records, per-fixture, with
`player.type` = "Missing Fixture" | "Questionable") gives availability **days ahead**.
This feature feeds that day-ahead signal into the **same** shadow-first, bounded,
gated adjustment — upgrading it from "XI-only, ~1h before" to "injuries, days ahead."

## Core idea — one unified resolver

Everything downstream (offset math, shadow twin, note, benchmark) already exists from
v1. This feature only makes the *"who's available"* input smarter and adds the data to
feed it. For each team, compute **effective attacking capacity** from the best signal:

- **Announced XI present** (near kickoff) → the announced starters, exactly as v1. XI
  is ground truth and **supersedes** injuries.
- **XI absent, injuries present** (days ahead) → the reference XI (squad top-11 by
  minutes), each player carrying an availability multiplier: **1.0 fit, 0.0 "out"
  (Missing Fixture), 0.5 "doubtful" (Questionable)** — `DOUBTFUL_WEIGHT = 0.5`, tunable.

Then the *same* offset as v1: `clamp(ln(effective_capacity / full_strength_capacity),
−0.25, +0.10)`, attack-side only. v1's XI path is the all-multipliers-1 case, so this
is a generalization, not a parallel system.

**Path selection** (`availability_for_match`): both XIs present → XI path (v1
unchanged); else `Match.injuries` non-empty → injury path for **both** sides (a side
with no injuries → offset 0); else → None (no twin, no note). A lone XI without the
other is ignored in favour of injuries, preserving v1's both-sides discipline.

## Constraints & decisions

- **Best-available resolver**, one `+avail` twin version (no new version string).
- **Half-weight doubtful** (`0.5`); confirmed-out fully removed.
- **`Match.injuries` JSON column** (mirrors `goal_events`/`card_events`): `null` = not
  yet ingested, `[]` = checked/none, else `[{provider_player_id, name, type, reason, side}]`.
- **Champion untouched**, attack-side only, bounded, shadow-first, gated — same as v1.
- **One PR**, migration applied pre-merge (see Deploy).

## Components

### 1. Ingestion — `refresh_injuries`
- `pipeline/ingest/api_football.py`:
  - `fetch_injuries(api_key, league, season) -> list[dict]` — mirrors `fetch_fixtures`
    (`GET /injuries?league&season`, `x-apisports-key`, tolerates the `errors` object).
  - `parse_injuries(response) -> list[dict]` (pure) — each record →
    `{provider_player_id, name, type, reason, team_name, fixture_date}`, where
    `type = "out"` if `player.type == "Missing Fixture"` else `"doubtful"`.
- `pipeline/ingest/injuries.py` (new): `refresh_injuries(db, api_key)` — fetch the
  configured league+season **once**, group by (normalized team, fixture date), map to
  scheduled `Match` rows via the existing `normalize_team_name` + kickoff-date match
  (same mapping odds/live-scores use), and set `Match.injuries` to the per-match list
  with `side` ("home"/"away") assigned by which team the injured player belongs to.
  Matches checked but injury-free get `[]`.
- Wire into `pipeline/run_pipeline.py` **before** `generate_predictions`, gated on
  `settings.api_football_api_key` (like the odds step).

### 2. The adjustment
- `ml/models/availability.py` (extend, pure): add `DOUBTFUL_WEIGHT = 0.5` and
  `injury_availability_offset(squad, statuses: dict[int, str]) -> tuple[float, dict] | None`
  where `statuses` maps `provider_player_id → "out" | "doubtful"`. It builds the
  reference XI, applies multipliers (out → 0.0, doubtful → 0.5, else 1.0), and computes
  the ratio → clamped offset + explanation. The clamp/ratio→(offset, delta_pct) step is
  factored into a shared `_clamped_offset(effective, reference)` helper reused by both
  `availability_offset` (v1 XI path) and `injury_availability_offset` (DRY — no
  duplicated clamp logic). Explanation `players_out` entries gain `status` ("out"/
  "doubtful") and `reason`.
- `backend/app/availability.py` (extend): `availability_for_match` gains the injury
  branch — build per-side `statuses` from `match.injuries`, load each squad, call
  `injury_availability_offset`. Returns the same `(off_home, off_away, expl_home,
  expl_away) | None` shape, so the twin writer and serializer are unchanged. An
  injured player absent from our squad data (not in the reference XI) simply has no
  effect — the reference XI is drawn from our `Player` rows.

### 3. Twin + serving
- `pipeline/generate_predictions.py`: `write_availability_prediction` is **unchanged** —
  the smarter resolver means it now also fires in the day-ahead run, writing timestamped
  `+avail` twins that sharpen as the XI lands.
- `backend/app/serializers.py`: `_availability_note` extends to the injury explanation —
  *"France without Mbappé (Calf Injury, out), Camavinga doubtful → attack −11%."* Still
  explanation-only, one published number. `AvailabilityOut`/frontend `AvailabilityNote`
  render the backend-composed note string, so **no frontend change** is required (the
  richer detail lives in the note string).

### 4. Schema
- Alembic revision: add nullable `injuries` JSON column to `matches`.
- `backend/app/models/__init__.py`: `injuries: Mapped[list | None] = mapped_column(JSON)`
  on `Match` (mirrors `goal_events`/`card_events`).

## Deploy sequencing (the one real risk)

The `injuries` column is a schema change; the reading code 500s if it deploys before the
column exists. Use this repo's **proven card-aware pattern** (one PR, no 500 window):

1. Build the feature branch (migration + code) via SDD; open PR; CI green.
2. **[STOP-GATE]** Dispatch `refresh.yml` on the feature branch → `alembic upgrade head`
   applies the migration to the **prod DB**. The new column is nullable, so it is
   backward-compatible with the currently-running (pre-merge) code. Verify the column
   exists.
3. Human merges the PR → Render deploys the reading code → column already present → safe.
4. Verify prod (`GET /api/health`, spot-check a match's injury note).

## Non-goals

Attack-side only (no defensive/GK injury modelling); no player-injury history table
(injuries are transient — overwritten daily); one `+avail` twin version (source-tagging
XI vs injury for finer benchmarking is a later option); no change to the published
number, the sims, or the WC26 served routes beyond the additive `injuries` column + note.

## Testing

- **Unit:** `parse_injuries` (type mapping, malformed rows); `injury_availability_offset`
  (out → full removal, doubtful → half, mixed, clamp bounds, no-injuries → offset 0,
  empty squad guard); `_clamped_offset` shared by both paths.
- **Integration:** `refresh_injuries` maps league injuries onto the right `Match.injuries`
  with correct sides; `availability_for_match` uses the injury path when no XI and the XI
  path when both XIs present (XI supersedes); the day-ahead twin is written and its
  `lambda` is cut; no twin when `match.injuries` is empty.
- **Serving:** the note reflects injured players with status + reason; published
  probabilities unchanged.
- **Migration:** upgrade adds the column; downgrade drops it.
- Full suite green (`make test`) before PR.
