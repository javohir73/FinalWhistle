# NRL Match Intelligence — Wave 2 (Team-Stats Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest NRL team-level match statistics and try events behind a pluggable `StatsProvider`, store them in `nrl_match_stats` + `nrl_try_events`, backfill 2024–2026, serve them via `/api/nrl/matches/{id}/stats` and `/api/nrl/teams/{slug}/profile`, and render Scoring Breakdown, Try Timeline, matchup attack/defence tiers, and team-page venue splits.

**Architecture:** A source spike (Task 1) picks the data source and records real fixtures into the repo; every downstream task codes against the spec-frozen `StatsProvider` protocol and those recorded fixtures — never live HTTP in tests. Backend/pipeline/data tasks run first; UI-integration tasks are last and require Wave 1's merge (they append entries to `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` and add self-contained components only).

**Tech Stack:** Python 3.12, `requests`, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, FastAPI, pytest (+ root `conftest.py` `db_session` in-memory SQLite fixture, `monkeypatch` for HTTP), Next.js App Router (server components + client islands, ISR), jest + @testing-library/react.

**Branch:** `feat/nrl-match-intel-w2`, from `origin/main`.

## Global Constraints

(Copied verbatim from the program spec, "Global constraints (every wave, every task)". Every task's requirements implicitly include this section.)

- Isolated worktree; branch from `origin/main`; never commit `frontend/node_modules` (symlink —
  `git reset frontend/node_modules` before commit).
- Midnight theme tokens only — use existing CSS variables/Tailwind classes; no new hex values.
- **No bookmaker links, odds CTAs, or value-vs-odds badges.** Market comparison exists only
  where it already exists (football "Model vs market"). Try-scorer output is probabilities.
- Kickoff times: `Australia/Sydney` with `timeZoneName: "short"`.
- Footer disclaimer stays: analytics and entertainment only.
- Server components + Client islands, ISR like existing NRL pages; all `fetch` fall back with
  `.catch(() => null)` so `npm run build` succeeds without a backend.
- Backend/pipeline: pytest; frontend: jest (worker SIGSEGV under parallel load is a known flake
  — rerun once) + `npm run build` must pass.
- Model version strings come from params loaders (`current_model_version()` pattern), never
  hardcoded in consumers.
- PR per wave; merge order W1 → W2 → W3; each wave independently shippable.

---

## Setup (before Task 1)

The primary checkout is shared — **never work in it directly**. Create the isolated worktree exactly as the spec mandates:

```bash
cd "/Users/macbookpro/Projects/FIFA WC26 Prediction"
git fetch origin
git worktree add /tmp/nrl-match-intel-w2 -b feat/nrl-match-intel-w2 origin/main
cd /tmp/nrl-match-intel-w2
ln -s "/Users/macbookpro/Projects/FIFA WC26 Prediction/frontend/node_modules" frontend/node_modules
cat > frontend/.env.local <<'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
```

Before **every** commit: `git reset frontend/node_modules`. Remove the worktree when the PR is up. All paths below are relative to `/tmp/nrl-match-intel-w2`.

## Codebase orientation (facts you need; verified 2026-07-10)

- **Existing NRL ingest:** `pipeline/sports/nrl_ingest.py`. Conventions to copy: plain `requests` with `headers={"User-Agent": "Mozilla/5.0"}`, `timeout=20.0`; `fetch_*` functions **never raise** (broad `except Exception` → log + return empty); pure `parse_*` functions returning plain data; idempotent upsert keyed on the DB unique constraint; a finished match's data is never clobbered; `argparse` CLI with `--seasons START END` (inclusive); per-unit `try/except + db.rollback()` error boundary in `main()` so one bad unit never aborts the run.
- **Match identity:** the 4-tuple `(sport="nrl", season, round, match_no)` — the `SportMatch` column is literally named `round` (not `round_no`), unique constraint `uq_sport_match_sport_season_round_no`. `SportMatch.id` (int PK) is the `{id}` in all Wave 1/2 API routes.
- **Team identity:** `SportTeam` rows keyed by `(sport, name)`; NRL names are fixturedownload nicknames (`"Knights"`, `"Wests Tigers"`). **No slug column exists anywhere** — Wave 2 derives slugs from names (see Task 9).
- **`nrl-refresh` is a GitHub Actions workflow**, `.github/workflows/nrl-refresh.yml`, NOT a step in `pipeline/run_pipeline.py` (that runner is football-only by design — documented in `docs/RUNBOOK-NRL-LAUNCH.md`). "Add an ingest step to nrl-refresh" means adding a YAML step there (Task 7).
- **Alembic:** `backend/alembic.ini`, versions in `backend/alembic/versions/`. Both header styles exist: `revision: str = "..."` (most files) and bare `revision = "..."` (`b2c3d4e5f6a8_probability_snapshots.py`) — **grep both** when tracing. At plan-writing time the single head is `b3c4d5e6f7a9`. **Wave 1 also adds a migration**, so at execution time you MUST re-check: `cd backend && alembic heads` and chain onto whatever head exists (Task 4).
- **Models:** all in `backend/app/models/__init__.py` (single file). SQLAlchemy 2.0 style, `id: Mapped[int] = mapped_column(primary_key=True)`, explicit named `UniqueConstraint`s, `DateTime(timezone=True), server_default=func.now()` timestamps, FK columns to `sport_matches.id` get `index=True`.
- **NRL API:** all NRL routes live in `backend/app/api/sports.py` (`router = APIRouter(prefix="/api/nrl", tags=["nrl"])`, registered in `backend/app/main.py`). Convention there: raw dict returns (no `response_model=`), 404s as `HTTPException(status_code=404, detail={"code": "...", "message": "..."})` which middleware wraps into `{"error": {code, message}}`. A `_latest_season(db)` helper resolves the default season. GET `/api/...` responses automatically get `Cache-Control: public, max-age=60, stale-while-revalidate=300` from middleware.
- **Pytest:** root `conftest.py` provides `db_session` (in-memory SQLite, `Base.metadata.create_all`). Pipeline tests are colocated `*_test.py` (e.g. `pipeline/sports/nrl_ingest_test.py`); backend API tests live in `backend/tests/test_*.py` and use `app.dependency_overrides[get_db]` + `TestClient`. HTTP is mocked with `monkeypatch.setattr(requests, "get", ...)` and hand-rolled `_Resp` classes — no `responses`/`respx` libs. Recorded fixture files precedent: `pipeline/ingest/testdata/*.json` (football). Run tests from the repo root (`pytest.ini` sets `pythonpath = backend .`).
- **Frontend:** NRL pages under `frontend/app/nrl/` (server components, `export const revalidate = 300`, data via `frontend/lib/api.ts`'s `getServer<T>(path, revalidate)` which returns `null` on 404; client islands fetch through `CLIENT_BASE = "/backend-api"`). Types in `frontend/lib/types.ts`. Theme tokens are semantic Tailwind classes: `glass`, `bg-surface-2`, `text-muted`, `text-foreground`, `bg-win/15 text-lime-deep`, `bg-draw/15 text-amber-ink`, `bg-loss/15 text-loss`, `font-display`, `fade-up` — there is no `midnight-*` literal class. Frontend tests: colocated `*.test.tsx` with `jest.mock("@/lib/api")`.
- **Existing team page:** `frontend/app/nrl/team/[id]/page.tsx` (int id — predates Wave 1 and is NOT a Wave 1 component; Task 12 may edit it).

## Task ordering & the Wave 1 merge gate

Tasks 1–9 are backend/pipeline/data and depend only on `origin/main` as of today. **Tasks 10–12 (UI integration) require Wave 1's PR to be merged** — they append entries to `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (a Wave 1 file) per the spec's `IntelSection` contract, and add self-contained component files only. **No edits to Wave 1 components, ever.** Before starting Task 10: `git fetch origin && git merge origin/main` and verify `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` exists. If it does not, Wave 1 has not merged — stop and wait; do not stub it.

---

### Task 1: Source spike — probe candidate sources, decide, record fixtures

The whole wave keys off this task. You will run a standalone probe script against real candidate sources, apply the decision procedure below, and **record at least 3 real response fixtures into the repo** at `pipeline/sports/testdata/nrl_stats/`. Every later task builds against those recorded fixtures; no test anywhere in this wave may perform live HTTP.

**Files:**
- Create: `pipeline/sports/nrl_stats_spike.py` (committed — it is a documented manual tool, never imported by tests or CI)
- Create: `pipeline/sports/testdata/nrl_stats/SOURCE.md` (decision record + fixture provenance)
- Create: `pipeline/sports/testdata/nrl_stats/draw_2025_r01.json` (recorded fixture 1)
- Create: `pipeline/sports/testdata/nrl_stats/match_2025_r01_a.json` (recorded fixture 2)
- Create: `pipeline/sports/testdata/nrl_stats/match_2025_r01_b.json` (recorded fixture 3)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the recorded fixture files above and the adopted-source decision in `SOURCE.md`. Task 2's parsers and tests read these exact file paths. The fixture set contract: one round-listing document and ≥2 full finished-match stat documents (each containing all nine `TeamMatchStats` fields and try events with minute/player/running score), for matches that exist in the 2025 season of the `sport_matches` table.

**Candidate sources to probe, in order of preference:**

1. **NRL.com match-centre public JSON** — the draw endpoint `https://www.nrl.com/draw/data?competition=111&season={season}&round={round}` (competition 111 = NRL Premiership) and, from each fixture's `matchCentreUrl` path, the match data document (probe both `https://www.nrl.com{matchCentreUrl}data` as JSON and the HTML page's embedded `q-data` attribute on `#vue-match-centre`).
2. **rugbyleagueproject.org** — HTML pages per match (historical scorelines/scorers). Expect it to fail the field-completeness check (no run metres / tackle efficiency), in which case it is only a fallback for try events, which is insufficient alone.
3. **Public GitHub NRL datasets** — check for maintained repos with per-match team stats CSVs covering ≥ 2024–2026 (search github.com for "NRL match statistics dataset" / "NRL data csv"; inspect data recency and licence by hand in a browser).

**Decision procedure (apply in order; adopt the first candidate that passes all three):**

1. **Works:** unauthenticated GET returns 200 with parseable JSON (or HTML with an extractable embedded JSON document) for a 2025 round listing AND for ≥2 finished matches.
2. **Has required fields:** for each probed match you can locate ALL of: tries, conversions, penalties conceded, errors, set restarts, run metres, line breaks, tackles, tackle efficiency — per team — AND a try-event list with minute, scorer name, team, and running score (or enough to reconstruct running score by accumulating events in order).
3. **Tolerable ToS:** fetch the host's `/robots.txt`; the probed paths must not be disallowed. Skim the site ToS for scraping prohibitions. Our access pattern (≤1 request/second, browser UA, weekly refresh + one-off backfill) must be defensible. Record your reading in `SOURCE.md`.

If NO candidate passes: **fall back to a documented CSV/community-dataset import** — the provider in Task 3 becomes `CsvStatsProvider` reading `pipeline/sports/testdata/nrl_stats/*.csv` (and, in production, a configured data directory), with the CSV column schema documented in `SOURCE.md`; your three recorded fixtures are then three real CSV files from the chosen dataset. The `StatsProvider` protocol, payload types, DB tables, endpoints, and UI are **identical either way** — that is the point of the protocol.

- [ ] **Step 1: Write the probe script**

```python
# pipeline/sports/nrl_stats_spike.py
"""MANUAL source spike for NRL team-level match stats (Wave 2, Task 1).

Run by hand; never imported by tests or CI. Probes candidate sources for
team-level match stats + try events, prints what it finds, and (with
--record) saves raw responses into pipeline/sports/testdata/nrl_stats/
as the recorded fixtures every downstream Wave 2 test builds against.

Usage:
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_stats_spike --season 2025 --round 1
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_stats_spike --season 2025 --round 1 --record

Respectful by construction: >= 1s between requests, browser UA, one round.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0"}
TESTDATA = Path(__file__).parent / "testdata" / "nrl_stats"
DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round_no}"
RLP_SEASON_URL = "https://www.rugbyleagueproject.org/seasons/nrl-{season}/results.html"

_last = 0.0


def _get(url: str) -> requests.Response | None:
    """Rate-limited GET (>= 1s between requests). Returns None on any failure."""
    global _last
    wait = 1.0 - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    try:
        resp = requests.get(url, headers=UA, timeout=20)
        print(f"GET {url} -> {resp.status_code} ({len(resp.content)} bytes)")
        return resp
    except Exception as exc:  # noqa: BLE001 - spike tool, report and move on
        print(f"GET {url} FAILED: {exc}")
        return None


def _extract_qdata(html: str) -> dict | None:
    """Pull the embedded q-data JSON out of an NRL.com match-centre page."""
    m = re.search(r'q-data="([^"]*)"', html)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("&quot;", '"'))
    except ValueError:
        return None


def _walk_titles(obj, depth=0, out=None):
    """Print every dict key path containing stat-ish words, to map field names."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _walk_titles(v, depth + 1, out)
            elif isinstance(k, str) and re.search(
                r"tackle|metre|break|error|penalt|restart|tr(y|ies)|conversion|minute|player",
                k, re.I,
            ):
                out.append(f"{'  ' * depth}{k} = {v!r}")
            if isinstance(v, str) and re.search(
                r"tackle|metre|break|error|penalt|restart|tries|conversion",
                v, re.I,
            ):
                out.append(f"{'  ' * depth}{k}: {v!r}")
    elif isinstance(obj, list):
        for item in obj[:20]:
            _walk_titles(item, depth + 1, out)
    return out


def probe_nrl_com(season: int, round_no: int, record: bool) -> None:
    print("\n=== Candidate 1: NRL.com match centre ===")
    robots = _get("https://www.nrl.com/robots.txt")
    if robots is not None:
        print("--- robots.txt (first 40 lines) ---")
        print("\n".join(robots.text.splitlines()[:40]))

    resp = _get(DRAW_URL.format(season=season, round_no=round_no))
    if resp is None or resp.status_code != 200:
        print("NRL.com draw endpoint: FAIL (criterion 1)")
        return
    try:
        draw = resp.json()
    except ValueError:
        print("NRL.com draw endpoint returned non-JSON: FAIL (criterion 1)")
        return
    fixtures = draw.get("fixtures") or draw.get("drawGroups") or []
    print(f"draw JSON top-level keys: {sorted(draw)[:20]}")
    print(f"fixture-ish entries found: {len(fixtures) if isinstance(fixtures, list) else 'nested'}")
    if record:
        TESTDATA.mkdir(parents=True, exist_ok=True)
        path = TESTDATA / f"draw_{season}_r{round_no:02d}.json"
        path.write_text(json.dumps(draw, indent=2))
        print(f"RECORDED {path}")

    # Probe up to two finished matches for the full stats document.
    flat = fixtures if isinstance(fixtures, list) else []
    recorded = 0
    for fx in flat:
        if not isinstance(fx, dict):
            continue
        url_path = fx.get("matchCentreUrl") or (fx.get("match") or {}).get("matchCentreUrl")
        if not url_path:
            continue
        # Variant A: the JSON data document behind the page.
        data_resp = _get(f"https://www.nrl.com{url_path}data")
        doc = None
        if data_resp is not None and data_resp.status_code == 200:
            try:
                doc = data_resp.json()
                print(f"variant A (…/data JSON) OK for {url_path}")
            except ValueError:
                doc = None
        if doc is None:
            # Variant B: embedded q-data in the HTML page.
            page_resp = _get(f"https://www.nrl.com{url_path}")
            if page_resp is not None and page_resp.status_code == 200:
                doc = _extract_qdata(page_resp.text)
                if doc is not None:
                    print(f"variant B (embedded q-data) OK for {url_path}")
        if doc is None:
            continue
        print("--- stat-ish key paths (criterion 2 checklist) ---")
        print("\n".join(_walk_titles(doc)[:80]))
        if record:
            suffix = "a" if recorded == 0 else "b"
            path = TESTDATA / f"match_{season}_r{round_no:02d}_{suffix}.json"
            path.write_text(json.dumps(doc, indent=2))
            print(f"RECORDED {path}")
        recorded += 1
        if recorded >= 2:
            break
    print(f"NRL.com: recorded {recorded} match documents")


def probe_rugbyleagueproject(season: int) -> None:
    print("\n=== Candidate 2: rugbyleagueproject.org ===")
    robots = _get("https://www.rugbyleagueproject.org/robots.txt")
    if robots is not None:
        print("\n".join(robots.text.splitlines()[:20]))
    resp = _get(RLP_SEASON_URL.format(season=season))
    if resp is None or resp.status_code != 200:
        print("rugbyleagueproject: FAIL (criterion 1)")
        return
    has_stats = bool(re.search(r"run metres|tackle", resp.text, re.I))
    print(f"page fetched; team-level stat fields present: {has_stats} "
          "(expected False -> fails criterion 2 as a sole source)")


def probe_github_datasets() -> None:
    print("\n=== Candidate 3: public GitHub datasets (manual) ===")
    print("Inspect these by hand in a browser (recency >= 2024, per-match team stats, licence):")
    print("  https://github.com/search?q=NRL+match+statistics+dataset&type=repositories")
    print("  https://github.com/search?q=NRL+data+csv+try+scorers&type=repositories")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--round", dest="round_no", type=int, default=1)
    ap.add_argument("--record", action="store_true",
                    help="save raw responses into pipeline/sports/testdata/nrl_stats/")
    args = ap.parse_args()
    probe_nrl_com(args.season, args.round_no, args.record)
    probe_rugbyleagueproject(args.season)
    probe_github_datasets()
    print("\nApply the Task 1 decision procedure to the output above; record the "
          "verdict in pipeline/sports/testdata/nrl_stats/SOURCE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe (no recording yet)**

Run: `cd /tmp/nrl-match-intel-w2 && PYTHONPATH=backend:. python -m pipeline.sports.nrl_stats_spike --season 2025 --round 1`

Expected: per-candidate output. For NRL.com you should see `-> 200` on the draw URL, fixture entries found, and a stat-ish key-path dump per match showing candidates for all nine stat fields plus try events. If the draw endpoint 404s or the structure lacks required fields, note it and evaluate candidates 2–3 per the decision procedure.

- [ ] **Step 3: Apply the decision procedure and record fixtures**

Run (assuming a candidate passed): `PYTHONPATH=backend:. python -m pipeline.sports.nrl_stats_spike --season 2025 --round 1 --record`

Expected: `RECORDED pipeline/sports/testdata/nrl_stats/draw_2025_r01.json` plus two `RECORDED … match_2025_r01_a.json` / `…_b.json` lines. Verify: `ls pipeline/sports/testdata/nrl_stats/` shows **at least 3 `.json` files** (CSV fallback: at least 3 real `.csv` files instead, same directory). Open each match fixture and manually confirm criterion 2 (all nine stat fields + try events) — write down the exact key names/spellings you find; Tasks 2–3 need them.

If a fixture is enormous (>1 MB), you may prune list entries that are irrelevant to the nine stat fields and try events (e.g. commentary blobs), but never rename keys or alter structure — note any pruning in `SOURCE.md`.

- [ ] **Step 4: Write the decision record**

```markdown
<!-- pipeline/sports/testdata/nrl_stats/SOURCE.md -->
# NRL team-stats source decision (Wave 2, Task 1 spike)

- **Date probed:** <fill: date you ran the spike>
- **Adopted source:** <fill: e.g. "NRL.com match-centre JSON (draw endpoint + per-match data document)">
- **Decision procedure results:**
  - Works: <fill: HTTP results per candidate>
  - Required fields: <fill: where each of the nine TeamMatchStats fields + try events live — exact key paths>
  - ToS/robots: <fill: robots.txt verdict for probed paths + ToS reading>
- **Rejected candidates & why:** <fill>
- **Fixtures recorded (never edit by hand except documented pruning):**
  - draw_2025_r01.json — <fill: URL fetched, date>
  - match_2025_r01_a.json — <fill: URL, home v away, final score>
  - match_2025_r01_b.json — <fill: URL, home v away, final score>
- **Access policy:** >= 1s between requests, browser UA, weekly nrl-refresh + one-off backfill only.
```

Fill every `<fill>` with real values from Steps 2–3. This file is the provenance record the PR reviewer reads.

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add pipeline/sports/nrl_stats_spike.py pipeline/sports/testdata/nrl_stats/
git commit -m "feat(nrl-stats): source spike + recorded fixtures for team-stats provider"
```

---

### Task 2: StatsProvider protocol, payload types, and pure parsers

Create `pipeline/sports/nrl_stats.py` with the spec-frozen `StatsProvider` protocol, frozen payload dataclasses, and pure parse functions that turn a recorded fixture document into a `MatchStatsPayload`. Parsers are pure (no I/O, no DB) — the `nrl_ingest.parse_row` convention.

**Source-adaptation note (applies to Steps 1–5):** the parser code below targets the NRL.com match-centre shape (default candidate). Two small module constants — `_STAT_TITLES` and the try-event extraction in `_parse_try_events` — encode every source-specific key name. Your first action is to open the recorded fixtures from Task 1 and correct those constants/key lookups to the exact spellings you recorded. If the spike adopted a different source (or the CSV fallback), rewrite ONLY the private `_stat_lookup`/`_parse_try_events` internals against your fixtures — the public signatures, dataclasses, and protocol below are frozen by the spec and MUST NOT change. Test expected values are transcribed by you from the real fixtures.

**Files:**
- Create: `pipeline/sports/nrl_stats.py`
- Create: `pipeline/sports/nrl_stats_test.py`
- Read (from Task 1): `pipeline/sports/testdata/nrl_stats/match_2025_r01_a.json`, `…_b.json`, `draw_2025_r01.json`

**Interfaces:**
- Consumes: recorded fixtures from Task 1.
- Produces (frozen; Tasks 3, 5, 6 and Wave 3 import these exact names from `pipeline.sports.nrl_stats`):
  - `class StatsProvider(Protocol)` with `fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None`, `fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]`, `fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None` (verbatim from spec)
  - `@dataclass(frozen=True) TeamStatsLine(team: str, tries: int, conversions: int, penalties_conceded: int, errors: int, set_restarts: int, run_metres: int, line_breaks: int, tackles: int, tackle_efficiency: float)`
  - `@dataclass(frozen=True) TryEventLine(minute: int, team: str, player: str, score_home: int, score_away: int)`
  - `@dataclass(frozen=True) MatchStatsPayload(home: TeamStatsLine, away: TeamStatsLine, try_events: list[TryEventLine])`
  - `@dataclass(frozen=True) TeamListEntry(team: str, jersey: int, player: str, position: str)` and `@dataclass(frozen=True) LivePayload(status: str, minute: int | None, score_home: int, score_away: int)` — shape-only in W2; Wave 3 implements the fetchers.
  - `parse_match_stats(doc: dict) -> MatchStatsPayload | None`
  - `parse_draw_fixtures(doc: dict) -> list[dict]` — each `{"home": str, "away": str, "match_path": str}`

- [ ] **Step 1: Write the failing tests**

Transcribe `EXPECTED_*` values below from YOUR recorded fixtures (open the JSON, read the real numbers — do not invent them).

```python
# pipeline/sports/nrl_stats_test.py
"""Tests for pipeline/sports/nrl_stats.py — parsers run against the recorded
fixtures from the Task 1 spike (pipeline/sports/testdata/nrl_stats/). No live
HTTP anywhere in this file."""
import json
from pathlib import Path

from pipeline.sports.nrl_stats import (
    MatchStatsPayload,
    TeamStatsLine,
    TryEventLine,
    parse_draw_fixtures,
    parse_match_stats,
)

TESTDATA = Path(__file__).parent / "testdata" / "nrl_stats"


def _load(name: str) -> dict:
    with (TESTDATA / name).open() as f:
        return json.load(f)


# ---- transcribe these from your recorded fixtures (Task 1, Step 3 notes) ----
EXPECTED_HOME_TEAM = "Knights"          # <- exact team string in match_2025_r01_a.json
EXPECTED_AWAY_TEAM = "Cowboys"          # <- exact away team string
EXPECTED_HOME_TRIES = 5                 # <- real value from the fixture
EXPECTED_AWAY_RUN_METRES = 1432         # <- real value from the fixture
EXPECTED_TRY_COUNT = 8                  # <- total try events in the fixture
EXPECTED_FIRST_TRY_MINUTE = 7           # <- minute of the first try event
EXPECTED_FIRST_TRY_PLAYER = "K. Ponga"  # <- exact player string
# -----------------------------------------------------------------------------


def test_parse_match_stats_full_document():
    payload = parse_match_stats(_load("match_2025_r01_a.json"))
    assert isinstance(payload, MatchStatsPayload)
    assert payload.home.team == EXPECTED_HOME_TEAM
    assert payload.away.team == EXPECTED_AWAY_TEAM
    assert payload.home.tries == EXPECTED_HOME_TRIES
    assert payload.away.run_metres == EXPECTED_AWAY_RUN_METRES
    # every one of the nine contract fields is populated with a sane value
    for line in (payload.home, payload.away):
        assert line.tries >= 0
        assert line.conversions >= 0
        assert line.penalties_conceded >= 0
        assert line.errors >= 0
        assert line.set_restarts >= 0
        assert line.run_metres > 0
        assert line.line_breaks >= 0
        assert line.tackles > 0
        assert 0.0 < line.tackle_efficiency <= 100.0


def test_parse_match_stats_try_events_ordered_with_running_score():
    payload = parse_match_stats(_load("match_2025_r01_a.json"))
    events = payload.try_events
    assert len(events) == EXPECTED_TRY_COUNT
    assert events[0].minute == EXPECTED_FIRST_TRY_MINUTE
    assert events[0].player == EXPECTED_FIRST_TRY_PLAYER
    minutes = [e.minute for e in events]
    assert minutes == sorted(minutes)
    for e in events:
        assert isinstance(e, TryEventLine)
        assert e.team in (EXPECTED_HOME_TEAM, EXPECTED_AWAY_TEAM)
        assert e.score_home >= 0 and e.score_away >= 0


def test_parse_match_stats_second_fixture_also_parses():
    payload = parse_match_stats(_load("match_2025_r01_b.json"))
    assert isinstance(payload, MatchStatsPayload)
    assert payload.home.team != payload.away.team


def test_parse_match_stats_returns_none_on_garbage():
    assert parse_match_stats({}) is None
    assert parse_match_stats({"stats": None}) is None


def test_parse_draw_fixtures_lists_round_matches():
    fixtures = parse_draw_fixtures(_load("draw_2025_r01.json"))
    assert len(fixtures) >= 4  # a normal NRL round has 8; never fewer than 4
    for fx in fixtures:
        assert set(fx) == {"home", "away", "match_path"}
        assert fx["home"] and fx["away"] and fx["match_path"]


def test_parse_draw_fixtures_returns_empty_on_garbage():
    assert parse_draw_fixtures({}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'pipeline.sports.nrl_stats'` (collection error counts).

- [ ] **Step 3: Write the module — types, protocol, parsers**

```python
# pipeline/sports/nrl_stats.py
"""NRL team-level match stats + try events (Wave 2).

StatsProvider protocol (frozen program-spec contract; Wave 3 consumes it),
the default provider implementation, pure parsers, idempotent upsert, and
the resumable backfill CLI.

Source: decided by the Task 1 spike — see
pipeline/sports/testdata/nrl_stats/SOURCE.md for provenance and field map.

Mirrors nrl_ingest.py conventions: fetch_* never raises; parse_* are pure;
upsert is idempotent per match; a finished match's recorded stats are
replaced atomically, never merged. Deliberately NOT wired into
pipeline/run_pipeline.py (football-only): runs as its own CLI step in
.github/workflows/nrl-refresh.yml.
"""
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import requests

log = logging.getLogger("pipeline.sports.nrl_stats")

SPORT = "nrl"


# --------------------------------------------------------------------------
# Payload types + StatsProvider protocol (FROZEN cross-wave contract).
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamStatsLine:
    """One team's stat line — field names match the API TeamMatchStats contract."""
    team: str                    # exact SportTeam.name spelling, e.g. "Knights"
    tries: int
    conversions: int
    penalties_conceded: int
    errors: int
    set_restarts: int
    run_metres: int
    line_breaks: int
    tackles: int
    tackle_efficiency: float     # percentage, e.g. 91.3


@dataclass(frozen=True)
class TryEventLine:
    minute: int
    team: str
    player: str
    score_home: int              # running score after this try (+conversion)
    score_away: int


@dataclass(frozen=True)
class MatchStatsPayload:
    home: TeamStatsLine
    away: TeamStatsLine
    try_events: list[TryEventLine] = field(default_factory=list)


@dataclass(frozen=True)
class TeamListEntry:
    """Shape-only in Wave 2; Wave 3's team-lists ingest populates it."""
    team: str
    jersey: int
    player: str
    position: str


@dataclass(frozen=True)
class LivePayload:
    """Shape-only in Wave 2; Wave 3's live layer populates it."""
    status: str                  # "pre" | "live" | "final"
    minute: int | None
    score_home: int
    score_away: int


class StatsProvider(Protocol):
    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None: ...
    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]: ...
    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None: ...


# --------------------------------------------------------------------------
# Pure parsers. ALL source-specific key names live in the two blocks below —
# verify every string against the recorded fixtures (SOURCE.md field map)
# and correct spellings here and nowhere else.
# --------------------------------------------------------------------------

# Stat-row titles as they appear in the source document -> contract field.
_STAT_TITLES: dict[str, str] = {
    "tries": "Tries",
    "conversions": "Conversions",
    "penalties_conceded": "Penalties Conceded",
    "errors": "Errors",
    "set_restarts": "Set Restarts",
    "run_metres": "All Run Metres",
    "line_breaks": "Line Breaks",
    "tackles": "Tackles Made",
    "tackle_efficiency": "Effective Tackle",
}


def _num(value) -> float:
    """Best-effort numeric coercion ('1,432' / '91.3%' / 28 -> float)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _stat_lookup(doc: dict) -> dict[str, tuple[float, float]]:
    """Flatten the source's grouped stat rows into {title: (home, away)}."""
    out: dict[str, tuple[float, float]] = {}
    groups = (doc.get("stats") or {}).get("groups") or []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for stat in group.get("stats") or []:
            if not isinstance(stat, dict):
                continue
            title = stat.get("title")
            if title:
                out[str(title)] = (_num(stat.get("home")), _num(stat.get("away")))
    return out


def _team_names(doc: dict) -> tuple[str, str] | None:
    home = (doc.get("homeTeam") or {}).get("nickName")
    away = (doc.get("awayTeam") or {}).get("nickName")
    if not home or not away:
        return None
    return str(home), str(away)


def _parse_try_events(doc: dict, home: str, away: str) -> list[TryEventLine]:
    """Extract try events sorted by minute, with running score."""
    events: list[TryEventLine] = []
    for entry in doc.get("timeline") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("title") or entry.get("type") or "").lower() != "try":
            continue
        minute = int(_num(entry.get("minutes") if entry.get("minutes") is not None
                          else entry.get("minute")))
        player = str(entry.get("playerName") or entry.get("player") or "").strip()
        team_raw = str(entry.get("teamNickName") or entry.get("team") or "").strip()
        team = team_raw if team_raw in (home, away) else (home if team_raw == "" else team_raw)
        events.append(TryEventLine(
            minute=minute,
            team=team,
            player=player,
            score_home=int(_num(entry.get("homeScore"))),
            score_away=int(_num(entry.get("awayScore"))),
        ))
    events.sort(key=lambda e: e.minute)
    return events


def _stats_line(team: str, lookup: dict[str, tuple[float, float]], side: int) -> TeamStatsLine | None:
    values: dict[str, float] = {}
    for fieldname, title in _STAT_TITLES.items():
        if title not in lookup:
            return None
        values[fieldname] = lookup[title][side]
    return TeamStatsLine(
        team=team,
        tries=int(values["tries"]),
        conversions=int(values["conversions"]),
        penalties_conceded=int(values["penalties_conceded"]),
        errors=int(values["errors"]),
        set_restarts=int(values["set_restarts"]),
        run_metres=int(values["run_metres"]),
        line_breaks=int(values["line_breaks"]),
        tackles=int(values["tackles"]),
        tackle_efficiency=round(values["tackle_efficiency"], 1),
    )


def parse_match_stats(doc: dict) -> MatchStatsPayload | None:
    """Pure: recorded match document -> MatchStatsPayload, or None if the
    document lacks team names or any of the nine contract stat fields."""
    if not isinstance(doc, dict):
        return None
    names = _team_names(doc)
    if names is None:
        return None
    home_name, away_name = names
    lookup = _stat_lookup(doc)
    home = _stats_line(home_name, lookup, side=0)
    away = _stats_line(away_name, lookup, side=1)
    if home is None or away is None:
        return None
    return MatchStatsPayload(
        home=home, away=away,
        try_events=_parse_try_events(doc, home_name, away_name),
    )


def parse_draw_fixtures(doc: dict) -> list[dict]:
    """Pure: round-draw document -> [{"home", "away", "match_path"}] for every
    fixture that has both team names and a match-centre path."""
    if not isinstance(doc, dict):
        return []
    out: list[dict] = []
    for fx in doc.get("fixtures") or []:
        if not isinstance(fx, dict):
            continue
        home = (fx.get("homeTeam") or {}).get("nickName")
        away = (fx.get("awayTeam") or {}).get("nickName")
        path = fx.get("matchCentreUrl")
        if home and away and path:
            out.append({"home": str(home), "away": str(away), "match_path": str(path)})
    return out
```

- [ ] **Step 4: Run tests, fix the source-specific constants until they pass**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: `6 passed`. If a test fails on a missing stat title or key, the fixture's real spelling differs — fix `_STAT_TITLES` / the key names inside `_stat_lookup`, `_team_names`, `_parse_try_events`, `parse_draw_fixtures` to match the fixture (and update SOURCE.md's field map). Never change the dataclasses, the protocol, or public signatures.

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add pipeline/sports/nrl_stats.py pipeline/sports/nrl_stats_test.py pipeline/sports/testdata/nrl_stats/SOURCE.md
git commit -m "feat(nrl-stats): StatsProvider protocol, payload types, fixture-backed parsers"
```

---

### Task 3: Default provider — rate-limited fetch + match resolution

Add the concrete provider class to `pipeline/sports/nrl_stats.py`. It fetches the round listing, resolves `(season, round_no, match_no)` to a source fixture by team names (supplied by a caller-provided lookup, keeping the protocol frozen), fetches the match document, and returns `parse_match_stats(...)`. Built-in throttle: **>= 1 s between any two HTTP requests** (spec backfill requirement). `fetch_*` never raises. Tests use `monkeypatch` + recorded fixtures — no live HTTP.

If Task 1 adopted the CSV fallback: implement `CsvStatsProvider` instead (constructor takes `data_dir: Path`; `fetch_match_stats` reads the documented CSV schema from SOURCE.md and returns the same `MatchStatsPayload`); keep the same class-level docstring discipline, the same never-raises rule, and adapt the tests to read the recorded CSV fixtures. Everything downstream (Tasks 5–12) only touches the `StatsProvider` protocol, so nothing else changes.

**Files:**
- Modify: `pipeline/sports/nrl_stats.py` (append after the parsers)
- Modify: `pipeline/sports/nrl_stats_test.py` (append tests)

**Interfaces:**
- Consumes: `parse_match_stats`, `parse_draw_fixtures` (Task 2).
- Produces (Task 6 and Wave 3 construct this): `NrlComStatsProvider(team_names: Callable[[int, int, int], tuple[str, str] | None] | None = None, min_interval: float = 1.0, timeout: float = 20.0)` — satisfies `StatsProvider`. `team_names(season, round_no, match_no)` returns our DB's `(home_name, away_name)` for that match, or `None`. `fetch_team_list` returns `[]` and `fetch_live` returns `None` in Wave 2 (documented stubs; Wave 3 implements them behind the same protocol).

- [ ] **Step 1: Write the failing tests (append to `pipeline/sports/nrl_stats_test.py`)**

```python
# --- append to pipeline/sports/nrl_stats_test.py ---
import requests  # noqa: E402  (top of file if not already imported)

from pipeline.sports.nrl_stats import NrlComStatsProvider  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def _provider_with_recorded_http(monkeypatch, sleeps: list | None = None):
    """Provider whose HTTP layer serves the recorded fixtures by URL shape."""
    draw = _load("draw_2025_r01.json")
    match_doc = _load("match_2025_r01_a.json")
    fixtures = parse_draw_fixtures(draw)
    target = fixtures[0]
    calls: list[str] = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        assert headers == {"User-Agent": "Mozilla/5.0"}
        if "draw/data" in url:
            return _Resp(draw)
        if target["match_path"] in url:
            return _Resp(match_doc)
        return _Resp({}, status=404)

    monkeypatch.setattr(requests, "get", fake_get)
    if sleeps is not None:
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    lookup = lambda season, rnd, no: (target["home"], target["away"])  # noqa: E731
    return NrlComStatsProvider(team_names=lookup, min_interval=1.0), calls, target


def test_provider_fetches_and_parses_match_stats(monkeypatch):
    provider, calls, target = _provider_with_recorded_http(monkeypatch, sleeps=[])
    payload = provider.fetch_match_stats(2025, 1, 1)
    assert isinstance(payload, MatchStatsPayload)
    assert payload.home.team == target["home"]
    assert len(calls) == 2  # one draw fetch + one match fetch


def test_provider_caches_round_draw_across_matches(monkeypatch):
    provider, calls, target = _provider_with_recorded_http(monkeypatch, sleeps=[])
    provider.fetch_match_stats(2025, 1, 1)
    provider.fetch_match_stats(2025, 1, 1)
    draw_calls = [c for c in calls if "draw/data" in c]
    assert len(draw_calls) == 1  # round listing fetched once, then cached


def test_provider_returns_none_when_teams_unresolvable(monkeypatch):
    provider, _, _ = _provider_with_recorded_http(monkeypatch, sleeps=[])
    provider._team_names = lambda season, rnd, no: ("Nonexistent", "AlsoNot")
    assert provider.fetch_match_stats(2025, 1, 1) is None


def test_provider_never_raises_on_http_error(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(requests, "get", boom)
    provider = NrlComStatsProvider(team_names=lambda *a: ("Knights", "Cowboys"))
    assert provider.fetch_match_stats(2025, 1, 1) is None


def test_provider_throttles_at_least_one_second_between_requests(monkeypatch):
    sleeps: list = []
    provider, calls, _ = _provider_with_recorded_http(monkeypatch, sleeps=sleeps)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)  # freeze the clock
    provider.fetch_match_stats(2025, 1, 1)
    # 2 HTTP calls with a frozen clock -> the 2nd must have slept ~min_interval
    assert len(calls) == 2
    assert any(s >= 0.99 for s in sleeps)


def test_wave3_stubs_are_honest():
    provider = NrlComStatsProvider()
    assert provider.fetch_team_list(2025, 1) == []
    assert provider.fetch_live(2025, 1, 1) is None
```

Also add `import time` to the test file's imports if missing.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: `6 passed` (Task 2) and the 6 new tests FAIL/ERROR with `ImportError: cannot import name 'NrlComStatsProvider'`.

- [ ] **Step 3: Implement the provider (append to `pipeline/sports/nrl_stats.py`)**

```python
# --- append to pipeline/sports/nrl_stats.py ---

# URL shapes verified by the Task 1 spike — see SOURCE.md. If the spike found
# a different working variant (e.g. embedded q-data instead of a /data JSON
# document), adjust _MATCH_DATA_URL / _get_json here only.
_DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round_no}"
_MATCH_DATA_URL = "https://www.nrl.com{path}data"


class NrlComStatsProvider:
    """Default StatsProvider against the source adopted by the Task 1 spike.

    - team_names(season, round_no, match_no) -> (home, away) | None resolves
      OUR match identity to team names so the right source fixture is picked
      (the source has no notion of fixturedownload's match_no). The backfill
      CLI supplies a DB-backed lookup; tests supply a lambda.
    - Throttled: >= min_interval seconds between any two HTTP requests.
    - fetch_* NEVER raises (nrl_ingest convention): any failure -> None/[].
    """

    def __init__(
        self,
        team_names: Callable[[int, int, int], tuple[str, str] | None] | None = None,
        min_interval: float = 1.0,
        timeout: float = 20.0,
    ) -> None:
        self._team_names = team_names or (lambda season, round_no, match_no: None)
        self._min_interval = min_interval
        self._timeout = timeout
        self._last_request = 0.0
        self._draw_cache: dict[tuple[int, int], list[dict]] = {}

    # -- plumbing ----------------------------------------------------------

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get_json(self, url: str):
        self._throttle()
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                                timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - a feed hiccup must never abort a run
            log.warning("nrl_stats GET %s failed: %s", url, exc)
            return None

    def _round_fixtures(self, season: int, round_no: int) -> list[dict]:
        key = (season, round_no)
        if key not in self._draw_cache:
            doc = self._get_json(_DRAW_URL.format(season=season, round_no=round_no))
            self._draw_cache[key] = parse_draw_fixtures(doc) if isinstance(doc, dict) else []
        return self._draw_cache[key]

    # -- StatsProvider -----------------------------------------------------

    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None:
        names = self._team_names(season, round_no, match_no)
        if names is None:
            log.warning("nrl_stats: no team names for %s r%s m%s", season, round_no, match_no)
            return None
        home, away = names
        fixture = next(
            (fx for fx in self._round_fixtures(season, round_no)
             if fx["home"] == home and fx["away"] == away),
            None,
        )
        if fixture is None:
            log.warning("nrl_stats: no source fixture for %s v %s (%s r%s)",
                        home, away, season, round_no)
            return None
        doc = self._get_json(_MATCH_DATA_URL.format(path=fixture["match_path"]))
        if not isinstance(doc, dict):
            return None
        return parse_match_stats(doc)

    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]:
        return []  # Wave 3 implements (team-lists ingest); honest empty until then

    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None:
        return None  # Wave 3 implements (live layer); honest None until then
```

- [ ] **Step 4: Run the full module test file**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add pipeline/sports/nrl_stats.py pipeline/sports/nrl_stats_test.py
git commit -m "feat(nrl-stats): rate-limited default StatsProvider with recorded-fixture tests"
```

---

### Task 4: ORM models + alembic migration for `nrl_match_stats` and `nrl_try_events`

Table names are frozen by the spec (`nrl_match_stats`, `nrl_try_events`) — a deliberate, documented deviation from the repo's `sport_*` naming: the column set is rugby-league-specific and Wave 3 builds on these exact names.

**Files:**
- Modify: `backend/app/models/__init__.py` (append at end of file, after `ProbabilitySnapshot`)
- Create: `backend/alembic/versions/d6e7f8a9b0c1_add_nrl_stats_tables.py`
- Create: `backend/tests/test_nrl_stats_schema.py`

**Interfaces:**
- Consumes: `Base`, `SportMatch` (existing).
- Produces (Tasks 5, 6, 8, 9 import from `app.models`):
  - `NrlMatchStat` — `__tablename__ = "nrl_match_stats"`; columns `id`, `match_id` (FK `sport_matches.id`, indexed), `team: str`, `tries: int`, `conversions: int`, `penalties_conceded: int`, `errors: int`, `set_restarts: int`, `run_metres: int`, `line_breaks: int`, `tackles: int`, `tackle_efficiency: float`, `created_at`; unique `(match_id, team)`.
  - `NrlTryEvent` — `__tablename__ = "nrl_try_events"`; columns `id`, `match_id` (FK `sport_matches.id`, indexed), `team: str`, `player: str`, `minute: int`, `score_home: int`, `score_away: int`.

- [ ] **Step 1: Write the failing schema test**

```python
# backend/tests/test_nrl_stats_schema.py
"""Wave 2 schema: the ORM metadata builds nrl_match_stats + nrl_try_events
(same pattern as backend/tests/test_schema.py)."""
from sqlalchemy import create_engine, inspect

from app.db import Base
import app.models  # noqa: F401  (registers all models on Base.metadata)


def test_nrl_stats_tables_build():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"nrl_match_stats", "nrl_try_events"}.issubset(tables)

    stat_cols = {c["name"] for c in inspector.get_columns("nrl_match_stats")}
    assert {"id", "match_id", "team", "tries", "conversions", "penalties_conceded",
            "errors", "set_restarts", "run_metres", "line_breaks", "tackles",
            "tackle_efficiency", "created_at"} <= stat_cols

    try_cols = {c["name"] for c in inspector.get_columns("nrl_try_events")}
    assert {"id", "match_id", "team", "player", "minute",
            "score_home", "score_away"} <= try_cols

    uqs = {u["name"] for u in inspector.get_unique_constraints("nrl_match_stats")}
    assert "uq_nrl_match_stats_match_team" in uqs
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /tmp/nrl-match-intel-w2 && pytest backend/tests/test_nrl_stats_schema.py`
Expected: FAIL — `AssertionError` on the `issubset` check (tables don't exist yet).

- [ ] **Step 3: Append the models**

Append to the END of `backend/app/models/__init__.py`:

```python
# --- Wave 2: NRL team-stats layer -------------------------------------------
# Table names nrl_match_stats / nrl_try_events are frozen by the match-intel
# program spec (Wave 3 builds on them). They deviate from the sport_* naming
# deliberately: the column set is rugby-league-specific.


class NrlMatchStat(Base):
    """One team's stat line for one finished NRL match (two rows per match)."""

    __tablename__ = "nrl_match_stats"
    __table_args__ = (
        UniqueConstraint("match_id", "team", name="uq_nrl_match_stats_match_team"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    tries: Mapped[int] = mapped_column(Integer)
    conversions: Mapped[int] = mapped_column(Integer)
    penalties_conceded: Mapped[int] = mapped_column(Integer)
    errors: Mapped[int] = mapped_column(Integer)
    set_restarts: Mapped[int] = mapped_column(Integer)
    run_metres: Mapped[int] = mapped_column(Integer)
    line_breaks: Mapped[int] = mapped_column(Integer)
    tackles: Mapped[int] = mapped_column(Integer)
    tackle_efficiency: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NrlTryEvent(Base):
    """One try event with running score (Wave 3's scorer model trains on these)."""

    __tablename__ = "nrl_try_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    player: Mapped[str] = mapped_column(String(120))
    minute: Mapped[int] = mapped_column(Integer)
    score_home: Mapped[int] = mapped_column(Integer)
    score_away: Mapped[int] = mapped_column(Integer)
```

(All names used — `UniqueConstraint`, `ForeignKey`, `String`, `Integer`, `Float`, `DateTime`, `func`, `Mapped`, `mapped_column`, `datetime` — are already imported at the top of this file.)

- [ ] **Step 4: Determine the real migration head, then write the migration**

**Wave 1 merges before Wave 2 and adds its own migration — the head at plan-writing time (`b3c4d5e6f7a9`) is probably stale.** Determine the actual head now:

Run: `cd /tmp/nrl-match-intel-w2/backend && alembic heads`
Expected output shape: `<revision_id> (head)` — exactly ONE head. If two heads appear, stop: `git fetch origin && git merge origin/main`, re-run, and if still ambiguous escalate to the human before writing the migration. (Remember when grepping migrations by hand: both `revision = "..."` and `revision: str = "..."` styles exist in this repo.)

Use the printed head as `down_revision` below (the value shown is the plan-time head; **replace it with the `alembic heads` output**):

```python
# backend/alembic/versions/d6e7f8a9b0c1_add_nrl_stats_tables.py
"""add nrl_match_stats + nrl_try_events (Wave 2 team-stats layer)

Revision ID: d6e7f8a9b0c1
Revises: b3c4d5e6f7a9
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "b3c4d5e6f7a9"  # <- REPLACE with `alembic heads` output at execution time
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nrl_match_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False),
        sa.Column("conversions", sa.Integer(), nullable=False),
        sa.Column("penalties_conceded", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("set_restarts", sa.Integer(), nullable=False),
        sa.Column("run_metres", sa.Integer(), nullable=False),
        sa.Column("line_breaks", sa.Integer(), nullable=False),
        sa.Column("tackles", sa.Integer(), nullable=False),
        sa.Column("tackle_efficiency", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("match_id", "team", name="uq_nrl_match_stats_match_team"),
    )
    op.create_index("ix_nrl_match_stats_match_id", "nrl_match_stats", ["match_id"])

    op.create_table(
        "nrl_try_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("player", sa.String(length=120), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("score_home", sa.Integer(), nullable=False),
        sa.Column("score_away", sa.Integer(), nullable=False),
    )
    op.create_index("ix_nrl_try_events_match_id", "nrl_try_events", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_nrl_try_events_match_id", table_name="nrl_try_events")
    op.drop_table("nrl_try_events")
    op.drop_index("ix_nrl_match_stats_match_id", table_name="nrl_match_stats")
    op.drop_table("nrl_match_stats")
```

If `d6e7f8a9b0c1` collides with a revision id Wave 1 introduced (check: `grep -rn "d6e7f8a9b0c1" backend/alembic/versions/`), pick another unused mnemonic id (e.g. `e8f9a0b1c2d3`) and rename the file and both header fields consistently.

- [ ] **Step 5: Verify schema test passes and the migration chain is sound**

Run: `cd /tmp/nrl-match-intel-w2 && pytest backend/tests/test_nrl_stats_schema.py`
Expected: `1 passed`.

Run: `cd /tmp/nrl-match-intel-w2/backend && alembic heads`
Expected: exactly one head: `d6e7f8a9b0c1 (head)`.

- [ ] **Step 6: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add backend/app/models/__init__.py backend/alembic/versions/d6e7f8a9b0c1_add_nrl_stats_tables.py backend/tests/test_nrl_stats_schema.py
git commit -m "feat(nrl-stats): nrl_match_stats + nrl_try_events models and migration"
```

---

### Task 5: Idempotent upsert layer

`upsert_match_stats(db, match, payload)` — atomic replace-per-match into both tables. Only finished matches get stats; re-running is safe (delete-then-insert inside one transaction — try events have no natural unique key, so replace-all is the correct idempotency strategy).

**Files:**
- Modify: `pipeline/sports/nrl_stats.py` (append)
- Modify: `pipeline/sports/nrl_stats_test.py` (append)

**Interfaces:**
- Consumes: `MatchStatsPayload` (Task 2), `NrlMatchStat`/`NrlTryEvent` (Task 4), `SportMatch` (existing).
- Produces (Task 6 calls this): `upsert_match_stats(db: Session, match: SportMatch, payload: MatchStatsPayload) -> dict` returning `{"stats_rows": int, "try_events": int}`; raises `ValueError` if `match.status != "finished"`.

- [ ] **Step 1: Write the failing tests (append to `pipeline/sports/nrl_stats_test.py`)**

```python
# --- append to pipeline/sports/nrl_stats_test.py ---
import pytest  # noqa: E402  (top of file if not already imported)
from datetime import datetime, timezone  # noqa: E402

from app.models import NrlMatchStat, NrlTryEvent, SportMatch, SportTeam  # noqa: E402
from pipeline.sports.nrl_stats import upsert_match_stats  # noqa: E402


def _mk_match(db, status="finished") -> SportMatch:
    home = SportTeam(sport="nrl", name="Knights")
    away = SportTeam(sport="nrl", name="Cowboys")
    db.add_all([home, away])
    db.flush()
    match = SportMatch(
        sport="nrl", season=2025, round=1, match_no=1,
        kickoff_utc=datetime(2025, 3, 6, 9, 0, tzinfo=timezone.utc),
        venue="McDonald Jones Stadium",
        home_team_id=home.id, away_team_id=away.id,
        score_home=28, score_away=18, status=status,
    )
    db.add(match)
    db.commit()
    return match


def _payload() -> MatchStatsPayload:
    return MatchStatsPayload(
        home=TeamStatsLine(team="Knights", tries=5, conversions=4,
                           penalties_conceded=6, errors=8, set_restarts=4,
                           run_metres=1650, line_breaks=6, tackles=310,
                           tackle_efficiency=91.3),
        away=TeamStatsLine(team="Cowboys", tries=3, conversions=3,
                           penalties_conceded=8, errors=11, set_restarts=6,
                           run_metres=1432, line_breaks=3, tackles=345,
                           tackle_efficiency=88.7),
        try_events=[
            TryEventLine(minute=7, team="Knights", player="K. Ponga",
                         score_home=6, score_away=0),
            TryEventLine(minute=23, team="Cowboys", player="S. Drinkwater",
                         score_home=6, score_away=6),
        ],
    )


def test_upsert_writes_two_stat_rows_and_events(db_session):
    match = _mk_match(db_session)
    counts = upsert_match_stats(db_session, match, _payload())
    assert counts == {"stats_rows": 2, "try_events": 2}
    rows = db_session.query(NrlMatchStat).filter_by(match_id=match.id).all()
    assert {r.team for r in rows} == {"Knights", "Cowboys"}
    knights = next(r for r in rows if r.team == "Knights")
    assert knights.run_metres == 1650
    assert knights.tackle_efficiency == 91.3
    events = (db_session.query(NrlTryEvent).filter_by(match_id=match.id)
              .order_by(NrlTryEvent.minute).all())
    assert [e.player for e in events] == ["K. Ponga", "S. Drinkwater"]
    assert events[1].score_away == 6


def test_upsert_is_idempotent_replace(db_session):
    match = _mk_match(db_session)
    upsert_match_stats(db_session, match, _payload())
    upsert_match_stats(db_session, match, _payload())  # second run: replace, not duplicate
    assert db_session.query(NrlMatchStat).filter_by(match_id=match.id).count() == 2
    assert db_session.query(NrlTryEvent).filter_by(match_id=match.id).count() == 2


def test_upsert_rejects_unfinished_match(db_session):
    match = _mk_match(db_session, status="scheduled")
    with pytest.raises(ValueError):
        upsert_match_stats(db_session, match, _payload())
    assert db_session.query(NrlMatchStat).count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: previous 12 pass; the 3 new tests ERROR with `ImportError: cannot import name 'upsert_match_stats'`.

- [ ] **Step 3: Implement (append to `pipeline/sports/nrl_stats.py`)**

```python
# --- append to pipeline/sports/nrl_stats.py ---
from sqlalchemy.orm import Session  # (place with the other imports at top of file)

from app.models import NrlMatchStat, NrlTryEvent, SportMatch, SportTeam  # (top of file)


def upsert_match_stats(db: Session, match: SportMatch, payload: MatchStatsPayload) -> dict:
    """Atomically replace this match's rows in both stats tables.

    Idempotent: delete-then-insert per match_id in one transaction (try
    events have no natural unique key, so replace-all is the idempotency
    strategy). Only finished matches may carry stats — stats for a live
    match would go stale silently.
    """
    if match.status != "finished":
        raise ValueError(f"match {match.id} is not finished (status={match.status!r})")

    db.query(NrlTryEvent).filter_by(match_id=match.id).delete()
    db.query(NrlMatchStat).filter_by(match_id=match.id).delete()

    for line in (payload.home, payload.away):
        db.add(NrlMatchStat(
            match_id=match.id,
            team=line.team,
            tries=line.tries,
            conversions=line.conversions,
            penalties_conceded=line.penalties_conceded,
            errors=line.errors,
            set_restarts=line.set_restarts,
            run_metres=line.run_metres,
            line_breaks=line.line_breaks,
            tackles=line.tackles,
            tackle_efficiency=line.tackle_efficiency,
        ))
    for ev in payload.try_events:
        db.add(NrlTryEvent(
            match_id=match.id,
            team=ev.team,
            player=ev.player,
            minute=ev.minute,
            score_home=ev.score_home,
            score_away=ev.score_away,
        ))
    db.commit()
    return {"stats_rows": 2, "try_events": len(payload.try_events)}
```

- [ ] **Step 4: Run tests**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: `15 passed`.

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add pipeline/sports/nrl_stats.py pipeline/sports/nrl_stats_test.py
git commit -m "feat(nrl-stats): idempotent replace-per-match upsert"
```

---

### Task 6: Resumable, rate-limited backfill CLI

`python -m pipeline.sports.nrl_stats --seasons 2024 2026` — same CLI shape as `nrl_ingest`. Iterates finished NRL matches in the season range, **skips matches that already have stats rows (resumable)**, fetches via the provider (whose built-in throttle guarantees >= 1 s between requests), upserts, and never lets one bad match abort the run. **Backfill scope: seasons 2024–2026 minimum.**

**Files:**
- Modify: `pipeline/sports/nrl_stats.py` (append `backfill_stats`, `_db_team_names`, `main`)
- Modify: `pipeline/sports/nrl_stats_test.py` (append)

**Interfaces:**
- Consumes: `StatsProvider` (Task 2), `NrlComStatsProvider` (Task 3), `upsert_match_stats` (Task 5).
- Produces: `backfill_stats(db: Session, provider: StatsProvider, start: int, end: int) -> dict` returning `{"fetched": int, "skipped_existing": int, "missing": int, "failed": int}`; `main() -> int` CLI with `--seasons START END`. Task 7's workflow step runs this module.

- [ ] **Step 1: Write the failing tests (append to `pipeline/sports/nrl_stats_test.py`)**

```python
# --- append to pipeline/sports/nrl_stats_test.py ---
import sys  # noqa: E402  (top of file if not already imported)

import app.db  # noqa: E402
import pipeline.sports.nrl_stats as nrl_stats  # noqa: E402
from pipeline.sports.nrl_stats import backfill_stats  # noqa: E402


class _FakeProvider:
    """In-memory StatsProvider — proves consumers only touch the protocol."""

    def __init__(self, payloads: dict):
        self.payloads = payloads          # {(season, round, match_no): payload|None}
        self.calls: list[tuple] = []

    def fetch_match_stats(self, season, round_no, match_no):
        self.calls.append((season, round_no, match_no))
        return self.payloads.get((season, round_no, match_no))

    def fetch_team_list(self, season, round_no):
        return []

    def fetch_live(self, season, round_no, match_no):
        return None


def test_backfill_ingests_finished_matches_only(db_session):
    finished = _mk_match(db_session)                     # 2025 r1 m1, finished
    scheduled = SportMatch(sport="nrl", season=2025, round=2, match_no=1,
                           status="scheduled")
    db_session.add(scheduled)
    db_session.commit()
    provider = _FakeProvider({(2025, 1, 1): _payload()})
    summary = backfill_stats(db_session, provider, 2024, 2026)
    assert summary == {"fetched": 1, "skipped_existing": 0, "missing": 0, "failed": 0}
    assert provider.calls == [(2025, 1, 1)]              # scheduled match never fetched
    assert db_session.query(NrlMatchStat).filter_by(match_id=finished.id).count() == 2


def test_backfill_resumes_by_skipping_already_ingested(db_session):
    match = _mk_match(db_session)
    upsert_match_stats(db_session, match, _payload())    # simulate a prior run
    provider = _FakeProvider({(2025, 1, 1): _payload()})
    summary = backfill_stats(db_session, provider, 2024, 2026)
    assert summary["skipped_existing"] == 1
    assert summary["fetched"] == 0
    assert provider.calls == []                          # resumable: zero re-fetches


def test_backfill_counts_missing_and_continues(db_session):
    _mk_match(db_session)
    provider = _FakeProvider({})                         # source has nothing
    summary = backfill_stats(db_session, provider, 2024, 2026)
    assert summary == {"fetched": 0, "skipped_existing": 0, "missing": 1, "failed": 0}


def test_backfill_one_bad_match_does_not_abort(db_session):
    m1 = _mk_match(db_session)                           # 2025 r1 m1
    home = db_session.query(SportTeam).filter_by(name="Knights").one()
    away = db_session.query(SportTeam).filter_by(name="Cowboys").one()
    m2 = SportMatch(sport="nrl", season=2025, round=1, match_no=2,
                    home_team_id=away.id, away_team_id=home.id,
                    score_home=10, score_away=12, status="finished")
    db_session.add(m2)
    db_session.commit()

    class _Exploding(_FakeProvider):
        def fetch_match_stats(self, season, round_no, match_no):
            if match_no == 1:
                raise RuntimeError("boom")
            return _payload()

    summary = backfill_stats(db_session, _Exploding({}), 2024, 2026)
    assert summary["failed"] == 1
    assert summary["fetched"] == 1
    assert db_session.query(NrlMatchStat).filter_by(match_id=m2.id).count() == 2
    assert db_session.query(NrlMatchStat).filter_by(match_id=m1.id).count() == 0


def test_main_runs_backfill_over_season_range(monkeypatch, db_session):
    _mk_match(db_session)
    db_session.close = lambda: None  # the fixture owns teardown, not main()
    monkeypatch.setattr(app.db, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(nrl_stats, "NrlComStatsProvider",
                        lambda team_names=None, **kw: _FakeProvider({(2025, 1, 1): _payload()}))
    monkeypatch.setattr(sys, "argv", ["nrl_stats.py", "--seasons", "2024", "2026"])
    rc = nrl_stats.main()
    assert rc == 0
    assert db_session.query(NrlMatchStat).count() == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: previous 15 pass; the 5 new tests ERROR with `ImportError: cannot import name 'backfill_stats'`.

- [ ] **Step 3: Implement backfill + CLI (append to `pipeline/sports/nrl_stats.py`)**

```python
# --- append to pipeline/sports/nrl_stats.py ---

def _db_team_names(db: Session) -> Callable[[int, int, int], tuple[str, str] | None]:
    """team_names lookup for NrlComStatsProvider, backed by our sport_matches."""
    def lookup(season: int, round_no: int, match_no: int) -> tuple[str, str] | None:
        match = (
            db.query(SportMatch)
            .filter_by(sport=SPORT, season=season, round=round_no, match_no=match_no)
            .one_or_none()
        )
        if match is None or match.home_team_id is None or match.away_team_id is None:
            return None
        names = dict(
            db.query(SportTeam.id, SportTeam.name)
            .filter(SportTeam.id.in_([match.home_team_id, match.away_team_id]))
            .all()
        )
        home = names.get(match.home_team_id)
        away = names.get(match.away_team_id)
        if home is None or away is None:
            return None
        return home, away
    return lookup


def backfill_stats(db: Session, provider: StatsProvider, start: int, end: int) -> dict:
    """Backfill team stats for finished NRL matches, seasons start..end inclusive.

    Resumable: matches that already have nrl_match_stats rows are skipped
    before any fetch happens, so re-runs cost zero requests for done work.
    Rate limiting lives in the provider (>= 1s between requests).
    One bad match never aborts the run (rollback + continue).
    """
    summary = {"fetched": 0, "skipped_existing": 0, "missing": 0, "failed": 0}
    done_ids = {mid for (mid,) in db.query(NrlMatchStat.match_id).distinct().all()}
    matches = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT,
            SportMatch.season >= start,
            SportMatch.season <= end,
            SportMatch.status == "finished",
        )
        .order_by(SportMatch.season, SportMatch.round, SportMatch.match_no)
        .all()
    )
    for match in matches:
        if match.id in done_ids:
            summary["skipped_existing"] += 1
            continue
        try:
            payload = provider.fetch_match_stats(match.season, match.round, match.match_no)
        except Exception as exc:  # noqa: BLE001 - one bad match must never abort the backfill
            log.warning("nrl_stats: fetch failed for match %s (%s r%s m%s): %s",
                        match.id, match.season, match.round, match.match_no, exc)
            summary["failed"] += 1
            continue
        if payload is None:
            summary["missing"] += 1
            continue
        try:
            upsert_match_stats(db, match, payload)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.warning("nrl_stats: upsert failed for match %s: %s", match.id, exc)
            summary["failed"] += 1
            continue
        summary["fetched"] += 1
    log.info("nrl_stats backfill %s-%s: %s", start, end, summary)
    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--seasons", nargs=2, type=int, required=True, metavar=("START", "END"),
        help="inclusive season range to backfill, e.g. --seasons 2024 2026",
    )
    args = ap.parse_args()
    start, end = args.seasons

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider = NrlComStatsProvider(team_names=_db_team_names(db))
        backfill_stats(db, provider, start, end)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full pipeline test file, then the whole backend+pipeline suite**

Run: `cd /tmp/nrl-match-intel-w2 && pytest pipeline/sports/nrl_stats_test.py`
Expected: `20 passed`.

Run: `cd /tmp/nrl-match-intel-w2 && pytest`
Expected: full suite passes (no regressions in existing `nrl_ingest`/backend tests).

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add pipeline/sports/nrl_stats.py pipeline/sports/nrl_stats_test.py
git commit -m "feat(nrl-stats): resumable rate-limited backfill CLI (--seasons 2024 2026)"
```

---

### Task 7: Wire the stats step into the nrl-refresh workflow

`nrl-refresh` is a GitHub Actions workflow (`.github/workflows/nrl-refresh.yml`), not a `run_pipeline.py` step — NRL modules are deliberately separate from the football pipeline (documented in `docs/RUNBOOK-NRL-LAUNCH.md`). Add the stats step after ingest (stats need the match rows ingest creates/updates) and before predictions. Because `backfill_stats` is resumable, the weekly run only fetches newly finished matches.

**Files:**
- Modify: `.github/workflows/nrl-refresh.yml` (insert one step between the "Ingest NRL seasons" step and the "Generate frozen shadow predictions" step)
- Modify: `docs/RUNBOOK-NRL-LAUNCH.md` (append one line to the module list noting `pipeline/sports/nrl_stats.py` and its workflow step)

**Interfaces:**
- Consumes: the Task 6 CLI (`python -m pipeline.sports.nrl_stats --seasons 2024 2026`).
- Produces: fresh `nrl_match_stats`/`nrl_try_events` rows on every scheduled run, which Tasks 8–9 serve.

- [ ] **Step 1: Insert the workflow step**

In `.github/workflows/nrl-refresh.yml`, directly after the `Ingest NRL seasons (idempotent)` step and before `Generate frozen shadow predictions + grade finished matches`, insert (matching the existing steps' exact `env:`/`run:` shape):

```yaml
      - name: Ingest NRL team stats + try events (idempotent, resumable)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.sports.nrl_stats --seasons 2024 2026
```

- [ ] **Step 2: Validate the YAML parses**

Run: `cd /tmp/nrl-match-intel-w2 && python -c "import yaml; yaml.safe_load(open('.github/workflows/nrl-refresh.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 3: Append the runbook line**

In `docs/RUNBOOK-NRL-LAUNCH.md`, in the section that lists the NRL modules/workflow steps (the one describing `nrl_ingest`/`nrl_predict`), append:

```markdown
- `pipeline/sports/nrl_stats.py` — team-level match stats + try events (StatsProvider;
  source per `pipeline/sports/testdata/nrl_stats/SOURCE.md`). Runs in `nrl-refresh` after
  ingest: `python -m pipeline.sports.nrl_stats --seasons 2024 2026` (resumable — skips
  matches that already have stats; >= 1s between requests). Not wired into the football
  daily pipeline by design.
```

- [ ] **Step 4: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add .github/workflows/nrl-refresh.yml docs/RUNBOOK-NRL-LAUNCH.md
git commit -m "feat(nrl-stats): nrl-refresh workflow step for team-stats ingest"
```

---

### Task 8: `GET /api/nrl/matches/{id}/stats` endpoint

Spec contract (frozen): `→ { home: TeamMatchStats, away: TeamMatchStats, try_timeline: TryEvent[] }` with `TeamMatchStats = { tries, conversions, penalties_conceded, errors, set_restarts, run_metres, line_breaks, tackles, tackle_efficiency }` and `TryEvent = { minute, team, player, score_home, score_away }`. `{id}` is `SportMatch.id` (same id as Wave 1's `GET /api/nrl/matches/{id}`). Follow `sports.py`'s own conventions: raw dict return (no `response_model` — the file deviates from the rest of the app deliberately), `{"code", "message"}` 404 details, plus the additive `disclaimer` key every NRL endpoint carries.

**Files:**
- Modify: `backend/app/api/sports.py` (append the handler; add `NrlMatchStat`, `NrlTryEvent` to the existing `from app.models import ...`)
- Create: `backend/tests/test_nrl_stats_api.py`

**Interfaces:**
- Consumes: `NrlMatchStat`, `NrlTryEvent` (Task 4), rows written by Tasks 5–7.
- Produces: the frozen JSON contract above (Task 10's `getNrlMatchStatsServer` fetches it; Wave 3 reads the same tables).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_nrl_stats_api.py
"""GET /api/nrl/matches/{id}/stats — Wave 2 contract endpoint."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import NrlMatchStat, NrlTryEvent, SportMatch, SportTeam


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _seed(SessionFactory) -> int:
    db = SessionFactory()
    home = SportTeam(sport="nrl", name="Knights")
    away = SportTeam(sport="nrl", name="Cowboys")
    db.add_all([home, away])
    db.flush()
    match = SportMatch(
        sport="nrl", season=2025, round=1, match_no=1,
        kickoff_utc=datetime(2025, 3, 6, 9, 0, tzinfo=timezone.utc),
        venue="McDonald Jones Stadium",
        home_team_id=home.id, away_team_id=away.id,
        score_home=28, score_away=18, status="finished",
    )
    db.add(match)
    db.flush()
    db.add_all([
        NrlMatchStat(match_id=match.id, team="Knights", tries=5, conversions=4,
                     penalties_conceded=6, errors=8, set_restarts=4,
                     run_metres=1650, line_breaks=6, tackles=310,
                     tackle_efficiency=91.3),
        NrlMatchStat(match_id=match.id, team="Cowboys", tries=3, conversions=3,
                     penalties_conceded=8, errors=11, set_restarts=6,
                     run_metres=1432, line_breaks=3, tackles=345,
                     tackle_efficiency=88.7),
        NrlTryEvent(match_id=match.id, team="Cowboys", player="S. Drinkwater",
                    minute=23, score_home=6, score_away=6),
        NrlTryEvent(match_id=match.id, team="Knights", player="K. Ponga",
                    minute=7, score_home=6, score_away=0),
    ])
    match_id = match.id
    db.commit()
    db.close()
    return match_id


def test_stats_returns_contract_shape(client):
    tc, SessionFactory = client
    match_id = _seed(SessionFactory)
    res = tc.get(f"/api/nrl/matches/{match_id}/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["home"] == {
        "tries": 5, "conversions": 4, "penalties_conceded": 6, "errors": 8,
        "set_restarts": 4, "run_metres": 1650, "line_breaks": 6,
        "tackles": 310, "tackle_efficiency": 91.3,
    }
    assert body["away"]["tries"] == 3
    # try_timeline ordered by minute regardless of insert order
    assert [e["minute"] for e in body["try_timeline"]] == [7, 23]
    assert body["try_timeline"][0] == {
        "minute": 7, "team": "Knights", "player": "K. Ponga",
        "score_home": 6, "score_away": 0,
    }


def test_stats_404_when_match_missing(client):
    tc, _ = client
    res = tc.get("/api/nrl/matches/99999/stats")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "match_not_found"


def test_stats_404_when_no_stats_ingested(client):
    tc, SessionFactory = client
    db = SessionFactory()
    match = SportMatch(sport="nrl", season=2025, round=1, match_no=9,
                       status="finished", score_home=10, score_away=8)
    db.add(match)
    db.commit()
    match_id = match.id
    db.close()
    res = tc.get(f"/api/nrl/matches/{match_id}/stats")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "stats_not_available"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /tmp/nrl-match-intel-w2 && pytest backend/tests/test_nrl_stats_api.py`
Expected: 3 FAIL — the two 404-code tests get `http_404` (route doesn't exist yet, FastAPI default) instead of the contract codes, and the shape test gets 404 instead of 200.

- [ ] **Step 3: Implement the handler**

In `backend/app/api/sports.py`: extend the existing models import to include `NrlMatchStat, NrlTryEvent`, then append:

```python
@router.get("/matches/{match_id}/stats")
def nrl_match_stats(match_id: int, db: Session = Depends(get_db)):
    """Team stat lines + try timeline for one finished NRL match (Wave 2
    contract): { home: TeamMatchStats, away: TeamMatchStats,
    try_timeline: TryEvent[] }. 404 stats_not_available until the
    nrl-refresh stats step has ingested this match."""
    match = (
        db.query(SportMatch)
        .filter(SportMatch.id == match_id, SportMatch.sport == "nrl")
        .first()
    )
    if match is None:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found",
            "message": f"No NRL match with id {match_id}",
        })

    rows = db.query(NrlMatchStat).filter(NrlMatchStat.match_id == match_id).all()
    names = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.id.in_([tid for tid in (match.home_team_id, match.away_team_id)
                                  if tid is not None]))
        .all()
    )
    by_team = {r.team: r for r in rows}
    home_row = by_team.get(names.get(match.home_team_id))
    away_row = by_team.get(names.get(match.away_team_id))
    if home_row is None or away_row is None:
        raise HTTPException(status_code=404, detail={
            "code": "stats_not_available",
            "message": f"No team stats ingested for match {match_id}",
        })

    def stat_line(r: NrlMatchStat) -> dict:
        return {
            "tries": r.tries, "conversions": r.conversions,
            "penalties_conceded": r.penalties_conceded, "errors": r.errors,
            "set_restarts": r.set_restarts, "run_metres": r.run_metres,
            "line_breaks": r.line_breaks, "tackles": r.tackles,
            "tackle_efficiency": r.tackle_efficiency,
        }

    events = (
        db.query(NrlTryEvent)
        .filter(NrlTryEvent.match_id == match_id)
        .order_by(NrlTryEvent.minute, NrlTryEvent.id)
        .all()
    )
    return {
        "home": stat_line(home_row),
        "away": stat_line(away_row),
        "try_timeline": [
            {"minute": e.minute, "team": e.team, "player": e.player,
             "score_home": e.score_home, "score_away": e.score_away}
            for e in events
        ],
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

Route-ordering note: FastAPI matches `/matches/{match_id}/stats` independently of the existing `/matches` route (different segment count) — appending at the end of the file is safe.

- [ ] **Step 4: Run tests**

Run: `cd /tmp/nrl-match-intel-w2 && pytest backend/tests/test_nrl_stats_api.py`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add backend/app/api/sports.py backend/tests/test_nrl_stats_api.py
git commit -m "feat(nrl-stats): /api/nrl/matches/{id}/stats endpoint"
```

---

### Task 9: `GET /api/nrl/teams/{slug}/profile` endpoint

Spec contract (frozen): `→ { attack_rank, defence_rank, venue_splits, position_concessions }`. No slug infrastructure exists anywhere in the repo — resolve slugs by slugifying `SportTeam.name` at request time (17 NRL teams; no schema change, no backfill, deterministic). Rankings are computed over the season's finished matches: `attack_rank` = rank by avg points scored (desc), `defence_rank` = rank by avg points conceded (asc, 1 = best defence). `venue_splits` shape (frozen here for Tasks 10–12 and the frontend): `[{ venue, played, wins, draws, losses, avg_for, avg_against }]` sorted by `played` desc then venue. `position_concessions` is `[]` in Wave 2 — computing it needs player→position data, which arrives with Wave 3's team-lists ingest; the key ships now (shape: `[{ position, tries_conceded }]`) so the contract is stable.

**Files:**
- Modify: `backend/app/api/sports.py` (append `_slugify` helper + handler)
- Create: `backend/tests/test_nrl_team_profile_api.py`

**Interfaces:**
- Consumes: `SportTeam`, `SportMatch` (existing), `_latest_season` (existing helper in `sports.py`).
- Produces: the JSON contract above. Slug rule (must match the frontend in Tasks 11–12): lowercase, every run of non-alphanumerics → single `-`, trimmed (`"Wests Tigers"` → `"wests-tigers"`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_nrl_team_profile_api.py
"""GET /api/nrl/teams/{slug}/profile — Wave 2 contract endpoint."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportTeam


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _seed(SessionFactory) -> None:
    """3 teams, 2025: Tigers beat Knights twice at Leichhardt (48-10, 30-12);
    Knights beat Cowboys once away (20-16). Tigers: best attack, best defence."""
    db = SessionFactory()
    tigers = SportTeam(sport="nrl", name="Wests Tigers")
    knights = SportTeam(sport="nrl", name="Knights")
    cowboys = SportTeam(sport="nrl", name="Cowboys")
    db.add_all([tigers, knights, cowboys])
    db.flush()

    def match(no, home, away, sh, sa, venue):
        return SportMatch(
            sport="nrl", season=2025, round=no, match_no=1,
            kickoff_utc=datetime(2025, 3, 6, 9, 0, tzinfo=timezone.utc),
            venue=venue, home_team_id=home.id, away_team_id=away.id,
            score_home=sh, score_away=sa, status="finished",
        )

    db.add_all([
        match(1, tigers, knights, 48, 10, "Leichhardt Oval"),
        match(2, tigers, knights, 30, 12, "Leichhardt Oval"),
        match(3, cowboys, knights, 16, 20, "Queensland Country Bank Stadium"),
    ])
    db.commit()
    db.close()


def test_profile_ranks_and_venue_splits(client):
    tc, SessionFactory = client
    _seed(SessionFactory)
    res = tc.get("/api/nrl/teams/wests-tigers/profile")
    assert res.status_code == 200
    body = res.json()
    assert body["team"]["name"] == "Wests Tigers"
    assert body["team"]["slug"] == "wests-tigers"
    assert body["season"] == 2025
    assert body["attack_rank"] == 1          # 39.0 avg for — best attack
    assert body["defence_rank"] == 1         # 11.0 avg against — best defence
    assert body["position_concessions"] == []  # W2: populated after W3 team lists
    splits = body["venue_splits"]
    assert splits == [{
        "venue": "Leichhardt Oval", "played": 2, "wins": 2, "draws": 0,
        "losses": 0, "avg_for": 39.0, "avg_against": 11.0,
    }]


def test_profile_worst_defence_ranks_last(client):
    tc, SessionFactory = client
    _seed(SessionFactory)
    res = tc.get("/api/nrl/teams/knights/profile")
    assert res.status_code == 200
    body = res.json()
    assert body["defence_rank"] == 3         # 31.3 avg against — worst of 3
    # Knights played at two venues; away split present
    venues = {s["venue"] for s in body["venue_splits"]}
    assert venues == {"Leichhardt Oval", "Queensland Country Bank Stadium"}


def test_profile_404_unknown_slug(client):
    tc, SessionFactory = client
    _seed(SessionFactory)
    res = tc.get("/api/nrl/teams/melbourne-storm/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "team_not_found"


def test_profile_404_when_no_data(client):
    tc, _ = client
    res = tc.get("/api/nrl/teams/knights/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "team_not_found"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /tmp/nrl-match-intel-w2 && pytest backend/tests/test_nrl_team_profile_api.py`
Expected: 4 FAIL (route missing → default `http_404` codes / 404 where 200 expected).

- [ ] **Step 3: Implement the handler (append to `backend/app/api/sports.py`)**

```python
def _slugify(name: str) -> str:
    """URL slug from a team name: 'Wests Tigers' -> 'wests-tigers'.
    Must stay in lockstep with slugify() in frontend/lib/nrlSlug.ts."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@router.get("/teams/{slug}/profile")
def nrl_team_profile(slug: str, season: int | None = None, db: Session = Depends(get_db)):
    """Attack/defence season ranks + venue splits (Wave 2 contract):
    { attack_rank, defence_rank, venue_splits, position_concessions }.
    Slugs derive from SportTeam.name (no slug column exists — 17 teams,
    resolved in-process). position_concessions is [] until Wave 3's
    team-lists ingest supplies player positions."""
    teams = db.query(SportTeam).filter(SportTeam.sport == "nrl").all()
    team = next((t for t in teams if _slugify(t.name) == slug), None)
    if team is None:
        raise HTTPException(status_code=404, detail={
            "code": "team_not_found",
            "message": f"No NRL team with slug {slug!r}",
        })
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    finished = (
        db.query(SportMatch)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season,
                SportMatch.status == "finished",
                SportMatch.score_home.isnot(None), SportMatch.score_away.isnot(None))
        .all()
    )

    # Per-team scoring aggregates over the season's finished matches.
    agg: dict[int, dict] = {}

    def bucket(team_id: int) -> dict:
        return agg.setdefault(team_id, {"played": 0, "for": 0, "against": 0})

    for m in finished:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        h, a = bucket(m.home_team_id), bucket(m.away_team_id)
        h["played"] += 1; a["played"] += 1
        h["for"] += m.score_home; h["against"] += m.score_away
        a["for"] += m.score_away; a["against"] += m.score_home

    def rank_of(key: str, reverse: bool) -> int | None:
        """1-based rank of `team` among teams with played > 0."""
        rows = [(tid, b[key] / b["played"]) for tid, b in agg.items() if b["played"] > 0]
        if not any(tid == team.id for tid, _ in rows):
            return None
        rows.sort(key=lambda r: r[1], reverse=reverse)
        return next(i for i, (tid, _) in enumerate(rows, start=1) if tid == team.id)

    attack_rank = rank_of("for", reverse=True)     # most points scored = rank 1
    defence_rank = rank_of("against", reverse=False)  # fewest conceded = rank 1

    # Venue splits for this team.
    venues: dict[str, dict] = {}
    for m in finished:
        if team.id not in (m.home_team_id, m.away_team_id) or not m.venue:
            continue
        was_home = m.home_team_id == team.id
        score_for = m.score_home if was_home else m.score_away
        score_against = m.score_away if was_home else m.score_home
        v = venues.setdefault(m.venue, {
            "venue": m.venue, "played": 0, "wins": 0, "draws": 0, "losses": 0,
            "for": 0, "against": 0,
        })
        v["played"] += 1
        v["for"] += score_for
        v["against"] += score_against
        if score_for > score_against:
            v["wins"] += 1
        elif score_for < score_against:
            v["losses"] += 1
        else:
            v["draws"] += 1

    venue_splits = [
        {"venue": v["venue"], "played": v["played"], "wins": v["wins"],
         "draws": v["draws"], "losses": v["losses"],
         "avg_for": round(v["for"] / v["played"], 1),
         "avg_against": round(v["against"] / v["played"], 1)}
        for v in sorted(venues.values(), key=lambda v: (-v["played"], v["venue"]))
    ]

    return {
        "team": {"id": team.id, "name": team.name, "slug": slug},
        "season": season,
        "attack_rank": attack_rank,
        "defence_rank": defence_rank,
        "venue_splits": venue_splits,
        "position_concessions": [],  # Wave 3: filled once team lists provide positions
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

Add `import re` to `sports.py`'s imports if not already present. Route-conflict note: the existing `GET /teams/{team_id}` has one path segment after `/teams`, this handler has two (`{slug}/profile`) — no ambiguity.

- [ ] **Step 4: Run tests, then the whole suite**

Run: `cd /tmp/nrl-match-intel-w2 && pytest backend/tests/test_nrl_team_profile_api.py`
Expected: `4 passed`.

Run: `cd /tmp/nrl-match-intel-w2 && pytest`
Expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add backend/app/api/sports.py backend/tests/test_nrl_team_profile_api.py
git commit -m "feat(nrl-stats): /api/nrl/teams/{slug}/profile endpoint"
```

---

## MERGE GATE — before Tasks 10–12

Tasks 10–12 integrate with Wave 1's match-page skeleton. **They must not start until Wave 1's PR is merged to main.**

```bash
cd /tmp/nrl-match-intel-w2
git fetch origin
git merge origin/main
ls frontend/app/nrl/match/[season]/[round]/[no]/sections.ts
```

- If `sections.ts` does not exist → Wave 1 has not merged. STOP. Do not stub it, do not create the directory. Wait (Tasks 1–9 are already committed and the PR can go up as data-layer-only if the program decides so — but the spec scope includes the UI, so the default is to wait).
- Resolve any merge conflicts (likely in `frontend/lib/api.ts`, `frontend/lib/types.ts`, `backend/app/api/sports.py` imports, and the alembic chain — if Wave 1's migration landed after yours was written, re-check `cd backend && alembic heads` and fix your migration's `down_revision` so there is exactly one head).
- Read `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` now. The spec freezes `IntelSection = { id: string; label: string; render: React.ComponentType<IntelSectionProps> }` but `IntelSectionProps` is Wave 1's to define. The components below assume it carries the match id and status as `{ matchId: number | string; status?: string }` — **adapt the two section components' prop destructuring to the real `IntelSectionProps`** (it will at minimum expose the match id; if status isn't in props, keep the components' internal 404-fallback behavior, which already handles unfinished matches). Wave 1 components themselves are never edited.

---

### Task 10: Scoring Breakdown + Try Timeline (stats section)

Presentational components are pure and jest-tested; a thin client island fetches `/api/nrl/matches/{id}/stats` through the `/backend-api` rewrite (existing client-fetch convention) and handles "not available yet" (404 → the section renders a quiet placeholder, since stats exist only for finished, ingested matches). Registration = **append one entry** to `sections.ts` + add self-contained files. Midnight tokens only.

**Files:**
- Modify: `frontend/lib/types.ts` (append)
- Modify: `frontend/lib/api.ts` (append fetchers next to the other NRL fetchers)
- Create: `frontend/components/nrl/ScoringBreakdown.tsx`
- Create: `frontend/components/nrl/TryTimeline.tsx`
- Create: `frontend/components/nrl/ScoringBreakdown.test.tsx`
- Create: `frontend/components/nrl/TryTimeline.test.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/StatsSection.tsx`
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (append ONE array entry — the only Wave 1 file touched, per the spec's extension contract)

**Interfaces:**
- Consumes: Task 8's endpoint; Wave 1's `IntelSection`/`IntelSectionProps` from `sections.ts`.
- Produces (Tasks 11–12 reuse): types `NrlTeamMatchStats`, `NrlTryEventOut`, `NrlMatchStatsResponse`, `NrlStatsProfile`, `NrlVenueSplit` in `frontend/lib/types.ts`; fetchers `getNrlMatchStatsServer(id)`, `getNrlStatsProfileServer(slug)` in `frontend/lib/api.ts`; components `ScoringBreakdown({ stats })`, `TryTimeline({ events, homeTeam, awayTeam })`.

- [ ] **Step 1: Append types to `frontend/lib/types.ts`**

```ts
/** /api/nrl/matches/{id}/stats — Wave 2 team-stats contract. */
export interface NrlTeamMatchStats {
  tries: number;
  conversions: number;
  penalties_conceded: number;
  errors: number;
  set_restarts: number;
  run_metres: number;
  line_breaks: number;
  tackles: number;
  tackle_efficiency: number;
}
export interface NrlTryEventOut {
  minute: number;
  team: string;
  player: string;
  score_home: number;
  score_away: number;
}
export interface NrlMatchStatsResponse {
  home: NrlTeamMatchStats;
  away: NrlTeamMatchStats;
  try_timeline: NrlTryEventOut[];
  disclaimer?: string;
}
/** /api/nrl/teams/{slug}/profile — Wave 2 contract. */
export interface NrlVenueSplit {
  venue: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  avg_for: number;
  avg_against: number;
}
export interface NrlStatsProfile {
  team: { id: number; name: string; slug: string };
  season: number;
  attack_rank: number | null;
  defence_rank: number | null;
  venue_splits: NrlVenueSplit[];
  position_concessions: { position: string; tries_conceded: number }[];
  disclaimer: string;
}
```

- [ ] **Step 2: Append fetchers to `frontend/lib/api.ts`** (next to `getNrlTeamServer`; add `NrlMatchStatsResponse, NrlStatsProfile` to the types import)

```ts
export const getNrlMatchStatsServer = (id: number | string) =>
  getServer<NrlMatchStatsResponse>(`/api/nrl/matches/${id}/stats`, 300);
export const getNrlStatsProfileServer = (slug: string) =>
  getServer<NrlStatsProfile>(`/api/nrl/teams/${slug}/profile`, 300);
```

- [ ] **Step 3: Write the failing component tests**

```tsx
// frontend/components/nrl/ScoringBreakdown.test.tsx
import { render, screen } from "@testing-library/react";
import { ScoringBreakdown } from "./ScoringBreakdown";
import type { NrlMatchStatsResponse } from "@/lib/types";

const stats: NrlMatchStatsResponse = {
  home: { tries: 5, conversions: 4, penalties_conceded: 6, errors: 8,
          set_restarts: 4, run_metres: 1650, line_breaks: 6, tackles: 310,
          tackle_efficiency: 91.3 },
  away: { tries: 3, conversions: 3, penalties_conceded: 8, errors: 11,
          set_restarts: 6, run_metres: 1432, line_breaks: 3, tackles: 345,
          tackle_efficiency: 88.7 },
  try_timeline: [],
};

test("renders one labelled row per contract stat with both values", () => {
  render(<ScoringBreakdown stats={stats} />);
  expect(screen.getByText("Tries")).toBeInTheDocument();
  expect(screen.getByText("Run metres")).toBeInTheDocument();
  expect(screen.getByText("Tackle efficiency")).toBeInTheDocument();
  expect(screen.getByText("1,650")).toBeInTheDocument();  // home run metres
  expect(screen.getByText("91.3%")).toBeInTheDocument();  // home efficiency
  expect(screen.getByText("88.7%")).toBeInTheDocument();  // away efficiency
});
```

```tsx
// frontend/components/nrl/TryTimeline.test.tsx
import { render, screen } from "@testing-library/react";
import { TryTimeline } from "./TryTimeline";
import type { NrlTryEventOut } from "@/lib/types";

const events: NrlTryEventOut[] = [
  { minute: 7, team: "Knights", player: "K. Ponga", score_home: 6, score_away: 0 },
  { minute: 23, team: "Cowboys", player: "S. Drinkwater", score_home: 6, score_away: 6 },
];

test("renders each try with minute, player and running score", () => {
  render(<TryTimeline events={events} homeTeam="Knights" awayTeam="Cowboys" />);
  expect(screen.getByText("7'")).toBeInTheDocument();
  expect(screen.getByText("K. Ponga")).toBeInTheDocument();
  expect(screen.getByText("6–0")).toBeInTheDocument();
  expect(screen.getByText("6–6")).toBeInTheDocument();
});

test("empty timeline renders the no-tries note", () => {
  render(<TryTimeline events={[]} homeTeam="Knights" awayTeam="Cowboys" />);
  expect(screen.getByText(/no tries recorded/i)).toBeInTheDocument();
});
```

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl`
Expected: FAIL — `Cannot find module './ScoringBreakdown'` / `'./TryTimeline'`.

- [ ] **Step 4: Implement the presentational components**

```tsx
// frontend/components/nrl/ScoringBreakdown.tsx
import type { NrlMatchStatsResponse, NrlTeamMatchStats } from "@/lib/types";

const ROWS: { key: keyof NrlTeamMatchStats; label: string; pct?: boolean }[] = [
  { key: "tries", label: "Tries" },
  { key: "conversions", label: "Conversions" },
  { key: "penalties_conceded", label: "Penalties conceded" },
  { key: "errors", label: "Errors" },
  { key: "set_restarts", label: "Set restarts" },
  { key: "run_metres", label: "Run metres" },
  { key: "line_breaks", label: "Line breaks" },
  { key: "tackles", label: "Tackles" },
  { key: "tackle_efficiency", label: "Tackle efficiency", pct: true },
];

function fmt(value: number, pct?: boolean): string {
  return pct ? `${value.toFixed(1)}%` : value.toLocaleString("en-AU");
}

export function ScoringBreakdown({ stats }: { stats: NrlMatchStatsResponse }) {
  return (
    <div className="glass rounded-2xl p-6">
      <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Scoring breakdown
      </h3>
      <ul className="mt-4 space-y-2">
        {ROWS.map(({ key, label, pct }) => {
          const home = stats.home[key];
          const away = stats.away[key];
          const total = home + away;
          const homeShare = total > 0 ? (home / total) * 100 : 50;
          return (
            <li key={key} className="grid grid-cols-[64px_1fr_64px] items-center gap-3">
              <span className="text-right text-sm font-extrabold tabular-nums text-foreground">
                {fmt(home, pct)}
              </span>
              <div>
                <div className="text-center text-xs text-muted">{label}</div>
                <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <div className="bg-win/60" style={{ width: `${homeShare}%` }} />
                  <div className="bg-loss/60" style={{ width: `${100 - homeShare}%` }} />
                </div>
              </div>
              <span className="text-left text-sm font-extrabold tabular-nums text-foreground">
                {fmt(away, pct)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

```tsx
// frontend/components/nrl/TryTimeline.tsx
import type { NrlTryEventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TryTimeline({
  events,
  homeTeam,
  awayTeam,
}: {
  events: NrlTryEventOut[];
  homeTeam: string | null;
  awayTeam: string | null;
}) {
  return (
    <div className="glass rounded-2xl p-6">
      <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Try timeline
      </h3>
      {events.length === 0 ? (
        <p className="mt-4 text-sm text-muted">No tries recorded for this match.</p>
      ) : (
        <ol className="mt-4 space-y-3">
          {events.map((e, i) => {
            const isHome = e.team === homeTeam;
            return (
              <li key={`${e.minute}-${e.player}-${i}`} className="flex items-center gap-3">
                <span className="min-w-[40px] text-right text-sm font-extrabold tabular-nums text-muted">
                  {e.minute}&apos;
                </span>
                <span
                  className={cn(
                    "rounded-lg px-2 py-1 text-xs font-bold",
                    isHome ? "bg-win/15 text-lime-deep" : "bg-loss/15 text-loss",
                  )}
                >
                  {e.team}
                </span>
                <span className="flex-1 truncate text-sm text-foreground">{e.player}</span>
                <span className="text-sm font-extrabold tabular-nums text-foreground">
                  {e.score_home}–{e.score_away}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <p className="mt-4 text-[11px] text-muted">
        {homeTeam ?? "Home"} left, {awayTeam ?? "Away"} right.
      </p>
    </div>
  );
}
```

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl`
Expected: `3 passed` (2 test files). (Known flake: jest workers can SIGSEGV under parallel load — rerun once before investigating.)

- [ ] **Step 5: Add the section island + register it**

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/StatsSection.tsx
"use client";

/** Wave 2 "stats" intel section: Scoring Breakdown + Try Timeline.
 *  Self-contained client island — fetches its own data through the
 *  /backend-api rewrite; renders a quiet placeholder until stats exist
 *  (finished + ingested matches only). Adds no props requirements beyond
 *  the match id from IntelSectionProps. */
import { useEffect, useState } from "react";
import { CLIENT_BASE } from "@/lib/api";
import type { NrlMatchStatsResponse } from "@/lib/types";
import { ScoringBreakdown } from "@/components/nrl/ScoringBreakdown";
import { TryTimeline } from "@/components/nrl/TryTimeline";
import type { NrlTryEventOut } from "@/lib/types";

/** Attribute sides from running-score deltas: the team on the event where
 *  score_home first increases is the home side (and vice versa). */
function inferSides(events: NrlTryEventOut[]): { home: string | null; away: string | null } {
  let prevHome = 0;
  let prevAway = 0;
  let home: string | null = null;
  let away: string | null = null;
  for (const e of events) {
    if (home === null && e.score_home > prevHome) home = e.team;
    if (away === null && e.score_away > prevAway) away = e.team;
    prevHome = e.score_home;
    prevAway = e.score_away;
    if (home !== null && away !== null) break;
  }
  return { home, away };
}

// NOTE (merge gate): confirm the real IntelSectionProps in sections.ts and
// adapt this signature — it must at minimum receive the match id.
export default function StatsSection({ matchId }: { matchId: number | string }) {
  const [stats, setStats] = useState<NrlMatchStatsResponse | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    fetch(`${CLIENT_BASE}/api/nrl/matches/${matchId}/stats`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => {
        if (!cancelled) setStats(body);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [matchId]);

  if (stats === undefined) {
    return <div className="glass rounded-2xl p-6 text-sm text-muted">Loading match stats…</div>;
  }
  if (stats === null) {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Team stats are published after full time.
      </div>
    );
  }
  const sides = inferSides(stats.try_timeline);
  return (
    <div className="space-y-6">
      <ScoringBreakdown stats={stats} />
      <TryTimeline events={stats.try_timeline} homeTeam={sides.home} awayTeam={sides.away} />
    </div>
  );
}
```

(If `IntelSectionProps` exposes home/away team names — check after the merge gate — pass them into `TryTimeline` directly instead of `inferSides`, which cannot label a side that never scores; `TryTimeline` already tolerates null names.)

Then in `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts`, append ONE entry to the exported sections array (after Wave 1's `model` entry), importing the island at the top of the file:

```ts
import StatsSection from "./StatsSection";
// ... existing Wave 1 entries stay untouched; append:
  { id: "stats", label: "Stats", render: StatsSection },
```

- [ ] **Step 6: Build + commit**

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl && npm run build`
Expected: tests pass; build succeeds (all new fetches are client-side or `.catch`-guarded, so no backend is needed).

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/nrl/ frontend/app/nrl/match/
git commit -m "feat(nrl-stats): stats intel section — scoring breakdown + try timeline"
```

---

### Task 11: Matchup section — attack/defence tiers

A second self-contained intel section: both clubs' attack/defence season ranks rendered as tier chips. Fetches the Wave 1 match detail (`/api/nrl/matches/{id}`) for the two team names, slugifies them, then fetches both profiles. Tier bands (17-team league): 1–4 Elite, 5–8 Strong, 9–12 Mid, 13+ Struggling.

**Files:**
- Create: `frontend/lib/nrlSlug.ts`
- Create: `frontend/components/nrl/MatchupTiers.tsx`
- Create: `frontend/components/nrl/MatchupTiers.test.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/MatchupSection.tsx`
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (append ONE entry)

**Interfaces:**
- Consumes: Task 9's profile endpoint; Wave 1's `GET /api/nrl/matches/{id}`; types/fetchers from Task 10.
- Produces (Task 12 reuses): `slugify(name: string): string` in `frontend/lib/nrlSlug.ts`; `MatchupTiers({ home, away })` where each side is `{ name: string; profile: NrlStatsProfile | null }`.

- [ ] **Step 1: Slug util + failing tests**

```ts
// frontend/lib/nrlSlug.ts
/** Team-name -> URL slug. MUST stay in lockstep with _slugify() in
 *  backend/app/api/sports.py: lowercase, runs of non-alphanumerics -> "-",
 *  trimmed. "Wests Tigers" -> "wests-tigers". */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
```

```tsx
// frontend/components/nrl/MatchupTiers.test.tsx
import { render, screen } from "@testing-library/react";
import { MatchupTiers } from "./MatchupTiers";
import type { NrlStatsProfile } from "@/lib/types";
import { slugify } from "@/lib/nrlSlug";

function profile(name: string, attack: number, defence: number): NrlStatsProfile {
  return {
    team: { id: 1, name, slug: slugify(name) },
    season: 2025,
    attack_rank: attack,
    defence_rank: defence,
    venue_splits: [],
    position_concessions: [],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
}

test("slugify matches the backend rule", () => {
  expect(slugify("Wests Tigers")).toBe("wests-tigers");
  expect(slugify("Knights")).toBe("knights");
});

test("renders attack/defence ranks with tier labels for both clubs", () => {
  render(
    <MatchupTiers
      home={{ name: "Knights", profile: profile("Knights", 2, 10) }}
      away={{ name: "Cowboys", profile: profile("Cowboys", 14, 6) }}
    />,
  );
  expect(screen.getByText("Knights")).toBeInTheDocument();
  expect(screen.getAllByText("Elite").length).toBe(1);      // attack rank 2
  expect(screen.getAllByText("Mid").length).toBe(1);        // defence rank 10
  expect(screen.getAllByText("Struggling").length).toBe(1); // attack rank 14
  expect(screen.getAllByText("Strong").length).toBe(1);     // defence rank 6
  expect(screen.getByText("#2")).toBeInTheDocument();
});

test("missing profile renders em-dashes, not a crash", () => {
  render(
    <MatchupTiers
      home={{ name: "Knights", profile: null }}
      away={{ name: "Cowboys", profile: null }}
    />,
  );
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
});
```

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl/MatchupTiers`
Expected: FAIL — `Cannot find module './MatchupTiers'`.

- [ ] **Step 2: Implement `MatchupTiers`**

```tsx
// frontend/components/nrl/MatchupTiers.tsx
import type { NrlStatsProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

function tier(rank: number | null): { label: string; cls: string } {
  if (rank == null) return { label: "—", cls: "bg-surface-2 text-muted" };
  if (rank <= 4) return { label: "Elite", cls: "bg-win/15 text-lime-deep" };
  if (rank <= 8) return { label: "Strong", cls: "bg-win/10 text-lime-deep" };
  if (rank <= 12) return { label: "Mid", cls: "bg-draw/15 text-amber-ink" };
  return { label: "Struggling", cls: "bg-loss/15 text-loss" };
}

function TierChip({ heading, rank }: { heading: string; rank: number | null }) {
  const t = tier(rank);
  return (
    <div className="rounded-xl bg-surface-2/70 p-3 text-center">
      <div className="text-[11px] uppercase tracking-wider text-muted">{heading}</div>
      <div className="mt-1 text-lg font-extrabold tabular-nums text-foreground">
        {rank == null ? "—" : `#${rank}`}
      </div>
      <span className={cn("mt-1 inline-block rounded-lg px-2 py-0.5 text-xs font-bold", t.cls)}>
        {t.label}
      </span>
    </div>
  );
}

export function MatchupTiers({
  home,
  away,
}: {
  home: { name: string; profile: NrlStatsProfile | null };
  away: { name: string; profile: NrlStatsProfile | null };
}) {
  return (
    <div className="glass rounded-2xl p-6">
      <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Matchup — attack &amp; defence
      </h3>
      <div className="mt-4 grid grid-cols-2 gap-6">
        {[home, away].map((side) => (
          <div key={side.name}>
            <div className="text-sm font-bold text-foreground">{side.name}</div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <TierChip heading="Attack" rank={side.profile?.attack_rank ?? null} />
              <TierChip heading="Defence" rank={side.profile?.defence_rank ?? null} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-muted">
        Season ranks across all 17 clubs — points scored (attack) and conceded (defence) per game.
      </p>
    </div>
  );
}
```

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl/MatchupTiers`
Expected: `3 passed`.

- [ ] **Step 3: Section island + registration**

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/MatchupSection.tsx
"use client";

/** Wave 2 "matchup" intel section: attack/defence tier ranks for both clubs.
 *  Self-contained island: resolves team names from the Wave 1 match detail
 *  endpoint, then loads both /teams/{slug}/profile responses. */
import { useEffect, useState } from "react";
import { CLIENT_BASE } from "@/lib/api";
import { slugify } from "@/lib/nrlSlug";
import type { NrlStatsProfile } from "@/lib/types";
import { MatchupTiers } from "@/components/nrl/MatchupTiers";

type Side = { name: string; profile: NrlStatsProfile | null };

// NOTE (merge gate): confirm the real IntelSectionProps in sections.ts and
// adapt this signature — it must at minimum receive the match id.
export default function MatchupSection({ matchId }: { matchId: number | string }) {
  const [sides, setSides] = useState<{ home: Side; away: Side } | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const detail = await fetch(`${CLIENT_BASE}/api/nrl/matches/${matchId}`, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : null))
        .catch(() => null);
      const homeName: string | null = detail?.match?.home ?? null;
      const awayName: string | null = detail?.match?.away ?? null;
      if (!homeName || !awayName) {
        if (!cancelled) setSides(null);
        return;
      }
      const fetchProfile = (name: string) =>
        fetch(`${CLIENT_BASE}/api/nrl/teams/${slugify(name)}/profile`, { cache: "no-store" })
          .then((res) => (res.ok ? res.json() : null))
          .catch(() => null);
      const [homeProfile, awayProfile] = await Promise.all([
        fetchProfile(homeName),
        fetchProfile(awayName),
      ]);
      if (!cancelled) {
        setSides({
          home: { name: homeName, profile: homeProfile },
          away: { name: awayName, profile: awayProfile },
        });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [matchId]);

  if (sides === undefined) {
    return <div className="glass rounded-2xl p-6 text-sm text-muted">Loading matchup…</div>;
  }
  if (sides === null) {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Matchup profiles are unavailable for this fixture.
      </div>
    );
  }
  return <MatchupTiers home={sides.home} away={sides.away} />;
}
```

(The `detail?.match?.home` path follows the Wave 1 contract `GET /api/nrl/matches/{id} → { match, prediction, form, h2h, factors }` and `NrlMatch`'s `home`/`away` fields; verify the field names in the merged Wave 1 code and adjust the two property reads if its `match` object nests names differently.)

In `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts`, append after the `stats` entry:

```ts
import MatchupSection from "./MatchupSection";
// append:
  { id: "matchup", label: "Matchup", render: MatchupSection },
```

- [ ] **Step 4: Build + commit**

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl && npm run build`
Expected: all component tests pass; build succeeds.

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add frontend/lib/nrlSlug.ts frontend/components/nrl/ frontend/app/nrl/match/
git commit -m "feat(nrl-stats): matchup intel section with attack/defence tiers"
```

---

### Task 12: Team-page venue splits + final verification sweep

Add a venue-splits card to the existing club profile page `frontend/app/nrl/team/[id]/page.tsx`. This page predates Wave 1 (it is NOT a Wave 1 component), so editing it is allowed. The page is a server component: fetch the profile with `.catch(() => null)` so builds and pages survive a missing backend or a not-yet-deployed endpoint.

**Files:**
- Create: `frontend/components/nrl/VenueSplits.tsx`
- Create: `frontend/components/nrl/VenueSplits.test.tsx`
- Modify: `frontend/app/nrl/team/[id]/page.tsx` (one fetch + one render block)
- Modify: `frontend/app/nrl/team/[id]/page.test.tsx` (mock the new fetcher)

**Interfaces:**
- Consumes: `getNrlStatsProfileServer` + `NrlVenueSplit` (Task 10), `slugify` (Task 11).
- Produces: `VenueSplits({ splits })` — terminal consumer, nothing downstream.

- [ ] **Step 1: Failing component test**

```tsx
// frontend/components/nrl/VenueSplits.test.tsx
import { render, screen } from "@testing-library/react";
import { VenueSplits } from "./VenueSplits";
import type { NrlVenueSplit } from "@/lib/types";

const splits: NrlVenueSplit[] = [
  { venue: "Leichhardt Oval", played: 2, wins: 2, draws: 0, losses: 0,
    avg_for: 39.0, avg_against: 11.0 },
  { venue: "Accor Stadium", played: 1, wins: 0, draws: 0, losses: 1,
    avg_for: 12.0, avg_against: 30.0 },
];

test("renders one row per venue with record and averages", () => {
  render(<VenueSplits splits={splits} />);
  expect(screen.getByText("Leichhardt Oval")).toBeInTheDocument();
  expect(screen.getByText("2-0-0")).toBeInTheDocument();
  expect(screen.getByText("39.0 for / 11.0 against")).toBeInTheDocument();
  expect(screen.getByText("Accor Stadium")).toBeInTheDocument();
});

test("empty splits renders nothing", () => {
  const { container } = render(<VenueSplits splits={[]} />);
  expect(container.firstChild).toBeNull();
});
```

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl/VenueSplits`
Expected: FAIL — `Cannot find module './VenueSplits'`.

- [ ] **Step 2: Implement `VenueSplits`**

```tsx
// frontend/components/nrl/VenueSplits.tsx
import type { NrlVenueSplit } from "@/lib/types";

export function VenueSplits({ splits }: { splits: NrlVenueSplit[] }) {
  if (splits.length === 0) return null;
  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Venue splits
      </h2>
      <ul className="mt-4 space-y-2">
        {splits.map((s) => (
          <li key={s.venue} className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm text-foreground">{s.venue}</span>
            <span className="whitespace-nowrap text-sm tabular-nums text-muted">
              <strong className="font-extrabold text-foreground">
                {s.wins}-{s.draws}-{s.losses}
              </strong>{" "}
              · {s.avg_for.toFixed(1)} for / {s.avg_against.toFixed(1)} against
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] text-muted">W-D-L and per-game averages this season.</p>
    </section>
  );
}
```

Run: `cd /tmp/nrl-match-intel-w2/frontend && npx jest components/nrl/VenueSplits`
Expected: `2 passed`.

- [ ] **Step 3: Wire into the team page**

In `frontend/app/nrl/team/[id]/page.tsx`:

1. Add imports at the top:

```tsx
import { getNrlStatsProfileServer } from "@/lib/api";
import { slugify } from "@/lib/nrlSlug";
import { VenueSplits } from "@/components/nrl/VenueSplits";
```

2. Inside `NrlTeamPage`, directly after the existing `const { team, ladder, summary, results, upcoming, model, season, disclaimer } = data;` line, add:

```tsx
  const statsProfile = await getNrlStatsProfileServer(slugify(team.name)).catch(() => null);
```

3. In the returned JSX, after the existing summary/results sections (pick the spot after the last existing `<section>` before the disclaimer/footer block), add:

```tsx
      {statsProfile ? <VenueSplits splits={statsProfile.venue_splits} /> : null}
```

4. In `frontend/app/nrl/team/[id]/page.test.tsx`, the file already does `jest.mock("@/lib/api")`. Add next to the existing `mockTeam` setup:

```tsx
import { getNrlStatsProfileServer } from "@/lib/api";

const mockStatsProfile = getNrlStatsProfileServer as jest.MockedFunction<
  typeof getNrlStatsProfileServer
>;
```

and in the test setup (`beforeEach` or alongside each `mockTeam.mockResolvedValue(...)` call):

```tsx
mockStatsProfile.mockResolvedValue(null);
```

(Existing tests then render exactly as before — `VenueSplits` is skipped on `null`. Add one new test if desired: resolve a profile with one split and assert `screen.getByText("Venue splits")`.)

- [ ] **Step 4: Full verification sweep**

Run each; all must pass before the PR:

```bash
cd /tmp/nrl-match-intel-w2 && pytest
# Expected: full backend+pipeline suite passes (includes the 20 nrl_stats tests,
# 1 schema test, 7 API tests added by this wave)

cd /tmp/nrl-match-intel-w2/frontend && npx jest
# Expected: all suites pass. Known flake: a worker SIGSEGV under parallel load —
# rerun once before treating as a failure.

cd /tmp/nrl-match-intel-w2/frontend && npm run build
# Expected: build succeeds with no backend running (all fetches .catch-guarded
# or client-side).

cd /tmp/nrl-match-intel-w2/backend && alembic heads
# Expected: exactly one head — this wave's migration id.
```

- [ ] **Step 5: Commit and finish the branch**

```bash
cd /tmp/nrl-match-intel-w2
git reset frontend/node_modules
git add frontend/components/nrl/ frontend/app/nrl/team/
git commit -m "feat(nrl-stats): venue splits on club profile pages"
```

Then use superpowers:finishing-a-development-branch to put the PR up (`feat/nrl-match-intel-w2` → `main`; merges after Wave 1 per the program's W1 → W2 → W3 order). Remove the worktree once the PR is up:

```bash
cd "/Users/macbookpro/Projects/FIFA WC26 Prediction"
git worktree remove /tmp/nrl-match-intel-w2
```

---

## Spec-coverage map (self-review record)

| Spec requirement (Wave 2) | Task |
|---|---|
| Source spike, robots/ToS respected, fallback procedure | 1 |
| Recorded fixtures; no live HTTP in tests, all downstream builds on fixtures | 1 (recorded), 2–6, 8–12 (consumed) |
| `StatsProvider` protocol verbatim; provider stays pluggable | 2 (protocol), 3 (default impl), 6 (`_FakeProvider` proves consumers touch only the protocol) |
| `nrl_match_stats` + `nrl_try_events` migrations | 4 |
| Backfill command, 2024–2026 minimum, resumable, >= 1s between requests | 6 (resume + provider throttle), 3 (throttle impl), 7 (workflow arg `--seasons 2024 2026`) |
| `nrl-refresh` ingest step | 7 |
| `GET /api/nrl/matches/{id}/stats` per contract | 8 |
| `GET /api/nrl/teams/{slug}/profile` per contract | 9 (`position_concessions` ships `[]` until W3 provides positions — documented) |
| UI after W1 merges; append to `sections.ts` + self-contained components; no Wave 1 edits | Merge gate + 10, 11 |
| Scoring Breakdown + Try Timeline on finished matches | 10 (404 → "published after full time") |
| Attack/defence tier ranks in a `matchup` section | 11 |
| Venue splits on team pages | 12 |




