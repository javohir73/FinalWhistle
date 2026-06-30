# Goalscorer Data Foundation (Stage 1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the schema and identity-linkage that goalscorer predictions need — a `Player` table, provider IDs on `Team` and `LineupPlayer`, and a team-id linker — without yet running the heavy per-player API ingestion.

**Architecture:** A new `Player` SQLAlchemy model + an Alembic migration (mirroring it) add the player table and two `provider_*_id` columns. The lineup parser starts keeping the `player.id` it currently drops, so an announced XI can join to `Player` by id. A small `link_team_ids()` maps API-Football team ids onto our `Team` rows by normalized name. The actual squad/stats ingestion + its production orchestration are Stage 1b (they need live API-shape verification and the backend's key).

**Tech Stack:** Python, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, FastAPI, pytest. API-Football (api-sports.io v3).

## Global Constraints

- **No behavior change to existing features** — these are additive columns/tables and one extra field carried through the lineup parser.
- **Test DB is model-driven:** `conftest` builds the schema via `Base.metadata.create_all`, so the `Player` model + new columns are what tests see. The Alembic migration must mirror the model exactly (it is what prod runs via `refresh.yml`).
- **Migration chain:** current head is `a1b2c3d4e5f9`; the new migration's `down_revision` is `a1b2c3d4e5f9`.
- **Never fabricate data:** `provider_player_id` / `provider_team_id` are nullable; absent provider ids stay `None`, never invented.
- **Stage 1b (separate plan):** squad ingestion, per-player club/WC stats, rate-limit pacing, and the production trigger (a backend internal endpoint + cron, since the api-football key lives on Render, not in GitHub Actions). Do NOT build those here.

---

### Task 1: `Player` model + provider-id columns + migration

**Files:**
- Modify: `backend/app/models/__init__.py` (add `provider_team_id` to `Team`, `provider_player_id` to `LineupPlayer`, new `Player` model, add `"Player"` to `__all__`)
- Create: `backend/alembic/versions/b2c3d4e5f6a0_player_data_foundation.py`
- Test: `backend/tests/test_player_model.py`

**Interfaces:**
- Produces: `Player(provider_player_id: int, name: str, team_id: int|None, position: str|None, club_goals/club_minutes/club_penalties: int|None, wc_goals/wc_minutes: int|None, season: int|None, updated_at: datetime|None)`; `Team.provider_team_id: int|None`; `LineupPlayer.provider_player_id: int|None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_player_model.py`:

```python
from datetime import datetime, timezone

from app.models import LineupPlayer, Match, MatchLineup, Player, Team


def test_player_row_roundtrips_with_provider_ids(db_session):
    team = Team(name="Brazil", provider_team_id=6)
    db_session.add(team)
    db_session.commit()

    p = Player(
        provider_player_id=1179, name="Vinicius Junior", team_id=team.id,
        position="F", club_goals=24, club_minutes=2800, club_penalties=2,
        wc_goals=1, wc_minutes=270, season=2025,
        updated_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    db_session.add(p)
    db_session.commit()

    got = db_session.query(Player).filter_by(provider_player_id=1179).one()
    assert got.name == "Vinicius Junior"
    assert got.team_id == team.id
    assert got.club_goals == 24 and got.wc_goals == 1
    assert db_session.query(Team).filter_by(name="Brazil").one().provider_team_id == 6


def test_lineup_player_carries_provider_player_id(db_session):
    m = Match(tournament_id=1, stage="group", is_neutral=True)
    db_session.add(m)
    db_session.commit()
    ml = MatchLineup(match_id=m.id, side="home", provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db_session.add(ml)
    db_session.commit()
    lp = LineupPlayer(match_lineup_id=ml.id, name="Vini", number=7, position="F",
                      grid="4:1", is_starter=True, order=0, provider_player_id=1179)
    db_session.add(lp)
    db_session.commit()
    assert db_session.query(LineupPlayer).one().provider_player_id == 1179
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_player_model.py -q`
Expected: FAIL — `ImportError: cannot import name 'Player'` (and `provider_team_id` unknown).

- [ ] **Step 3: Add the model columns + `Player` model**

In `backend/app/models/__init__.py`, inside `class Team(Base)`, add after the `is_host` column:

```python
    # API-Football team id (api-sports.io), linked by normalized name. Lets the
    # goalscorer ingestion pull this team's squad. Nullable until linked.
    provider_team_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
```

Inside `class LineupPlayer(Base)`, add after the `order` column:

```python
    # API-Football player id — links an announced XI row to a Player by id
    # (no fuzzy name matching). Nullable; older rows / unmatched players stay None.
    provider_player_id: Mapped[int | None] = mapped_column(Integer, index=True)
```

Add a new model (place it right after the `LineupPlayer` class):

```python
class Player(Base):
    """A squad player plus scoring stats, ingested from API-Football. Feeds the
    Phase 2 goalscorer model; never shown raw. Rates blend club-season form
    (season=2025) with WC-2026 form, so both are stored."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_player_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    position: Mapped[str | None] = mapped_column(String(2))  # G/D/M/F
    club_goals: Mapped[int | None] = mapped_column(Integer)
    club_minutes: Mapped[int | None] = mapped_column(Integer)
    club_penalties: Mapped[int | None] = mapped_column(Integer)
    wc_goals: Mapped[int | None] = mapped_column(Integer)
    wc_minutes: Mapped[int | None] = mapped_column(Integer)
    season: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

In the `__all__` list at the bottom of the file, add `"Player"` next to `"Team"`.

(`Integer`, `String`, `ForeignKey`, `DateTime`, `Mapped`, `mapped_column`, and `datetime` are already imported in this file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_player_model.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Write the Alembic migration (mirrors the model)**

Create `backend/alembic/versions/b2c3d4e5f6a0_player_data_foundation.py`:

```python
"""Player data foundation.

Adds the players table plus provider id columns on teams and lineup_players,
for Phase 2 goalscorer predictions.

Revision ID: b2c3d4e5f6a0
Revises: a1b2c3d4e5f9
Create Date: 2026-06-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a0"
down_revision: Union[str, None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("provider_team_id", sa.Integer(), nullable=True))
    op.create_index("ix_teams_provider_team_id", "teams", ["provider_team_id"], unique=True)
    op.add_column("lineup_players", sa.Column("provider_player_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_lineup_players_provider_player_id", "lineup_players", ["provider_player_id"]
    )
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_player_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("position", sa.String(length=2), nullable=True),
        sa.Column("club_goals", sa.Integer(), nullable=True),
        sa.Column("club_minutes", sa.Integer(), nullable=True),
        sa.Column("club_penalties", sa.Integer(), nullable=True),
        sa.Column("wc_goals", sa.Integer(), nullable=True),
        sa.Column("wc_minutes", sa.Integer(), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_players_provider_player_id", "players", ["provider_player_id"], unique=True)
    op.create_index("ix_players_team_id", "players", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_players_team_id", table_name="players")
    op.drop_index("ix_players_provider_player_id", table_name="players")
    op.drop_table("players")
    op.drop_index("ix_lineup_players_provider_player_id", table_name="lineup_players")
    op.drop_column("lineup_players", "provider_player_id")
    op.drop_index("ix_teams_provider_team_id", table_name="teams")
    op.drop_column("teams", "provider_team_id")
```

- [ ] **Step 6: Verify the migration applies cleanly on a scratch DB**

Run:
```bash
cd backend && DATABASE_URL="sqlite:////tmp/mig_check.db" ../.venv/bin/alembic upgrade head && DATABASE_URL="sqlite:////tmp/mig_check.db" ../.venv/bin/alembic downgrade -1 && rm -f /tmp/mig_check.db && cd ..
```
Expected: both `upgrade head` and `downgrade -1` run without error (chain resolves `a1b2c3d4e5f9 -> b2c3d4e5f6a0`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/b2c3d4e5f6a0_player_data_foundation.py backend/tests/test_player_model.py
git commit -m "feat(db): Player model + provider id columns (goalscorer foundation)"
```

---

### Task 2: Keep `player.id` in lineup parsing + persistence

**Files:**
- Modify: `pipeline/ingest/api_football.py` (`_player_row` — add `player_id`)
- Modify: `backend/app/lineups.py:238-244` (persist `provider_player_id`)
- Test: `pipeline/ingest/api_football_test.py` (or the existing api-football test module; create `pipeline/ingest/players_test.py` if none is suitable)

**Interfaces:**
- Consumes: nothing new.
- Produces: each dict from `parse_lineups(...)`'s `players` list now carries `"player_id": int | None`; persisted `LineupPlayer` rows set `provider_player_id` from it.

- [ ] **Step 1: Write the failing test**

Create `pipeline/ingest/players_test.py`:

```python
from pipeline.ingest.api_football import parse_lineups


def test_parse_lineups_keeps_provider_player_id():
    response = [
        {
            "team": {"name": "Brazil"},
            "formation": "4-3-3",
            "coach": {"name": "Dorival"},
            "startXI": [
                {"player": {"id": 1179, "name": "Vinicius", "number": 7, "pos": "F", "grid": "4:1"}},
            ],
            "substitutes": [
                {"player": {"id": 2040, "name": "Endrick", "number": 9, "pos": "F", "grid": None}},
            ],
        }
    ]
    teams = parse_lineups(response)
    rows = teams[0]["players"]
    starter = next(r for r in rows if r["name"] == "Vinicius")
    bench = next(r for r in rows if r["name"] == "Endrick")
    assert starter["player_id"] == 1179
    assert bench["player_id"] == 2040
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_test.py -q`
Expected: FAIL — `KeyError: 'player_id'`.

- [ ] **Step 3: Add `player_id` to the parsed row**

In `pipeline/ingest/api_football.py`, in `_player_row`, the returned dict currently begins with `"name": name,`. Add `player.id` to it — change the returned dict to include:

```python
    return {
        "player_id": player.get("id"),
        "name": name,
        "number": player.get("number"),
        "position": _position(player.get("pos")),
        "grid": player.get("grid") if is_starter else None,
        "is_starter": is_starter,
        "order": order,
    }
```

(Keep every existing key; only the `"player_id"` line is new. Match the existing keys/values exactly — do not drop `is_starter`/`order`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_test.py -q`
Expected: PASS.

- [ ] **Step 5: Persist it on `LineupPlayer`**

In `backend/app/lineups.py`, the `LineupPlayer(...)` construction at lines 238-244 currently passes `name/number/position/grid/is_starter/order`. Add the provider id — change that construction to:

```python
                LineupPlayer(
                    name=row["name"],
                    number=row.get("number"),
                    position=row.get("position"),
                    grid=row.get("grid"),
                    is_starter=row["is_starter"],
                    order=row["order"],
                    provider_player_id=row.get("player_id"),
                )
```

(Only the `provider_player_id=` line is new; keep the other kwargs exactly as they are — confirm the existing `grid=` argument source against the surrounding code and leave it unchanged.)

- [ ] **Step 6: Run the lineups + api-football tests to confirm no regression**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_test.py backend/tests -q -k "lineup or player"`
Expected: PASS (new test + existing lineup tests).

- [ ] **Step 7: Commit**

```bash
git add pipeline/ingest/api_football.py backend/app/lineups.py pipeline/ingest/players_test.py
git commit -m "feat(lineups): keep api-football player.id -> provider_player_id"
```

---

### Task 3: Link API-Football team ids onto `Team`

**Files:**
- Modify: `pipeline/ingest/api_football.py` (add `fetch_teams`)
- Create: `pipeline/ingest/players.py` (add `link_team_ids`)
- Test: `pipeline/ingest/players_link_test.py`

**Interfaces:**
- Consumes: `Team.provider_team_id` (Task 1); `normalize_team_name` from `pipeline.team_mapping`.
- Produces: `fetch_teams(api_key: str, league: int, season: int, timeout: float = 15.0) -> list[dict]` (raw api-sports `response`); `link_team_ids(db: Session, teams_response: list[dict]) -> int` — sets `provider_team_id` on matching `Team` rows by normalized name, returns the number linked.

- [ ] **Step 1: Write the failing test**

Create `pipeline/ingest/players_link_test.py`:

```python
from app.models import Team
from pipeline.ingest.players import link_team_ids


def test_link_team_ids_matches_by_normalized_name(db_session):
    db_session.add_all([Team(name="Brazil"), Team(name="South Korea")])
    db_session.commit()

    teams_response = [
        {"team": {"id": 6, "name": "Brazil"}},
        {"team": {"id": 17, "name": "Korea Republic"}},   # api-sports alias
        {"team": {"id": 999, "name": "Wales"}},            # not in our DB -> ignored
    ]
    linked = link_team_ids(db_session, teams_response)

    assert db_session.query(Team).filter_by(name="Brazil").one().provider_team_id == 6
    # alias maps via normalize_team_name -> South Korea
    assert db_session.query(Team).filter_by(name="South Korea").one().provider_team_id == 17
    assert linked == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_link_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.ingest.players'`.

- [ ] **Step 3: Add `fetch_teams`**

In `pipeline/ingest/api_football.py`, after `fetch_lineups`, add (mirrors the existing `fetch_*` pattern — `BASE_URL`, `x-apisports-key`, 200-with-`errors` body):

```python
def fetch_teams(api_key: str, league: int, season: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw team list for a league+season from api-sports.io (used to
    map api-football team ids onto our Team rows)."""
    resp = requests.get(
        f"{BASE_URL}/teams",
        headers={"x-apisports-key": api_key},
        params={"league": league, "season": season},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football teams errors: %s", data["errors"])
    return data.get("response") or []
```

- [ ] **Step 4: Create `pipeline/ingest/players.py` with `link_team_ids`**

Create `pipeline/ingest/players.py`:

```python
"""Goalscorer-data ingestion helpers (Phase 2). Stage 1a ships only the team-id
linker; squad + per-player stats ingestion arrive in Stage 1b."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Team
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)


def link_team_ids(db: Session, teams_response: list[dict]) -> int:
    """Set Team.provider_team_id from an api-sports /teams response, matching on
    the normalized team name. Returns the number of Team rows linked. Unknown
    provider teams are ignored (never create a Team)."""
    by_norm = {normalize_team_name(t.name): t for t in db.query(Team).all()}
    linked = 0
    for entry in teams_response or []:
        team = entry.get("team") or {}
        pid, pname = team.get("id"), team.get("name")
        if pid is None or not pname:
            continue
        row = by_norm.get(normalize_team_name(pname))
        if row is not None and row.provider_team_id != pid:
            row.provider_team_id = pid
            linked += 1
    db.commit()
    return linked
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/players_link_test.py -q`
Expected: PASS.

Note: the test assumes `normalize_team_name` maps the api-sports alias "Korea Republic" to the same value as our "South Korea". If the assertion on the alias fails, that reveals a real alias gap — fix it by adding the alias to `pipeline/team_mapping.py` (where other aliases live) rather than weakening the test; the direct "Brazil" match and the `linked` count must still pass.

- [ ] **Step 6: Run the broader pipeline tests to confirm no regression**

Run: `.venv/bin/python -m pytest pipeline backend ml -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/players.py pipeline/ingest/players_link_test.py
git commit -m "feat(ingest): fetch_teams + link_team_ids (api-football team ids onto Team)"
```

---

## Self-Review

**Spec coverage (Stage 1a slice):** `Player` model + migration ✓ (Task 1); `provider_team_id` on Team ✓ (Task 1) + populated via `link_team_ids` ✓ (Task 3); `provider_player_id` on `LineupPlayer` + `player.id` extraction ✓ (Tasks 1-2). Deferred to Stage 1b (explicitly, per Global Constraints): squad ingestion, per-player club/WC stats, rate-limit pacing, production orchestration (backend endpoint + cron). Model fields match the spec's `Player` schema exactly.

**Placeholder scan:** none — every step has complete code and exact commands. Task 2 Steps 3/5 show the full surrounding dict/constructor, not a diff fragment.

**Type consistency:** `provider_player_id`/`provider_team_id` are `int|None` everywhere (model, migration, parser key `player_id` → column `provider_player_id`). `link_team_ids(db, teams_response) -> int` and `fetch_teams(...) -> list[dict]` are consistent between the Interfaces blocks, the test, and the implementation. Migration columns mirror the `Player` model field-for-field.
