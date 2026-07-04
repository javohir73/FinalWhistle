# StatsBomb xG-nudged Team Offsets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the shelved xG-team-offsets feature on a NEW data source. The ML CORE (offset fit, re-anchor, κ-blend) and the shadow-twin write pattern are reused UNCHANGED; only the DATA LAYER moves from API-Football (no WC2022 xG) to StatsBomb open data (free, 314 international matches across 6 editions). Ships SHADOW-FIRST — `params.team_offsets` stays `null`; nothing served changes.

**Architecture:** (1) additive nullable `xg_a`/`xg_b` migration on `historical_matches`; (2) an offline, cached, idempotent StatsBomb backfill (`pipeline/backfill_xg.py`) with a pure shot-xG parser and a swapped-orientation fixture matcher that reuses the `join_odds_to_rows` precedent; (3) a one-parameter (`goal_keys`) parametrization of `fit_offsets` so the SAME fitter reads `xg_a`/`xg_b`, feeding the (unchanged) re-anchor + κ-blend to write `team_offsets_xg.json`; (4) a `write_offsets_prediction` shadow twin tagged `OFFSETS_MODEL_VERSION` plus a dedicated benchmark runner/endpoint cloned from the availability pair; (5) an A/B/C WC backtest as a sanity check (NOT the proof bar).

**Tech Stack:** Python, SQLAlchemy, Alembic, `requests` (already in venv — do NOT vendor `statsbombpy`), numpy, pytest.

**Design spec:** `docs/superpowers/specs/2026-07-04-xg-team-offsets-design.md` (SHELVED; this plan is the StatsBomb pivot the spec's closing line anticipates).

---

## Corrections vs the shelved spec (grounded — read before starting)

The spec predates this data-source swap and the grounding pass. Where it conflicts with the real repo, **the grounding wins**:

1. **Table & columns.** Spec says "mirrors the injuries-column precedent" (spec:48, :191). **There is no migration about "injuries" anywhere in `backend/alembic/versions/`.** The `injur` grep only hits `matches.injury_time` (a live-clock field). The structurally-identical precedent to mirror is `backend/alembic/versions/e0f1a2b3c4d5_prediction_lambdas.py` (nullable `Float` columns, additive, no backfill, no `server_default`). Use that, not a mythical injuries migration.
2. **Target table has no home/away.** `HistoricalMatch` (`backend/app/models/__init__.py:215-233`) stores orientation-neutral `team_a_id`/`team_b_id` + `score_a`/`score_b` + `is_neutral`. `xg_a`/`xg_b` map onto `team_a`/`team_b`, NOT home/away. This is exactly why the swapped-orientation fixture match is mandatory.
3. **`xg_a`/`xg_b` do NOT exist yet.** Repo-wide grep returns zero hits outside `TeamStats.xg_for/xg_against` (unrelated). Clean additive migration, no conflict. Alembic head is **`c4d5e6f7a8b0`** (`add_is_internal_flag`), verified by `alembic heads`. New migration's `down_revision = "c4d5e6f7a8b0"`.
4. **Data source.** Spec's Phase 0 (API-Football coverage probe) and Phase 2 (`fetch_fixture_statistics`/`parse_team_xg`) are REPLACED by StatsBomb open data. Phase 0 is already cleared (314 free matches). No API-Football fetcher is consumed.
5. **Fitter parametrization is exactly 2 lines.** Goal source is read ONLY at `pipeline/fit_attack_defence.py:93-94` (`float(r["score_home"])` / `["score_away"]`). No other line in `fit_offsets` touches the raw dict. `n_eff`, re-anchor (`:145-146`), and shrink/cap are all provider-agnostic — untouched.
6. **Twin insertion point.** New `write_offsets_prediction` mirrors `write_availability_prediction` (`generate_predictions.py:324-363`) and is called in the per-match loop immediately after `write_availability_prediction(...)` (after line 555, before `predicted += 1`). It loads the store INDEPENDENT of `params.team_offsets` — do NOT gate it on that flag, and do NOT thread offsets into the simulators (`_simulate_standings`/`_simulate_tournament` stay offset-free).

---

## Global Constraints

- **Shadow-first, no promotion.** `params.team_offsets` stays `null`. The xG store is loaded ONLY by the new twin writer. No served field changes. No `model_params.json` flip.
- **Migration STOP-GATE (CLAUDE.md).** Render's free tier runs no migrations on deploy — they run only via `refresh.yml`'s `alembic upgrade head` (`.github/workflows/refresh.yml:31-35`). Sequence is **hard**: (1) merge the migration to `main`; (2) dispatch `refresh.yml` and confirm the "Apply migrations" step succeeds against prod; (3) ONLY THEN is any code path that SELECTs `historical_matches.xg_a`/`xg_b` safe to serve. Dispatching `refresh.yml` touches prod → **stop, show a plain-English summary, wait for an explicit "go" before dispatching or merging to main.** The backfill and store production are OFFLINE so they don't serve — but the twin (which does not SELECT the columns; it reads the JSON store) still must not run against a prod DB whose `predictions` schema lags. In practice: land the migration through the gate before Phase 6.
- **Reuse the ML core VERBATIM.** Do NOT touch the MLE/decay/shrink/cap/re-anchor logic in `pipeline/fit_attack_defence.py` or `ml/models/team_offsets.py`. The ONLY fitter edit is adding a `goal_keys` parameter and rewriting lines 93-94 to read from it.
- **Never fabricate xG.** Absent side / fetch failure / malformed shot → `None` → NULL. Writing `0.0` for a missing value poisons the fit. Real summed shot-xG → a float.
- **Exclude the penalty shootout (period 5).** `historical_matches.score_a/score_b` is the after-extra-time score, which excludes shootouts, so the xG must too. StatsBomb encodes shootout penalties as `Shot` events in `period == 5`; summing them would roughly **double** a knockout team's xG against a score that ignores them, systematically inflating that team's attack offset. Grounded on the WC2022 final (Argentina **3–3** France after ET): all-periods xG = 5.89/5.41 vs periods-1–4 xG = 2.76/2.27. The parser filters `period <= 4` (keeps regulation + extra time, drops the shootout). This was open-question #3 from grounding — **resolved: exclude shootout.**
- **Offline tests only.** All StatsBomb logic is tested against on-disk JSON fixtures. `make test` never hits the network. Cache dir (`pipeline/data/statsbomb_cache/`) is gitignored — never commit ~314 blobs.
- **Idempotency.** Backfill skips rows whose `xg_a` is already non-NULL; the event cache makes re-runs touch the network zero times. Resume is free.
- **`(competition_id, season_id)` PAIR keying.** Copa America 2024 `season_id=282` numerically equals UEFA Euro 2024 `season_id=282`; never key on `season_id` alone.
- **Venv:** the worktree has no `.venv`. Before running tests: `ln -sfn "/Users/macbookpro/Projects/FIFA WC26 Prediction/.venv" .venv` (NOT gitignored — never `git add` it; stage only named source/test files). Run Python with `PYTHONPATH=backend:.` where a test imports `app.*`.

---

## File Structure

- `backend/app/models/__init__.py` — **modify.** Add `xg_a`/`xg_b` nullable `Float` columns to `HistoricalMatch`.
- `backend/alembic/versions/<newrev>_add_historical_xg.py` — **create.** `down_revision="c4d5e6f7a8b0"`; additive nullable columns.
- `pipeline/backfill_xg.py` — **create.** StatsBomb ingestion + pure parser + fixture matcher + `backfill_xg(db, ...)` orchestrator.
- `pipeline/backfill_xg_test.py` — **create.** Offline parser + matcher + idempotency tests.
- `.gitignore` — **modify.** Ignore `pipeline/data/statsbomb_cache/`.
- `pipeline/fit_attack_defence.py` — **modify.** Add `goal_keys` param to `fit_offsets` (+ pass-through in `fit_and_write`); rewrite lines 93-94.
- `pipeline/fit_attack_defence_test.py` — **modify/create.** Assert `goal_keys` default is bit-identical and an xG-keyed fit works.
- `pipeline/build_xg_offsets.py` — **create.** Runs goals-fit + xG-fit + re-anchor (δ̂) + κ-blend → writes `ml/models/team_offsets_xg.json`.
- `pipeline/build_xg_offsets_test.py` — **create.** Re-anchor/blend unit tests + κ=0 identity test.
- `pipeline/generate_predictions.py` — **modify.** Add `OFFSETS_MODEL_VERSION`, `write_offsets_prediction`, one loop call.
- `pipeline/generate_predictions_offsets_twin_test.py` — **create.** Null-test + λ-scaling + tag + production-untouched.
- `ml/evaluation/offsets_benchmark.py` — **create.** `benchmark_offsets` (clone of `benchmark_availability`).
- `pipeline/run_offsets_benchmark.py` — **create.** `_latest`/`_verdict`/`offsets_record(db)` (clone).
- `pipeline/run_offsets_benchmark_test.py` — **create.** Record scoring + honest-empty + exclude-missing-twin.
- `backend/app/api/internal.py` — **modify.** Add `GET /api/internal/offsets-record`.
- `backend/tests/test_offsets_record.py` — **create.** Endpoint token-gate + paired-comparison tests.
- `pipeline/backtest_xg_offsets.py` — **create.** A/B/C walk-forward WC report (sanity check).

---

## Phase 0 — Coverage gate (DONE, do not re-run)

**Status: CLEARED.** The shelved spec's blocking gate was that API-Football had **no WC2022 xG**. The pivot resolves it: StatsBomb open data is reachable (HTTP 200, `competitions.json` = 34,887 bytes) and enumerates exactly **6 editions / 314 matches**, FREE, with per-team shot-xG verified on WC22 match 3857276 (Canada 1.096 / Morocco 0.426, 0 missing xG):

| Edition | competition_id | season_id | matches |
|---|---|---|---|
| FIFA World Cup 2018 | 43 | 3 | 64 |
| FIFA World Cup 2022 | 43 | 106 | 64 |
| UEFA Euro 2020 | 55 | 43 | 51 |
| UEFA Euro 2024 | 55 | 282 | 51 |
| African Cup of Nations 2023 | 1267 | 107 | 52 |
| Copa America 2024 | 223 | 282 | 32 |

**Total 314.** (Note: AFCON real `competition_id=1267`, `competition_name="African Cup of Nations"`; Copa `season_id=282` collides numerically with Euro 2024 — key on the PAIR.) No go/no-go decision remains; record and move on. Pin the 6 `(cid,sid)` pairs as a `SIX_EDITIONS` constant AND filter-verify them from `competitions.json` at runtime so ids can't silently drift.

---

## Phase 1 — Migration: nullable `xg_a`/`xg_b` on `historical_matches`  ⚠️ STOP-GATE

**Files:**
- Modify: `backend/app/models/__init__.py` (`HistoricalMatch`, lines 215-233)
- Create: `backend/alembic/versions/<newrev>_add_historical_xg.py`

**Interfaces:**
- Produces: `HistoricalMatch.xg_a: Mapped[float | None]`, `HistoricalMatch.xg_b: Mapped[float | None]`; a migration with `revision=<newrev>`, `down_revision="c4d5e6f7a8b0"`.

- [ ] **Step 1: Add the model columns.** Inside `HistoricalMatch`, after `venue`, add:
  ```python
  xg_a: Mapped[float | None] = mapped_column(Float)
  xg_b: Mapped[float | None] = mapped_column(Float)
  ```
  `Float` is already imported in this module (used by `TeamStats.xg_for`/`xg_against`, `Prediction.lambda_home`). No new import.

- [ ] **Step 2: Write the migration**, mirroring `backend/alembic/versions/e0f1a2b3c4d5_prediction_lambdas.py:1-33` verbatim (docstring header convention + `from typing import Sequence, Union` / `import sqlalchemy as sa` / `from alembic import op` boilerplate + the four `revision`/`down_revision`/`branch_labels`/`depends_on` assignments):
  ```python
  revision = "<newrev>"            # e.g. a1b2c3d4e5f6
  down_revision = "c4d5e6f7a8b0"   # current head: add_is_internal_flag

  def upgrade() -> None:
      op.add_column("historical_matches", sa.Column("xg_a", sa.Float(), nullable=True))
      op.add_column("historical_matches", sa.Column("xg_b", sa.Float(), nullable=True))

  def downgrade() -> None:
      op.drop_column("historical_matches", "xg_b")
      op.drop_column("historical_matches", "xg_a")
  ```

- [ ] **Step 3: Verify the chain locally (read-only).**
  ```bash
  cd backend && PYTHONPATH=../backend:.. ../.venv/bin/python -m alembic heads
  ```
  Expected: prints `<newrev> (head)` — single head, `<newrev>` now chains onto `c4d5e6f7a8b0`. (`alembic` must run from `backend/` because `alembic.ini`'s `script_location='alembic'` is relative.)

- [ ] **Step 4: Verify the model change is loadable (read-only).**
  ```bash
  PYTHONPATH=backend:. .venv/bin/python -c "from app.models import HistoricalMatch; print(HistoricalMatch.xg_a, HistoricalMatch.xg_b)"
  ```

- [ ] **Step 5: Commit** (model + migration only):
  ```bash
  git add backend/app/models/__init__.py backend/alembic/versions/<newrev>_add_historical_xg.py
  git commit -m "feat(xg-offsets): nullable xg_a/xg_b columns on historical_matches"
  ```

- [ ] **Step 6: ⚠️ STOP-GATE — prod migration sequencing.** After this reaches `main` (via the normal branch→PR→CI→human-merge pipeline), the migration must reach prod BEFORE any Phase-6 twin runs against a prod DB. **STOP: present a plain-English summary of the migration diff and wait for an explicit "go" before dispatching `refresh.yml` or merging to `main`.** On "go": merge → dispatch `refresh.yml` (workflow_dispatch) → confirm the "Apply migrations" step (`.github/workflows/refresh.yml:31-35`) succeeded → only then is downstream serving-adjacent code safe. The migration is additive/nullable/reversible (symmetric `downgrade`), but dispatching `refresh.yml` touches the prod DB, so it is a stop-gate action regardless.

---

## Phase 2 — StatsBomb ingestion + pure xG parser (offline, cached)

**Files:**
- Create: `pipeline/backfill_xg.py` (parser + fetch/cache helpers only in this phase)
- Create: `pipeline/backfill_xg_test.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces (pure, network-free): `sum_shot_xg_by_team(events: list[dict]) -> dict[str, float]`; `match_xg(match: dict, events: list[dict]) -> tuple[float | None, float | None]` (returns `(home_xg, away_xg)`, or `None` for a side with zero shot-xG entries — absent, never `0.0`-as-data).
- Produces (network, best-effort, never raises): `_get_json(url) -> dict | list | None`; `_fetch_events(match_id, cache_dir) -> list[dict]`; `SIX_EDITIONS` constant; `enumerate_editions(competitions_json) -> list[tuple[int,int]]` (filter-verify against the pinned pairs).

- [ ] **Step 1: Write failing parser tests** (`pipeline/backfill_xg_test.py`). Feed hand-built fixtures — no network, no DB. Named cases:
  - `test_sum_shot_xg_by_team_sums_only_shots` — two teams, mixed event types; only `type.name=="Shot"` `shot.statsbomb_xg` values summed per `team.name`.
  - `test_sum_shot_xg_skips_missing_xg` — a Shot with `shot.statsbomb_xg` absent is skipped (not counted as 0), matches with other shots still sum.
  - `test_match_xg_maps_home_away` — given a match record `{home_team:{home_team_name}, away_team:{away_team_name}}` + events, returns `(home_xg, away_xg)` correctly oriented.
  - `test_match_xg_absent_side_is_none` — a side with zero shot-xG entries → that side is `None` (NOT `0.0`); malformed events → `(None, None)`, no raise.
  - `test_sum_shot_xg_excludes_shootout` — Shot events in `period == 5` (the penalty shootout) are NOT counted; a match with periods 1–5 sums only the periods-1–4 xG. (Grounded: WC2022 final Argentina 3–3 France sums to 5.89/5.41 xG with the shootout vs 2.76/2.27 without — see decision below.)

- [ ] **Step 2: Run to verify fail.** `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/backfill_xg_test.py -q` → FAIL (ImportError).

- [ ] **Step 3: Implement the pure parser + fetch/cache scaffolding.** Base URL `https://raw.githubusercontent.com/statsbomb/open-data/master/data`. `_get_json` uses `requests.get(url, timeout=20)` wrapped in try/except returning `None` (idiom: `pipeline/probe_club_xg.py:19-24`). `_fetch_events(match_id, cache_dir)`: if `cache_dir/events/{match_id}.json` exists and parses → load; else GET, and on HTTP 200 write to cache before returning. Cache keyed by immutable StatsBomb ids (never stale). Parser exactly as the design boundary:
  ```python
  def sum_shot_xg_by_team(events):
      out = {}
      for e in events:
          if (e.get("type") or {}).get("name") == "Shot":
              if (e.get("period") or 0) > 4:   # exclude penalty shootout (period 5) — see decision below
                  continue
              team = (e.get("team") or {}).get("name")
              v = (e.get("shot") or {}).get("statsbomb_xg")
              if team is None or v is None:
                  continue
              out[team] = out.get(team, 0.0) + float(v)
      return out
  ```
  `match_xg` maps that dict against the match's home/away names → `(home_xg, away_xg)`, `None` for a side absent from the dict.

- [ ] **Step 4: Add cache dir to `.gitignore`** — `pipeline/data/statsbomb_cache/`.

- [ ] **Step 5: Run to verify pass**, then commit:
  ```bash
  git add pipeline/backfill_xg.py pipeline/backfill_xg_test.py .gitignore
  git commit -m "feat(xg-offsets): StatsBomb pure shot-xG parser + cached fetch scaffolding"
  ```

---

## Phase 3 — Fixture matcher + idempotent backfill orchestrator

**Files:**
- Modify: `pipeline/backfill_xg.py` (add matcher + `backfill_xg(db, ...)`)
- Modify: `pipeline/backfill_xg_test.py`

**Interfaces:**
- Consumes: `pipeline.team_mapping.normalize_team_name` (`:70`); `pipeline.backtest_data.build_enriched_rows(db)` output (`home_id/away_id/date/score_home/score_away`) — but the matcher writes onto `HistoricalMatch` rows, so it queries `HistoricalMatch` directly to get `.id`, `.team_a_id`, `.team_b_id`, `.date`, `.score_a`, `.score_b`, `.xg_a` and the `Team.id→name` map.
- Produces: `match_statsbomb_to_rows(sb_records, historical_rows, id_to_name, normalize) -> tuple[list[write], list[unmatched]]` (pure over dicts, mirrors `ml/evaluation/market_benchmark.py::join_odds_to_rows`:82-103); `backfill_xg(db, cache_dir=..., editions=SIX_EDITIONS) -> dict` summary.

- [ ] **Step 1: Write failing matcher tests** (`pipeline/backfill_xg_test.py`). All pure over dict fixtures — no network. Named cases:
  - `test_direct_key_writes_a_b` — StatsBomb `(date, home, away)` matches a row's normalized `(date, name_a, name_b)` → `xg_a=home_xg`, `xg_b=away_xg`.
  - `test_swapped_key_flips_xg` — the row is stored `(team_a=StatsBomb away)`; the direct key misses, the swapped `(date, away, home)` hits → **flip**: `xg_a=away_xg`, `xg_b=home_xg`. (Reuses the `join_odds_to_rows:94` swap-and-flip precedent — the neutral-venue WC case, where most coverage is recovered.)
  - `test_unmatched_is_logged_left_null` — no key hit → appended to unmatched list + logged; row's xg stays NULL, no write, no raise.
  - `test_normalize_bridges_iran_and_czechia` — `normalize_team_name("IR Iran")=="Iran"`, `("Czech Republic")=="Czechia"` (existing aliases at `team_mapping.py:32,42`); empty-string names (`normalize_team_name(None)==""`) → record skipped, never keyed.
  - `test_score_crosscheck_flags_mismatch` — on a key hit, StatsBomb `(home_score,away_score)` disagreeing with the row's `(score_a,score_b)` after the same orientation flip → logged as suspicious, not silently written (cheap defensive discriminator; NEW logic layered on the reused swap).
  - `test_ambiguous_key_collision_dropped` — if a `(date, home, away)` key ever collides in the in-scope set → drop + log, don't write.

- [ ] **Step 2: Write failing idempotency test** (same file):
  - `test_backfill_skips_populated_rows` — a row with `xg_a` already non-NULL is skipped (its events file is never fetched); the summary's `skipped_populated` reflects it. Use an in-memory SQLite DB (`Base.metadata.create_all`) seeded with `HistoricalMatch` rows and a fake `cache_dir` pre-seeded with event JSON so the test stays offline.

- [ ] **Step 3: Run to verify fail.**

- [ ] **Step 4: Implement the matcher.** Build `by_key: dict[(civil_date, norm_a, norm_b)] -> row` over ONLY in-scope national-team rows (rows whose `.date.date()` falls inside the 6 editions' date spans — keeps the swapped fallback from matching an unrelated same-date friendly). Civil-date key: `historical.date.date() == datetime.date.fromisoformat(sb_match["match_date"])` (both sources are midnight-UTC-pinned civil dates per `pipeline/ingest/historical_results.py:106`; StatsBomb `match_date` is a bare `YYYY-MM-DD` — no instant conversion; keep a one-line date-equality assertion in a test). Direct key → write `(xg_a=home_xg, xg_b=away_xg)`; swapped key → flip; else → unmatched + log.

- [ ] **Step 5: Implement `backfill_xg(db, ...)`** (best-effort, never raises): fetch/cache `competitions.json` → enumerate + filter-verify the 6 `(cid,sid)` pairs → fetch/cache each `matches/{cid}/{sid}.json` → build the in-scope join dict ONCE → per StatsBomb match: idempotent skip if target row's `xg_a` already non-NULL, else fetch/cache events, compute `(home_xg, away_xg)` via `match_xg`, hand to the matcher → write or log. `db.commit()` per edition (bounds lost work on interruption; resume is free via the skip). Return `{editions, matches_seen, rows_written, skipped_populated, unmatched, xg_absent}` (mirrors `backfill_90min`'s count + log line). Distinct log lines for: unmatched fixture (name gap), xG-absent match, events-fetch failure.

- [ ] **Step 6: Run to verify pass**, then commit:
  ```bash
  git add pipeline/backfill_xg.py pipeline/backfill_xg_test.py
  git commit -m "feat(xg-offsets): swapped-orientation fixture matcher + idempotent StatsBomb backfill"
  ```

- [ ] **Step 7 (operational, after Phase-1 migration is in prod):** run the real backfill once against a DB that has the columns (`PYTHONPATH=backend:. .venv/bin/python -c "from app.db import SessionLocal; from pipeline.backfill_xg import backfill_xg; print(backfill_xg(SessionLocal()))"`). Inspect the summary; investigate any large `unmatched` count as a likely `_ALIASES` gap (add the alias following `team_mapping.py:13`'s `alias(lowercased)->canonical` pattern, re-run — idempotent). This is a read-of-web + local-DB-write; not a stop-gate action against prod unless run against the prod DB.

---

## Phase 4 — Parametrize `fit_offsets` goal-source (ML core untouched)

**Files:**
- Modify: `pipeline/fit_attack_defence.py` (`fit_offsets` signature + lines 93-94; `fit_and_write` pass-through)
- Modify/Create: `pipeline/fit_attack_defence_test.py`

**Interfaces:**
- Change: `fit_offsets(rows, ref_date, half_life_days=DEFAULT_HALF_LIFE_DAYS, params=None, max_iter=_MAX_ITER, tol=_TOL, goal_keys=("score_home", "score_away")) -> dict[int, dict]`. Lines 93-94 become `gh = np.array([float(r[goal_keys[0]]) for r in train]); ga = np.array([float(r[goal_keys[1]]) for r in train])`. NOTHING else in the function changes — `gh`/`ga` are opaque float arrays to the MLE loop (116-148), `n_eff` (104-106) depends only on `w`/`h`/`a`, and the re-anchor (145-146) is pure array arithmetic. `fit_and_write` gains a matching `goal_keys=("score_home","score_away")` pass-through parameter forwarded to `fit_offsets` at line 181.

- [ ] **Step 1: Write failing tests** (`pipeline/fit_attack_defence_test.py`). Named cases:
  - `test_goal_keys_default_is_bit_identical` — `fit_offsets(rows, ref)` with the default equals a call with explicit `goal_keys=("score_home","score_away")` on the same rows (the refactor is a no-op on the served path — the shadow-first guarantee at the fitter level).
  - `test_goal_keys_reads_xg_fields` — rows carrying `xg_a`/`xg_b` fit via `goal_keys=("xg_a","xg_b")` and produce DIFFERENT offsets than the goals fit on the same fixtures, proving the SAME machinery reads xG. (No assertion on MLE internals — only that the two goal sources drive distinct outputs.)

- [ ] **Step 2: Run to verify fail** (`goal_keys` unknown kwarg).

- [ ] **Step 3: Implement the 2-line + signature change** in `fit_offsets`, and the `goal_keys` pass-through in `fit_and_write`. Do NOT touch anything between lines 95-160.

- [ ] **Step 4: Run to verify pass**, then commit:
  ```bash
  git add pipeline/fit_attack_defence.py pipeline/fit_attack_defence_test.py
  git commit -m "feat(xg-offsets): parametrize fit_offsets goal-source (default bit-identical)"
  ```

---

## Phase 5 — Produce `team_offsets_xg.json` (re-anchor + κ-blend, reused method)

**Files:**
- Create: `pipeline/build_xg_offsets.py`
- Create: `pipeline/build_xg_offsets_test.py`

**Interfaces:**
- Consumes: `fit_offsets(..., goal_keys=("xg_a","xg_b"))` (Phase 4); `build_enriched_rows(db)` (goals rows) + the same rows filtered to xG-covered (`xg_a`/`xg_b` non-NULL) for the xG fit; `ml/models/team_offsets.py` loader shape `{team_name: {atk, def, n_matches}}`. NOTE: `n_eff` is NOT persisted by the fitter (only `n_matches`), so the blend must recompute or capture `n_eff_xg` in-process — `build_xg_offsets` runs both fits itself and has `n_eff` available in-memory (do NOT try to recover it from the store).
- Produces: `ml/models/team_offsets_xg.json`, same shape the loader reads.

- [ ] **Step 1: Write failing unit tests** (`pipeline/build_xg_offsets_test.py`) — pure over small synthetic offset dicts, no DB:
  - `test_reanchor_removes_zero_point_shift` — given goals-fit `{ĝ_t}` and an xG-fit `{x̂_t}` deliberately offset by a scalar over the shared set `S`, `δ̂ = Σ_{t∈S} n_eff_xg,t·(ĝ_t − x̂_t)/Σ n_eff_xg,t` and `x̂′_t = x̂_t + δ̂` makes the shared-set gap mean-zero (weighted by `n_eff_xg`).
  - `test_blend_kappa_zero_is_goals_identity` — a team with `n_eff_xg=0` (not in `S`) → `κ_t=0` → `offset_t == ĝ_t` exactly (the shadow-first identity: κ=0 teams reproduce today's served numbers through the twin).
  - `test_blend_stays_capped` + `test_blend_clamps_delta_driven_breach` — blended `|offset_t| ≤ OFFSET_CAP = 0.075` on **both** channels. **Correction to the spec:** δ̂ is applied **per channel** (`fit_offsets` centres atk/def separately, `fit_attack_defence.py:146-147`, so each has its own zero-point) and the blend is **explicitly re-clamped** to `OFFSET_CAP` — convexity does NOT keep it capped once δ̂ shifts a channel out of the capped region (a review caught an atk-derived δ pushing def to 0.12). `κ_t = min(1, √(n_eff_xg,t/30))`.
  - `test_empty_S_writes_goals_store` — if no team has any xG coverage (`S` empty) → `δ̂` undefined → skip the xG fit, write the goals store, log the no-op loudly (kill-switch).

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `build_xg_offsets(db, out_path="ml/models/team_offsets_xg.json")`** exactly per the design's ML core (spec:73-110), calling the reused `fit_offsets` TWICE (goals over full history; xG over `xg_a`/`xg_b`-covered rows via `goal_keys`), then applying the **per-channel** re-anchor δ̂_c and the κ-blend `offset_t,c = clamp(ĝ_t,c + κ_t·(x̂′_t,c − ĝ_t,c))`, re-clamped to `OFFSET_CAP`. Write `{team_name: {atk, def, n_matches}}` via the same name-keyed payload shape as `fit_and_write:186-194`. **No new MLE/decay/shrink logic** — this only wires the validated blend to WC data.

- [ ] **Step 4: Run to verify pass**, then commit:
  ```bash
  git add pipeline/build_xg_offsets.py pipeline/build_xg_offsets_test.py
  git commit -m "feat(xg-offsets): re-anchored goals+xG blend -> team_offsets_xg.json"
  ```

- [ ] **Step 5 (operational, after Phase-3 backfill has populated `xg_a`/`xg_b`):** run `build_xg_offsets(db)` to produce the real `team_offsets_xg.json`; spot-check that κ=0 teams' atk/def equal the goals store's and that offsets land on plausible teams. Commit the generated store.

---

## Phase 6 — Shadow twin (`OFFSETS_MODEL_VERSION`) + dedicated benchmark runner

**Files:**
- Modify: `pipeline/generate_predictions.py`
- Create: `pipeline/generate_predictions_offsets_twin_test.py`
- Create: `ml/evaluation/offsets_benchmark.py`
- Create: `pipeline/run_offsets_benchmark.py`
- Create: `pipeline/run_offsets_benchmark_test.py`
- Modify: `backend/app/api/internal.py`
- Create: `backend/tests/test_offsets_record.py`

**Interfaces:**
- Add constant after `AVAILABILITY_MODEL_VERSION` (line 41): `OFFSETS_MODEL_VERSION = "poisson-elo-v0.3+xg"` (is_shadow, never served).
- Add `write_offsets_prediction(db: Session, match: Match, payload: dict, strengths: dict[int, float], params: ModelParams) -> None` — EXACT body shape of `write_availability_prediction` (324-363), substituting the offset source: `store = load_team_offsets("ml/models/team_offsets_xg.json")` (INDEPENDENT of `params.team_offsets`); `atk_h, def_h = offsets_for(store, home.name)`; `atk_a, def_a = offsets_for(store, away.name)`; if BOTH sides are all-zero (no coverage) → `return` (no row — clean null test, mirrors `if adj is None: return`); else `lam_h = payload["lambda_home"] * math.exp(atk_h + def_a)`, `lam_a = payload["lambda_away"] * math.exp(atk_a + def_h)` (cross-term per `ml/models/poisson.py:66-69`). Then the identical `predict_from_lambdas(...)` + dict-spread `twin` + `_write_prediction(db, match, twin, OFFSETS_MODEL_VERSION, is_shadow=True)`. Look up by `home.name`/`away.name` (NOT id — `offsets_for` takes a name string).
- Loop call: in `generate_predictions` (546-556), add `write_offsets_prediction(db, match, payload, strengths, params)` immediately after the `write_availability_prediction(...)` call (line 555), before `predicted += 1`.
- `benchmark_offsets(prod_probs, offsets_probs, labels, n_bootstrap=2000, seed=26) -> dict` — clone of `benchmark_availability` (`ml/evaluation/availability_benchmark.py:29-65`); identical bootstrap/CI95 math, `seed=26`, `_LABEL_INDEX/_EPS/_log_loss_one` copied verbatim, `compute_metrics` imported from `ml.evaluation.backtest`; only dict keys `"availability"→"offsets"` and `"availability_win_rate"→"offsets_win_rate"` renamed.
- `run_offsets_benchmark.py`: `_latest(db, match_id, *, offsets)` (twin branch filters `Prediction.model_version == OFFSETS_MODEL_VERSION`; production branch stays `is_shadow.is_(False)` with NO model_version filter); `_verdict` with labels `offsets_beats_published`/`published_beats_offsets`/`no_credible_difference`/`insufficient`; `offsets_record(db) -> dict`. NEVER writes to `PredictionResult` (its `uq_prediction_result_match_shadow` allows only one shadow row per match — compute-on-read only).
- `GET /api/internal/offsets-record` — sibling of `availability_record_endpoint` (`internal.py:239-254`): same `_require_token(x_recompute_token)` guard, lazy-imports `offsets_record` from `pipeline.run_offsets_benchmark`, returns it.

- [ ] **Step 1: Write failing twin tests** (`pipeline/generate_predictions_offsets_twin_test.py`), in-memory SQLite, monkeypatching `load_team_offsets` to return a fixture store. Named cases:
  - `test_no_offsets_writes_no_row` — store empty for both teams → no `OFFSETS_MODEL_VERSION` row written (null-test).
  - `test_scales_lambdas_and_tags` — with a store, the twin row's λ = production λ × `exp(atk+def)` cross-term, tagged `OFFSETS_MODEL_VERSION`, `is_shadow=True`.
  - `test_production_and_other_twins_untouched` — the published row and the availability twin are byte-for-byte unchanged by adding the offsets call.
  - `test_independent_of_team_offsets_flag` — twin loads the xG store even when `params.team_offsets is None` (the shadow-first invariant).

- [ ] **Step 2: Write failing benchmark/record tests** (`pipeline/run_offsets_benchmark_test.py`, cloned from `pipeline/run_availability_benchmark_test.py`): `test_scores_matches_with_both_rows`, `test_excludes_match_missing_twin`, `test_honest_empty_with_no_data` (using `OFFSETS_MODEL_VERSION` + `offsets_record`).

- [ ] **Step 3: Write failing endpoint tests** (`backend/tests/test_offsets_record.py`, cloned from `backend/tests/test_availability_record.py`): `test_fails_closed_without_token` (503), `test_rejects_bad_token` (401), `test_returns_paired_comparison` (200 + verdict), `test_is_honest_when_empty`.

- [ ] **Step 4: Run all three to verify fail.**

- [ ] **Step 5: Implement** the constant + `write_offsets_prediction` + loop call; `ml/evaluation/offsets_benchmark.py`; `pipeline/run_offsets_benchmark.py`; the endpoint. Reuse verbatim: `_write_prediction`, `predict_from_lambdas`, `_host_adv`, `effective_gap`, the dict-spread twin pattern, `load_team_offsets`/`offsets_for`.

- [ ] **Step 6: Run all three to verify pass**, then commit:
  ```bash
  git add pipeline/generate_predictions.py pipeline/generate_predictions_offsets_twin_test.py \
          ml/evaluation/offsets_benchmark.py pipeline/run_offsets_benchmark.py \
          pipeline/run_offsets_benchmark_test.py backend/app/api/internal.py backend/tests/test_offsets_record.py
  git commit -m "feat(xg-offsets): shadow twin + dedicated benchmark runner + internal record endpoint"
  ```

---

## Phase 7 — A/B/C WC backtest (sanity check, NOT the proof bar) + whole-branch verify

**Files:**
- Create: `pipeline/backtest_xg_offsets.py`

**Interfaces:**
- Consumes: `build_enriched_rows(db)` (walk-forward, exclusive `ref_date`); `fit_offsets` (goals + xG via `goal_keys`); the re-anchor/blend from `build_xg_offsets`.
- Produces: an offline report comparing **A** no-offsets / **B** goals-offsets / **C** xG-nudged on held-out past WC editions, scoring Brier + log-loss on W/D/L, plus per-edition xG coverage.

- [ ] **Step 1: Write a failing smoke test** (add to `pipeline/build_xg_offsets_test.py` or a new `pipeline/backtest_xg_offsets_test.py`): `test_abc_report_runs_and_prints_coverage` — on a tiny synthetic history the report produces A/B/C log-loss + per-edition coverage without raising, and **C is never far from B** on a κ≈0 fixture (sanity, not significance).

- [ ] **Step 2: Implement `backtest_xg_offsets.py`.** Frame the output explicitly as a sanity check: xG exists only in recent editions' training windows (~2 clusters, too few to exclude zero either way). Print per-edition coverage so a null reads as "underpowered here," not "xG doesn't help." This is NOT the proof bar — the served model is untouched regardless of the result.

- [ ] **Step 3: Run the smoke test to verify pass.**

- [ ] **Step 4: Whole-branch verification** — the honest ship gate:
  ```bash
  ln -sfn "/Users/macbookpro/Projects/FIFA WC26 Prediction/.venv" .venv
  PYTHONPATH=backend:. .venv/bin/python -m pytest backend ml pipeline -q
  ```
  Expected: ALL green — every new test file passes AND nothing pre-existing regressed (the `goal_keys` default is bit-identical; the twin is additive; `params.team_offsets` still `null`; no served field changed). Paste the real output — no success claim without it.

- [ ] **Step 5: Commit + open PR** (human merges — never self-merge):
  ```bash
  git add pipeline/backtest_xg_offsets.py pipeline/backtest_xg_offsets_test.py
  git commit -m "feat(xg-offsets): A/B/C WC backtest sanity report + whole-branch verify"
  ```

---

## Self-Review

- **Spec coverage:** migration (§Migration required / spec:47) → Phase 1; StatsBomb ingestion+parser (pivot of spec Phase 2) → Phase 2; backfill+matcher (spec:112-130, testing:213-215) → Phase 3; `fit_offsets` goal-source (spec:80-82) → Phase 4; re-anchor+κ-blend store (spec:83-110, Phase 4/5) → Phase 5; twin + benchmark runner (spec:132-144, 181-182) → Phase 6; A/B/C backtest (spec:146-160) → Phase 7. Shadow-first / no-promotion / match-level-only / never-fabricate all honored.
- **Corrections flagged:** no injuries migration (use `e0f1a2b3c4d5`); table is `team_a`/`team_b` not home/away; head is `c4d5e6f7a8b0`; data source is StatsBomb not API-Football; fitter change is exactly lines 93-94 + signature; twin loads store independent of `params.team_offsets` and is called after line 555.
- **Stop-gate:** Phase 1 Step 6 explicitly halts before dispatching `refresh.yml`/merging to `main`; the migration must reach prod before Phase 6 twin runs against prod.
- **Type consistency:** `goal_keys: tuple[str,str]` default `("score_home","score_away")`; `offsets_for` takes a NAME; twin cross-term matches `poisson.py:66-69`; `OFFSETS_MODEL_VERSION="poisson-elo-v0.3+xg"` imported never hardcoded; benchmark `seed=26` preserved.
- **Placeholder scan:** `<newrev>` in Phase 1 is the only intentional placeholder (a fresh Alembic revision id the implementer generates); every other step is runnable.