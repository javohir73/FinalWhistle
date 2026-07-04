# Club-league xG Method Validation — Implementation Plan

> **⚠️ SHELVED 2026-07-04** — Task 0's depth-probe gate returned STOP: API-Football lacks the international xG this feature needs (no WC-2022 / friendlies / qualifier xG; only 2023+ club xG). Execution halted at Task 0; Tasks 1–8 were never built. See the design spec's status line and `.superpowers/sdd/progress.md`. The provider-agnostic pieces (parametrized fitter goal-source, re-anchor/κ-blend) remain reusable if a real xG source ever lands.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove-or-kill the goals-prior + xG-nudge offset method on dense API-Football club-league xG, so the WC xG-offset feature only builds if the method demonstrably helps.

**Architecture:** Fully offline/read-only. Pull club fixtures + per-fixture xG from API-Football (cached to disk), replay Elo for club ratings, then run a walk-forward A/B/C backtest (no-offset / goals-offset / xG-nudged) scored with the existing `compute_metrics`, aggregated per league-season with a clustered bootstrap. A pre-registered directional+consistent verdict decides the gate.

**Tech Stack:** Python 3, numpy, `requests` (existing api_football pattern), pytest. Reuses `ml/ratings/elo.replay_with_prematch`, `ml/evaluation/backtest.compute_metrics`, `pipeline/fit_attack_defence.fit_offsets`, `ml/models/team_offsets` (`OFFSET_CAP`, `FULL_WEIGHT_EFF_MATCHES`, `shrink_and_cap`).

**Design spec:** `docs/superpowers/specs/2026-07-04-club-xg-method-validation-design.md`

## Global Constraints

- **Offline/read-only.** No DB writes, no Alembic migration, no served-model change, no network at test time. Live API calls happen only in CLI runs, never in tests (tests use fakes/fixtures). Does **not** touch the stop gate.
- **Same xG source as production:** API-Football `/fixtures/statistics`, `expected_goals` statistic, auth via `x-apisports-key` header, base `https://v3.football.api-sports.io`.
- **No fuzzy club-name join:** the club spine is sourced from API-Football fixtures and xG is keyed by `fixture_id`. Never match club matches by `(date, name)`.
- **Cap is verbatim:** `OFFSET_CAP = 0.075` log-λ; `FULL_WEIGHT_EFF_MATCHES = 30`. Do not redefine — import from `ml/models/team_offsets.py`.
- **PRE-REGISTERED depth-probe gate (Phase 0, decided now, before any data is seen):** proceed on API-Football only if the probe finds **≥ 3000 club matches carrying `expected_goals`, spanning ≥ 6 league-seasons**. Below that → STOP and escalate the Understat/FBref-fallback decision (out of scope for this plan).
- **PRE-REGISTERED verdict thresholds (Phase 8, decided now, before Phase 7 produces any numbers):** the method PASSES iff **all three** hold:
  1. **Aggregate:** n-weighted `C.log_loss < B.log_loss` AND `C.brier < B.brier` (strict point estimate).
  2. **Consistency:** `C.log_loss ≤ B.log_loss` in **≥ ⌈2/3 of league-season cells**.
  3. **No-harm floor:** for **every** league, season-aggregated `C.log_loss − B.log_loss ≤ +0.002`.
  CIs (clustered bootstrap) are reported but **not** required to exclude zero. These numbers are frozen by this document; do not adjust them after seeing results.
- **Naming:** offsets are log-λ units; keys are `atk`, `def`. Elo baseline for club matches uses `is_neutral=False` always (club venues aren't neutral).

---

## File Structure

- `pipeline/ingest/api_football.py` — **modify.** Add `fetch_fixture_statistics` + pure `parse_team_xg`. (Shared with the WC spec.)
- `pipeline/fit_attack_defence.py` — **modify.** Parametrize the goal-source arrays in `fit_offsets` (default unchanged). (Shared.)
- `ml/models/xg_offset_blend.py` — **create.** Pure re-anchor + κ-blend of a goals-fit and an xG-fit. (Shared.)
- `pipeline/club_xg_data.py` — **create.** Disk-cached API-Football club ingestion: fixtures spine, per-fixture xG backfill, enriched-row assembly (Elo replay + xg attach).
- `ml/evaluation/cluster_bootstrap.py` — **create.** Clustered (by league-season) bootstrap CI for a paired metric diff.
- `pipeline/run_club_xg_validation.py` — **create.** The A/B/C walk-forward harness + verdict + CLI report.
- `pipeline/probe_club_xg.py` — **create.** Phase-0 depth probe CLI (prints coverage; applies the pre-registered gate).

Tests (one per module): `pipeline/ingest/fixture_statistics_test.py`, `pipeline/fit_attack_defence_test.py` (append), `ml/models/xg_offset_blend_test.py`, `pipeline/club_xg_data_test.py`, `ml/evaluation/cluster_bootstrap_test.py`, `pipeline/run_club_xg_validation_test.py`.

Run all backend tests with: `.venv/bin/python -m pytest ml pipeline -q`

---

## Task 0: Phase-0 depth probe (fork gate)

**Files:**
- Create: `pipeline/probe_club_xg.py`
- (No test — throwaway diagnostic; it only prints. It must never raise.)

**Interfaces:**
- Consumes: `fetch_fixture_statistics` does not exist yet, so the probe calls `/fixtures` + `/fixtures/statistics` inline via `requests` (self-contained, like `probe_player_access` in `api_football.py`).
- Produces: a printed coverage table + a GO/STOP line applying the pre-registered gate (≥3000 matches, ≥6 league-seasons).

- [ ] **Step 1: Write the probe** (diagnostic, never raises; mirrors `probe_player_access` style)

```python
"""Phase-0 depth probe: how much club xG can API-Football actually give us?

Prints per (league, season) the fixture count and how many carry a non-null
`expected_goals` statistic, then applies the PRE-REGISTERED gate from the plan
(>=3000 covered matches across >=6 league-seasons). Diagnostic only: no writes,
never raises. Usage:
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.probe_club_xg --api-key $KEY
"""
from __future__ import annotations
import argparse, sys, requests

BASE = "https://v3.football.api-sports.io"
# API-Football league ids for the top-5 European leagues.
LEAGUES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
SEASONS = [2018, 2019, 2020, 2021, 2022, 2023]
GATE_MATCHES, GATE_CELLS = 3000, 6

def _get(path, key, params):
    try:
        r = requests.get(f"{BASE}{path}", headers={"x-apisports-key": key}, params=params, timeout=20)
        return r.json().get("response") or []
    except Exception as exc:  # noqa: BLE001 - diagnostic must never raise
        print(f"  ! {path} {params}: {exc}", file=sys.stderr)
        return []

def _has_xg(fixture_id, key) -> bool:
    for block in _get("/fixtures/statistics", key, {"fixture": fixture_id}):
        for s in block.get("statistics") or []:
            if s.get("type") == "expected_goals" and s.get("value") not in (None, ""):
                return True
    return False

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--api-key", required=True)
    ap.add_argument("--sample", type=int, default=20, help="fixtures/cell to probe for xG")
    args = ap.parse_args()
    total_covered, cells_with_xg = 0, 0
    for lid, lname in LEAGUES.items():
        for season in SEASONS:
            fx = _get("/fixtures", args.api_key, {"league": lid, "season": season})
            done = [f for f in fx if ((f.get("fixture") or {}).get("status") or {}).get("short") == "FT"]
            sample = done[: args.sample]
            covered = sum(_has_xg((f.get("fixture") or {}).get("id"), args.api_key) for f in sample)
            frac = covered / len(sample) if sample else 0.0
            est = int(round(frac * len(done)))
            if covered:
                cells_with_xg += 1
                total_covered += est
            print(f"{lname} {season}: {len(done)} FT, xG in {covered}/{len(sample)} sampled -> ~{est} covered")
    ok = total_covered >= GATE_MATCHES and cells_with_xg >= GATE_CELLS
    print(f"\nESTIMATE: ~{total_covered} covered matches across {cells_with_xg} league-seasons")
    print(f"GATE (>= {GATE_MATCHES} matches AND >= {GATE_CELLS} cells): {'GO' if ok else 'STOP -> escalate Understat fallback'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Sanity-run against the real key** (not a unit test — a manual gate)

Run: `PYTHONPATH=backend:. .venv/bin/python -m pipeline.probe_club_xg --api-key "$API_FOOTBALL_API_KEY"`
Expected: a per-cell table and a final `GATE: GO` (or `STOP`). **If STOP, halt the plan and escalate** — do not build Tasks 1-8 against an underpowered source.

- [ ] **Step 3: Commit**

```bash
git add pipeline/probe_club_xg.py
git commit -m "feat(club-xg): phase-0 depth probe with pre-registered gate"
```

---

## Task 1: Shared xG fetcher/parser

**Files:**
- Modify: `pipeline/ingest/api_football.py` (add two functions near the other `fetch_*`)
- Test: `pipeline/ingest/fixture_statistics_test.py`

**Interfaces:**
- Produces: `parse_team_xg(response: list[dict]) -> dict[int, float | None]` — maps api-football team id → its `expected_goals` (float, or `None` when absent/blank/unparseable). `fetch_fixture_statistics(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]` — raw `/fixtures/statistics` response list.

- [ ] **Step 1: Write the failing test** (`pipeline/ingest/fixture_statistics_test.py`)

```python
from pipeline.ingest.api_football import parse_team_xg

def _block(team_id, xg):
    stats = [{"type": "Shots on Goal", "value": 5}]
    if xg is not None:
        stats.append({"type": "expected_goals", "value": xg})
    return {"team": {"id": team_id, "name": f"T{team_id}"}, "statistics": stats}

def test_parse_team_xg_reads_expected_goals():
    resp = [_block(33, "1.5"), _block(40, "0.8")]
    assert parse_team_xg(resp) == {33: 1.5, 40: 0.8}

def test_parse_team_xg_missing_or_blank_is_none():
    resp = [_block(33, None), _block(40, "")]
    assert parse_team_xg(resp) == {33: None, 40: None}

def test_parse_team_xg_unparseable_is_none_never_raises():
    resp = [_block(33, "N/A"), {"team": {}, "statistics": None}]
    assert parse_team_xg(resp) == {33: None}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/fixture_statistics_test.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_team_xg'`.

- [ ] **Step 3: Implement** (append to `pipeline/ingest/api_football.py`)

```python
def fetch_fixture_statistics(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw per-team statistics list for one fixture (/fixtures/statistics)."""
    resp = requests.get(
        f"{BASE_URL}/fixtures/statistics",
        headers={"x-apisports-key": api_key},
        params={"fixture": fixture_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football statistics errors: %s", data["errors"])
    return data.get("response") or []


def parse_team_xg(response: list[dict]) -> dict[int, float | None]:
    """Map team id -> its expected_goals for one fixture; None when absent/blank/unparseable.

    Pure: api-football reports xG as the "expected_goals" statistic with a string
    value (e.g. "1.5"). Never fabricate — a missing/garbled value is None, and a
    block with no usable team id is skipped."""
    out: dict[int, float | None] = {}
    for block in response or []:
        if not isinstance(block, dict):
            continue
        tid = (block.get("team") or {}).get("id")
        if tid is None:
            continue
        xg: float | None = None
        for stat in block.get("statistics") or []:
            if isinstance(stat, dict) and stat.get("type") == "expected_goals":
                try:
                    xg = float(stat.get("value"))
                except (TypeError, ValueError):
                    xg = None
                break
        out[tid] = xg
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/fixture_statistics_test.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/fixture_statistics_test.py
git commit -m "feat(club-xg): shared /fixtures/statistics fetcher + parse_team_xg"
```

---

## Task 2: Parametrize the fitter's goal source

**Files:**
- Modify: `pipeline/fit_attack_defence.py` (`fit_offsets` signature + the two goal arrays)
- Test: `pipeline/fit_attack_defence_test.py` (append; create if absent)

**Interfaces:**
- Produces: `fit_offsets(rows, ref_date, half_life_days=..., params=None, max_iter=..., tol=..., home_goal_key="score_home", away_goal_key="score_away")`. Default keys reproduce today's behavior bit-for-bit; passing `home_goal_key="xg_home", away_goal_key="xg_away"` fits on xG.

- [ ] **Step 1: Write the failing test** (append to `pipeline/fit_attack_defence_test.py`)

```python
from datetime import date
from pipeline.fit_attack_defence import fit_offsets

def _row(h, a, sh, sa, xgh, xga, d="2022-01-01"):
    return {"date": date.fromisoformat(d), "home_id": h, "away_id": a,
            "score_home": sh, "score_away": sa, "xg_home": xgh, "xg_away": xga,
            "is_neutral": True, "pre_home": 1500.0, "pre_away": 1500.0}

def test_goal_source_defaults_reproduce_goals_fit():
    rows = [_row(1, 2, 3, 0, 0.5, 0.5), _row(2, 1, 2, 0, 0.4, 0.4)]
    ref = date(2023, 1, 1)
    a = fit_offsets(rows, ref)
    b = fit_offsets(rows, ref, home_goal_key="score_home", away_goal_key="score_away")
    assert a == b

def test_xg_source_differs_from_goals_when_xg_diverges():
    # Team 1 outscores its xG heavily; the xG fit must give it a lower atk than the goals fit.
    rows = [_row(1, 2, 4, 0, 0.5, 0.5), _row(1, 2, 4, 0, 0.5, 0.5), _row(2, 1, 1, 1, 1.0, 1.0)]
    ref = date(2023, 1, 1)
    g = fit_offsets(rows, ref)
    x = fit_offsets(rows, ref, home_goal_key="xg_home", away_goal_key="xg_away")
    assert x[1]["atk"] < g[1]["atk"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/fit_attack_defence_test.py -q`
Expected: FAIL — `fit_offsets() got an unexpected keyword argument 'home_goal_key'`.

- [ ] **Step 3: Implement** — change the signature and the two array builders in `fit_offsets`.

Signature (add the two kwargs at the end):
```python
def fit_offsets(
    rows: list[dict],
    ref_date,
    half_life_days: int = DEFAULT_HALF_LIFE_DAYS,
    params: ModelParams | None = None,
    max_iter: int = _MAX_ITER,
    tol: float = _TOL,
    home_goal_key: str = "score_home",
    away_goal_key: str = "score_away",
) -> dict[int, dict]:
```
Replace the two goal-array lines (currently `gh = np.array([float(r["score_home"]) ...])` / `ga = ...`):
```python
    gh = np.array([float(r[home_goal_key]) for r in train])
    ga = np.array([float(r[away_goal_key]) for r in train])
```

- [ ] **Step 4: Run to verify it passes + regression**

Run: `.venv/bin/python -m pytest pipeline/fit_attack_defence_test.py -q`
Expected: PASS (existing tests still pass — defaults unchanged).

- [ ] **Step 5: Commit**

```bash
git add pipeline/fit_attack_defence.py pipeline/fit_attack_defence_test.py
git commit -m "feat(club-xg): parametrize fit_offsets goal source (default unchanged)"
```

---

## Task 3: Re-anchor + κ-blend

**Files:**
- Create: `ml/models/xg_offset_blend.py`
- Test: `ml/models/xg_offset_blend_test.py`

**Interfaces:**
- Consumes: two `fit_offsets` outputs — `goals_fit`/`xg_fit`, each `{team_id: {"atk", "def", "n_matches", "n_eff"}}`.
- Produces: `blend_goals_xg(goals_fit: dict, xg_fit: dict) -> dict[int, tuple[float, float]]` → `{team_id: (atk, def)}`. Teams absent from `xg_fit` (or with `n_eff==0`) return their goals offset unchanged (κ=0).

- [ ] **Step 1: Write the failing test** (`ml/models/xg_offset_blend_test.py`)

```python
import math
from ml.models.team_offsets import OFFSET_CAP, FULL_WEIGHT_EFF_MATCHES
from ml.models.xg_offset_blend import blend_goals_xg

def _fit(**teams):  # teams: id -> (atk, def, n_eff)
    return {tid: {"atk": a, "def": d, "n_matches": int(n), "n_eff": n} for tid, (a, d, n) in teams.items()}

def test_no_xg_coverage_returns_goals_offsets():
    g = _fit(**{1: (0.03, -0.02, 50.0)})
    assert blend_goals_xg(g, {}) == {1: (0.03, -0.02)}

def test_full_coverage_reanchored_residual_is_mean_zero():
    # Two teams, both fully covered (n_eff=30 -> kappa=1). Re-anchor => sum of
    # kappa-weighted (x' - g) residuals is ~0, so the blend can't add a net level shift.
    g = _fit(**{1: (0.04, 0.0, 30.0), 2: (-0.04, 0.0, 30.0)})
    x = _fit(**{1: (0.02, 0.0, 30.0), 2: (-0.02, 0.0, 30.0)})  # xG frame sits 0.0 higher on avg here
    out = blend_goals_xg(g, x)
    resid = sum(out[t][0] - g[t]["atk"] for t in (1, 2))
    assert abs(resid) < 1e-9

def test_blend_never_exceeds_cap():
    g = _fit(**{1: (OFFSET_CAP, OFFSET_CAP, 30.0)})
    x = _fit(**{1: (-OFFSET_CAP, -OFFSET_CAP, 30.0)})
    atk, dfn = blend_goals_xg(g, x)[1]
    assert -OFFSET_CAP <= atk <= OFFSET_CAP and -OFFSET_CAP <= dfn <= OFFSET_CAP

def test_kappa_ramps_with_coverage():
    g = _fit(**{1: (0.05, 0.0, 100.0), 2: (0.05, 0.0, 100.0)})
    # team 2 has thin xG coverage -> kappa small -> stays near goals offset
    x = _fit(**{1: (-0.05, 0.0, 30.0), 2: (-0.05, 0.0, 3.0)})
    out = blend_goals_xg(g, x)
    assert abs(out[2][0] - 0.05) < abs(out[1][0] - 0.05)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest ml/models/xg_offset_blend_test.py -q`
Expected: FAIL — `ModuleNotFoundError: ml.models.xg_offset_blend`.

- [ ] **Step 3: Implement** (`ml/models/xg_offset_blend.py`)

```python
"""Re-anchor + coverage-weighted blend of a goals-fit and an xG-fit (shared method).

offset_t = ĝ_t + κ_t·(x̂′_t − ĝ_t), where x̂′ is the xG fit shifted onto the goals
frame (removing the two fits' zero-point mismatch) and κ_t ramps with xG coverage.
See docs/superpowers/specs/2026-07-04-club-xg-method-validation-design.md."""
from __future__ import annotations
import math
from ml.models.team_offsets import OFFSET_CAP, FULL_WEIGHT_EFF_MATCHES


def _reanchor(goals_fit: dict, xg_fit: dict, key: str) -> dict[int, float]:
    """δ̂ = n_eff_xg-weighted mean over covered teams of (goals − xg); return x + δ̂."""
    num = den = 0.0
    for tid, xe in xg_fit.items():
        w = float(xe.get("n_eff", 0.0))
        if w <= 0.0 or tid not in goals_fit:
            continue
        num += w * (goals_fit[tid][key] - xe[key])
        den += w
    delta = num / den if den > 0.0 else 0.0
    return {tid: xe[key] + delta for tid, xe in xg_fit.items()}


def blend_goals_xg(goals_fit: dict, xg_fit: dict) -> dict[int, tuple[float, float]]:
    """Blend per team; teams without xG coverage keep their goals offset (κ=0)."""
    x_atk = _reanchor(goals_fit, xg_fit, "atk")
    x_def = _reanchor(goals_fit, xg_fit, "def")
    out: dict[int, tuple[float, float]] = {}
    for tid, ge in goals_fit.items():
        n_eff = float(xg_fit.get(tid, {}).get("n_eff", 0.0))
        k = min(1.0, math.sqrt(n_eff / FULL_WEIGHT_EFF_MATCHES)) if n_eff > 0.0 else 0.0
        atk = ge["atk"] + k * (x_atk.get(tid, ge["atk"]) - ge["atk"])
        dfn = ge["def"] + k * (x_def.get(tid, ge["def"]) - ge["def"])
        clamp = lambda v: max(-OFFSET_CAP, min(OFFSET_CAP, v))  # noqa: E731
        out[tid] = (clamp(atk), clamp(dfn))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest ml/models/xg_offset_blend_test.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ml/models/xg_offset_blend.py ml/models/xg_offset_blend_test.py
git commit -m "feat(club-xg): re-anchor + kappa-blend of goals and xG fits"
```

---

## Task 4: Disk-cached club data (fixtures spine + xG backfill + enriched rows)

**Files:**
- Create: `pipeline/club_xg_data.py`
- Test: `pipeline/club_xg_data_test.py`

**Interfaces:**
- Consumes: `fetch_club_fixtures`/`fetch_fixture_statistics` are injected as callables so tests use fakes (no network). `replay_with_prematch`, `parse_team_xg`.
- Produces:
  - `build_enriched_club_rows(league, seasons, fixtures_by_season, xg_by_fixture) -> list[dict]` — pure assembler. Each row: `{date, home_id, away_id, score_home, score_away, is_neutral=False, competition, season, pre_home, pre_away, xg_home, xg_away}` (xg floats or None), sorted oldest-first with leak-free Elo.
  - `cached_json(path, fetch) -> obj` — read `path` if present else call `fetch()` and write it (idempotent resume).

- [ ] **Step 1: Write the failing test** (`pipeline/club_xg_data_test.py`)

```python
import json
from datetime import date
from pipeline.club_xg_data import build_enriched_club_rows, cached_json

def _fx(fid, d, h, a, sh, sa):
    return {"fixture": {"id": fid, "date": f"{d}T15:00:00+00:00"},
            "teams": {"home": {"id": h}, "away": {"id": a}},
            "goals": {"home": sh, "away": sa},
            "fixture_status": "FT"}

def test_enriched_rows_are_leakfree_and_carry_xg():
    fixtures = {2022: [_fx(100, "2022-08-01", 1, 2, 2, 0), _fx(101, "2022-08-08", 2, 1, 1, 1)]}
    xg = {100: {1: 1.8, 2: 0.4}, 101: {2: 1.1, 1: 0.9}}
    rows = build_enriched_club_rows("Premier League", [2022], fixtures, xg)
    assert [r["date"] for r in rows] == [date(2022, 8, 1), date(2022, 8, 8)]
    # First match: both teams unseen -> pre-match Elo is the 1500 base (leak-free).
    assert rows[0]["pre_home"] == 1500.0 and rows[0]["pre_away"] == 1500.0
    assert rows[0]["xg_home"] == 1.8 and rows[0]["xg_away"] == 0.4
    assert rows[0]["is_neutral"] is False and rows[0]["season"] == 2022

def test_missing_xg_side_is_none():
    fixtures = {2022: [_fx(100, "2022-08-01", 1, 2, 2, 0)]}
    rows = build_enriched_club_rows("Premier League", [2022], fixtures, {100: {1: 1.8}})
    assert rows[0]["xg_home"] == 1.8 and rows[0]["xg_away"] is None

def test_cached_json_writes_once_then_reads(tmp_path):
    calls = []
    def fetch():
        calls.append(1); return {"v": 1}
    p = tmp_path / "c.json"
    assert cached_json(str(p), fetch) == {"v": 1}
    assert cached_json(str(p), fetch) == {"v": 1}  # served from disk
    assert len(calls) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/club_xg_data_test.py -q`
Expected: FAIL — `ModuleNotFoundError: pipeline.club_xg_data`.

- [ ] **Step 3: Implement** (`pipeline/club_xg_data.py`)

```python
"""Disk-cached API-Football club ingestion for the xG method-validation harness.

Offline research helper: pulls club fixtures + per-fixture xG (cached to disk so a
run resumes without duplicate calls), then assembles leak-free enriched rows
(Elo replay + xg attach) the A/B/C harness fits on. No DB, no served-model path."""
from __future__ import annotations
import json, os
from datetime import date, datetime
from ml.ratings.elo import MatchInput, replay_with_prematch


def cached_json(path: str, fetch):
    """Return JSON at `path`, else call fetch(), persist, and return it (idempotent)."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    obj = fetch()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return obj


def _fx_date(fx: dict) -> date:
    return datetime.fromisoformat((fx.get("fixture") or {}).get("date")).date()


def build_enriched_club_rows(league, seasons, fixtures_by_season, xg_by_fixture) -> list[dict]:
    """Assemble leak-free enriched rows for one league across `seasons`.

    fixtures_by_season: {season: [api-football fixture dict, ...]}
    xg_by_fixture: {fixture_id: {team_id: xg_float_or_None}}  (from parse_team_xg)
    Concatenates all seasons oldest-first, replays Elo pre-match, and attaches
    date/season/xg keyed by fixture_id — no name join anywhere."""
    flat = []
    for season in seasons:
        for fx in fixtures_by_season.get(season, []):
            flat.append((season, fx))
    flat.sort(key=lambda sf: _fx_date(sf[1]))

    inputs = [
        MatchInput(
            home_id=(fx["teams"]["home"]["id"]),
            away_id=(fx["teams"]["away"]["id"]),
            score_home=(fx["goals"]["home"]),
            score_away=(fx["goals"]["away"]),
            competition=league,
            is_neutral=False,
        )
        for _, fx in flat
    ]
    replayed, _ = replay_with_prematch(inputs)

    rows = []
    for (season, fx), rep in zip(flat, replayed):
        fid = (fx.get("fixture") or {}).get("id")
        xg = xg_by_fixture.get(fid, {})
        rows.append({
            "date": _fx_date(fx),
            "season": season,
            "competition": league,
            "home_id": rep["home_id"],
            "away_id": rep["away_id"],
            "score_home": rep["score_home"],
            "score_away": rep["score_away"],
            "is_neutral": False,
            "pre_home": rep["pre_home"],
            "pre_away": rep["pre_away"],
            "xg_home": xg.get(rep["home_id"]),
            "xg_away": xg.get(rep["away_id"]),
        })
    return rows
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/club_xg_data_test.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/club_xg_data.py pipeline/club_xg_data_test.py
git commit -m "feat(club-xg): disk-cached club ingestion + leak-free enriched rows"
```

---

## Task 5: Clustered bootstrap CI

**Files:**
- Create: `ml/evaluation/cluster_bootstrap.py`
- Test: `ml/evaluation/cluster_bootstrap_test.py`

**Interfaces:**
- Produces: `paired_diff_ci(cells, key_a, key_b, n_boot=2000, seed=2026) -> dict` where `cells` is a list of `{"n": int, key_a: float, key_b: float}` (one per league-season). Returns `{"mean": float, "ci_lo": float, "ci_hi": float}` for the n-weighted `(a − b)` diff, resampling **whole cells** with replacement.

- [ ] **Step 1: Write the failing test** (`ml/evaluation/cluster_bootstrap_test.py`)

```python
from ml.evaluation.cluster_bootstrap import paired_diff_ci

def test_weighted_mean_diff_matches_point_estimate():
    cells = [{"n": 100, "c": 0.90, "b": 1.00}, {"n": 300, "c": 0.80, "b": 0.82}]
    res = paired_diff_ci(cells, "c", "b", n_boot=500, seed=1)
    # n-weighted mean of (c-b): (100*-0.10 + 300*-0.02)/400 = -0.04
    assert abs(res["mean"] - (-0.04)) < 1e-9
    assert res["ci_lo"] <= res["mean"] <= res["ci_hi"]

def test_all_negative_diffs_give_negative_upper_bound():
    cells = [{"n": 50, "c": 0.9, "b": 1.0}] * 8
    res = paired_diff_ci(cells, "c", "b", n_boot=500, seed=2)
    assert res["ci_hi"] < 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest ml/evaluation/cluster_bootstrap_test.py -q`
Expected: FAIL — `ModuleNotFoundError: ml.evaluation.cluster_bootstrap`.

- [ ] **Step 3: Implement** (`ml/evaluation/cluster_bootstrap.py`)

```python
"""Clustered bootstrap for a paired metric diff (cluster = league-season cell).

Resamples whole cells with replacement so the CI reflects between-cell variance,
not per-match independence (matches within a season are correlated)."""
from __future__ import annotations
import numpy as np


def _weighted(cells, key_a, key_b):
    n = np.array([c["n"] for c in cells], dtype=float)
    d = np.array([c[key_a] - c[key_b] for c in cells], dtype=float)
    return float(np.average(d, weights=n)) if n.sum() > 0 else float("nan")


def paired_diff_ci(cells, key_a, key_b, n_boot=2000, seed=2026) -> dict:
    if not cells:
        return {"mean": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    rng = np.random.default_rng(seed)
    idx = np.arange(len(cells))
    boots = []
    for _ in range(n_boot):
        pick = rng.choice(idx, size=len(cells), replace=True)
        boots.append(_weighted([cells[i] for i in pick], key_a, key_b))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"mean": _weighted(cells, key_a, key_b), "ci_lo": float(lo), "ci_hi": float(hi)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest ml/evaluation/cluster_bootstrap_test.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/cluster_bootstrap.py ml/evaluation/cluster_bootstrap_test.py
git commit -m "feat(club-xg): clustered bootstrap CI for paired metric diff"
```

---

## Task 6: A/B/C walk-forward harness + verdict

**Files:**
- Create: `pipeline/run_club_xg_validation.py`
- Test: `pipeline/run_club_xg_validation_test.py`

**Interfaces:**
- Consumes: `fit_offsets` (goal-source kwargs), `blend_goals_xg`, `compute_metrics`, `predict_match`, `paired_diff_ci`.
- Produces:
  - `offsets_for_config(train_rows, ref_date, config) -> dict[int, tuple[float,float]]` — `config` ∈ `{"A","B","C"}`; A→{} (no offsets), B→goals fit, C→blended.
  - `score_cell(rows, config, offsets) -> dict` — `compute_metrics` over a season's held-out matches under `offsets`.
  - `walk_forward(rows_by_league) -> list[dict]` — one cell per (league, season) with `{"league","season","n","A_log_loss","B_log_loss","C_log_loss","A_brier","B_brier","C_brier"}`.
  - `verdict(cells) -> dict` — applies the **pre-registered** thresholds; returns `{"pass": bool, ...evidence...}`.

- [ ] **Step 1: Write the failing tests** (`pipeline/run_club_xg_validation_test.py`)

```python
from datetime import date
from ml.models.params import load_params
from pipeline.run_club_xg_validation import offsets_for_config, walk_forward, verdict, _score

def _row(h, a, sh, sa, season, xgh=None, xga=None, d=None):
    return {"date": date.fromisoformat(d or f"{season}-03-01"), "season": season,
            "competition": "L", "home_id": h, "away_id": a, "score_home": sh,
            "score_away": sa, "is_neutral": False, "pre_home": 1500.0, "pre_away": 1500.0,
            "xg_home": xgh, "xg_away": xga}

def test_config_A_has_no_offsets():
    assert offsets_for_config([_row(1, 2, 1, 0, 2021)], date(2022, 1, 1), "A") == {}

def test_walk_forward_skips_earliest_season_no_prior_data():
    rows = {"L": [_row(1, 2, 1, 0, 2021), _row(1, 2, 2, 1, 2022)]}
    cells = walk_forward(rows)
    # 2021 has no prior training window -> only 2022 is a scored cell.
    assert {c["season"] for c in cells} == {2022}

def test_verdict_passes_on_consistent_improvement():
    cells = [{"league": L, "season": 2022, "n": 100,
              "A_log_loss": 1.10, "B_log_loss": 1.00, "C_log_loss": 0.98,
              "A_brier": 0.62, "B_brier": 0.60, "C_brier": 0.59} for L in ("E", "S", "I", "D", "F", "N")]
    v = verdict(cells)
    assert v["pass"] is True

def test_verdict_fails_when_one_league_clearly_worse():
    cells = [{"league": L, "season": 2022, "n": 100,
              "A_log_loss": 1.10, "B_log_loss": 1.00, "C_log_loss": 0.98,
              "A_brier": 0.62, "B_brier": 0.60, "C_brier": 0.59} for L in ("E", "S", "I", "D", "F")]
    cells.append({"league": "N", "season": 2022, "n": 100,
                  "A_log_loss": 1.10, "B_log_loss": 1.00, "C_log_loss": 1.05,  # +0.05 > +0.002 floor
                  "A_brier": 0.62, "B_brier": 0.60, "C_brier": 0.62})
    assert verdict(cells)["pass"] is False

def test_score_applies_home_advantage_for_nonneutral():
    params = load_params()
    home_win = _score([_row(1, 2, 1, 0, 2022)], {}, params)  # equal Elo, home wins
    away_win = _score([_row(1, 2, 0, 1, 2022)], {}, params)  # equal Elo, away wins
    # Home advantage makes a home win likelier than an away win at equal Elo, so its
    # log-loss is lower. With home_adv hardcoded to 0.0 these would be equal.
    assert home_win["log_loss"] < away_win["log_loss"]

def test_walk_forward_uses_held_season_start_across_calendar_boundary():
    # Prior season 2021 crosses the calendar boundary (autumn 2021 -> spring 2022).
    rows = {"L": [
        _row(1, 2, 3, 0, 2021, d="2021-09-01"),
        _row(2, 1, 0, 2, 2021, d="2022-03-01"),  # spring: must survive into the fit
        _row(1, 2, 1, 1, 2022, d="2022-09-01"),
    ]}
    cell = next(c for c in walk_forward(rows) if c["season"] == 2022)
    params = load_params()
    train = [r for r in rows["L"] if r["season"] < 2022]
    held = [r for r in rows["L"] if r["season"] == 2022]
    ref = min(r["date"] for r in held)  # correct cutoff keeps the spring-2022 row
    expected = _score(held, offsets_for_config(train, ref, "B"), params)
    assert abs(cell["B_log_loss"] - expected["log_loss"]) < 1e-12
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/run_club_xg_validation_test.py -q`
Expected: FAIL — `ModuleNotFoundError: pipeline.run_club_xg_validation`.

- [ ] **Step 3: Implement** (`pipeline/run_club_xg_validation.py`)

```python
"""A/B/C walk-forward validation of the goals-prior + xG-nudge method on club xG.

A = no offsets, B = goals-offsets, C = xG-nudged. Per league, for each season with
a prior training window, fit on all earlier matches (exclusive cutoff = leak-free),
predict the held-out season, score with compute_metrics, and apply the plan's
PRE-REGISTERED directional+consistent verdict. Offline; run via CLI."""
from __future__ import annotations
import argparse, logging, math

from ml.evaluation.backtest import compute_metrics
from ml.evaluation.cluster_bootstrap import paired_diff_ci
from ml.models.poisson import predict_match
from ml.models.xg_offset_blend import blend_goals_xg
from ml.models.params import load_params
from pipeline.fit_attack_defence import fit_offsets

log = logging.getLogger(__name__)

# PRE-REGISTERED verdict thresholds — frozen by the plan, never tuned to results.
CELL_FRACTION = 2.0 / 3.0
NO_HARM_FLOOR = 0.002


def offsets_for_config(train_rows, ref_date, config) -> dict:
    if config == "A":
        return {}
    goals_fit = fit_offsets(train_rows, ref_date)
    if config == "B":
        return {tid: (e["atk"], e["def"]) for tid, e in goals_fit.items()}
    xg_rows = [r for r in train_rows if r["xg_home"] is not None and r["xg_away"] is not None]
    xg_fit = fit_offsets(xg_rows, ref_date, home_goal_key="xg_home", away_goal_key="xg_away") if xg_rows else {}
    return blend_goals_xg(goals_fit, xg_fit)


def _score(rows, offsets, params) -> dict:
    probs, labels = [], []
    for r in rows:
        atk_h, def_h = offsets.get(r["home_id"], (0.0, 0.0))
        atk_a, def_a = offsets.get(r["away_id"], (0.0, 0.0))
        adv = 0.0 if r["is_neutral"] else params.home_adv  # club rows are non-neutral
        p = predict_match(
            r["pre_home"], r["pre_away"], home_adv=adv,
            base=params.base, beta=params.beta, rho=params.rho,
            atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
        )
        probs.append((p.prob_home_win, p.prob_draw, p.prob_away_win))
        sh, sa = r["score_home"], r["score_away"]
        labels.append("H" if sh > sa else ("A" if sh < sa else "D"))
    return compute_metrics(probs, labels)


def walk_forward(rows_by_league, params=None) -> list[dict]:
    params = params or load_params()
    cells = []
    for league, rows in rows_by_league.items():
        rows = sorted(rows, key=lambda r: r["date"])
        seasons = sorted({r["season"] for r in rows})
        for season in seasons:
            train = [r for r in rows if r["season"] < season]
            held = [r for r in rows if r["season"] == season]
            if not train or not held:
                continue
            # ref is the held season's first match — the leak-free cutoff AND the
            # decay reference. NOT date(season, 1, 1): European seasons span Aug-May,
            # so a Jan-1 cutoff silently drops the spring half of every prior season
            # from the fit and needlessly weakens the test.
            ref = min(r["date"] for r in held)
            cell = {"league": league, "season": season, "n": len(held)}
            for cfg in ("A", "B", "C"):
                offs = offsets_for_config(train, ref, cfg)
                m = _score(held, offs, params)
                cell[f"{cfg}_log_loss"] = m["log_loss"]
                cell[f"{cfg}_brier"] = m["brier"]
            cells.append(cell)
    return cells


def verdict(cells) -> dict:
    if not cells:
        return {"pass": False, "reason": "no cells"}
    tot = sum(c["n"] for c in cells)
    agg = lambda k: sum(c["n"] * c[k] for c in cells) / tot
    c_ll, b_ll, c_br, b_br = agg("C_log_loss"), agg("B_log_loss"), agg("C_brier"), agg("B_brier")
    aggregate_ok = c_ll < b_ll and c_br < b_br
    consistent = sum(c["C_log_loss"] <= c["B_log_loss"] for c in cells) >= math.ceil(CELL_FRACTION * len(cells))
    by_league: dict[str, list] = {}
    for c in cells:
        by_league.setdefault(c["league"], []).append(c)
    no_harm = all(
        (sum(x["n"] * x["C_log_loss"] for x in cs) - sum(x["n"] * x["B_log_loss"] for x in cs))
        / sum(x["n"] for x in cs) <= NO_HARM_FLOOR
        for cs in by_league.values()
    )
    ci = paired_diff_ci(
        [{"n": c["n"], "c": c["C_log_loss"], "b": c["B_log_loss"]} for c in cells], "c", "b"
    )
    return {
        "pass": bool(aggregate_ok and consistent and no_harm),
        "aggregate_ok": aggregate_ok, "consistent": consistent, "no_harm": no_harm,
        "C_log_loss": c_ll, "B_log_loss": b_ll, "C_brier": c_br, "B_brier": b_br,
        "cell_ci95": ci, "n_cells": len(cells),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/run_club_xg_validation_test.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Add the CLI glue** (append to `pipeline/run_club_xg_validation.py`) — wires cached ingestion → `walk_forward` → `verdict`, printing the report. Network only here.

```python
def _load_rows(api_key, cache_dir, leagues, seasons) -> dict:
    from pipeline.club_xg_data import build_enriched_club_rows, cached_json
    from pipeline.ingest.api_football import fetch_fixtures, fetch_fixture_statistics, parse_team_xg
    out = {}
    for lid, lname in leagues.items():
        fixtures_by_season, xg_by_fixture = {}, {}
        for season in seasons:
            fx = cached_json(f"{cache_dir}/fx_{lid}_{season}.json",
                             lambda: fetch_fixtures(api_key, lid, season))
            done = [f for f in fx if ((f.get("fixture") or {}).get("status") or {}).get("short") == "FT"]
            fixtures_by_season[season] = done
            for f in done:
                fid = (f.get("fixture") or {}).get("id")
                raw = cached_json(f"{cache_dir}/stat_{fid}.json",
                                  lambda fid=fid: fetch_fixture_statistics(api_key, fid))
                xg_by_fixture[fid] = parse_team_xg(raw)
        out[lname] = build_enriched_club_rows(lname, seasons, fixtures_by_season, xg_by_fixture)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--cache-dir", default="data/club_xg_cache")
    args = ap.parse_args()
    leagues = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
    seasons = [2018, 2019, 2020, 2021, 2022, 2023]
    rows = _load_rows(args.api_key, args.cache_dir, leagues, seasons)
    cells = walk_forward(rows)
    for c in sorted(cells, key=lambda c: (c["league"], c["season"])):
        d = c["C_log_loss"] - c["B_log_loss"]
        log.info("%-16s %d  n=%4d  C-B log_loss=%+.4f", c["league"], c["season"], c["n"], d)
    v = verdict(cells)
    log.info("\nVERDICT: %s", "PASS -> unblock WC spec" if v["pass"] else "FAIL -> shelve")
    log.info("  aggregate C<B (ll & brier): %s | consistent >=2/3 cells: %s | no league worse than +%.3f: %s",
             v["aggregate_ok"], v["consistent"], NO_HARM_FLOOR, v["no_harm"])
    log.info("  C/B log_loss %.4f/%.4f  brier %.4f/%.4f  cell CI95 %s",
             v["C_log_loss"], v["B_log_loss"], v["C_brier"], v["B_brier"], v["cell_ci95"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest ml pipeline -q`
Expected: PASS (all green, including the 5 new test files).

```bash
git add pipeline/run_club_xg_validation.py pipeline/run_club_xg_validation_test.py
git commit -m "feat(club-xg): A/B/C walk-forward harness + pre-registered verdict"
```

---

## Task 7: Run the validation & record the verdict

**Files:** none (an execution + documentation step).

- [ ] **Step 1: Backfill + run** (spends Pro quota; resumable via the disk cache)

Run: `PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_club_xg_validation --api-key "$API_FOOTBALL_API_KEY"`
Expected: per-cell `C-B log_loss` lines and a final `VERDICT: PASS`/`FAIL`.

- [ ] **Step 2: Record the outcome** in the spec's status line (append `— Validation: PASS`/`FAIL (<date>)` to `docs/superpowers/specs/2026-07-04-club-xg-method-validation-design.md`), and **stop for a human decision**:
  - **PASS** → the WC xG-offset spec is unblocked; its implementation plan can be written next.
  - **FAIL** → the WC feature is shelved. If it was a `B<A` but `C≈B` result, note that goals-offsets remain a *separate* candidate that must clear `experiment_model_eval`, not this bar.

- [ ] **Step 3: Commit the recorded verdict**

```bash
git add docs/superpowers/specs/2026-07-04-club-xg-method-validation-design.md
git commit -m "docs(club-xg): record validation verdict"
```

---

## Self-Review (completed)

- **Spec coverage:** Purpose→Tasks 6-7; same-source constraint→Tasks 1,4; spine-no-join→Task 4; shared method→Tasks 2,3; directional+consistent verdict→Task 6 `verdict`; pre-registered thresholds→Global Constraints + Task 6 constants; depth-probe fork gate→Task 0; offline/no-stop-gate→Global Constraints; clustered bootstrap→Task 5. All covered.
- **Placeholder scan:** none — every code step carries real, runnable code.
- **Type consistency:** `fit_offsets(..., home_goal_key, away_goal_key)` (Task 2) is called with those exact kwargs in Tasks 6; `blend_goals_xg` returns `{id: (atk, def)}` consumed as tuples in `offsets_for_config`; enriched-row keys (`xg_home`/`xg_away`/`pre_home`/`season`) defined in Task 4 match every consumer; `compute_metrics` keys (`log_loss`/`brier`) match `_score`/`walk_forward`/`verdict`.
