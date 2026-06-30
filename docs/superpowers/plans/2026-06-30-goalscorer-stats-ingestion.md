# Goalscorer Stats Ingestion (Stage 1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the `Player` table from API-Football — squads (identity + position) and per-player club-season + WC scoring stats — via a bounded, idempotent, rate-limit-paced ingester that runs on the backend (which holds the key) behind a token-guarded internal endpoint + a weekly cron.

**Architecture:** Pure HTTP fetchers (`fetch_squad`, `fetch_player_stats`) + pure aggregation (`_aggregate_stats`) feed upsert functions (`ingest_squad`, `ingest_player_stats`). A bounded `refresh_players(...)` orchestrator links team ids, ingests squads, and refreshes a capped number of stale players per call (paced under the Pro plan's rate limit). It's exposed at `POST /api/internal/refresh-players` (token-guarded, mirrors `/refresh-live`) and driven by a weekly GitHub Action loop. Idempotent via `Player.updated_at`.

**Tech Stack:** Python, SQLAlchemy 2.0, FastAPI, requests, pytest. API-Football (api-sports.io v3).

## Global Constraints

- **Runs on the backend only** (the api-football key lives on Render, not in GitHub Actions). The cron POSTs to the token-guarded endpoint; the work happens server-side.
- **Verified API shapes (captured live, 2026-06-30):**
  - `/players/squads?team={id}` → `response[0].players[]` = `{id, name, age, number, position}` where `position` ∈ {"Goalkeeper","Defender","Midfielder","Attacker"} (full words). Identity only, NO stats.
  - `/players?id={pid}&season={yr}` → `response[0]` = `{player: {id, name, ...}, statistics: [ {league:{id,season,...}, games:{minutes}, goals:{total}, penalty:{scored}, ...}, ... ]}`. `statistics` is **one entry per (team,league)** — SUM across entries. `goals.total` / `games.minutes` / `penalty.scored` are frequently `null` → treat as `0`.
- **Club stats:** `season=2025` (the 2025-26 club season), sum ALL statistics entries. **WC stats:** `season=2026`, sum only entries where `league.id == 1` (the WC league id from `settings.api_football_league`).
- **Position mapping:** Goalkeeper→`G`, Defender→`D`, Midfielder→`M`, Attacker→`F`; unknown→`None`.
- **Never fabricate / never raise in the orchestrator:** skip players/teams with missing ids; a per-player fetch failure must not abort the whole run.
- **Idempotent + bounded:** each `refresh_players` call links team ids, ingests squads where missing, and refreshes at most `max_players` players whose `updated_at` is `None` or older than `stale_days`. Pace with `time.sleep(pace_seconds)` between per-player stat fetches.
- Reuse: `Player`, `Team` (`provider_team_id`) from Stage 1a; `link_team_ids`, `fetch_teams` from `pipeline/ingest/players.py` / `api_football.py`; the token guard pattern from `backend/app/api/internal.py` (`_require_token`, `x_recompute_token` Header); the cron pattern from `.github/workflows/refresh-live.yml`. The `API_URL` + `RECOMPUTE_TOKEN` GitHub secrets already exist.

---

### Task 1: Squad fetch + upsert (identity + position)

**Files:**
- Modify: `pipeline/ingest/api_football.py` (add `fetch_squad`)
- Modify: `pipeline/ingest/players.py` (add `_squad_position`, `ingest_squad`)
- Test: `pipeline/ingest/players_squad_test.py`

**Interfaces:**
- Consumes: `Team.provider_team_id`, `Player` (Stage 1a); `BASE_URL`, `requests`, `log` in `api_football.py`.
- Produces: `fetch_squad(api_key: str, team_id: int, timeout: float = 15.0) -> list[dict]` (raw `response`); `ingest_squad(db: Session, api_key: str, team: Team) -> int` — upserts `Player` rows for the team's squad (by `provider_player_id`), returns the count seen. `_squad_position(pos: str | None) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/ingest/players_squad_test.py`:

```python
from app.models import Player, Team
from pipeline.ingest import players as players_mod
from pipeline.ingest.players import ingest_squad


def _patch_squad(monkeypatch, response):
    monkeypatch.setattr(players_mod, "fetch_squad", lambda api_key, team_id, **k: response)


def test_ingest_squad_upserts_players_with_mapped_position(db_session, monkeypatch):
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    # api-sports /players/squads shape: response[0].players[]
    _patch_squad(db_session_response := monkeypatch, [
        {"team": {"id": 1, "name": "Belgium"}, "players": [
            {"id": 730, "name": "T. Courtois", "age": 33, "number": 1, "position": "Goalkeeper"},
            {"id": 909, "name": "K. De Bruyne", "age": 34, "number": 7, "position": "Midfielder"},
        ]},
    ])
    n = ingest_squad(db_session, "k", team)
    assert n == 2
    courtois = db_session.query(Player).filter_by(provider_player_id=730).one()
    assert courtois.name == "T. Courtois"
    assert courtois.team_id == team.id
    assert courtois.position == "G"           # Goalkeeper -> G
    assert db_session.query(Player).filter_by(provider_player_id=909).one().position == "M"


def test_ingest_squad_is_idempotent(db_session, monkeypatch):
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    resp = [{"team": {"id": 1}, "players": [{"id": 730, "name": "T. Courtois", "position": "Goalkeeper"}]}]
    _patch_squad(monkeypatch, resp)
    ingest_squad(db_session, "k", team)
    ingest_squad(db_session, "k", team)   # second run must not duplicate
    assert db_session.query(Player).filter_by(provider_player_id=730).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_squad_test.py -q`
Expected: FAIL — `ImportError: cannot import name 'ingest_squad'`.

- [ ] **Step 3: Add `fetch_squad`**

In `pipeline/ingest/api_football.py`, after `fetch_teams`, add (mirrors the established pattern):

```python
def fetch_squad(api_key: str, team_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw squad list for a team from api-sports.io (/players/squads)."""
    resp = requests.get(
        f"{BASE_URL}/players/squads",
        headers={"x-apisports-key": api_key},
        params={"team": team_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football squads errors: %s", data["errors"])
    return data.get("response") or []
```

- [ ] **Step 4: Add `_squad_position` + `ingest_squad`**

In `pipeline/ingest/players.py`, add the import and functions:

```python
from datetime import datetime, timezone   # add near the top imports

from app.models import Player, Team        # extend the existing "from app.models import Team"
from pipeline.ingest.api_football import fetch_squad   # add to imports

_POSITION_MAP = {"Goalkeeper": "G", "Defender": "D", "Midfielder": "M", "Attacker": "F"}


def _squad_position(pos: str | None) -> str | None:
    """Map an api-sports squad position word to our G/D/M/F code (None if unknown)."""
    return _POSITION_MAP.get(pos or "")


def ingest_squad(db: Session, api_key: str, team: Team) -> int:
    """Upsert Player rows (identity + position) for one team's squad, keyed on
    provider_player_id. Returns the number of squad players seen. No stats here."""
    if team.provider_team_id is None:
        return 0
    response = fetch_squad(api_key, team.provider_team_id)
    squad_players = (response[0].get("players") if response else None) or []
    seen = 0
    for p in squad_players:
        pid = p.get("id")
        if pid is None:
            continue
        row = db.query(Player).filter_by(provider_player_id=pid).one_or_none()
        if row is None:
            row = Player(provider_player_id=pid)
            db.add(row)
        if p.get("name"):
            row.name = p["name"]
        row.team_id = team.id
        mapped = _squad_position(p.get("position"))
        if mapped is not None:
            row.position = mapped
        seen += 1
    db.commit()
    return seen
```

(Keep the existing `link_team_ids`/`fetch_teams` import lines; only add the new imports.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_squad_test.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/players.py pipeline/ingest/players_squad_test.py
git commit -m "feat(ingest): fetch_squad + ingest_squad (player identity + position)"
```

---

### Task 2: Per-player stats fetch + aggregation

**Files:**
- Modify: `pipeline/ingest/api_football.py` (add `fetch_player_stats`)
- Modify: `pipeline/ingest/players.py` (add `_aggregate_stats`, `ingest_player_stats`)
- Test: `pipeline/ingest/players_stats_test.py`

**Interfaces:**
- Consumes: `Player` (Stage 1a); `fetch_player_stats`.
- Produces: `fetch_player_stats(api_key: str, player_id: int, season: int, timeout: float = 15.0) -> list[dict]`; `_aggregate_stats(statistics: list[dict] | None, league_id: int | None = None) -> tuple[int, int, int]` returning `(goals, minutes, penalties_scored)`; `ingest_player_stats(db, api_key, player, club_season, wc_season, wc_league) -> None` sets `club_goals/club_minutes/club_penalties/wc_goals/wc_minutes/season/updated_at`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/ingest/players_stats_test.py`:

```python
from app.models import Player
from pipeline.ingest import players as players_mod
from pipeline.ingest.players import _aggregate_stats, ingest_player_stats


def test_aggregate_sums_entries_and_treats_null_as_zero():
    statistics = [
        {"league": {"id": 15, "season": 2025}, "games": {"minutes": 540}, "goals": {"total": None}, "penalty": {"scored": 0}},
        {"league": {"id": 140, "season": 2025}, "games": {"minutes": 2880}, "goals": {"total": 4}, "penalty": {"scored": 2}},
        {"league": {"id": 2, "season": 2025}, "games": {"minutes": None}, "goals": {"total": 1}, "penalty": {"scored": None}},
    ]
    goals, minutes, pens = _aggregate_stats(statistics)
    assert goals == 5          # None + 4 + 1
    assert minutes == 3420     # 540 + 2880 + 0
    assert pens == 2           # 0 + 2 + 0


def test_aggregate_filters_by_league_id():
    statistics = [
        {"league": {"id": 1}, "games": {"minutes": 270}, "goals": {"total": 2}, "penalty": {"scored": 1}},
        {"league": {"id": 140}, "games": {"minutes": 900}, "goals": {"total": 9}, "penalty": {"scored": 3}},
    ]
    goals, minutes, pens = _aggregate_stats(statistics, league_id=1)
    assert (goals, minutes, pens) == (2, 270, 1)   # only the WC (league 1) entry


def test_ingest_player_stats_sets_club_and_wc(db_session, monkeypatch):
    player = Player(provider_player_id=909, name="K. De Bruyne", position="M")
    db_session.add(player)
    db_session.commit()

    def fake_fetch(api_key, player_id, season, **k):
        if season == 2025:   # club season -> sum all
            return [{"player": {"id": 909}, "statistics": [
                {"league": {"id": 140}, "games": {"minutes": 2400}, "goals": {"total": 8}, "penalty": {"scored": 1}},
                {"league": {"id": 2}, "games": {"minutes": 600}, "goals": {"total": 2}, "penalty": {"scored": 0}},
            ]}]
        return [{"player": {"id": 909}, "statistics": [   # WC season -> filter league 1
            {"league": {"id": 1}, "games": {"minutes": 270}, "goals": {"total": 1}, "penalty": {"scored": 0}},
        ]}]

    monkeypatch.setattr(players_mod, "fetch_player_stats", fake_fetch)
    ingest_player_stats(db_session, "k", player, club_season=2025, wc_season=2026, wc_league=1)

    got = db_session.query(Player).filter_by(provider_player_id=909).one()
    assert got.club_goals == 10 and got.club_minutes == 3000 and got.club_penalties == 1
    assert got.wc_goals == 1 and got.wc_minutes == 270
    assert got.season == 2025 and got.updated_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_stats_test.py -q`
Expected: FAIL — `ImportError: cannot import name '_aggregate_stats'`.

- [ ] **Step 3: Add `fetch_player_stats`**

In `pipeline/ingest/api_football.py`, after `fetch_squad`, add:

```python
def fetch_player_stats(api_key: str, player_id: int, season: int, timeout: float = 15.0) -> list[dict]:
    """Return one player's per-(team,league) statistics for a season (/players?id=&season=)."""
    resp = requests.get(
        f"{BASE_URL}/players",
        headers={"x-apisports-key": api_key},
        params={"id": player_id, "season": season},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football players errors: %s", data["errors"])
    return data.get("response") or []
```

- [ ] **Step 4: Add `_aggregate_stats` + `ingest_player_stats`**

In `pipeline/ingest/players.py`, add (and add `fetch_player_stats` to the `from pipeline.ingest.api_football import ...` line):

```python
def _aggregate_stats(statistics: list[dict] | None, league_id: int | None = None) -> tuple[int, int, int]:
    """Sum goals.total, games.minutes and penalty.scored across a player's
    statistics entries (api-sports returns one per team+league). Nulls count as 0.
    When league_id is given, only that league's entries are summed."""
    goals = minutes = pens = 0
    for s in statistics or []:
        if league_id is not None and (s.get("league") or {}).get("id") != league_id:
            continue
        goals += (s.get("goals") or {}).get("total") or 0
        minutes += (s.get("games") or {}).get("minutes") or 0
        pens += (s.get("penalty") or {}).get("scored") or 0
    return goals, minutes, pens


def ingest_player_stats(
    db: Session, api_key: str, player: Player,
    club_season: int, wc_season: int, wc_league: int,
) -> None:
    """Fill one Player's club-season and WC scoring stats. Club = sum of all
    club_season entries; WC = sum of wc_season entries for the WC league only."""
    club = fetch_player_stats(api_key, player.provider_player_id, club_season)
    if club:
        cg, cm, cp = _aggregate_stats(club[0].get("statistics"))
        player.club_goals, player.club_minutes, player.club_penalties = cg, cm, cp
        player.season = club_season
    wc = fetch_player_stats(api_key, player.provider_player_id, wc_season)
    if wc:
        wg, wm, _pens = _aggregate_stats(wc[0].get("statistics"), league_id=wc_league)
        player.wc_goals, player.wc_minutes = wg, wm
    player.updated_at = datetime.now(timezone.utc)
    db.commit()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_stats_test.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/players.py pipeline/ingest/players_stats_test.py
git commit -m "feat(ingest): fetch_player_stats + aggregate club/WC scoring stats"
```

---

### Task 3: Bounded, idempotent, paced `refresh_players` orchestrator

**Files:**
- Modify: `pipeline/ingest/players.py` (add `refresh_players`)
- Test: `pipeline/ingest/players_refresh_test.py`

**Interfaces:**
- Consumes: `fetch_teams`, `link_team_ids`, `ingest_squad`, `ingest_player_stats`, `Player`, `Team`.
- Produces: `refresh_players(db, api_key, league, club_season=2025, wc_season=2026, max_players=40, stale_days=7, pace_seconds=0.5, now=None) -> dict` returning `{"teams_linked": int, "squads_ingested": int, "players_refreshed": int}`. Links team ids, ingests squads for teams that have no Player rows yet, then refreshes up to `max_players` players whose `updated_at` is `None` or older than `stale_days`, sleeping `pace_seconds` between per-player stat fetches. Never raises on a single player's failure.

- [ ] **Step 1: Write the failing test**

Create `pipeline/ingest/players_refresh_test.py`:

```python
from datetime import datetime, timedelta, timezone

from app.models import Player, Team
from pipeline.ingest import players as players_mod
from pipeline.ingest.players import refresh_players


def test_refresh_players_links_ingests_and_bounds(db_session, monkeypatch):
    db_session.add(Team(name="Belgium"))
    db_session.commit()

    monkeypatch.setattr(players_mod, "fetch_teams", lambda *a, **k: [{"team": {"id": 1, "name": "Belgium"}}])
    # squad of 3 players for the linked team
    monkeypatch.setattr(players_mod, "fetch_squad", lambda api_key, team_id, **k: [
        {"team": {"id": 1}, "players": [
            {"id": 730, "name": "A", "position": "Goalkeeper"},
            {"id": 909, "name": "B", "position": "Midfielder"},
            {"id": 200, "name": "C", "position": "Attacker"},
        ]}])
    monkeypatch.setattr(players_mod, "fetch_player_stats", lambda api_key, pid, season, **k: [
        {"player": {"id": pid}, "statistics": [{"league": {"id": 1}, "games": {"minutes": 90}, "goals": {"total": 1}, "penalty": {"scored": 0}}]}])
    monkeypatch.setattr(players_mod.time, "sleep", lambda *_a: None)   # no real waiting

    out = refresh_players(db_session, "k", league=1, max_players=2)

    assert out["teams_linked"] == 1
    assert out["squads_ingested"] == 1
    assert out["players_refreshed"] == 2          # capped at max_players, not 3
    assert db_session.query(Team).filter_by(name="Belgium").one().provider_team_id == 1
    refreshed = db_session.query(Player).filter(Player.updated_at.isnot(None)).count()
    assert refreshed == 2


def test_refresh_players_skips_fresh_players(db_session, monkeypatch):
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    fresh = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(Player(provider_player_id=730, name="A", team_id=team.id, updated_at=fresh))
    db_session.commit()

    monkeypatch.setattr(players_mod, "fetch_teams", lambda *a, **k: [{"team": {"id": 1, "name": "Belgium"}}])
    monkeypatch.setattr(players_mod, "fetch_squad", lambda api_key, team_id, **k: [
        {"team": {"id": 1}, "players": [{"id": 730, "name": "A", "position": "Goalkeeper"}]}])
    called = []
    monkeypatch.setattr(players_mod, "fetch_player_stats",
                        lambda api_key, pid, season, **k: called.append(pid) or [])
    monkeypatch.setattr(players_mod.time, "sleep", lambda *_a: None)

    out = refresh_players(db_session, "k", league=1, stale_days=7)
    assert out["players_refreshed"] == 0          # the one player is fresh (1 day < 7)
    assert called == []                            # no stat fetch issued
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_refresh_test.py -q`
Expected: FAIL — `ImportError: cannot import name 'refresh_players'`.

- [ ] **Step 3: Implement `refresh_players`**

In `pipeline/ingest/players.py`, add `import time` near the top and append:

```python
def refresh_players(
    db: Session, api_key: str, league: int,
    club_season: int = 2025, wc_season: int = 2026,
    max_players: int = 40, stale_days: int = 7, pace_seconds: float = 0.5,
    now: datetime | None = None,
) -> dict:
    """One bounded, idempotent ingestion pass (runs server-side; the cron repeats
    it to cover everyone). Links team ids, ingests squads for teams with no Player
    rows yet, then refreshes up to max_players players whose stats are missing or
    older than stale_days. Paced; a single player's failure never aborts the run."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=stale_days)

    teams_linked = link_team_ids(db, fetch_teams(api_key, league, wc_season))

    squads_ingested = 0
    for team in db.query(Team).filter(Team.provider_team_id.isnot(None)).all():
        has_players = db.query(Player).filter_by(team_id=team.id).first() is not None
        if not has_players:
            ingest_squad(db, api_key, team)
            squads_ingested += 1

    stale = (
        db.query(Player)
        .filter((Player.updated_at.is_(None)) | (Player.updated_at < cutoff))
        .order_by(Player.updated_at.is_(None).desc(), Player.id)
        .limit(max_players)
        .all()
    )
    refreshed = 0
    for player in stale:
        try:
            ingest_player_stats(db, api_key, player, club_season, wc_season, league)
            refreshed += 1
        except Exception:  # noqa: BLE001 - one bad player must not abort the pass
            log.warning("player stats refresh failed for %s", player.provider_player_id)
        time.sleep(pace_seconds)

    return {"teams_linked": teams_linked, "squads_ingested": squads_ingested,
            "players_refreshed": refreshed}
```

Add `from datetime import datetime, timedelta, timezone` (extend the Task-1 datetime import to include `timedelta`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_refresh_test.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the broader pipeline+backend suite**

Run: `.venv/bin/python -m pytest pipeline backend ml -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/players.py pipeline/ingest/players_refresh_test.py
git commit -m "feat(ingest): bounded idempotent paced refresh_players orchestrator"
```

---

### Task 4: Token-guarded `POST /api/internal/refresh-players` endpoint

**Files:**
- Modify: `backend/app/api/internal.py` (add the endpoint)
- Test: `backend/tests/test_refresh_players_endpoint.py`

**Interfaces:**
- Consumes: `refresh_players` (Task 3); `_require_token`, the `x_recompute_token` Header pattern, `settings`, `get_db` (existing in `internal.py`).
- Produces: `POST /api/internal/refresh-players` → runs one bounded `refresh_players` pass with the configured api-football key, returns its summary dict. 401 without a valid token; a no-op summary when the provider/key isn't configured.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_refresh_players_endpoint.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.config import settings


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_refresh_players_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        assert client.post("/api/internal/refresh-players").status_code == 401
        assert client.post("/api/internal/refresh-players",
                           headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_refresh_players_runs_with_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    monkeypatch.setattr(settings, "live_provider", "api_football")
    monkeypatch.setattr(settings, "api_football_api_key", "k")
    import app.api.internal as internal_mod
    monkeypatch.setattr(
        internal_mod, "_run_refresh_players",
        lambda db, key, league: {"teams_linked": 2, "squads_ingested": 2, "players_refreshed": 10},
    )
    client = _client()
    try:
        r = client.post("/api/internal/refresh-players", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        assert r.json()["players_refreshed"] == 10
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_refresh_players_endpoint.py -q`
Expected: FAIL — 404 (route not defined) / `AttributeError: _run_refresh_players`.

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/internal.py`, add a thin indirection (so tests can patch it) and the route. Near the other imports / module top, add:

```python
def _run_refresh_players(db, api_key: str, league: int) -> dict:
    """Indirection point (patchable in tests) for the player-stats ingestion pass."""
    from pipeline.ingest.players import refresh_players
    return refresh_players(db, api_key, league)
```

Then add the route (mirror the existing `refresh-live` route — same `Depends(get_db)`, `x_recompute_token` Header, `_require_token`):

```python
@router.post("/refresh-players")
def refresh_players_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
) -> dict:
    """Run one bounded player-stats ingestion pass (squads + club/WC scoring).
    Token-guarded; the heavy api-football calls run here, where the key lives."""
    _require_token(x_recompute_token)
    if settings.live_provider != "api_football" or not settings.api_football_api_key:
        return {"skipped": "api_football not active or no key",
                "teams_linked": 0, "squads_ingested": 0, "players_refreshed": 0}
    return _run_refresh_players(db, settings.api_football_api_key, settings.api_football_league)
```

(Use the same `Session`/`Depends`/`Header` imports already present in `internal.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_refresh_players_endpoint.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the backend suite**

Run: `.venv/bin/python -m pytest backend -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/internal.py backend/tests/test_refresh_players_endpoint.py
git commit -m "feat(api): token-guarded /api/internal/refresh-players endpoint"
```

---

### Task 5: Weekly cron workflow

**Files:**
- Create: `.github/workflows/refresh-players.yml`

**Interfaces:**
- Consumes: the `API_URL` + `RECOMPUTE_TOKEN` GitHub secrets (already configured); the `/api/internal/refresh-players` endpoint (Task 4).
- Produces: nothing in code.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/refresh-players.yml` (mirrors `refresh-live.yml`'s loop, but weekly and longer-paced — player stats change slowly, and each call is bounded so the loop walks through stale players):

```yaml
# Refresh player squads + scoring stats (Stage 1b). POSTs to the token-guarded
# /api/internal/refresh-players, which runs the bounded api-football ingestion
# server-side (where the key lives). Each call refreshes a capped number of stale
# players; the loop + weekly cadence walk through the whole pool over time.
#
# Repo secrets required (already set for refresh-live):
#   - API_URL          the deployed API base, e.g. https://pitchprophet-api.onrender.com
#   - RECOMPUTE_TOKEN  the SAME value as the backend's RECOMPUTE_TOKEN env var
name: refresh-players

on:
  schedule:
    - cron: "30 4 * * 1"   # Mondays 04:30 UTC
  workflow_dispatch: {}

concurrency:
  group: refresh-players
  cancel-in-progress: false

jobs:
  refresh-players:
    runs-on: ubuntu-latest
    steps:
      - name: POST refresh-players (loop to cover stale players)
        env:
          API_URL: ${{ secrets.API_URL }}
          RECOMPUTE_TOKEN: ${{ secrets.RECOMPUTE_TOKEN }}
        run: |
          set -euo pipefail
          if [ -z "${API_URL:-}" ] || [ -z "${RECOMPUTE_TOKEN:-}" ]; then
            echo "API_URL / RECOMPUTE_TOKEN secrets not set — skipping."
            exit 0
          fi
          for i in $(seq 1 20); do
            code=$(curl -sS -o /tmp/players.json -w "%{http_code}" -m 120 \
              -X POST "${API_URL%/}/api/internal/refresh-players" \
              -H "X-Recompute-Token: ${RECOMPUTE_TOKEN}" || echo 000)
            echo "tick $i -> HTTP $code: $(cat /tmp/players.json 2>/dev/null)"
            if [ "$code" != "200" ]; then echo "non-200; stopping loop"; break; fi
            refreshed=$(python3 -c "import json,sys; print(json.load(open('/tmp/players.json')).get('players_refreshed',0))" 2>/dev/null || echo 0)
            if [ "$refreshed" = "0" ]; then echo "no stale players left; done"; break; fi
            sleep 20
          done
```

- [ ] **Step 2: Validate the workflow YAML**

Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/refresh-players.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/refresh-players.yml
git commit -m "ci: weekly refresh-players cron (loops the bounded ingestion)"
```

---

## Self-Review

**Spec coverage (Stage 1b slice):** squad ingestion (Task 1) ✓; per-player club-season + WC stats with multi-entry aggregation + null→0 (Task 2) ✓; bounded/idempotent/paced orchestration (Task 3) ✓; server-side execution behind a token-guarded endpoint (Task 4) ✓; weekly cron driving it (Task 5) ✓; `player.id` linkage + `provider_team_id` are from Stage 1a; position mapping ✓; WC = league==1 filter ✓; club = season 2025 sum ✓.

**Placeholder scan:** none — every code step has complete content and exact commands. Shapes are the live-captured ones.

**Type consistency:** `fetch_squad/fetch_player_stats/fetch_teams -> list[dict]`; `_aggregate_stats -> tuple[int,int,int]`; `ingest_squad -> int`; `ingest_player_stats -> None`; `refresh_players -> dict` with keys `teams_linked/squads_ingested/players_refreshed` — identical across the Interfaces blocks, tests, implementations, the endpoint, and the cron's JSON read (`players_refreshed`). `_run_refresh_players(db, key, league)` indirection matches the endpoint test's patch target. Position codes G/D/M/F consistent with Stage 1a's `LineupPlayer.position`.
