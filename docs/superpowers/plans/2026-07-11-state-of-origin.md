# State of Origin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add State of Origin (rugby league, NSW Blues vs QLD Maroons, 3 games/year) to FinalWhistle end to end: seeded history → Elo model → shadow predictions → API → `/nrl/origin` page → scheduled refresh.

**Architecture:** A thin second lane on the existing sport-generic rail. History (1982–2024) is compiled once from TheSportsDB into a committed JSON; live seasons (2025+) come from fixturedownload's `state-of-origin-{year}` feed. Both flow through the (lightly parameterized) NRL ingest into the existing `sport_*` tables under `sport="origin"`. The NRL margin-Elo model is reused with Origin-tuned committed params and a new neutral-venue flag. Two endpoints under `/api/nrl/origin/*` serve a new Next.js page.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, pytest; Next.js 15 (App Router, server components), TypeScript, Jest; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-11-state-of-origin-design.md` (read it first).

## Global Constraints

- DB sport slug is **`"origin"`** — the `sport` column is `String(10)`; `"state-of-origin"` (15 chars) would fail on Postgres. Never use the long slug in DB values.
- Canonical team names: **"NSW Blues"** and **"QLD Maroons"** — every source name maps to these before any DB write.
- **No DB migration.** Existing `SportMatch`/`SportTeam`/`SportPrediction`/`SportPredictionResult` tables only.
- **No changes to NRL behavior.** Signature additions to shared code must be backward-compatible keyword args with NRL defaults; all existing NRL tests must still pass untouched.
- Predictions are **shadow-only** (`is_shadow=True`) and **frozen**: never write a prediction for a non-scheduled match (`_write_prediction`'s hard guard). Retrodictions never enter the DB — backtest numbers live only in the committed artifact.
- Model version string: **`origin-elo-v0.1`**.
- Frontend: Origin is **not** a third sport and **not** a sixth nav tab (BottomNav is a fixed five-tab design). Entry is a card on `/nrl`.
- Run Python tests with `.venv/bin/python -m pytest` from the repo root. Frontend: `cd frontend && npm run typecheck && npm run lint && npm test`.
- Work on branch `feat/state-of-origin`. Commit after every task (steps say when).
- The repo is private; the seed data file is public-record sports results and fine to commit.

---

### Task 1: Team-name canonicalization + history seed script + committed seed data

**Files:**
- Create: `pipeline/sports/origin_names.py`
- Create: `pipeline/sports/origin_seed.py`
- Create: `pipeline/sports/origin_seed_test.py`
- Create (generated, committed): `data/raw/state_of_origin_history.json`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `origin_names.CANONICAL: dict[str, str]` — source name → canonical name.
  - `origin_names.TEAM_INDEX: dict[str, int]` — `{"NSW Blues": 0, "QLD Maroons": 1}` (used by the backtest in Task 4).
  - `data/raw/state_of_origin_history.json` with shape:
    `{"source": str, "fetched": "YYYY-MM-DD", "matches": [{"season": int, "round": int, "match_no": int, "kickoff_utc": "YYYY-MM-DD HH:MM:SSZ", "venue": str|null, "home_team": str, "away_team": str, "score_home": int, "score_away": int}, ...]}`
    — `kickoff_utc` deliberately uses **fixturedownload's `DateUtc` string format** so seed rows can be fed through the existing feed parser (Task 2).

- [ ] **Step 1: Write `origin_names.py`** (pure data, no test file needed — it's exercised by every other test)

```python
"""Canonical State of Origin team names (design 2026-07-11).

The two data sources disagree on naming (fixturedownload: "Blues"/"Maroons";
TheSportsDB: "New South Wales Blues"/"Queensland Maroons"). Everything is
mapped to the canonical pair below BEFORE any DB write so the sources can
never create duplicate SportTeam rows. Unknown names are absent from the map
on purpose — callers treat a miss as malformed data, not a new team.
"""
from __future__ import annotations

NSW = "NSW Blues"
QLD = "QLD Maroons"

CANONICAL: dict[str, str] = {
    "Blues": NSW,
    "New South Wales Blues": NSW,
    "New South Wales": NSW,
    "NSW": NSW,
    NSW: NSW,
    "Maroons": QLD,
    "Queensland Maroons": QLD,
    "Queensland": QLD,
    "QLD": QLD,
    QLD: QLD,
}

# Stable indices for DB-free replay (ml.sports.origin.backtest).
TEAM_INDEX: dict[str, int] = {NSW: 0, QLD: 1}
```

- [ ] **Step 2: Write the failing tests for the seed transformer**

`pipeline/sports/origin_seed_test.py`:

```python
"""Tests for the one-time TheSportsDB -> seed-file transformer.

transform_events is strict, NOT best-effort: the seed file is committed and
must be 100% clean, so anything unexpected raises instead of being skipped.
"""
import pytest

from pipeline.sports.origin_seed import transform_events, validate_season

# Verified live shape from
# https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=5835&s=1990
def _event(round_no, home="New South Wales Blues", away="Queensland Maroons",
           hs="8", as_="0", date="1990-05-09", venue=""):
    return {"strEvent": f"{home} vs {away}", "dateEvent": date,
            "intRound": str(round_no), "strHomeTeam": home, "strAwayTeam": away,
            "intHomeScore": hs, "intAwayScore": as_, "strVenue": venue}


def test_transform_three_games_canonical_names_and_feed_format_kickoff():
    events = [_event(2, date="1990-06-13"), _event(1), _event(3, date="1990-07-11")]
    matches = transform_events(events, 1990)
    assert [m["round"] for m in matches] == [1, 2, 3]      # sorted by round
    assert matches[0] == {
        "season": 1990, "round": 1, "match_no": 1,
        "kickoff_utc": "1990-05-09 09:30:00Z",              # DateUtc feed format
        "venue": None,                                       # "" -> None
        "home_team": "NSW Blues", "away_team": "QLD Maroons",
        "score_home": 8, "score_away": 0,
    }


def test_transform_keeps_venue_and_parses_string_scores():
    m = transform_events(
        [_event(1, venue="Suncorp Stadium", hs="18", as_="18"),
         _event(2), _event(3)], 1999)[0]
    assert m["venue"] == "Suncorp Stadium"
    assert m["score_home"] == 18 and m["score_away"] == 18   # draws are real


def test_transform_unknown_team_raises():
    with pytest.raises(ValueError, match="unrecognized"):
        transform_events([_event(1, home="Fiji Bati"), _event(2), _event(3)], 2001)


def test_validate_wrong_game_count_raises():
    with pytest.raises(ValueError, match="expected 3 games"):
        validate_season([{"round": 1}, {"round": 2}], 1980)


def test_validate_wrong_rounds_raise():
    with pytest.raises(ValueError, match="rounds"):
        validate_season([{"round": 1}, {"round": 1}, {"round": 3}], 2003)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/sports/origin_seed_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.origin_seed'`

- [ ] **Step 4: Write `pipeline/sports/origin_seed.py`**

```python
"""One-time State of Origin history seed builder (design 2026-07-11).

Pulls 1982-2024 series results from TheSportsDB (league 5835,
eventsseason.php) and writes the committed seed file
data/raw/state_of_origin_history.json. Run ONCE, verify, commit the output;
serving never touches TheSportsDB — pipeline.sports.origin_ingest --seed
reads the committed file.

Unlike the ingest adapters this is strict, not best-effort: the seed must be
complete and clean, so any missing season, unknown team name, or malformed
field ABORTS the run (nonzero exit) instead of being skipped.

CLI: python -m pipeline.sports.origin_seed \
        --start 1982 --end 2024 --out data/raw/state_of_origin_history.json
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

import requests

from pipeline.sports.origin_names import CANONICAL

log = logging.getLogger(__name__)

API_URL = "https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=5835&s={year}"
# TheSportsDB's dateEvent is date-only; Origin is an evening-AEST fixture, so
# pin a nominal 09:30 UTC kickoff. Only within-season ordering matters to the
# Elo replay and the three games are weeks apart, so the exact hour is moot.
_NOMINAL_TIME = "09:30:00Z"


def fetch_events(year: int, timeout: float = 20.0) -> list[dict]:
    """One season's raw events. Raises on any HTTP/JSON problem (strict)."""
    resp = requests.get(
        API_URL.format(year=year), headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json().get("events") or []


def transform_events(events: list[dict], season: int) -> list[dict]:
    """TheSportsDB events -> seed match dicts (canonical names, feed-format
    kickoff string). Raises ValueError on anything unexpected."""
    matches = []
    for e in events:
        home = CANONICAL.get((e.get("strHomeTeam") or "").strip())
        away = CANONICAL.get((e.get("strAwayTeam") or "").strip())
        if home is None or away is None or home == away:
            raise ValueError(
                f"{season}: unrecognized teams "
                f"{e.get('strHomeTeam')!r} vs {e.get('strAwayTeam')!r}"
            )
        datetime.strptime(e["dateEvent"], "%Y-%m-%d")  # validate, keep string
        round_no = int(e["intRound"])
        matches.append({
            "season": season, "round": round_no, "match_no": round_no,
            "kickoff_utc": f"{e['dateEvent']} {_NOMINAL_TIME}",
            "venue": (e.get("strVenue") or "").strip() or None,
            "home_team": home, "away_team": away,
            "score_home": int(e["intHomeScore"]),
            "score_away": int(e["intAwayScore"]),
        })
    matches.sort(key=lambda m: m["round"])
    validate_season(matches, season)
    return matches


def validate_season(matches: list[dict], season: int) -> None:
    if len(matches) != 3:
        raise ValueError(f"{season}: expected 3 games, got {len(matches)}")
    rounds = [m["round"] for m in matches]
    if rounds != [1, 2, 3]:
        raise ValueError(f"{season}: rounds are {rounds}, expected [1, 2, 3]")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=1982)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    all_matches: list[dict] = []
    for year in range(args.start, args.end + 1):
        events = fetch_events(year)
        matches = transform_events(events, year)
        all_matches.extend(matches)
        log.info("%s: %d games", year, len(matches))
        time.sleep(1.1)  # free-tier rate limit

    draws = sum(1 for m in all_matches if m["score_home"] == m["score_away"])
    payload = {
        "source": "TheSportsDB eventsseason.php, league 5835 (State of Origin)",
        "fetched": date.today().isoformat(),
        "matches": all_matches,
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    log.info(
        "wrote %s: %d matches, %d seasons, %d drawn games",
        args.out, len(all_matches), args.end - args.start + 1, draws,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/sports/origin_seed_test.py -v`
Expected: all PASS

- [ ] **Step 6: Build the real seed file (network)**

Run from repo root:
```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.origin_seed \
  --start 1982 --end 2024 --out data/raw/state_of_origin_history.json
```
Expected: per-season "N: 3 games" lines and a final summary of **129 matches, 43 seasons**.

- [ ] **Step 7: Verify the generated file**

```bash
python3 - <<'EOF'
import json
d = json.load(open("data/raw/state_of_origin_history.json"))
ms = d["matches"]
assert len(ms) == 129, len(ms)
seasons = {m["season"] for m in ms}
assert seasons == set(range(1982, 2025)), sorted(seasons ^ set(range(1982, 2025)))
assert {m["home_team"] for m in ms} | {m["away_team"] for m in ms} == {"NSW Blues", "QLD Maroons"}
draws = [(m["season"], m["round"]) for m in ms if m["score_home"] == m["score_away"]]
print("OK — 129 matches, 43 seasons, drawn games:", draws)
EOF
```
Expected: `OK` and a **non-empty** drawn-games list (Origin history contains drawn games, e.g. in 1999 and 2002). **If the draws list is empty or any assert fires, STOP — the data is wrong; report back rather than committing.**

- [ ] **Step 8: Commit**

```bash
git add pipeline/sports/origin_names.py pipeline/sports/origin_seed.py \
        pipeline/sports/origin_seed_test.py data/raw/state_of_origin_history.json
git commit -m "feat(origin): team canonicalization + seeded 1982-2024 history"
```

---

### Task 2: Ingest — parameterize `nrl_ingest`, add `origin_ingest`

**Files:**
- Modify: `pipeline/sports/nrl_ingest.py` (functions `fetch_season`, `_get_or_create_team`, `upsert_season`)
- Create: `pipeline/sports/origin_ingest.py`
- Create: `pipeline/sports/origin_ingest_test.py`

**Interfaces:**
- Consumes: `origin_names.CANONICAL`; seed file from Task 1; existing `nrl_ingest.parse_row` (unchanged).
- Produces:
  - `nrl_ingest.fetch_season(year, timeout=20.0, url_template=FEED_URL)` — new optional kwarg.
  - `nrl_ingest.upsert_season(db, year, rows, sport=SPORT, team_name_map=None)` — new optional kwargs. `team_name_map` maps parsed team names to canonical ones; a name missing from the map ⇒ row skipped with a warning.
  - `origin_ingest.SPORT = "origin"`, `origin_ingest.FEED_URL`, `origin_ingest.SEED_FILE`
  - `origin_ingest.seed_rows_by_season(path=SEED_FILE) -> dict[int, list[dict]]` — feed-shape rows.
  - CLI: `python -m pipeline.sports.origin_ingest --seed` and/or `--seasons START END`.

- [ ] **Step 1: Write the failing tests**

`pipeline/sports/origin_ingest_test.py`:

```python
"""Origin ingest: both sources flow through nrl_ingest.upsert_season with
sport="origin" and canonical team names. Uses the repo-root conftest
db_session fixture (in-memory SQLite)."""
from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_ingest import upsert_season
from pipeline.sports.origin_ingest import SPORT, seed_rows_by_season
from pipeline.sports.origin_names import CANONICAL

# Verified live shape from fixturedownload.com/feed/json/state-of-origin-2026
LIVE_ROW = {"MatchNumber": 1, "RoundNumber": 1, "DateUtc": "2026-05-27 10:05:00Z",
            "Location": "Accor Stadium", "HomeTeam": "Blues", "AwayTeam": "Maroons",
            "Group": None, "HomeTeamScore": 22, "AwayTeamScore": 20, "Winner": "Blues"}


def test_live_row_canonicalized_and_scoped_to_origin(db_session):
    counts = upsert_season(db_session, 2026, [LIVE_ROW],
                           sport=SPORT, team_name_map=CANONICAL)
    assert counts == {"created": 1, "updated": 0}
    m = db_session.query(SportMatch).one()
    assert m.sport == "origin" and m.season == 2026 and m.round == 1
    names = {t.name for t in db_session.query(SportTeam).filter_by(sport="origin")}
    assert names == {"NSW Blues", "QLD Maroons"}


def test_unknown_team_name_is_skipped(db_session):
    bad = dict(LIVE_ROW, HomeTeam="Fiji Bati")
    counts = upsert_season(db_session, 2026, [bad], sport=SPORT, team_name_map=CANONICAL)
    assert counts == {"created": 0, "updated": 0}
    assert db_session.query(SportMatch).count() == 0


def test_same_name_in_two_sports_is_two_teams(db_session):
    upsert_season(db_session, 2026, [dict(LIVE_ROW, HomeTeam="Broncos", AwayTeam="Storm")])
    upsert_season(db_session, 2026, [LIVE_ROW], sport=SPORT, team_name_map=CANONICAL)
    assert db_session.query(SportTeam).filter_by(sport="nrl").count() == 2
    assert db_session.query(SportTeam).filter_by(sport="origin").count() == 2


def test_seed_rows_round_trip_through_upsert(tmp_path, db_session):
    import json
    seed = {"source": "test", "fetched": "2026-07-11", "matches": [
        {"season": 1982, "round": 1, "match_no": 1,
         "kickoff_utc": "1982-06-08 09:30:00Z", "venue": None,
         "home_team": "NSW Blues", "away_team": "QLD Maroons",
         "score_home": 20, "score_away": 16},
        {"season": 1982, "round": 2, "match_no": 2,
         "kickoff_utc": "1982-06-22 09:30:00Z", "venue": "Lang Park",
         "home_team": "QLD Maroons", "away_team": "NSW Blues",
         "score_home": 11, "score_away": 7},
    ]}
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(seed))

    by_season = seed_rows_by_season(p)
    assert set(by_season) == {1982}
    for season, rows in by_season.items():
        upsert_season(db_session, season, rows, sport=SPORT, team_name_map=CANONICAL)
    ms = db_session.query(SportMatch).filter_by(sport="origin", season=1982).all()
    assert {(m.round, m.status, m.score_home) for m in ms} == {(1, "finished", 20), (2, "finished", 11)}


def test_seed_ingest_is_idempotent(tmp_path, db_session):
    import json
    seed = {"source": "t", "fetched": "d", "matches": [
        {"season": 1983, "round": 1, "match_no": 1,
         "kickoff_utc": "1983-06-07 09:30:00Z", "venue": None,
         "home_team": "NSW Blues", "away_team": "QLD Maroons",
         "score_home": 10, "score_away": 24}]}
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(seed))
    for _ in range(2):
        for season, rows in seed_rows_by_season(p).items():
            upsert_season(db_session, season, rows, sport=SPORT, team_name_map=CANONICAL)
    assert db_session.query(SportMatch).filter_by(sport="origin").count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/sports/origin_ingest_test.py -v`
Expected: FAIL — `ModuleNotFoundError` (origin_ingest) / `TypeError: upsert_season() got an unexpected keyword argument 'sport'`

- [ ] **Step 3: Parameterize `nrl_ingest.py`** (backward-compatible; do NOT change any default behavior)

In `pipeline/sports/nrl_ingest.py`:

1. `fetch_season` — add `url_template: str = FEED_URL` parameter; body uses `url = url_template.format(year=year)` (the log lines already print `url`-relevant info via the exception; change the first log to `log.warning("fetch_season(%s) failed: %s", url, exc)` and the second to reference `url` likewise).
2. `_get_or_create_team(db, cache, name, sport: str = SPORT)` — replace both `SPORT` uses in the body with `sport`.
3. `upsert_season(db, year, rows, sport: str = SPORT, team_name_map: dict[str, str] | None = None)`:
   - replace the `filter_by(sport=SPORT, ...)` and `SportMatch(sport=SPORT, ...)` uses with `sport`;
   - pass `sport` through both `_get_or_create_team` calls;
   - immediately after the `parse_row` malformed check, insert:

```python
        if team_name_map is not None:
            home_name = team_name_map.get(parsed["home_team"])
            away_name = team_name_map.get(parsed["away_team"])
            if home_name is None or away_name is None:
                log.warning(
                    "%s upsert_season(%s): unrecognized team in %r, skipping",
                    sport, year, raw,
                )
                continue
            parsed["home_team"], parsed["away_team"] = home_name, away_name
```

   - update the docstring's first line to mention the two kwargs (one sentence), and change the hardcoded `"nrl ..."` log prefixes inside `upsert_season` to use `%s` with `sport`.

- [ ] **Step 4: Write `pipeline/sports/origin_ingest.py`**

```python
"""State of Origin ingest (design 2026-07-11).

Two idempotent entry points over sport="origin" rows, both flowing through
nrl_ingest.upsert_season — same parse, identity key (sport, season, round,
match_no), freshness guard (finished matches immutable) and best-effort CLI
idiom; origin passes sport= and team_name_map= instead of duplicating any of
it:

  --seed               load the committed history file (data/raw/
                       state_of_origin_history.json, 1982-2024, built once by
                       pipeline.sports.origin_seed from TheSportsDB).
  --seasons START END  fetch live seasons from fixturedownload
                       (state-of-origin-{year}, same JSON shape as nrl-{year}).

CLI: python -m pipeline.sports.origin_ingest --seed --seasons 2025 2027
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from pipeline.sports.nrl_ingest import fetch_season, upsert_season
from pipeline.sports.origin_names import CANONICAL

log = logging.getLogger(__name__)

SPORT = "origin"
FEED_URL = "https://fixturedownload.com/feed/json/state-of-origin-{year}"
SEED_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "state_of_origin_history.json"


def seed_rows_by_season(path: Path = SEED_FILE) -> dict[int, list[dict]]:
    """Committed seed matches -> feed-shape rows keyed by season, so the seed
    flows through the exact same parse/upsert path as the live feed."""
    data = json.loads(path.read_text())
    by_season: dict[int, list[dict]] = {}
    for m in data["matches"]:
        by_season.setdefault(m["season"], []).append({
            "MatchNumber": m["match_no"], "RoundNumber": m["round"],
            "DateUtc": m["kickoff_utc"], "Location": m["venue"],
            "HomeTeam": m["home_team"], "AwayTeam": m["away_team"],
            "HomeTeamScore": m["score_home"], "AwayTeamScore": m["score_away"],
        })
    return by_season


def _upsert(db, year: int, rows: list[dict]) -> None:
    """One season through upsert_season with the origin scope; best-effort
    (rollback + continue), mirroring nrl_ingest.main's per-season loop."""
    try:
        counts = upsert_season(db, year, rows, sport=SPORT, team_name_map=CANONICAL)
    except Exception as exc:  # noqa: BLE001 - one bad season must never abort the run
        db.rollback()
        log.warning("%s: upsert_season failed, skipping season: %s", year, exc)
        return
    log.info("%s: %d rows, created=%d updated=%d",
             year, len(rows), counts["created"], counts["updated"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", action="store_true", help="load the committed 1982-2024 history file")
    ap.add_argument("--seasons", nargs=2, type=int, metavar=("START", "END"),
                    help="inclusive year range to fetch from fixturedownload, e.g. --seasons 2025 2027")
    args = ap.parse_args()
    if not args.seed and not args.seasons:
        ap.error("pass --seed, --seasons, or both")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.seed:
            for year, rows in sorted(seed_rows_by_season().items()):
                _upsert(db, year, rows)
        if args.seasons:
            start, end = args.seasons
            for year in range(start, end + 1):
                rows = fetch_season(year, url_template=FEED_URL)
                if not rows:
                    log.info("%s: no data (feed empty or unavailable)", year)
                    continue
                _upsert(db, year, rows)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run new tests AND the untouched NRL ingest tests**

Run: `.venv/bin/python -m pytest pipeline/sports/origin_ingest_test.py pipeline/sports/nrl_ingest_test.py -v`
Expected: all PASS (NRL tests prove backward compatibility).

- [ ] **Step 6: Commit**

```bash
git add pipeline/sports/nrl_ingest.py pipeline/sports/origin_ingest.py pipeline/sports/origin_ingest_test.py
git commit -m "feat(origin): ingest lane — seed + fixturedownload through shared upsert"
```

---

### Task 3: Model plumbing — neutral flag, Origin params, venues, series odds

**Files:**
- Modify: `ml/sports/nrl/model.py` (function `update` only)
- Create: `ml/sports/origin/__init__.py` (empty)
- Create: `ml/sports/origin/params.py`, `ml/sports/origin/params_test.py`
- Create: `ml/sports/origin/venues.py`
- Create: `ml/sports/origin/series.py`, `ml/sports/origin/series_test.py`
- Test (extend): `ml/sports/nrl/model_test.py` (add one neutral-flag test)

**Interfaces:**
- Consumes: `NrlParams`, `expected_home_prob`, `predict` from `ml.sports.nrl.model` (predict already has `neutral: bool = False`).
- Produces:
  - `update(elo_home, elo_away, score_home, score_away, p, neutral: bool = False)` — zeroes home advantage in the expected term when neutral.
  - `ml.sports.origin.params.ORIGIN_DEFAULTS: NrlParams` (version `origin-elo-v0.1`), `load_origin_params() -> NrlParams`, `save_origin_params(params) -> None` (file `ml/sports/origin/params.json`).
  - `ml.sports.origin.venues.is_neutral(venue: str | None) -> bool`, `NEUTRAL_VENUES: frozenset[str]`.
  - `ml.sports.origin.series.series_odds(wins_a: int, wins_b: int, remaining: list[tuple[float, float, float]]) -> dict` returning `{"p_a": float, "p_b": float, "p_drawn": float}`; each remaining triple is `(p_a_wins_game, p_draw_game, p_b_wins_game)`.

- [ ] **Step 1: Write the failing tests**

Append to `ml/sports/nrl/model_test.py`:

```python
def test_update_neutral_flag_removes_home_edge():
    from ml.sports.nrl.model import NrlParams, update
    p = NrlParams()
    # Equal ratings, home side wins by 10. With home_adv the home win was
    # partly expected; at a neutral venue the same win is a bigger surprise,
    # so the home side must gain MORE Elo from the neutral update.
    home_with_adv, _ = update(1500.0, 1500.0, 20, 10, p)
    home_neutral, away_neutral = update(1500.0, 1500.0, 20, 10, p, neutral=True)
    assert home_neutral > home_with_adv
    assert home_neutral + away_neutral == pytest.approx(3000.0)  # still zero-sum
```

(Ensure `import pytest` exists at the top of that test file; add it if missing.)

`ml/sports/origin/params_test.py`:

```python
"""Origin params loader — mirrors ml/sports/nrl/params_test.py's pattern."""
from ml.sports.origin import params as origin_params
from ml.sports.origin.params import ORIGIN_DEFAULTS, load_origin_params, save_origin_params


def test_defaults_are_origin_branded():
    assert ORIGIN_DEFAULTS.version == "origin-elo-v0.1"


def test_load_falls_back_to_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(origin_params, "_PARAMS_FILE", tmp_path / "params.json")
    assert load_origin_params() == ORIGIN_DEFAULTS


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(origin_params, "_PARAMS_FILE", tmp_path / "params.json")
    tuned = replace(ORIGIN_DEFAULTS, k=64.0, home_adv=15.0)
    save_origin_params(tuned)
    assert load_origin_params() == tuned
```

`ml/sports/origin/series_test.py`:

```python
"""series_odds — exact enumeration over the remaining games of a 3-game series."""
import pytest

from ml.sports.origin.series import series_odds
from ml.sports.origin.venues import is_neutral


def test_decided_series_no_remaining():
    assert series_odds(2, 0, []) == {"p_a": 1.0, "p_b": 0.0, "p_drawn": 0.0}
    assert series_odds(1, 1, []) == {"p_a": 0.0, "p_b": 0.0, "p_drawn": 1.0}


def test_single_remaining_game_at_one_all():
    out = series_odds(1, 1, [(0.6, 0.1, 0.3)])
    assert out == pytest.approx({"p_a": 0.6, "p_b": 0.3, "p_drawn": 0.1})


def test_full_series_sums_to_one_and_symmetric():
    g = (0.45, 0.1, 0.45)
    out = series_odds(0, 0, [g, g, g])
    assert out["p_a"] + out["p_b"] + out["p_drawn"] == pytest.approx(1.0)
    assert out["p_a"] == pytest.approx(out["p_b"])


def test_drawn_games_count_toward_drawn_series():
    # 1-0 up with two remaining; opponent wins one, other drawn -> 1-1-1 drawn.
    out = series_odds(1, 0, [(0.0, 1.0, 0.0), (0.0, 0.0, 1.0)])
    assert out == pytest.approx({"p_a": 0.0, "p_b": 0.0, "p_drawn": 1.0})


def test_is_neutral_known_venues_case_insensitive():
    assert is_neutral("Melbourne Cricket Ground")
    assert is_neutral("optus stadium")
    assert not is_neutral("Suncorp Stadium")
    assert not is_neutral(None)
    assert not is_neutral("")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/sports/origin ml/sports/nrl/model_test.py -v`
Expected: FAIL — missing modules / `TypeError: update() got an unexpected keyword argument 'neutral'`

- [ ] **Step 3: Implement**

`ml/sports/nrl/model.py` — change `update`'s signature and first line only:

```python
def update(
    elo_home: float,
    elo_away: float,
    score_home: int,
    score_away: int,
    p: NrlParams,
    neutral: bool = False,
) -> tuple[float, float]:
    """Return updated (home, away) Elo ratings after one match. Pure, zero-sum.

    `neutral` zeroes the home-advantage term in the expectation (for
    neutral-venue fixtures, e.g. State of Origin at the MCG); all NRL call
    sites use the default.
    """
    adv = 0.0 if neutral else p.home_adv
    expected = expected_home_prob(elo_home, elo_away, adv)
```

(rest of the function unchanged).

`ml/sports/origin/__init__.py`: empty file.

`ml/sports/origin/params.py`:

```python
"""Tuned parameter loader for the Origin Elo model (design 2026-07-11).

Same load/save pattern as ml/sports/nrl/params.py, with Origin-flavored
defaults: only 3 games a year means each result carries more information
(higher K), the designated "home" side's edge is weaker than a club ground's
(lower home_adv), the rep player pool is stable era to era (weak season
regression), and pre-golden-point history has real draws (higher p_draw).
These hand-set values are the pre-tuning fallback; ml.sports.origin.backtest
--tune --write fits the real ones into params.json.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ml.sports.nrl.model import NrlParams

_PARAMS_FILE = Path(__file__).with_name("params.json")

ORIGIN_DEFAULTS = NrlParams(
    version="origin-elo-v0.1",
    k=48.0,
    home_adv=30.0,
    margin_mult_cap=2.2,
    season_regress=0.10,
    margin_slope=0.045,
    margin_sigma=14.0,
    p_draw=0.02,
)


def load_origin_params() -> NrlParams:
    """Load tuned params from params.json, or ORIGIN_DEFAULTS if absent/invalid."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlParams(
            version=data.get("version", ORIGIN_DEFAULTS.version),
            k=float(data["k"]),
            home_adv=float(data["home_adv"]),
            margin_mult_cap=float(data["margin_mult_cap"]),
            season_regress=float(data["season_regress"]),
            margin_slope=float(data["margin_slope"]),
            margin_sigma=float(data["margin_sigma"]),
            p_draw=float(data["p_draw"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return ORIGIN_DEFAULTS


def save_origin_params(params: NrlParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")
```

`ml/sports/origin/venues.py`:

```python
"""Neutral-venue detection for State of Origin fixtures.

Origin's "home" team designation at an interstate/neutral ground is
administrative — nobody has a crowd edge at the MCG. Venue strings missing
from this set (including the seed file's many empty venues) default to
NON-neutral: the designated home side keeps its advantage. Accepted
approximation per the design doc.
"""
from __future__ import annotations

NEUTRAL_VENUES = frozenset({
    "melbourne cricket ground",
    "mcg",
    "docklands stadium",
    "etihad stadium",
    "marvel stadium",
    "optus stadium",
    "perth stadium",
    "adelaide oval",
    "tio stadium",
})


def is_neutral(venue: str | None) -> bool:
    return bool(venue) and venue.strip().lower() in NEUTRAL_VENUES
```

`ml/sports/origin/series.py`:

```python
"""Best-of-three series odds by exact enumeration (design 2026-07-11).

Pure math, DB-free. A drawn game is a real outcome (pre-golden-point Origin
had them) and contributes to neither side's win count; a series with equal
wins after three games is drawn ("p_drawn"). Callers map home/away per game
onto a stable (team A, team B) orientation before calling.
"""
from __future__ import annotations

from itertools import product


def series_odds(
    wins_a: int, wins_b: int, remaining: list[tuple[float, float, float]]
) -> dict:
    """P(A wins series), P(B wins series), P(series drawn).

    `remaining`: one (p_a_wins_game, p_draw_game, p_b_wins_game) triple per
    game not yet played (0-3 of them). With no games remaining the current
    score decides with probability 1. Enumeration is exact: <= 3**3 outcomes.
    """
    totals = {"p_a": 0.0, "p_b": 0.0, "p_drawn": 0.0}
    for combo in product(range(3), repeat=len(remaining)):
        prob = 1.0
        a, b = wins_a, wins_b
        for game_idx, outcome in enumerate(combo):
            prob *= remaining[game_idx][outcome]
            if outcome == 0:
                a += 1
            elif outcome == 2:
                b += 1
        key = "p_a" if a > b else "p_b" if b > a else "p_drawn"
        totals[key] += prob
    return totals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest ml/sports/origin ml/sports/nrl -v`
Expected: all PASS (including every pre-existing NRL model/backtest/params test).

- [ ] **Step 5: Commit**

```bash
git add ml/sports/nrl/model.py ml/sports/nrl/model_test.py ml/sports/origin/
git commit -m "feat(origin): neutral-venue Elo flag, origin params, series odds"
```

---

### Task 4: Backtest + tuner → committed `params.json` and `backtest_record.json`

**Files:**
- Create: `ml/sports/origin/backtest.py`, `ml/sports/origin/backtest_test.py`
- Create (generated, committed): `ml/sports/origin/params.json`, `ml/sports/origin/backtest_record.json`

**Interfaces:**
- Consumes: seed file (Task 1), `TEAM_INDEX` from `pipeline.sports.origin_names`, `update`/`predict`/`regress_season` + `NrlParams` (Task 3), `is_neutral`, `ORIGIN_DEFAULTS`, `save_origin_params`.
- Produces:
  - `load_history(path=SEED_FILE) -> dict[int, list[dict]]` — rows `{"home_id": int, "away_id": int, "score_home": int, "score_away": int, "kickoff_utc": datetime, "neutral": bool}`.
  - `walk_forward(history, params, score_from=1985) -> dict` — `{"n", "winner_accuracy", "avg_log_loss", "avg_brier", "home_baseline_accuracy", "span": [score_from, max_season]}`.
  - `tune(history, val_from=2015, grid=None) -> NrlParams`.
  - `load_backtest_record() -> dict | None` — reads `backtest_record.json` (used by the API in Task 6).
  - Committed artifact `backtest_record.json`: `{"model_version", "span", "n", "winner_accuracy", "avg_log_loss", "avg_brier", "home_baseline_accuracy", "generated", "source"}`.

- [ ] **Step 1: Write the failing tests**

`ml/sports/origin/backtest_test.py`:

```python
"""Origin walk-forward backtest + tuner, on synthetic histories."""
from datetime import datetime, timezone

import pytest

from ml.sports.nrl.model import NrlParams
from ml.sports.origin.backtest import load_backtest_record, tune, walk_forward


def _game(season, rnd, home_id, away_id, sh, sa, neutral=False):
    return {"home_id": home_id, "away_id": away_id, "score_home": sh,
            "score_away": sa, "neutral": neutral,
            "kickoff_utc": datetime(season, 5 + rnd, 1, tzinfo=timezone.utc)}


def _dominant_history(n_seasons=8, start=2000):
    """Team 0 always wins by 20 at home and away — a perfectly learnable signal."""
    hist = {}
    for i in range(n_seasons):
        s = start + i
        hist[s] = [
            _game(s, 1, 0, 1, 30, 10),
            _game(s, 2, 1, 0, 10, 30),
            _game(s, 3, 0, 1, 30, 10),
        ]
    return hist


def test_walk_forward_learns_dominant_team():
    out = walk_forward(_dominant_history(), NrlParams(), score_from=2003)
    assert out["n"] == 15  # 5 scored seasons x 3
    assert out["winner_accuracy"] == 1.0
    assert out["avg_log_loss"] < 0.69  # better than a coin flip
    assert out["span"] == [2003, 2007]


def test_walk_forward_home_baseline_differs_from_model():
    # The dominant team wins even away, so always-pick-home is wrong 1/3 of the time.
    out = walk_forward(_dominant_history(), NrlParams(), score_from=2003)
    assert out["home_baseline_accuracy"] == pytest.approx(2 / 3)


def test_walk_forward_respects_neutral_flag():
    hist = {2000: [_game(2000, 1, 0, 1, 20, 20)]}  # single drawn game
    p = NrlParams(home_adv=100.0)
    scored = walk_forward(hist, p, score_from=2000)
    neutral_hist = {2000: [_game(2000, 1, 0, 1, 20, 20, neutral=True)]}
    scored_neutral = walk_forward(neutral_hist, p, score_from=2000)
    # With a draw outcome, log loss depends only on p_draw (same both runs),
    # but the baseline pick and brier differ through the home probability.
    assert scored["avg_brier"] != scored_neutral["avg_brier"]


def test_tune_returns_params_and_runs_on_tiny_grid():
    tuned = tune(_dominant_history(), val_from=2005,
                 grid={"k": [36.0], "home_adv": [30.0], "margin_mult_cap": [2.2],
                       "season_regress": [0.10], "p_draw": [0.02]})
    assert isinstance(tuned, NrlParams)
    assert tuned.k == 36.0 and tuned.version == "origin-elo-v0.1"


def test_load_backtest_record_missing_file_is_none(tmp_path, monkeypatch):
    import ml.sports.origin.backtest as bt
    monkeypatch.setattr(bt, "_RECORD_FILE", tmp_path / "backtest_record.json")
    assert load_backtest_record() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/sports/origin/backtest_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.sports.origin.backtest'`

- [ ] **Step 3: Write `ml/sports/origin/backtest.py`**

```python
"""Origin walk-forward backtest + coordinate-descent tuner (design 2026-07-11).

DB-free: replays the committed seed file. One chronological walk (43 seasons,
3 games each — trivially small): for scored seasons, predict-before-update
(leak-free, same rule as ml/sports/nrl/backtest.py), applying regress_season
at season boundaries and the neutral flag on interstate venues.

The first seasons are burn-in (ratings still settling from the 1500 seed), so
scoring starts at `score_from` (default 1985). The tuner scores seasons >=
val_from only, giving a chronological train/validate split.

Retrodictions produced here NEVER enter the DB — the summary is written to
backtest_record.json (committed) and served as the labeled "backtest" segment
of /api/nrl/origin/record.

CLI: PYTHONPATH=backend:. python -m ml.sports.origin.backtest --tune --write
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from ml.sports.nrl.model import NrlParams, predict, regress_season, update
from ml.sports.origin.params import ORIGIN_DEFAULTS, save_origin_params
from ml.sports.origin.venues import is_neutral
from pipeline.sports.origin_names import TEAM_INDEX

log = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parents[3] / "data" / "raw" / "state_of_origin_history.json"
_RECORD_FILE = Path(__file__).with_name("backtest_record.json")
_EPS = 1e-15

_K_GRID = [24.0, 36.0, 48.0, 64.0]
_HOME_ADV_GRID = [10.0, 20.0, 30.0, 45.0]
_MARGIN_CAP_GRID = [1.8, 2.2, 2.6]
_SEASON_REGRESS_GRID = [0.0, 0.10, 0.25]
_P_DRAW_GRID = [0.01, 0.02, 0.035]


def load_history(path: Path = SEED_FILE) -> dict[int, list[dict]]:
    """Seed file -> replay rows keyed by season (TEAM_INDEX ids, parsed
    kickoffs, neutral flags)."""
    data = json.loads(path.read_text())
    history: dict[int, list[dict]] = {}
    for m in data["matches"]:
        history.setdefault(m["season"], []).append({
            "home_id": TEAM_INDEX[m["home_team"]],
            "away_id": TEAM_INDEX[m["away_team"]],
            "score_home": m["score_home"],
            "score_away": m["score_away"],
            "neutral": is_neutral(m["venue"]),
            "kickoff_utc": datetime.strptime(
                m["kickoff_utc"], "%Y-%m-%d %H:%M:%SZ"
            ).replace(tzinfo=timezone.utc),
        })
    return history


def _result_index(sh: int, sa: int) -> int:
    return 0 if sh > sa else 2 if sh < sa else 1


def _clamp(p: float) -> float:
    return max(_EPS, min(1 - _EPS, p))


def walk_forward(
    history: dict[int, list[dict]], params: NrlParams, score_from: int = 1985
) -> dict:
    """Chronological replay; seasons >= score_from are scored (model + an
    always-pick-the-designated-home-side baseline), earlier ones are burn-in."""
    running: dict[int, float] = {}
    ll_sum = brier_sum = 0.0
    correct = home_correct = n = 0
    first = True

    for season in sorted(history):
        if not first:
            running = regress_season(running, params)
        first = False
        for m in sorted(history[season], key=lambda x: x["kickoff_utc"]):
            elo_h = running.get(m["home_id"], 1500.0)
            elo_a = running.get(m["away_id"], 1500.0)
            if season >= score_from:
                out = predict(elo_h, elo_a, params, neutral=m["neutral"])
                probs = (out["p_home"], out["p_draw"], out["p_away"])
                idx = _result_index(m["score_home"], m["score_away"])
                ll_sum += -math.log(_clamp(probs[idx]))
                brier_sum += sum(
                    (p - (1.0 if i == idx else 0.0)) ** 2 for i, p in enumerate(probs)
                )
                predicted = max(range(3), key=lambda i: (probs[i], -i))
                correct += int(predicted == idx)
                home_correct += int(idx == 0)
                n += 1
            new_h, new_a = update(
                elo_h, elo_a, m["score_home"], m["score_away"], params,
                neutral=m["neutral"],
            )
            running[m["home_id"]] = new_h
            running[m["away_id"]] = new_a

    return {
        "n": n,
        "winner_accuracy": correct / n if n else float("nan"),
        "avg_log_loss": ll_sum / n if n else float("nan"),
        "avg_brier": brier_sum / n if n else float("nan"),
        "home_baseline_accuracy": home_correct / n if n else float("nan"),
        "span": [score_from, max(history)] if history else [score_from, score_from],
    }


def tune(
    history: dict[int, list[dict]], val_from: int = 2015, grid: dict | None = None
) -> NrlParams:
    """Coordinate-descent the W/D/L-relevant knobs against validation log loss
    (all matches in seasons >= val_from), starting from ORIGIN_DEFAULTS. Two
    sweeps, same style as ml/sports/nrl/backtest.tune. margin_slope/sigma
    stay at defaults (they don't feed the 3-way objective)."""
    g = grid or {}
    grids = {
        "k": g.get("k", _K_GRID),
        "home_adv": g.get("home_adv", _HOME_ADV_GRID),
        "margin_mult_cap": g.get("margin_mult_cap", _MARGIN_CAP_GRID),
        "season_regress": g.get("season_regress", _SEASON_REGRESS_GRID),
        "p_draw": g.get("p_draw", _P_DRAW_GRID),
    }

    def val_logloss(p: NrlParams) -> float:
        return walk_forward(history, p, score_from=val_from)["avg_log_loss"]

    params = ORIGIN_DEFAULTS

    def best_on(field: str) -> float:
        best_v, best_ll = getattr(params, field), float("inf")
        for v in grids[field]:
            ll = val_logloss(replace(params, **{field: v}))
            if ll < best_ll:
                best_ll, best_v = ll, v
        return best_v

    for _ in range(2):
        for field in ("k", "home_adv", "margin_mult_cap", "season_regress", "p_draw"):
            params = replace(params, **{field: best_on(field)})

    return params


def load_backtest_record() -> dict | None:
    """The committed backtest artifact, or None if absent/corrupt."""
    try:
        return json.loads(_RECORD_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tune", action="store_true", help="fit params before reporting")
    ap.add_argument("--write", action="store_true",
                    help="write params.json + backtest_record.json")
    args = ap.parse_args()

    history = load_history()
    params = tune(history) if args.tune else ORIGIN_DEFAULTS
    report = walk_forward(history, params, score_from=1985)

    log.info("params: %s", params)
    log.info("backtest 1985-%s: n=%d acc=%.3f ll=%.4f brier=%.4f home-baseline=%.3f",
             report["span"][1], report["n"], report["winner_accuracy"],
             report["avg_log_loss"], report["home_baseline_accuracy"])

    if args.write:
        save_origin_params(params)
        _RECORD_FILE.write_text(json.dumps({
            "model_version": params.version,
            "span": report["span"],
            "n": report["n"],
            "winner_accuracy": round(report["winner_accuracy"], 4),
            "avg_log_loss": round(report["avg_log_loss"], 4),
            "avg_brier": round(report["avg_brier"], 4),
            "home_baseline_accuracy": round(report["home_baseline_accuracy"], 4),
            "generated": date.today().isoformat(),
            "source": "walk-forward backtest over data/raw/state_of_origin_history.json",
        }, indent=2) + "\n")
        log.info("wrote %s and params.json", _RECORD_FILE.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest ml/sports/origin -v`
Expected: all PASS

- [ ] **Step 5: Run the real tune + backtest and commit artifacts**

```bash
PYTHONPATH=backend:. .venv/bin/python -m ml.sports.origin.backtest --tune --write
```

Sanity gates on the printed report — **all three must hold, else STOP and report back instead of committing**:
1. `avg_log_loss < 1.0986` (better than uniform 1/3-1/3-1/3),
2. `winner_accuracy > home_baseline_accuracy` is *expected but not required* — if it fails, still stop and report (the evidence decides whether shipping a backtest page makes sense),
3. `n == 120` (129 games minus the 1982–84 burn-in seasons).

Then:

```bash
git add ml/sports/origin/backtest.py ml/sports/origin/backtest_test.py \
        ml/sports/origin/params.json ml/sports/origin/backtest_record.json
git commit -m "feat(origin): walk-forward backtest, tuned params + committed record"
```

---

### Task 5: Prediction pipeline — `origin_predict.py`

**Files:**
- Modify: `pipeline/sports/nrl_predict.py` (function `grade` only: add `sport` kwarg)
- Create: `pipeline/sports/origin_predict.py`
- Create: `pipeline/sports/origin_predict_test.py`

**Interfaces:**
- Consumes: `nrl_predict._kickoff_key`, `nrl_predict._write_prediction`, `nrl_predict.grade`; `load_origin_params`, `is_neutral`, model fns.
- Produces:
  - `nrl_predict.grade(db, sport: str = SPORT)` — backward-compatible kwarg.
  - `origin_predict.generate(db, params=None) -> int`, `origin_predict.grade(db) -> int`, CLI `--generate --grade`.

- [ ] **Step 1: Write the failing tests**

`pipeline/sports/origin_predict_test.py`:

```python
"""Origin frozen shadow predictions + grading (mirrors nrl_predict_test's
fixtures, sport="origin")."""
from datetime import datetime, timezone

import pytest

from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam
from pipeline.sports.origin_predict import SPORT, generate, grade


@pytest.fixture
def teams(db_session):
    nsw = SportTeam(sport=SPORT, name="NSW Blues")
    qld = SportTeam(sport=SPORT, name="QLD Maroons")
    db_session.add_all([nsw, qld])
    db_session.flush()
    return nsw, qld


def _match(db, teams, season, rnd, status="scheduled", sh=None, sa=None,
           venue="Suncorp Stadium", kickoff=None):
    nsw, qld = teams
    m = SportMatch(sport=SPORT, season=season, round=rnd, match_no=rnd,
                   kickoff_utc=kickoff or datetime(season, 5, 20 + rnd, 9, tzinfo=timezone.utc),
                   venue=venue, home_team_id=qld.id, away_team_id=nsw.id,
                   score_home=sh, score_away=sa, status=status)
    db.add(m)
    db.flush()
    return m


def test_generate_writes_shadow_prediction_for_scheduled_only(db_session, teams):
    _match(db_session, teams, 2027, 1, status="finished", sh=20, sa=10)
    scheduled = _match(db_session, teams, 2027, 2)
    db_session.commit()

    assert generate(db_session) == 1
    pred = db_session.query(SportPrediction).one()
    assert pred.match_id == scheduled.id
    assert pred.is_shadow is True
    assert pred.model_version == "origin-elo-v0.1"
    assert 0 < pred.p_home < 1 and pred.p_home + pred.p_draw + pred.p_away == pytest.approx(1.0)


def test_generate_is_idempotent(db_session, teams):
    _match(db_session, teams, 2027, 1)
    db_session.commit()
    assert generate(db_session) == 1
    assert generate(db_session) == 0  # unchanged Elo state -> no new row


def test_neutral_venue_flattens_home_edge(db_session, teams):
    home_ground = _match(db_session, teams, 2027, 1, venue="Suncorp Stadium")
    neutral = _match(db_session, teams, 2027, 2, venue="Melbourne Cricket Ground")
    db_session.commit()
    generate(db_session)

    p_home_ground = db_session.query(SportPrediction).filter_by(match_id=home_ground.id).one()
    p_neutral = db_session.query(SportPrediction).filter_by(match_id=neutral.id).one()
    # Equal fresh Elos: home edge only exists at the home ground.
    assert p_home_ground.p_home > p_home_ground.p_away
    assert p_neutral.p_home == pytest.approx(p_neutral.p_away)


def test_grade_scores_pre_kickoff_prediction_once(db_session, teams):
    kickoff = datetime(2027, 5, 21, 9, tzinfo=timezone.utc)
    m = _match(db_session, teams, 2027, 1, kickoff=kickoff)
    db_session.add(SportPrediction(
        match_id=m.id, model_version="origin-elo-v0.1",
        created_at=datetime(2027, 5, 20, 9, tzinfo=timezone.utc),
        p_home=0.6, p_draw=0.02, p_away=0.38, expected_margin=4.0))
    db_session.commit()
    m.status = "finished"
    m.score_home, m.score_away = 22, 12
    db_session.commit()

    assert grade(db_session) == 1
    r = db_session.query(SportPredictionResult).one()
    assert r.outcome == "home" and r.winner_correct is True
    assert grade(db_session) == 0  # never re-grades
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/sports/origin_predict_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.origin_predict'`

- [ ] **Step 3: Parameterize `nrl_predict.grade`**

In `pipeline/sports/nrl_predict.py`, change only the signature and the one query:

```python
def grade(db: Session, sport: str = SPORT) -> int:
```
and inside, `filter_by(sport=SPORT, status="finished")` → `filter_by(sport=sport, status="finished")`. Add one docstring sentence: "`sport` scopes the sweep; other verticals (origin) reuse this exact grading path."

- [ ] **Step 4: Write `pipeline/sports/origin_predict.py`**

```python
"""Origin frozen shadow prediction generation + grading (design 2026-07-11).

Mirror of pipeline.sports.nrl_predict scoped to sport="origin", with two
Origin-specific twists: params come from ml.sports.origin.params and each
fixture carries a neutral-venue flag (ml.sports.origin.venues.is_neutral)
through both replay (update) and prediction (predict). Grading reuses
nrl_predict.grade(sport="origin") verbatim — same pre-kickoff backstop,
same append-only ledger. The frozen-prediction hard guard lives in the
shared _write_prediction. No probability snapshots (movers doesn't cover
origin, by design).

CLI: python -m pipeline.sports.origin_predict --generate --grade
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy.orm import Session

from app.models import SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams, predict, regress_season, update
from ml.sports.origin.params import load_origin_params
from ml.sports.origin.venues import is_neutral
from pipeline.sports import nrl_predict
from pipeline.sports.nrl_predict import _kickoff_key, _write_prediction

log = logging.getLogger(__name__)

SPORT = "origin"
_DEDUP_TOL = 1e-9


def _current_elos(db: Session, params: NrlParams) -> dict[int, float]:
    """Replay every finished origin match in kickoff order (season-boundary
    regression + neutral flags) to the CURRENT per-team Elo state."""
    finished = db.query(SportMatch).filter_by(sport=SPORT, status="finished").all()
    finished.sort(key=_kickoff_key)

    elos: dict[int, float] = {}
    current_season: int | None = None
    for m in finished:
        if current_season is not None and m.season != current_season:
            elos = regress_season(elos, params)
        current_season = m.season
        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        new_home, new_away = update(
            elo_home, elo_away, m.score_home, m.score_away, params,
            neutral=is_neutral(m.venue),
        )
        elos[m.home_team_id] = new_home
        elos[m.away_team_id] = new_away
    return elos


def _sync_team_elos(db: Session, elos: dict[int, float]) -> int:
    """Display-cache sync, same contract as nrl_predict._sync_team_elos."""
    ids = [team_id for team_id in elos if team_id is not None]
    if not ids:
        return 0
    changed = 0
    for team in db.query(SportTeam).filter(
        SportTeam.sport == SPORT, SportTeam.id.in_(ids)
    ):
        new = elos[team.id]
        if team.elo_rating is None or abs(team.elo_rating - new) > _DEDUP_TOL:
            team.elo_rating = new
            changed += 1
    return changed


def generate(db: Session, params: NrlParams | None = None) -> int:
    """Predict every scheduled origin match from current Elo state. Returns
    the number of SportPrediction rows written this run."""
    params = params or load_origin_params()
    elos = _current_elos(db, params)
    synced = _sync_team_elos(db, elos)
    if synced:
        log.info("elo sync: %d team rating(s) updated", synced)

    written = 0
    for m in db.query(SportMatch).filter_by(sport=SPORT, status="scheduled").all():
        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        out = predict(elo_home, elo_away, params, neutral=is_neutral(m.venue))
        if _write_prediction(db, m, params, out):
            written += 1

    db.commit()
    return written


def grade(db: Session) -> int:
    """Grade finished origin matches against their latest pre-kickoff
    prediction — nrl_predict.grade scoped to this sport."""
    return nrl_predict.grade(db, sport=SPORT)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--grade", action="store_true")
    args = ap.parse_args()
    if not args.generate and not args.grade:
        ap.error("pass --generate, --grade, or both")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.generate:
            log.info("generate: %d prediction row(s) written", generate(db))
        if args.grade:
            log.info("grade: %d result row(s) written", grade(db))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run new tests AND the NRL predict tests**

Run: `.venv/bin/python -m pytest pipeline/sports/origin_predict_test.py pipeline/sports/nrl_predict_test.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/sports/nrl_predict.py pipeline/sports/origin_predict.py pipeline/sports/origin_predict_test.py
git commit -m "feat(origin): frozen shadow predictions + grading via shared ledger path"
```

---

### Task 6: API — `/api/nrl/origin/series` and `/api/nrl/origin/record`

**Files:**
- Modify: `backend/app/api/sports.py`
- Create: `backend/tests/test_origin_api.py`

**Interfaces:**
- Consumes: `series_odds` (Task 3), `load_backtest_record` (Task 4), `load_origin_params`, `is_neutral`, `wilson_ci95` (already imported in sports.py).
- Produces (response shapes the frontend binds to in Task 7):
  - `GET /api/nrl/origin/series?season=` →
    `{"season": int, "seasons": [int], "games": [{"round", "match_no", "kickoff_utc", "venue", "neutral", "home", "away", "score_home", "score_away", "status", "prediction"}], "series": {"blues_wins": int, "maroons_wins": int, "drawn_games": int, "winner": str|null, "odds": {"blues", "maroons", "drawn"}|null}, "disclaimer": str}`
    — `prediction` uses the exact NRL prediction dict shape. `winner` ∈ {"NSW Blues", "QLD Maroons", "drawn", null}. `odds` present only when ≥1 game is unplayed AND every unplayed game has a prediction.
  - `GET /api/nrl/origin/record` → `{"backtest": <backtest_record.json contents>|null, "live": {"evaluated_matches", "winner_accuracy", "winner_accuracy_ci95", "avg_log_loss", "avg_brier", "best_streak", "last_updated"}, "model_version": str, "disclaimer": str}`
  - Internal refactor: `_ledger_record(db, sport: str) -> dict` extracted from `nrl_model_record`, which now composes it — `/api/nrl/model/record`'s response shape is unchanged.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_origin_api.py`:

```python
"""GET /api/nrl/origin/series and /origin/record — mirrors test_sports_api.py's
fixture style, scoped to sport="origin"."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client():
    TestingSession = _make_session()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    yield TestClient(app), TestingSession
    cache.clear()
    app.dependency_overrides.clear()


def _seed_series(db, season, results):
    """results: list of (home_name, away_name, sh, sa, status, venue)."""
    teams = {}
    for name in ("NSW Blues", "QLD Maroons"):
        t = SportTeam(sport="origin", name=name)
        db.add(t)
        db.flush()
        teams[name] = t
    matches = []
    for i, (home, away, sh, sa, status, venue) in enumerate(results, start=1):
        m = SportMatch(sport="origin", season=season, round=i, match_no=i,
                       kickoff_utc=datetime(season, 5, 20 + i * 20, 10, tzinfo=timezone.utc),
                       venue=venue, home_team_id=teams[home].id,
                       away_team_id=teams[away].id,
                       score_home=sh, score_away=sa, status=status)
        db.add(m)
        db.flush()
        matches.append(m)
    db.commit()
    return teams, matches


def test_series_404_when_no_origin_data(client):
    c, _ = client
    r = c.get("/api/nrl/origin/series")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "no_origin_data"


def test_finished_series_score_winner_and_no_odds(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_series(db, 2026, [
        ("NSW Blues", "QLD Maroons", 22, 20, "finished", "Accor Stadium"),
        ("NSW Blues", "QLD Maroons", 24, 44, "finished", "Melbourne Cricket Ground"),
        ("QLD Maroons", "NSW Blues", 12, 30, "finished", "Suncorp Stadium"),
    ])
    r = c.get("/api/nrl/origin/series", params={"season": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2026 and body["seasons"] == [2026]
    assert body["series"] == {"blues_wins": 2, "maroons_wins": 1, "drawn_games": 0,
                              "winner": "NSW Blues", "odds": None}
    assert body["games"][1]["neutral"] is True   # MCG
    assert body["games"][0]["neutral"] is False


def test_live_series_has_odds_mapped_to_blues_orientation(client):
    c, TestingSession = client
    db = TestingSession()
    teams, matches = _seed_series(db, 2027, [
        ("QLD Maroons", "NSW Blues", 20, 10, "finished", "Suncorp Stadium"),
        ("NSW Blues", "QLD Maroons", None, None, "scheduled", "Accor Stadium"),
        ("QLD Maroons", "NSW Blues", None, None, "scheduled", "Suncorp Stadium"),
    ])
    for m, (ph, pd, pa) in zip(matches[1:], [(0.6, 0.02, 0.38), (0.38, 0.02, 0.6)]):
        db.add(SportPrediction(match_id=m.id, model_version="origin-elo-v0.1",
                               created_at=datetime(2027, 5, 1, tzinfo=timezone.utc),
                               p_home=ph, p_draw=pd, p_away=pa, expected_margin=3.0))
    db.commit()

    body = c.get("/api/nrl/origin/series", params={"season": 2027}).json()
    s = body["series"]
    assert s["blues_wins"] == 0 and s["maroons_wins"] == 1 and s["winner"] is None
    odds = s["odds"]
    assert odds is not None
    # Game 2: blues are HOME (p_blues=0.6); game 3: blues are AWAY (p_blues=0.6).
    # Maroons lead 1-0, so maroons odds must exceed blues odds overall.
    assert odds["maroons"] > odds["blues"]
    assert odds["blues"] + odds["maroons"] + odds["drawn"] == pytest.approx(1.0, abs=1e-6)


def test_series_odds_null_when_a_scheduled_game_lacks_prediction(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_series(db, 2027, [
        ("QLD Maroons", "NSW Blues", None, None, "scheduled", "Suncorp Stadium"),
        ("NSW Blues", "QLD Maroons", None, None, "scheduled", "Accor Stadium"),
        ("QLD Maroons", "NSW Blues", None, None, "scheduled", "Suncorp Stadium"),
    ])
    body = c.get("/api/nrl/origin/series", params={"season": 2027}).json()
    assert body["series"]["odds"] is None


def test_drawn_series_reports_drawn_winner(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_series(db, 1999, [
        ("QLD Maroons", "NSW Blues", 9, 8, "finished", None),
        ("NSW Blues", "QLD Maroons", 10, 10, "finished", None),
        ("QLD Maroons", "NSW Blues", 8, 20, "finished", None),
    ])
    body = c.get("/api/nrl/origin/series", params={"season": 1999}).json()
    assert body["series"] == {"blues_wins": 1, "maroons_wins": 1, "drawn_games": 1,
                              "winner": "drawn", "odds": None}


def test_record_has_backtest_and_empty_live_segments(client):
    c, _ = client
    r = c.get("/api/nrl/origin/record")
    assert r.status_code == 200
    body = r.json()
    # backtest artifact is committed in-repo (Task 4), so it must load.
    assert body["backtest"] is not None
    assert body["backtest"]["n"] > 100
    assert set(body["backtest"]) >= {"model_version", "span", "n", "winner_accuracy",
                                     "avg_log_loss", "avg_brier", "home_baseline_accuracy"}
    assert body["live"]["evaluated_matches"] == 0
    assert body["live"]["winner_accuracy"] is None
    assert body["model_version"] == "origin-elo-v0.1"


def test_nrl_model_record_unchanged_by_refactor(client):
    c, _ = client
    r = c.get("/api/nrl/model/record")
    assert r.status_code == 200
    assert set(r.json()) == {"evaluated_matches", "winner_accuracy", "winner_accuracy_ci95",
                             "avg_log_loss", "avg_brier", "best_streak", "model_version",
                             "last_updated", "disclaimer"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_origin_api.py -v`
Expected: FAIL — 404s on `/api/nrl/origin/*` routes

- [ ] **Step 3: Implement in `backend/app/api/sports.py`**

`sports.py` defers its `ml` imports into function bodies (see `nrl_model_record`); follow that idiom — `origin_series` starts with `from ml.sports.origin.series import series_odds` and `from ml.sports.origin.venues import is_neutral` inside the function.

Extract the ledger aggregation (place above `nrl_model_record`):

```python
_ORIGIN_SPORT = "origin"
_BLUES = "NSW Blues"
_MAROONS = "QLD Maroons"


def _ledger_record(db: Session, sport: str) -> dict:
    """Aggregate the graded SportPredictionResult ledger for one sport —
    shared by /model/record (nrl) and /origin/record (live segment)."""
    rows = (
        db.query(SportPredictionResult, SportMatch)
        .join(SportMatch, SportPredictionResult.match_id == SportMatch.id)
        .filter(SportMatch.sport == sport)
        .order_by(SportPredictionResult.evaluated_at.asc())
        .all()
    )
    n = len(rows)
    if n == 0:
        return {
            "evaluated_matches": 0, "winner_accuracy": None,
            "winner_accuracy_ci95": None, "avg_log_loss": None,
            "avg_brier": None, "best_streak": 0, "last_updated": None,
        }
    winners = sum(1 for r, _ in rows if r.winner_correct)
    by_kickoff = sorted(rows, key=lambda t: (t[1].kickoff_utc is None, t[1].kickoff_utc, t[1].id))
    best_streak = streak = 0
    for r, _ in by_kickoff:
        streak = streak + 1 if r.winner_correct else 0
        best_streak = max(best_streak, streak)
    last_updated = max(r.evaluated_at for r, _ in rows)
    return {
        "evaluated_matches": n,
        "winner_accuracy": round(winners / n, 4),
        "winner_accuracy_ci95": wilson_ci95(winners, n),
        "avg_log_loss": round(sum(r.log_loss for r, _ in rows) / n, 4),
        "avg_brier": round(sum(r.brier for r, _ in rows) / n, 4),
        "best_streak": best_streak,
        "last_updated": last_updated.isoformat() if last_updated else None,
    }
```

Rewrite `nrl_model_record`'s body to use it (identical response shape):

```python
@router.get("/model/record")
def nrl_model_record(db: Session = Depends(get_db)):
    from ml.sports.nrl.params import load_nrl_params

    return {
        **_ledger_record(db, "nrl"),
        "model_version": load_nrl_params().version,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

Add the two Origin endpoints (place after `nrl_model_record`):

```python
@router.get("/origin/series")
def origin_series(season: int | None = None, db: Session = Depends(get_db)):
    """One State of Origin series: games with latest predictions, series
    score, and — while games remain — exact series-winner odds."""
    from ml.sports.origin.series import series_odds
    from ml.sports.origin.venues import is_neutral

    seasons = [
        s for (s,) in db.query(SportMatch.season)
        .filter(SportMatch.sport == _ORIGIN_SPORT)
        .distinct().order_by(SportMatch.season.desc()).all()
    ]
    if not seasons:
        raise HTTPException(status_code=404, detail={
            "code": "no_origin_data", "message": "No State of Origin matches are loaded yet",
        })
    if season is None:
        season = seasons[0]
    elif season not in seasons:
        raise HTTPException(status_code=404, detail={
            "code": "season_not_found",
            "message": f"No State of Origin matches for season {season}",
        })

    home = aliased(SportTeam)
    away = aliased(SportTeam)
    rows = (
        db.query(SportMatch, home.name, away.name)
        .outerjoin(home, SportMatch.home_team_id == home.id)
        .outerjoin(away, SportMatch.away_team_id == away.id)
        .filter(SportMatch.sport == _ORIGIN_SPORT, SportMatch.season == season)
        .order_by(SportMatch.round.asc(), SportMatch.match_no.asc())
        .all()
    )

    match_ids = [m.id for m, _, _ in rows]
    preds = (
        db.query(SportPrediction)
        .filter(SportPrediction.match_id.in_(match_ids))
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .all()
    )
    latest_pred_by_match: dict[int, SportPrediction] = {}
    for p in preds:
        latest_pred_by_match.setdefault(p.match_id, p)

    games = []
    blues_wins = maroons_wins = drawn_games = 0
    remaining: list[tuple[float, float, float]] | None = []
    for m, home_name, away_name in rows:
        pred = latest_pred_by_match.get(m.id)
        pred_out = None
        if pred is not None:
            pred_out = {
                "p_home": pred.p_home, "p_draw": pred.p_draw, "p_away": pred.p_away,
                "expected_margin": pred.expected_margin,
                "model_version": pred.model_version,
                "created_at": pred.created_at.isoformat() if pred.created_at else None,
                "is_shadow": pred.is_shadow,
            }
        games.append({
            "round": m.round, "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue, "neutral": is_neutral(m.venue),
            "home": home_name, "away": away_name,
            "score_home": m.score_home, "score_away": m.score_away,
            "status": m.status, "prediction": pred_out,
        })
        if m.status == "finished" and m.score_home is not None:
            if m.score_home == m.score_away:
                drawn_games += 1
            elif (m.score_home > m.score_away) == (home_name == _BLUES):
                blues_wins += 1
            else:
                maroons_wins += 1
        else:
            # Unplayed: orient the game's probability triple to the Blues.
            if pred is None:
                remaining = None  # any unpredicted game -> no honest series odds
            elif remaining is not None:
                if home_name == _BLUES:
                    remaining.append((pred.p_home, pred.p_draw, pred.p_away))
                else:
                    remaining.append((pred.p_away, pred.p_draw, pred.p_home))

    all_finished = all(g["status"] == "finished" for g in games)
    winner = None
    if games and all_finished:
        winner = (_BLUES if blues_wins > maroons_wins
                  else _MAROONS if maroons_wins > blues_wins else "drawn")

    odds = None
    if remaining:  # non-empty list => at least one unplayed game, all predicted
        raw = series_odds(blues_wins, maroons_wins, remaining)
        odds = {"blues": round(raw["p_a"], 4), "maroons": round(raw["p_b"], 4),
                "drawn": round(raw["p_drawn"], 4)}

    return {
        "season": season,
        "seasons": seasons,
        "games": games,
        "series": {"blues_wins": blues_wins, "maroons_wins": maroons_wins,
                   "drawn_games": drawn_games, "winner": winner, "odds": odds},
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


@router.get("/origin/record")
def origin_record(db: Session = Depends(get_db)):
    """Two honestly-labeled segments: `backtest` (committed walk-forward
    artifact — retrodictions, never DB rows) and `live` (the real graded
    ledger, empty until 2027+ predictions grade)."""
    from ml.sports.origin.backtest import load_backtest_record
    from ml.sports.origin.params import load_origin_params

    return {
        "backtest": load_backtest_record(),
        "live": _ledger_record(db, _ORIGIN_SPORT),
        "model_version": load_origin_params().version,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

- [ ] **Step 4: Run new tests AND every existing sports/NRL API test**

Run: `.venv/bin/python -m pytest backend/tests/test_origin_api.py backend/tests/test_sports_api.py backend/tests/test_nrl_ladder_api.py backend/tests/test_nrl_team_api.py -v`
Expected: all PASS (the `/model/record` refactor must not change its shape)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/sports.py backend/tests/test_origin_api.py
git commit -m "feat(origin): series + record API endpoints, shared ledger aggregation"
```

---

### Task 7: Frontend — types, fetchers, `/nrl/origin` page, NRL-home entry card

**Files:**
- Modify: `frontend/lib/types.ts` (append after the NRL types), `frontend/lib/api.ts` (after the NRL fetchers), `frontend/app/nrl/page.tsx`
- Create: `frontend/app/nrl/origin/page.tsx`, `frontend/app/nrl/origin/page.test.tsx`

**Interfaces:**
- Consumes: API shapes from Task 6; existing `getServer`, `NrlPrediction` type.
- Produces: `OriginGame`, `OriginSeriesState`, `OriginSeriesResponse`, `OriginBacktest`, `OriginLiveRecord`, `OriginRecord` types; `getOriginSeriesServer(season?)`, `getOriginRecordServer()` fetchers.

- [ ] **Step 1: Add types** (append to `frontend/lib/types.ts` after `NrlRecord`)

```typescript
/** /api/nrl/origin/* shapes (backend/app/api/sports.py). */
export interface OriginGame {
  round: number | null;
  match_no: number;
  kickoff_utc: string | null;
  venue: string | null;
  neutral: boolean;
  home: string | null;
  away: string | null;
  score_home: number | null;
  score_away: number | null;
  status: string;
  prediction: NrlPrediction | null;
}
export interface OriginSeriesState {
  blues_wins: number;
  maroons_wins: number;
  drawn_games: number;
  winner: string | null;
  odds: { blues: number; maroons: number; drawn: number } | null;
}
export interface OriginSeriesResponse {
  season: number;
  seasons: number[];
  games: OriginGame[];
  series: OriginSeriesState;
  disclaimer: string;
}
export interface OriginBacktest {
  model_version: string;
  span: [number, number];
  n: number;
  winner_accuracy: number;
  avg_log_loss: number;
  avg_brier: number;
  home_baseline_accuracy: number;
  generated: string;
  source: string;
}
export interface OriginLiveRecord {
  evaluated_matches: number;
  winner_accuracy: number | null;
  winner_accuracy_ci95: [number, number] | null;
  avg_log_loss: number | null;
  avg_brier: number | null;
  best_streak: number;
  last_updated: string | null;
}
export interface OriginRecord {
  backtest: OriginBacktest | null;
  live: OriginLiveRecord;
  model_version: string;
  disclaimer: string;
}
```

- [ ] **Step 2: Add fetchers** (append to `frontend/lib/api.ts` after `getNrlRecordServer`; extend the type import list at the top with `OriginRecord, OriginSeriesResponse`)

```typescript
/** State of Origin (design 2026-07-11): series view + two-segment record. */
export const getOriginSeriesServer = (season?: number) =>
  getServer<OriginSeriesResponse>(
    `/api/nrl/origin/series${season ? `?season=${season}` : ""}`, 300);
export const getOriginRecordServer = () =>
  getServer<OriginRecord>("/api/nrl/origin/record", 300);
```

- [ ] **Step 3: Write the failing page test**

`frontend/app/nrl/origin/page.test.tsx`:

```tsx
/** Origin page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import OriginPage from "./page";
import { getOriginRecordServer, getOriginSeriesServer } from "@/lib/api";
import type { OriginRecord, OriginSeriesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockSeries = getOriginSeriesServer as jest.MockedFunction<typeof getOriginSeriesServer>;
const mockRecord = getOriginRecordServer as jest.MockedFunction<typeof getOriginRecordServer>;

const series: OriginSeriesResponse = {
  season: 2026,
  seasons: [2026, 2025],
  games: [
    {
      round: 1, match_no: 1, kickoff_utc: "2026-05-27T10:05:00+00:00",
      venue: "Accor Stadium", neutral: false, home: "NSW Blues", away: "QLD Maroons",
      score_home: 22, score_away: 20, status: "finished",
      prediction: { p_home: 0.55, p_draw: 0.02, p_away: 0.43, expected_margin: 3.1,
                    model_version: "origin-elo-v0.1", created_at: null, is_shadow: true },
    },
    {
      round: 2, match_no: 2, kickoff_utc: "2026-06-17T10:05:00+00:00",
      venue: "Melbourne Cricket Ground", neutral: true, home: "NSW Blues",
      away: "QLD Maroons", score_home: 24, score_away: 44, status: "finished",
      prediction: null,
    },
    {
      round: 3, match_no: 3, kickoff_utc: "2026-07-08T10:05:00+00:00",
      venue: "Suncorp Stadium", neutral: false, home: "QLD Maroons", away: "NSW Blues",
      score_home: 12, score_away: 30, status: "finished", prediction: null,
    },
  ],
  series: { blues_wins: 2, maroons_wins: 1, drawn_games: 0, winner: "NSW Blues", odds: null },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const record: OriginRecord = {
  backtest: {
    model_version: "origin-elo-v0.1", span: [1985, 2024], n: 120,
    winner_accuracy: 0.6, avg_log_loss: 0.66, avg_brier: 0.46,
    home_baseline_accuracy: 0.52, generated: "2026-07-11", source: "walk-forward",
  },
  live: { evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
          avg_log_loss: null, avg_brier: null, best_streak: 0, last_updated: null },
  model_version: "origin-elo-v0.1",
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

beforeEach(() => {
  mockSeries.mockResolvedValue(series);
  mockRecord.mockResolvedValue(record);
});

it("renders the series score, winner and games", async () => {
  render(await OriginPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByRole("heading", { name: /state of origin/i })).toBeInTheDocument();
  expect(screen.getByText(/NSW Blues win the series 2–1/i)).toBeInTheDocument();
  expect(screen.getByText(/Game 2/)).toBeInTheDocument();
  expect(screen.getByText(/neutral/i)).toBeInTheDocument();
});

it("labels the backtest record segment as a backtest", async () => {
  render(await OriginPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByText(/backtest/i)).toBeInTheDocument();
  expect(screen.getByText(/1985–2024/)).toBeInTheDocument();
  expect(screen.getByText(/no graded live predictions yet/i)).toBeInTheDocument();
});

it("passes the season searchParam through to the fetcher", async () => {
  render(await OriginPage({ searchParams: Promise.resolve({ season: "2025" }) }));
  expect(mockSeries).toHaveBeenCalledWith(2025);
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd frontend && npx jest app/nrl/origin --verbose`
Expected: FAIL — cannot find module `./page`

- [ ] **Step 5: Write `frontend/app/nrl/origin/page.tsx`**

```tsx
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getOriginRecordServer, getOriginSeriesServer } from "@/lib/api";
import type { OriginGame } from "@/lib/types";
import { cn } from "@/lib/utils";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "State of Origin predictions — FinalWhistle",
  description:
    "NSW Blues vs QLD Maroons — series score, per-game model predictions and series-winner odds from the FinalWhistle Elo model.",
};

const kickoffFmt = new Intl.DateTimeFormat("en-AU", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Australia/Sydney",
});

function seriesLine(blues: number, maroons: number, drawn: number, winner: string | null) {
  const score = `NSW Blues ${blues} – ${maroons} QLD Maroons${drawn ? ` · ${drawn} drawn` : ""}`;
  if (winner === "drawn") return `Series drawn · ${score}`;
  if (winner) return `${winner} win the series ${winner === "NSW Blues" ? `${blues}–${maroons}` : `${maroons}–${blues}`}`;
  return `Series live · ${score}`;
}

function GameCard({ game }: { game: OriginGame }) {
  const played = game.status === "finished" && game.score_home != null;
  const pred = game.prediction;
  return (
    <div className="glass rounded-2xl p-4">
      <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
        Game {game.round ?? game.match_no}
        {game.venue ? ` · ${game.venue}` : ""}
        {game.neutral ? " · neutral venue" : ""}
      </p>
      <div className="mt-2 flex items-baseline justify-between gap-3">
        <p className="font-display text-lg font-extrabold">
          {game.home ?? "TBC"}{" "}
          <span className="tabular-nums">{played ? game.score_home : ""}</span>
          <span className="mx-2 text-muted">{played ? "–" : "vs"}</span>
          <span className="tabular-nums">{played ? game.score_away : ""}</span>{" "}
          {game.away ?? "TBC"}
        </p>
        {!played && game.kickoff_utc ? (
          <p className="text-xs text-muted">{kickoffFmt.format(new Date(game.kickoff_utc))} AEST</p>
        ) : null}
      </div>
      {pred ? (
        <div className="mt-3">
          <div className="flex h-2 overflow-hidden rounded-full">
            <div className="bg-lime-deep" style={{ width: `${pred.p_home * 100}%` }} />
            <div className="bg-white/25" style={{ width: `${pred.p_draw * 100}%` }} />
            <div className="bg-sky-500" style={{ width: `${pred.p_away * 100}%` }} />
          </div>
          <p className="mt-1 text-xs tabular-nums text-muted">
            {game.home} {(pred.p_home * 100).toFixed(0)}% · draw{" "}
            {(pred.p_draw * 100).toFixed(0)}% · {game.away}{" "}
            {(pred.p_away * 100).toFixed(0)}%
            {pred.expected_margin != null
              ? ` · expected margin ${pred.expected_margin > 0 ? "+" : ""}${pred.expected_margin.toFixed(1)}`
              : ""}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass rounded-2xl p-4">
      <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </p>
      <p className="mt-1 text-2xl font-extrabold tabular-nums">{value}</p>
    </div>
  );
}

export default async function OriginPage({
  searchParams,
}: {
  searchParams: Promise<{ season?: string }>;
}) {
  const { season } = await searchParams;
  const seasonNum = season ? Number(season) : undefined;
  const [series, record] = await Promise.all([
    getOriginSeriesServer(seasonNum).catch(() => null),
    getOriginRecordServer().catch(() => null),
  ]);
  if (!series) notFound();

  const s = series.series;
  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">
        State of Origin · {series.season}
      </h1>
      <p className="mt-1 text-sm text-muted">
        {seriesLine(s.blues_wins, s.maroons_wins, s.drawn_games, s.winner)}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {series.seasons.map((yr) => (
          <Link
            key={yr}
            href={yr === series.seasons[0] ? "/nrl/origin" : `/nrl/origin?season=${yr}`}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-semibold",
              yr === series.season ? "bg-lime-deep text-black" : "glass text-muted",
            )}
          >
            {yr}
          </Link>
        ))}
      </div>

      <div className="mt-6 grid gap-4">
        {series.games.map((g) => (
          <GameCard key={g.match_no} game={g} />
        ))}
      </div>

      {s.odds ? (
        <section className="mt-8">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
            Series-winner odds
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <Stat label="NSW Blues" value={`${(s.odds.blues * 100).toFixed(1)}%`} />
            <Stat label="QLD Maroons" value={`${(s.odds.maroons * 100).toFixed(1)}%`} />
            <Stat label="Series drawn" value={`${(s.odds.drawn * 100).toFixed(1)}%`} />
          </div>
        </section>
      ) : null}

      {record ? (
        <section className="mt-8">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
            Model record
          </h2>
          {record.backtest ? (
            <>
              <p className="mt-2 text-xs text-muted">
                Backtest · walk-forward retrodictions over{" "}
                {record.backtest.span[0]}–{record.backtest.span[1]} ({record.backtest.n}{" "}
                games) — not live predictions.
              </p>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Winner accuracy"
                      value={`${(record.backtest.winner_accuracy * 100).toFixed(1)}%`} />
                <Stat label="Log loss" value={record.backtest.avg_log_loss.toFixed(3)} />
                <Stat label="Brier" value={record.backtest.avg_brier.toFixed(3)} />
                <Stat label="Home-pick baseline"
                      value={`${(record.backtest.home_baseline_accuracy * 100).toFixed(1)}%`} />
              </div>
            </>
          ) : null}
          <p className="mt-4 text-xs text-muted">
            {record.live.evaluated_matches === 0
              ? "No graded live predictions yet — predictions freeze at kickoff from the 2027 series."
              : `Live record: ${record.live.evaluated_matches} graded games · ` +
                `${record.live.winner_accuracy != null ? (record.live.winner_accuracy * 100).toFixed(1) : "—"}% winner accuracy.`}
          </p>
        </section>
      ) : null}

      <p className="mt-8 text-xs text-white/40">{series.disclaimer}</p>
    </div>
  );
}
```

- [ ] **Step 6: Add the entry card to the NRL home page**

In `frontend/app/nrl/page.tsx`:
1. Extend the api import: `import { getNrlLadderServer, getNrlMatchesServer, getOriginSeriesServer } from "@/lib/api";`
2. Extend the parallel fetch:

```tsx
  const [fixtures, ladder, origin] = await Promise.all([
    getNrlMatchesServer().catch(() => null),
    getNrlLadderServer().catch(() => null),
    getOriginSeriesServer().catch(() => null),
  ]);
```

3. Insert between `<MoversPanel sport="nrl" />` and the `mt-6 grid` div:

```tsx
      {origin ? (
        <Link
          href="/nrl/origin"
          className="glass mt-6 block rounded-2xl p-4 transition hover:bg-white/5"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
                State of Origin · {origin.season}
              </p>
              <p className="mt-1 font-display text-lg font-extrabold">
                NSW Blues {origin.series.blues_wins} – {origin.series.maroons_wins} QLD
                Maroons
                {origin.series.drawn_games ? ` · ${origin.series.drawn_games} drawn` : ""}
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-lime-deep">
              Series &amp; model →
            </span>
          </div>
        </Link>
      ) : null}
```

- [ ] **Step 7: Run the frontend gates**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: all pass. If an existing NRL home page test fails because of the new fetch, add `getOriginSeriesServer` to its mock (resolving `null` keeps the old rendering).

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/app/nrl/origin/ frontend/app/nrl/page.tsx
git commit -m "feat(origin): /nrl/origin page, series odds panel, NRL home entry card"
```

---

### Task 8: Workflow scheduling + full gate

**Files:**
- Modify: `.github/workflows/nrl-refresh.yml`

**Interfaces:**
- Consumes: CLIs from Tasks 2 and 5.
- Produces: scheduled Origin refresh riding the existing Mon/Fri crons.

- [ ] **Step 1: Extend the workflow**

Append two steps to `.github/workflows/nrl-refresh.yml` after the existing predict step (same indentation):

```yaml
      - name: Ingest State of Origin (seed + live seasons, idempotent)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.sports.origin_ingest --seed --seasons 2025 2027
      - name: Origin frozen shadow predictions + grading
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.sports.origin_predict --generate --grade
```

Also update the workflow's top comment block: add one line — `# Also refreshes State of Origin (sport="origin") — cheap no-ops outside May-July.`

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/nrl-refresh.yml')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Run the FULL test gate**

```bash
make test
```
Expected: entire suite green (backend + ml + pipeline + frontend). Paste the tail of the output into the task report. If `make test` doesn't include frontend, additionally run `cd frontend && npm run typecheck && npm run lint && npm test`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/nrl-refresh.yml
git commit -m "feat(origin): schedule origin ingest+predict on the nrl-refresh crons"
```

---

### Task 9: Local end-to-end verification (evidence for the PR)

No new files. Prove the lane works against a scratch SQLite DB (never prod):

- [ ] **Step 1: Seed + ingest + predict + grade locally**

```bash
cd "/Users/macbookpro/Projects/FIFA WC26 Prediction"
export DATABASE_URL="sqlite:////tmp/origin-e2e.db"
export PYTHONPATH=backend:.
.venv/bin/python -c "
from app.db import Base, SessionLocal
Base.metadata.create_all(SessionLocal().get_bind())
print('tables created')
"
.venv/bin/python -m pipeline.sports.origin_ingest --seed --seasons 2025 2026
.venv/bin/python -m pipeline.sports.origin_predict --generate --grade
```
Expected: seed logs 43 seasons created; 2025+2026 ingested (6 matches, finished); generate writes 0 predictions (no scheduled matches — correct, the 2026 series is over); grade writes 0 (no pre-kickoff predictions exist — correct, retrodictions are forbidden).

- [ ] **Step 2: Exercise the API against that DB**

```bash
DATABASE_URL="sqlite:////tmp/origin-e2e.db" PYTHONPATH=backend:. \
  .venv/bin/python -c "
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
r = c.get('/api/nrl/origin/series?season=2026').json()
assert r['series']['winner'] == 'NSW Blues', r['series']
assert r['series']['blues_wins'] == 2 and r['series']['maroons_wins'] == 1
rec = c.get('/api/nrl/origin/record').json()
assert rec['backtest'] is not None and rec['live']['evaluated_matches'] == 0
print('E2E OK:', r['series'])
print('seasons loaded:', r['seasons'][:3], '... total', len(r['seasons']))
"
```
Expected: `E2E OK: {'blues_wins': 2, 'maroons_wins': 1, ...}` and 45 seasons loaded (1982–2024 seed + 2025 + 2026). **This independently confirms the real 2026 result (Blues 2–1) flows through the whole stack.**

- [ ] **Step 3: Push branch and open the PR (do NOT merge — stop gate)**

```bash
git push -u origin feat/state-of-origin
gh pr create --title "feat: State of Origin — seeded history, Elo lane, series odds, /nrl/origin" --body "$(cat <<'EOF'
Adds State of Origin end to end per docs/superpowers/specs/2026-07-11-state-of-origin-design.md.

- Seeded 1982-2024 history (TheSportsDB, committed JSON) + live 2025+ ingest (fixturedownload)
- Reused NRL margin-Elo with tuned origin params + neutral-venue flag; walk-forward backtest artifact
- Frozen shadow predictions + grading via the shared sport ledger (sport="origin")
- GET /api/nrl/origin/series (series score + exact best-of-3 winner odds) and /origin/record (labeled backtest vs live segments)
- /nrl/origin page + NRL-home entry card; no sixth nav tab (five-tab BottomNav preserved)
- Origin steps added to nrl-refresh.yml crons

No DB migration. No NRL behavior change (all existing NRL tests untouched and green).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Report the PR URL, the full-gate test output, and the E2E evidence. **Merging, and the prod backfill dispatch, are stop-gated — human "go" required.**

---

## Post-merge (orchestrator, stop-gated — not part of task execution)

1. After "go": merge PR, wait for CI + Render deploy.
2. Dispatch `nrl-refresh.yml` manually (it now includes origin ingest/predict) — **stop gate: touches prod DB**.
3. Verify prod: `GET /api/health`, `GET /api/nrl/origin/series?season=2026` (expect Blues 2–1), and the deployed `/nrl/origin` page.
