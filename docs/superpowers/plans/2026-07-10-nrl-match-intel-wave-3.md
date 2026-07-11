# NRL Match Intelligence — Wave 3 (Player + Live Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the NRL player + live layer on `feat/nrl-match-intel-w3` — weekly team-list ingest with late-change flagging, a try-scorer probability model over try-event history, an in-play win-probability model reusing the pre-game Elo prediction, and a live-score layer (scheduled poller + read endpoint + 60s-polling UI) — wired into the shared Match Intelligence page Wave 1 owns.

**Architecture:** Two new DB tables owned by this wave (`nrl_team_lists`, plus `nrl_live_state`/`nrl_live_events` for the live layer — additions beyond the spec's explicit table list, justified in Task 1). A `StatsProvider`-shaped shim (`pipeline/sports/nrl_stats_shim.py`) stands in for Wave 2's real protocol until it merges, so team-list ingest and live polling can be built and tested now against recorded fixtures. The in-play model is a small logistic layered on top of (never replacing) `ml.sports.nrl.model.predict()`, trained on synthetic-but-outcome-anchored scoreline trajectories because NRL ingest has no half-time/minute data. The try-scorer model additionally depends on Wave 2's `nrl_try_events` table, so it and the scorers endpoint are built against a second, clearly-marked reconciliation shim and ordered after everything Wave-2-independent. UI tasks append one `sections.ts` entry and one self-contained component file each, last, after a merge of `origin/main`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), plain-function pipeline modules run via `python -m` (pipeline), scikit-learn/numpy for the logistic fit (ml), Next.js server components + one client island using the existing `useFetch` hook (frontend), GitHub Actions cron workflows for scheduling.

## Global Constraints

- Isolated worktree; branch from `origin/main`; never commit `frontend/node_modules` (symlink — `git reset frontend/node_modules` before commit).
- Midnight theme tokens only — use existing CSS variables/Tailwind classes; no new hex values.
- **No bookmaker links, odds CTAs, or value-vs-odds badges.** Market comparison exists only where it already exists (football "Model vs market"). Try-scorer output is probabilities.
- Kickoff times: `Australia/Sydney` with `timeZoneName: "short"`.
- Footer disclaimer stays: analytics and entertainment only.
- Server components + Client islands, ISR like existing NRL pages; all `fetch` fall back with `.catch(() => null)` so `npm run build` succeeds without a backend.
- Backend/pipeline: pytest; frontend: jest (worker SIGSEGV under parallel load is a known flake — rerun once) + `npm run build` must pass.
- Model version strings come from params loaders (`current_model_version()` pattern), never hardcoded in consumers.
- PR per wave; merge order W1 → W2 → W3; each wave independently shippable.

---

## Setup (run once, before Task 1)

The primary checkout may be in use by another session. Work only inside an isolated worktree, per the spec's mandatory pattern:

```bash
cd "/Users/macbookpro/Projects/FIFA WC26 Prediction"
git worktree add /tmp/nrl-intel-w3 -b feat/nrl-match-intel-w3 origin/main
cd /tmp/nrl-intel-w3
ln -s "/Users/macbookpro/Projects/FIFA WC26 Prediction/frontend/node_modules" frontend/node_modules
printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\n' > frontend/.env.local
git reset frontend/node_modules
```

Run `git reset frontend/node_modules` again before every commit in this plan (the symlink must never be staged). Remove the worktree (`git worktree remove /tmp/nrl-intel-w3`) once the PR is up.

All file paths below are relative to this worktree's repo root unless stated otherwise. Backend/pipeline tests run with `pytest <path>`; frontend tests with `cd frontend && npx jest <path>` (rerun once on a worker SIGSEGV, per Global Constraints).

## Wave-2 reconciliation policy (read before Task 2 and Task 7)

`nrl_try_events` and the `StatsProvider` protocol are Wave 2 deliverables (`feat/nrl-match-intel-w2`), which runs concurrently and may not be merged when this plan executes. Two clearly-marked shim modules stand in:

- `pipeline/sports/nrl_stats_shim.py` (Task 2) — duplicates the `StatsProvider` Protocol plus the `TeamListEntry`/`LivePayload` payload shapes Wave 3 consumes, verbatim from the spec, with a recorded-fixture-backed default implementation. Task 2 and Task 4 import from it.
- `backend/app/models/nrl_wave2_shim.py` (Task 7) — duplicates the `nrl_try_events` table as a SQLAlchemy model, deliberately **not** wired into `app/models/__init__.py`'s `__all__` or into any Alembic migration (Wave 2 owns that migration; this shim only exists so pytest's in-memory SQLite can create the table). Task 7 and Task 8 import from it.

Both modules carry a large module-docstring flagged `WAVE 2 RECONCILIATION SHIM` with exact merge instructions (which imports to redirect, what to delete). **Final-reviewer note:** when `feat/nrl-match-intel-w2` merges to `main` before this branch does, the person doing the W1→W2→W3 integration must (1) diff the shim dataclasses/model against Wave 2's real ones for field-for-field parity, (2) redirect the imports listed in each shim's docstring, (3) delete both shim files. Until that merge, every place that would call a *real* live/team-list HTTP provider instead constructs `RecordedFixtureStatsProvider()` with no fixtures configured, which safely no-ops (matches the spec: "Until W2 merges, all model work runs against recorded fixtures").

---

### Task 1: DB models + migration for `nrl_team_lists`, `nrl_live_state`, `nrl_live_events`

Adds the three tables this wave owns outright (no Wave 2 dependency). `nrl_live_state`/`nrl_live_events` are additions beyond the spec's literal DB-table list (which names only `nrl_team_lists` for Wave 3) — necessary because the live endpoint's event timeline and "last known score" must survive across polls and process restarts; computing them fresh from `StatsProvider.fetch_live` on every read would either lose event history or still require storing prior polls somewhere to diff against. Purely additive, no spec field is removed or renamed.

**Files:**
- Modify: `backend/app/models/__init__.py` (append 3 classes + update `__all__`)
- Create: `backend/alembic/versions/<new_revision>_add_nrl_team_lists_and_live_tables.py`
- Test: `backend/tests/test_nrl_w3_models.py`

**Interfaces:**
- Produces:
  - `NrlTeamList(id, match_id, team, jersey, player, position, is_late_change, updated_at)` — `backend/app/models/__init__.py`, unique on `(match_id, team, jersey)`.
  - `NrlLiveState(id, match_id, status, minute, score_home, score_away, live_home_prob, updated_at)` — unique on `match_id`.
  - `NrlLiveEvent(id, match_id, minute, type, team, player, prob_after, created_at)`.

- [ ] **Step 1: Write the failing model tests**

```python
# backend/tests/test_nrl_w3_models.py
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NrlLiveEvent, NrlLiveState, NrlTeamList, SportMatch


def _make_match(db):
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="scheduled")
    db.add(m)
    db.flush()
    return m


def test_nrl_team_list_unique_match_team_jersey(db_session):
    m = _make_match(db_session)
    db_session.add(NrlTeamList(match_id=m.id, team="Broncos", jersey=1, player="A. Test", position="FB"))
    db_session.commit()
    db_session.add(NrlTeamList(match_id=m.id, team="Broncos", jersey=1, player="B. Test", position="FB"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_nrl_team_list_default_is_late_change_false(db_session):
    m = _make_match(db_session)
    row = NrlTeamList(match_id=m.id, team="Broncos", jersey=1, player="A. Test", position="FB")
    db_session.add(row)
    db_session.commit()
    assert row.is_late_change is False


def test_nrl_live_state_one_row_per_match(db_session):
    m = _make_match(db_session)
    db_session.add(NrlLiveState(match_id=m.id, status="live", minute=10,
                                 score_home=6, score_away=0, live_home_prob=0.7))
    db_session.commit()
    db_session.add(NrlLiveState(match_id=m.id, status="live", minute=20,
                                 score_home=12, score_away=0, live_home_prob=0.8))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_nrl_live_event_round_trips(db_session):
    m = _make_match(db_session)
    ev = NrlLiveEvent(match_id=m.id, minute=5, type="score", team="home",
                       player=None, prob_after=0.62)
    db_session.add(ev)
    db_session.commit()
    assert ev.id is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_nrl_w3_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'NrlTeamList' from 'app.models'`

- [ ] **Step 3: Add the three models**

Open `backend/app/models/__init__.py`. Confirm the existing import line includes `false` (it does, used by `is_shadow`/similar columns):

```python
from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String,
    UniqueConstraint, false, func, true,
)
```

Append after the `SportPredictionResult` class:

```python
class NrlTeamList(Base):
    """Weekly team-list announcement for one NRL match (Wave 3).

    One row per named player per team per match. Re-ingesting a match's list
    replaces the previous rows for that match; is_late_change flags a jersey
    slot whose named player differs from the previous ingest — never the
    very first announcement for that match (see pipeline/sports/nrl_team_lists.py).
    """
    __tablename__ = "nrl_team_lists"
    __table_args__ = (
        UniqueConstraint("match_id", "team", "jersey", name="uq_nrl_team_list_match_team_jersey"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    jersey: Mapped[int] = mapped_column(Integer)
    player: Mapped[str] = mapped_column(String(120))
    position: Mapped[str] = mapped_column(String(10))
    is_late_change: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NrlLiveState(Base):
    """Latest known live snapshot for one NRL match (Wave 3), upserted by
    pipeline.sports.nrl_live_poll. Absence of a row means the match has
    never been polled — the live endpoint falls back to a "pre"/"final"
    view derived from SportMatch + SportPrediction alone."""
    __tablename__ = "nrl_live_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(10))  # "live" | "final" (never "pre" — see docstring)
    minute: Mapped[int | None] = mapped_column(Integer)
    score_home: Mapped[int | None] = mapped_column(Integer)
    score_away: Mapped[int | None] = mapped_column(Integer)
    live_home_prob: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NrlLiveEvent(Base):
    """One scoring tick in an NRL match's live timeline (Wave 3)."""
    __tablename__ = "nrl_live_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    minute: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    team: Mapped[str] = mapped_column(String(10))  # "home" | "away"
    player: Mapped[str | None] = mapped_column(String(120))
    prob_after: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Then find the `__all__` list near the end of the file and add `"NrlTeamList"`, `"NrlLiveState"`, `"NrlLiveEvent"` to it.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest backend/tests/test_nrl_w3_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the Alembic migration**

This is a shared, moving checkout — Waves 1 and 2 each add their own migrations. Do **not** hardcode a `down_revision`. From the worktree:

```bash
cd backend && alembic heads
```

Note the single head id it prints (call it `<HEAD>`). Generate a new revision id:

```bash
python3 -c "import uuid; print(uuid.uuid4().hex[:12])"
```

Call that `<NEW>`. Create `backend/alembic/versions/<NEW>_add_nrl_team_lists_and_live_tables.py`:

```python
"""add nrl_team_lists, nrl_live_state, nrl_live_events (Wave 3 player + live layer)

Revision ID: <NEW>
Revises: <HEAD>
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "<NEW>"
down_revision: Union[str, None] = "<HEAD>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nrl_team_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("jersey", sa.Integer(), nullable=False),
        sa.Column("player", sa.String(length=120), nullable=False),
        sa.Column("position", sa.String(length=10), nullable=False),
        sa.Column("is_late_change", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("match_id", "team", "jersey", name="uq_nrl_team_list_match_team_jersey"),
    )
    op.create_index("ix_nrl_team_lists_match_id", "nrl_team_lists", ["match_id"])

    op.create_table(
        "nrl_live_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=True),
        sa.Column("score_home", sa.Integer(), nullable=True),
        sa.Column("score_away", sa.Integer(), nullable=True),
        sa.Column("live_home_prob", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("match_id", name="uq_nrl_live_state_match_id"),
    )
    op.create_index("ix_nrl_live_state_match_id", "nrl_live_state", ["match_id"])

    op.create_table(
        "nrl_live_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("team", sa.String(length=10), nullable=False),
        sa.Column("player", sa.String(length=120), nullable=True),
        sa.Column("prob_after", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_nrl_live_events_match_id", "nrl_live_events", ["match_id"])


def downgrade() -> None:
    op.drop_table("nrl_live_events")
    op.drop_table("nrl_live_state")
    op.drop_table("nrl_team_lists")
```

- [ ] **Step 6: Verify the migration**

At minimum, check it's syntactically valid:

Run: `python3 -m py_compile backend/alembic/versions/<NEW>_add_nrl_team_lists_and_live_tables.py`
Expected: no output (success)

If a local Postgres is available (see `docker-compose.yml` — `docker-compose up -d db`), also verify it applies and reverses cleanly:

Run: `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: each command exits 0

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/<NEW>_add_nrl_team_lists_and_live_tables.py backend/tests/test_nrl_w3_models.py
git commit -m "feat(nrl): add nrl_team_lists, nrl_live_state, nrl_live_events tables"
```

---

### Task 2: Team-lists ingest + Wave-2 StatsProvider shim

Weekly pipeline step: fetches announced team lists via a `StatsProvider`-shaped shim (see "Wave-2 reconciliation policy" above) and upserts them, flagging `is_late_change` on jersey slots whose named player changed since the last ingest for that match. Auto-detects which rounds need a fetch (any scheduled match kicking off in the next 10 days) so it can run unattended from a cron.

**Files:**
- Create: `pipeline/sports/nrl_stats_shim.py`
- Create: `pipeline/sports/nrl_team_lists.py`
- Test: `pipeline/sports/nrl_team_lists_test.py`
- Modify: `.github/workflows/nrl-refresh.yml`

**Interfaces:**
- Consumes: `NrlTeamList` (Task 1), `SportMatch` (existing).
- Produces:
  - `pipeline/sports/nrl_stats_shim.py`: `TeamListEntry(match_id, team, jersey, player, position)`, `LivePayload(minute, score_home, score_away, status)`, `StatsProvider` Protocol (`fetch_match_stats`, `fetch_team_list`, `fetch_live`), `RecordedFixtureStatsProvider(team_lists=None, live=None)`.
  - `pipeline/sports/nrl_team_lists.py`: `upsert_team_list(db, entries: list[TeamListEntry]) -> dict`, `ingest_round(db, season, round_no, provider) -> dict`, `main()` CLI (`python -m pipeline.sports.nrl_team_lists --season Y [--round N]`).

- [ ] **Step 1: Create the StatsProvider shim (no test — pure data classes + a literal-fixture default)**

```python
# pipeline/sports/nrl_stats_shim.py
"""WAVE 2 RECONCILIATION SHIM — delete this file once feat/nrl-match-intel-w2
merges and pipeline/sports/nrl_stats.py exists on main.

Wave 2 owns the real StatsProvider Protocol and its default implementation
in pipeline/sports/nrl_stats.py. This branch needs fetch_team_list and
fetch_live before Wave 2 has necessarily merged, so this module duplicates
ONLY the pieces this wave consumes, verbatim from the frozen spec contract,
plus a recorded-fixture-backed default so tests and the scheduled workflow
never make a live HTTP call.

MERGE INSTRUCTIONS for the integrator: once pipeline/sports/nrl_stats.py
exists on main with a real StatsProvider/TeamListEntry/LivePayload, replace
every `from pipeline.sports.nrl_stats_shim import ...` in this branch
(pipeline/sports/nrl_team_lists.py, pipeline/sports/nrl_live_poll.py,
backend/app/api/internal.py, and their tests) with
`from pipeline.sports.nrl_stats import ...`, verify field-for-field parity
with the dataclasses below, then delete this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TeamListEntry:
    match_id: int
    team: str
    jersey: int
    player: str
    position: str


@dataclass(frozen=True)
class LivePayload:
    minute: int
    score_home: int
    score_away: int
    status: str  # "live" | "final"


@dataclass(frozen=True)
class MatchStatsPayload:
    """Unused by Wave 3 — declared only so StatsProvider's shape matches the
    spec exactly; fetch_match_stats is Wave 2's own concern."""
    tries: int


class StatsProvider(Protocol):
    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None: ...
    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]: ...
    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None: ...


class RecordedFixtureStatsProvider:
    """Default StatsProvider for tests, local dev, and (until Wave 2 merges)
    the scheduled workflows — returns literal, hand-recorded fixture data,
    never makes an HTTP call. With no fixtures configured it safely no-ops."""

    def __init__(
        self,
        team_lists: dict[tuple[int, int], list[TeamListEntry]] | None = None,
        live: dict[tuple[int, int, int], LivePayload] | None = None,
    ) -> None:
        self._team_lists = team_lists or {}
        self._live = live or {}

    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None:
        return None  # not this wave's concern

    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]:
        return list(self._team_lists.get((season, round_no), []))

    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None:
        return self._live.get((season, round_no, match_no))
```

- [ ] **Step 2: Write the failing ingest tests**

```python
# pipeline/sports/nrl_team_lists_test.py
from app.models import NrlTeamList, SportMatch
from pipeline.sports.nrl_stats_shim import RecordedFixtureStatsProvider, TeamListEntry
from pipeline.sports.nrl_team_lists import ingest_round, upsert_team_list


def _make_match(db, match_no=1):
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=match_no, status="scheduled")
    db.add(m)
    db.flush()
    return m


def test_upsert_team_list_first_announcement_is_not_late_change(db_session):
    m = _make_match(db_session)
    entries = [
        TeamListEntry(match_id=m.id, team="Broncos", jersey=1, player="A. First", position="FB"),
        TeamListEntry(match_id=m.id, team="Broncos", jersey=2, player="B. Second", position="WG"),
    ]
    summary = upsert_team_list(db_session, entries)
    assert summary == {"matches": 1, "players": 2, "late_changes": 0}
    rows = db_session.query(NrlTeamList).filter_by(match_id=m.id).all()
    assert all(not r.is_late_change for r in rows)


def test_upsert_team_list_flags_swapped_player_as_late_change(db_session):
    m = _make_match(db_session)
    first = [TeamListEntry(match_id=m.id, team="Broncos", jersey=1, player="A. First", position="FB")]
    upsert_team_list(db_session, first)

    swapped = [TeamListEntry(match_id=m.id, team="Broncos", jersey=1, player="C. Replacement", position="FB")]
    summary = upsert_team_list(db_session, swapped)
    assert summary == {"matches": 1, "players": 1, "late_changes": 1}
    row = db_session.query(NrlTeamList).filter_by(match_id=m.id, jersey=1).one()
    assert row.player == "C. Replacement"
    assert row.is_late_change is True


def test_upsert_team_list_same_player_reingested_is_not_late_change(db_session):
    m = _make_match(db_session)
    entries = [TeamListEntry(match_id=m.id, team="Broncos", jersey=1, player="A. First", position="FB")]
    upsert_team_list(db_session, entries)
    summary = upsert_team_list(db_session, entries)
    assert summary["late_changes"] == 0


def test_ingest_round_never_raises_on_fetch_error(db_session):
    class _Boom:
        def fetch_team_list(self, season, round_no):
            raise RuntimeError("feed down")
        def fetch_match_stats(self, *a): return None
        def fetch_live(self, *a): return None

    summary = ingest_round(db_session, 2026, 1, _Boom())
    assert summary == {"matches": 0, "players": 0, "late_changes": 0}


def test_ingest_round_with_recorded_fixture_provider(db_session):
    m = _make_match(db_session)
    provider = RecordedFixtureStatsProvider(team_lists={
        (2026, 1): [TeamListEntry(match_id=m.id, team="Broncos", jersey=1, player="A. First", position="FB")],
    })
    summary = ingest_round(db_session, 2026, 1, provider)
    assert summary["matches"] == 1
    assert summary["players"] == 1


def test_ingest_round_ignores_entries_for_unknown_matches(db_session):
    provider = RecordedFixtureStatsProvider(team_lists={
        (2026, 1): [TeamListEntry(match_id=999999, team="Broncos", jersey=1, player="Ghost", position="FB")],
    })
    summary = ingest_round(db_session, 2026, 1, provider)
    assert summary == {"matches": 0, "players": 0, "late_changes": 0}
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest pipeline/sports/nrl_team_lists_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_team_lists'`

- [ ] **Step 4: Implement the ingest module**

```python
# pipeline/sports/nrl_team_lists.py
"""NRL team-list ingest (Wave 3).

Weekly pipeline step: pulls each round's announced team lists via
StatsProvider.fetch_team_list and upserts them into nrl_team_lists,
flagging is_late_change when a jersey slot's named player differs from the
last-ingested list for that match (never on the first-ever announcement).

CLI: python -m pipeline.sports.nrl_team_lists --season 2026 [--round 1]
     (omit --round to auto-detect rounds with a scheduled match in the next
     10 days — the rounds a fresh announcement would cover)
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import NrlTeamList, SportMatch
from pipeline.sports.nrl_stats_shim import RecordedFixtureStatsProvider, StatsProvider, TeamListEntry

log = logging.getLogger(__name__)

SPORT = "nrl"
_EMPTY = {"matches": 0, "players": 0, "late_changes": 0}


def upsert_team_list(db: Session, entries: list[TeamListEntry]) -> dict:
    """Replace the stored team list for every match referenced in `entries`,
    grouped by match_id. Returns {"matches": n, "players": n, "late_changes": n}."""
    by_match: dict[int, list[TeamListEntry]] = {}
    for e in entries:
        by_match.setdefault(e.match_id, []).append(e)

    matches = players = late_changes = 0
    for match_id, match_entries in by_match.items():
        existing = {
            (row.team, row.jersey): row.player
            for row in db.query(NrlTeamList).filter_by(match_id=match_id).all()
        }
        had_prior_list = bool(existing)
        db.query(NrlTeamList).filter_by(match_id=match_id).delete()

        for e in match_entries:
            is_late = had_prior_list and existing.get((e.team, e.jersey)) not in (None, e.player)
            db.add(NrlTeamList(
                match_id=e.match_id, team=e.team, jersey=e.jersey,
                player=e.player, position=e.position, is_late_change=is_late,
            ))
            players += 1
            if is_late:
                late_changes += 1
        matches += 1

    db.commit()
    return {"matches": matches, "players": players, "late_changes": late_changes}


def ingest_round(db: Session, season: int, round_no: int, provider: StatsProvider) -> dict:
    """Fetch + upsert one round's team lists. Never raises — a feed hiccup
    logs and returns a zeroed summary, matching nrl_ingest's best-effort idiom."""
    try:
        entries = provider.fetch_team_list(season, round_no)
    except Exception as exc:  # noqa: BLE001
        log.warning("nrl team-list fetch(%s, round %s) failed: %s", season, round_no, exc)
        return dict(_EMPTY)
    if not entries:
        return dict(_EMPTY)

    known_ids = {
        row.id for row in db.query(SportMatch.id).filter(
            SportMatch.sport == SPORT,
            SportMatch.id.in_({e.match_id for e in entries}),
        )
    }
    filtered = [e for e in entries if e.match_id in known_ids]
    if not filtered:
        return dict(_EMPTY)
    return upsert_team_list(db, filtered)


def rounds_needing_team_lists(db: Session, season: int, days_ahead: int = 10) -> list[int]:
    """Distinct round numbers with a scheduled match kicking off within the
    next `days_ahead` days — the rounds a team-list announcement covers."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)
    rows = (
        db.query(SportMatch.round)
        .filter(
            SportMatch.sport == SPORT, SportMatch.season == season,
            SportMatch.status == "scheduled",
            SportMatch.kickoff_utc.isnot(None),
            SportMatch.kickoff_utc >= now - timedelta(days=1),
            SportMatch.kickoff_utc <= cutoff,
        )
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0] is not None})


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--round", type=int, dest="round_no", default=None,
                     help="ingest one specific round; omit to auto-detect upcoming rounds")
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        # WAVE 2 RECONCILIATION: swap for the real provider from
        # pipeline.sports.nrl_stats once merged. Until then this safely
        # no-ops in production (no fixtures configured).
        provider = RecordedFixtureStatsProvider()
        rounds = [args.round_no] if args.round_no is not None else rounds_needing_team_lists(db, args.season)
        totals = dict(_EMPTY)
        for r in rounds:
            summary = ingest_round(db, args.season, r, provider)
            for k in totals:
                totals[k] += summary[k]
        log.info("nrl team-list ingest: season=%s rounds=%s totals=%s", args.season, rounds, totals)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest pipeline/sports/nrl_team_lists_test.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Write the `rounds_needing_team_lists` test**

```python
# append to pipeline/sports/nrl_team_lists_test.py
from datetime import datetime, timedelta, timezone

from pipeline.sports.nrl_team_lists import rounds_needing_team_lists


def test_rounds_needing_team_lists_only_includes_near_term_scheduled(db_session):
    now = datetime.now(timezone.utc)
    near = SportMatch(sport="nrl", season=2026, round=5, match_no=1, status="scheduled",
                       kickoff_utc=now + timedelta(days=2))
    far = SportMatch(sport="nrl", season=2026, round=9, match_no=1, status="scheduled",
                      kickoff_utc=now + timedelta(days=30))
    finished = SportMatch(sport="nrl", season=2026, round=4, match_no=1, status="finished",
                           kickoff_utc=now - timedelta(days=3), score_home=10, score_away=6)
    db_session.add_all([near, far, finished])
    db_session.commit()

    assert rounds_needing_team_lists(db_session, 2026) == [5]
```

- [ ] **Step 7: Run to verify it passes**

Run: `pytest pipeline/sports/nrl_team_lists_test.py -v`
Expected: PASS (7 tests)

- [ ] **Step 8: Wire into the weekly pipeline**

Real NRL team lists are announced Tuesday for the whole round; `nrl-refresh.yml`'s existing Monday 18:00 UTC run fires before that announcement, so add a third cron slot after it, plus the new step. Open `.github/workflows/nrl-refresh.yml` and replace:

```yaml
on:
  schedule:
    - cron: "0 18 * * 1"
    - cron: "0 18 * * 5"
  workflow_dispatch: {}
```

with:

```yaml
on:
  schedule:
    - cron: "0 18 * * 1"
    - cron: "0 18 * * 5"
    - cron: "0 8 * * 2"   # Tue ~18:00 AEST -- after the round's team-list announcement
  workflow_dispatch: {}
```

Then append, after the existing "Generate frozen shadow predictions + grade finished matches" step:

```yaml
      - name: Ingest NRL team lists (idempotent; late-change flagged)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.sports.nrl_team_lists --season 2026
```

Verify the YAML still parses:

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/nrl-refresh.yml'))"`
Expected: no output (success)

- [ ] **Step 9: Commit**

```bash
git add pipeline/sports/nrl_stats_shim.py pipeline/sports/nrl_team_lists.py pipeline/sports/nrl_team_lists_test.py .github/workflows/nrl-refresh.yml
git commit -m "feat(nrl): team-list ingest with late-change flagging + StatsProvider shim"
```

---

### Task 3: In-play win-probability logistic — synthetic-trajectory fit

Builds the logistic that updates the pre-game win probability during a live match. **Honesty note (read before implementing):** `pipeline/sports/nrl_ingest.py` only ever captures full-time scores — `SportMatch` has no half-time columns, so there is no minute-level or half-time historical data anywhere in this repo to fit on. Training rows are instead generated by simulating plausible scoring-event *timings* for each historical match, constrained to sum to that match's real final score; the label at every checkpoint is the match's real eventual winner (always known, regardless of the imagined timing). This is a standard technique for building a live win-probability curve from final-score-only history — documented in the module so nobody mistakes it for a fit on genuine play-by-play data.

**Files:**
- Create: `ml/sports/nrl/live_model.py`
- Create: `ml/sports/nrl/live_params.py`
- Create: `pipeline/sports/nrl_live_fit.py`
- Test: `ml/sports/nrl/live_model_test.py`
- Test: `pipeline/sports/nrl_live_fit_test.py`

**Interfaces:**
- Consumes: `SportMatch`, `SportPrediction` (existing).
- Produces:
  - `ml/sports/nrl/live_model.py`: `LiveWinProbModel().fit(rows) -> LiveWinProbModel`, `.predict_proba(score_diff, minutes_remaining, pregame_prob) -> float`, `.coefficients() -> dict`; `predict_live_prob(score_diff, minutes_remaining, pregame_prob, params: NrlLiveParams) -> float` (pure-math inference, no sklearn object needed — this is what Task 4/6 call).
  - `ml/sports/nrl/live_params.py`: `NrlLiveParams(version, intercept, coef_score_diff, coef_interaction, coef_pregame_logit)`, `load_nrl_live_params() -> NrlLiveParams`, `save_nrl_live_params(params) -> None`.
  - `pipeline/sports/nrl_live_fit.py`: `simulate_score_trajectory(final_score, rng) -> list[tuple[float,int]]`, `generate_training_rows(matches, trajectories_per_match, checkpoints_per_trajectory, seed) -> list[dict]`, `fit_from_db(db, trajectories_per_match=20, seed=42, version="nrl-live-v0.1") -> NrlLiveParams`, `main()` CLI.

- [ ] **Step 1: Write the failing live-model tests**

```python
# ml/sports/nrl/live_model_test.py
import math

from ml.sports.nrl.live_model import LiveWinProbModel, _features, predict_live_prob
from ml.sports.nrl.live_params import NrlLiveParams


def test_features_shape_and_interaction_term():
    x = _features(score_diff=6.0, minutes_remaining=40.0, pregame_prob=0.6)
    assert x[0] == 6.0
    assert x[1] == 6.0 * math.sqrt(40.0)
    assert x[2] == math.log(0.6 / 0.4)


def test_fit_recovers_a_monotonic_relationship():
    rows = []
    for score_diff in range(-20, 21, 2):
        rows.append({"score_diff": float(score_diff), "minutes_remaining": 5.0,
                      "pregame_prob": 0.5, "home_won": score_diff > 0})
    model = LiveWinProbModel().fit(rows)
    p_ahead = model.predict_proba(score_diff=12.0, minutes_remaining=5.0, pregame_prob=0.5)
    p_behind = model.predict_proba(score_diff=-12.0, minutes_remaining=5.0, pregame_prob=0.5)
    assert p_ahead > 0.5 > p_behind


def test_predict_live_prob_pure_math_matches_sigmoid_by_hand():
    params = NrlLiveParams(version="test", intercept=0.1, coef_score_diff=0.2,
                            coef_interaction=0.01, coef_pregame_logit=0.5)
    got = predict_live_prob(score_diff=4.0, minutes_remaining=20.0, pregame_prob=0.6, params=params)
    x = _features(4.0, 20.0, 0.6)
    z = 0.1 + 0.2 * x[0] + 0.01 * x[1] + 0.5 * x[2]
    expected = 1.0 / (1.0 + math.exp(-z))
    assert abs(got - expected) < 1e-9


def test_load_nrl_live_params_falls_back_to_defaults(tmp_path, monkeypatch):
    import ml.sports.nrl.live_params as live_params
    monkeypatch.setattr(live_params, "_PARAMS_FILE", tmp_path / "missing.json")
    params = live_params.load_nrl_live_params()
    assert params == NrlLiveParams()


def test_save_then_load_nrl_live_params_round_trips(tmp_path, monkeypatch):
    import ml.sports.nrl.live_params as live_params
    monkeypatch.setattr(live_params, "_PARAMS_FILE", tmp_path / "live_params.json")
    written = NrlLiveParams(version="nrl-live-v0.2", intercept=0.3, coef_score_diff=0.22,
                             coef_interaction=0.015, coef_pregame_logit=0.48)
    live_params.save_nrl_live_params(written)
    assert live_params.load_nrl_live_params() == written
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest ml/sports/nrl/live_model_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.sports.nrl.live_model'`

- [ ] **Step 3: Implement `live_params.py`**

```python
# ml/sports/nrl/live_params.py
"""Tuned parameter loader for the in-play win-probability logistic (Wave 3).
Mirrors ml/sports/nrl/params.py's load/save pattern exactly."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_PARAMS_FILE = Path(__file__).with_name("live_params.json")


@dataclass(frozen=True)
class NrlLiveParams:
    version: str = "nrl-live-v0.1"
    intercept: float = 0.0
    coef_score_diff: float = 0.25
    coef_interaction: float = 0.02
    coef_pregame_logit: float = 0.5


def load_nrl_live_params() -> NrlLiveParams:
    """Load tuned params from live_params.json, or NrlLiveParams() defaults
    if absent/invalid (missing file, bad JSON, or a missing/malformed field)."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlLiveParams(
            version=data.get("version", NrlLiveParams().version),
            intercept=float(data["intercept"]),
            coef_score_diff=float(data["coef_score_diff"]),
            coef_interaction=float(data["coef_interaction"]),
            coef_pregame_logit=float(data["coef_pregame_logit"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return NrlLiveParams()


def save_nrl_live_params(params: NrlLiveParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")
```

- [ ] **Step 4: Implement `live_model.py`**

```python
# ml/sports/nrl/live_model.py
"""In-play NRL win-probability model (Wave 3).

A small logistic regression layered on TOP of (never replacing) the
pre-game predict() in ml.sports.nrl.model, over three engineered features:
  1. score_diff -- home points minus away points, right now.
  2. score_diff * sqrt(minutes_remaining) -- interaction term (spec: "sqrt
     of minutes remaining interaction"); lets the model learn how much a
     given differential should move win probability as time runs out.
  3. logit(pregame_prob) -- the SAME p_home the pre-game model already
     froze for this fixture (spec: "pre-game probability offset"), so a
     0-0 scoreline at minute 1 still reflects the pre-game favourite.

See pipeline/sports/nrl_live_fit.py for how training rows are generated
(there is no real minute-level history to fit on -- read that module's
docstring before assuming this was fit on genuine play-by-play data).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression

from ml.sports.nrl.live_params import NrlLiveParams


def _logit(p: float, eps: float = 1e-6) -> float:
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def _features(score_diff: float, minutes_remaining: float, pregame_prob: float) -> list[float]:
    minutes_remaining = max(minutes_remaining, 0.0)
    return [score_diff, score_diff * math.sqrt(minutes_remaining), _logit(pregame_prob)]


@dataclass
class LiveWinProbModel:
    """Wraps a fitted sklearn LogisticRegression over the 3 features above.
    Used only at FIT time (pipeline/sports/nrl_live_fit.py); at inference
    time the live poller uses the pure-math predict_live_prob() below."""

    model: LogisticRegression | None = None

    def fit(self, rows: list[dict]) -> "LiveWinProbModel":
        """rows: [{"score_diff", "minutes_remaining", "pregame_prob", "home_won"}, ...]"""
        X = np.array([
            _features(r["score_diff"], r["minutes_remaining"], r["pregame_prob"])
            for r in rows
        ])
        y = np.array([1 if r["home_won"] else 0 for r in rows])
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X, y)
        return self

    def predict_proba(self, score_diff: float, minutes_remaining: float, pregame_prob: float) -> float:
        if self.model is None:
            raise RuntimeError("model not fitted")
        x = np.array([_features(score_diff, minutes_remaining, pregame_prob)])
        classes = list(self.model.classes_)
        proba = self.model.predict_proba(x)[0]
        return float(proba[classes.index(1)])

    def coefficients(self) -> dict:
        """Raw fitted coefficients, for persistence via live_params.py."""
        if self.model is None:
            raise RuntimeError("model not fitted")
        coef = self.model.coef_[0]
        return {
            "intercept": float(self.model.intercept_[0]),
            "coef_score_diff": float(coef[0]),
            "coef_interaction": float(coef[1]),
            "coef_pregame_logit": float(coef[2]),
        }


def predict_live_prob(
    score_diff: float, minutes_remaining: float, pregame_prob: float, params: NrlLiveParams,
) -> float:
    """Pure-math inference from persisted coefficients (no sklearn object
    needed) -- called on every live-poll tick and every /live read."""
    x = _features(score_diff, minutes_remaining, pregame_prob)
    z = (
        params.intercept
        + params.coef_score_diff * x[0]
        + params.coef_interaction * x[1]
        + params.coef_pregame_logit * x[2]
    )
    return 1.0 / (1.0 + math.exp(-z))
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest ml/sports/nrl/live_model_test.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Write the failing fitting-script tests**

```python
# pipeline/sports/nrl_live_fit_test.py
from datetime import datetime, timedelta, timezone

import numpy as np

from app.models import SportMatch, SportPrediction
from pipeline.sports.nrl_live_fit import fit_from_db, generate_training_rows, simulate_score_trajectory


def test_simulate_score_trajectory_sums_to_final_score():
    rng = np.random.default_rng(1)
    traj = simulate_score_trajectory(24, rng)
    assert traj[-1][1] == 24
    assert all(traj[i][0] <= traj[i + 1][0] for i in range(len(traj) - 1))


def test_simulate_score_trajectory_zero_score_is_empty():
    rng = np.random.default_rng(1)
    assert simulate_score_trajectory(0, rng) == []


def test_generate_training_rows_labels_match_real_outcome():
    matches = [{"score_home": 24, "score_away": 10, "pregame_prob": 0.55}]
    rows = generate_training_rows(matches, trajectories_per_match=3, checkpoints_per_trajectory=4, seed=7)
    assert len(rows) == 3 * 4
    assert all(r["home_won"] is True for r in rows)
    assert all(0.0 <= r["minutes_remaining"] <= 80.0 for r in rows)


def test_fit_from_db_falls_back_to_defaults_with_too_few_matches(db_session):
    params = fit_from_db(db_session)
    assert params.version == "nrl-live-v0.1"


def test_fit_from_db_uses_pre_kickoff_predictions_only(db_session):
    kickoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for i in range(25):
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=i, status="finished",
                        kickoff_utc=kickoff, score_home=20 + i % 3, score_away=10)
        db_session.add(m)
        db_session.flush()
        db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                        p_home=0.6, p_draw=0.01, p_away=0.39,
                                        created_at=kickoff - timedelta(hours=1)))
    db_session.commit()
    params = fit_from_db(db_session, trajectories_per_match=5, seed=3, version="nrl-live-v0.2")
    assert params.version == "nrl-live-v0.2"
```

- [ ] **Step 7: Run to verify it fails**

Run: `pytest pipeline/sports/nrl_live_fit_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_live_fit'`

- [ ] **Step 8: Implement the fitting script**

```python
# pipeline/sports/nrl_live_fit.py
"""Fit the in-play win-probability logistic from historical NRL results
(Wave 3). See ml/sports/nrl/live_model.py's module docstring: NRL ingest
has no half-time/minute data, so training rows are generated by simulating
scoring-event timings anchored to each match's real final score and real
eventual winner.

CLI: python -m pipeline.sports.nrl_live_fit --seed 42 --trajectories-per-match 20
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
from sqlalchemy.orm import Session

from app.models import SportMatch, SportPrediction
from ml.sports.nrl.live_model import LiveWinProbModel
from ml.sports.nrl.live_params import NrlLiveParams, save_nrl_live_params

log = logging.getLogger(__name__)

MATCH_MINUTES = 80.0
# Rough NRL scoring-play split (penalty goal / unconverted try / converted
# try) used only to make simulated event VALUES plausible -- the timing is
# synthetic regardless, so this doesn't need to be precise.
POINT_VALUES = [2, 4, 6]
POINT_WEIGHTS = [0.20, 0.15, 0.65]
CHECKPOINTS_PER_TRAJECTORY = 5
MIN_MATCHES_TO_FIT = 20


def simulate_score_trajectory(final_score: int, rng: np.random.Generator) -> list[tuple[float, int]]:
    """Return [(minute, cumulative_score), ...], strictly increasing in
    minute, summing exactly to final_score. The TIMING is synthetic
    (independently uniform-random in [0, 80)); the total is real."""
    events: list[tuple[float, int]] = []
    remaining = final_score
    while remaining > 0:
        choices = [v for v in POINT_VALUES if v <= remaining] or [remaining]
        weights = np.array([
            POINT_WEIGHTS[POINT_VALUES.index(v)] if v in POINT_VALUES else 1.0
            for v in choices
        ])
        value = int(rng.choice(choices, p=weights / weights.sum()))
        minute = float(rng.uniform(0, MATCH_MINUTES))
        events.append((minute, value))
        remaining -= value
    events.sort(key=lambda e: e[0])
    cum = 0
    out = []
    for minute, value in events:
        cum += value
        out.append((minute, cum))
    return out


def _score_at(trajectory: list[tuple[float, int]], minute: float) -> int:
    score = 0
    for t, cum in trajectory:
        if t <= minute:
            score = cum
        else:
            break
    return score


def generate_training_rows(
    matches: list[dict],
    trajectories_per_match: int = 20,
    checkpoints_per_trajectory: int = CHECKPOINTS_PER_TRAJECTORY,
    seed: int = 42,
) -> list[dict]:
    """matches: [{"score_home", "score_away", "pregame_prob"}, ...]. Returns
    rows with keys score_diff/minutes_remaining/pregame_prob/home_won."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for m in matches:
        home_won = m["score_home"] > m["score_away"]
        for _ in range(trajectories_per_match):
            home_traj = simulate_score_trajectory(m["score_home"], rng)
            away_traj = simulate_score_trajectory(m["score_away"], rng)
            checkpoints = sorted(rng.uniform(0, MATCH_MINUTES, size=checkpoints_per_trajectory))
            for minute in checkpoints:
                sh = _score_at(home_traj, minute)
                sa = _score_at(away_traj, minute)
                rows.append({
                    "score_diff": float(sh - sa),
                    "minutes_remaining": MATCH_MINUTES - float(minute),
                    "pregame_prob": m["pregame_prob"],
                    "home_won": home_won,
                })
    return rows


def _finished_matches_with_pregame_prob(db: Session) -> list[dict]:
    """Finished nrl matches paired with their latest PRE-KICKOFF prediction
    -- same eligibility rule as pipeline.sports.nrl_predict.grade(), so the
    fitting set matches exactly what the live poller reads at runtime."""
    out = []
    finished = db.query(SportMatch).filter_by(sport="nrl", status="finished").all()
    for m in finished:
        if m.score_home is None or m.score_away is None:
            continue
        q = db.query(SportPrediction).filter_by(match_id=m.id)
        if m.kickoff_utc is not None:
            q = q.filter(SportPrediction.created_at <= m.kickoff_utc)
        latest = q.order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc()).first()
        if latest is None:
            continue
        out.append({"score_home": m.score_home, "score_away": m.score_away, "pregame_prob": latest.p_home})
    return out


def fit_from_db(
    db: Session, trajectories_per_match: int = 20, seed: int = 42, version: str = "nrl-live-v0.1",
) -> NrlLiveParams:
    matches = _finished_matches_with_pregame_prob(db)
    if len(matches) < MIN_MATCHES_TO_FIT:
        log.warning("only %d finished+predicted nrl matches -- keeping default live params", len(matches))
        return NrlLiveParams()
    rows = generate_training_rows(matches, trajectories_per_match=trajectories_per_match, seed=seed)
    fitted = LiveWinProbModel().fit(rows)
    return NrlLiveParams(version=version, **fitted.coefficients())


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trajectories-per-match", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--version", default="nrl-live-v0.1")
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        params = fit_from_db(db, trajectories_per_match=args.trajectories_per_match,
                              seed=args.seed, version=args.version)
        save_nrl_live_params(params)
        log.info("nrl live-model fit: %s", params)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9: Run to verify it passes**

Run: `pytest pipeline/sports/nrl_live_fit_test.py -v`
Expected: PASS (5 tests)

- [ ] **Step 10: Commit**

```bash
git add ml/sports/nrl/live_model.py ml/sports/nrl/live_params.py ml/sports/nrl/live_model_test.py pipeline/sports/nrl_live_fit.py pipeline/sports/nrl_live_fit_test.py
git commit -m "feat(nrl): in-play win-probability logistic (synthetic-trajectory fit)"
```

---

### Task 4: Live-match poller

Polls every NRL match currently inside its live window via `StatsProvider.fetch_live`, computes the in-play probability via `predict_live_prob` (reusing the frozen pre-game `SportPrediction.p_home` — never recomputed), and upserts `NrlLiveState` + appends `NrlLiveEvent` rows on score changes.

**Files:**
- Create: `pipeline/sports/nrl_live_poll.py`
- Test: `pipeline/sports/nrl_live_poll_test.py`

**Interfaces:**
- Consumes: `StatsProvider`, `LivePayload` (Task 2's shim), `predict_live_prob`, `load_nrl_live_params` (Task 3), `NrlLiveState`, `NrlLiveEvent` (Task 1), `SportMatch`, `SportPrediction` (existing).
- Produces: `matches_in_live_window(db, now=None) -> list[SportMatch]`, `poll_match(db, match, provider, now=None) -> dict | None`, `poll_live_matches(db, provider, now=None) -> dict` (used by Task 5's internal endpoint).

- [ ] **Step 1: Write the failing poller tests**

```python
# pipeline/sports/nrl_live_poll_test.py
from datetime import datetime, timedelta, timezone

from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction
from pipeline.sports.nrl_live_poll import matches_in_live_window, poll_live_matches, poll_match
from pipeline.sports.nrl_stats_shim import LivePayload, RecordedFixtureStatsProvider


def _make_match(db, kickoff, match_no=1):
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=match_no,
                    status="scheduled", kickoff_utc=kickoff)
    db.add(m)
    db.flush()
    return m


def test_matches_in_live_window_includes_in_progress_excludes_far_future(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    live = _make_match(db_session, kickoff=now - timedelta(minutes=30), match_no=1)
    future = _make_match(db_session, kickoff=now + timedelta(days=2), match_no=2)
    db_session.commit()

    ids = {m.id for m in matches_in_live_window(db_session, now=now)}
    assert live.id in ids
    assert future.id not in ids


def test_poll_match_reuses_frozen_pregame_probability(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                    p_home=0.7, p_draw=0.01, p_away=0.29))
    db_session.commit()

    provider = RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(minute=20, score_home=6, score_away=0, status="live"),
    })
    result = poll_match(db_session, m, provider, now=now)
    assert result["status"] == "live"
    assert result["live_home_prob"] > 0.7  # ahead + favourite -> even more likely

    state = db_session.query(NrlLiveState).filter_by(match_id=m.id).one()
    assert state.score_home == 6 and state.minute == 20


def test_poll_match_logs_event_on_score_change(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                    p_home=0.5, p_draw=0.01, p_away=0.49))
    db_session.commit()

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(minute=10, score_home=0, score_away=0, status="live"),
    }), now=now)
    assert db_session.query(NrlLiveEvent).filter_by(match_id=m.id).count() == 0

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(minute=15, score_home=4, score_away=0, status="live"),
    }), now=now)
    events = db_session.query(NrlLiveEvent).filter_by(match_id=m.id).all()
    assert len(events) == 1
    assert events[0].team == "home"


def test_poll_match_returns_none_when_provider_has_nothing(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()
    assert poll_match(db_session, m, RecordedFixtureStatsProvider(), now=now) is None


def test_poll_live_matches_never_raises_on_provider_error(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()

    class _Boom:
        def fetch_match_stats(self, *a): return None
        def fetch_team_list(self, *a): return []
        def fetch_live(self, *a): raise RuntimeError("feed down")

    assert poll_live_matches(db_session, _Boom(), now=now) == {"candidates": 1, "polled": 0}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest pipeline/sports/nrl_live_poll_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_live_poll'`

- [ ] **Step 3: Implement the poller**

```python
# pipeline/sports/nrl_live_poll.py
"""NRL live-match polling (Wave 3).

For every nrl match currently inside its live window, calls
StatsProvider.fetch_live, computes the in-play win probability via
ml.sports.nrl.live_model.predict_live_prob (reusing the SAME pre-game
probability already frozen in SportPrediction -- never recomputed here),
and upserts NrlLiveState + appends any new NrlLiveEvent rows.

Matches don't carry an "in_play" status (NRL ingest only ever writes
"scheduled" or "finished" -- see pipeline/sports/nrl_ingest.py), and
nrl-refresh's twice-weekly ingest cron can lag a finished match's status
update by days. So "is this match live right now" is purely time-based:
kickoff_utc - 5min <= now <= kickoff_utc + 110min (80 minutes' play plus a
generous half-time/stoppage buffer), regardless of SportMatch.status.

The recorded-fixture shim's LivePayload doesn't carry scorer identity (a
real provider might), so events are logged as anonymous "score" deltas for
now -- enrich type/player once Wave 2's real fetch_live lands.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction
from ml.sports.nrl.live_model import predict_live_prob
from ml.sports.nrl.live_params import load_nrl_live_params
from pipeline.sports.nrl_stats_shim import LivePayload, StatsProvider

log = logging.getLogger(__name__)

SPORT = "nrl"
MATCH_MINUTES = 80
_WINDOW_AHEAD = timedelta(minutes=5)
_MATCH_DURATION = timedelta(minutes=110)


def matches_in_live_window(db: Session, now: datetime | None = None) -> list[SportMatch]:
    now = now or datetime.now(timezone.utc)
    return (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT,
            SportMatch.kickoff_utc.isnot(None),
            SportMatch.kickoff_utc >= now - _MATCH_DURATION,
            SportMatch.kickoff_utc <= now + _WINDOW_AHEAD,
        )
        .all()
    )


def _pregame_prob(db: Session, match: SportMatch) -> float:
    latest = (
        db.query(SportPrediction)
        .filter_by(match_id=match.id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    return latest.p_home if latest is not None else 0.5


def poll_match(db: Session, match: SportMatch, provider: StatsProvider, now: datetime | None = None) -> dict | None:
    """Poll one match. Returns the upserted state as a dict, or None if the
    provider has nothing yet (never raises -- a feed hiccup is logged)."""
    try:
        payload: LivePayload | None = provider.fetch_live(match.season, match.round, match.match_no)
    except Exception as exc:  # noqa: BLE001
        log.warning("nrl live fetch(%s,%s,%s) failed: %s", match.season, match.round, match.match_no, exc)
        return None
    if payload is None:
        return None

    pregame = _pregame_prob(db, match)
    minutes_remaining = max(MATCH_MINUTES - payload.minute, 0)
    live_prob = predict_live_prob(
        score_diff=float(payload.score_home - payload.score_away),
        minutes_remaining=float(minutes_remaining),
        pregame_prob=pregame,
        params=load_nrl_live_params(),
    )

    state = db.query(NrlLiveState).filter_by(match_id=match.id).one_or_none()
    prev_score = (state.score_home, state.score_away) if state is not None else None
    if state is None:
        state = NrlLiveState(match_id=match.id)
        db.add(state)
    state.status = payload.status
    state.minute = payload.minute
    state.score_home = payload.score_home
    state.score_away = payload.score_away
    state.live_home_prob = live_prob

    if prev_score is not None and (payload.score_home, payload.score_away) != prev_score:
        team = "home" if payload.score_home > prev_score[0] else "away"
        db.add(NrlLiveEvent(
            match_id=match.id, minute=payload.minute, type="score",
            team=team, player=None, prob_after=live_prob,
        ))

    db.commit()
    return {
        "match_id": match.id, "status": payload.status, "minute": payload.minute,
        "score_home": payload.score_home, "score_away": payload.score_away,
        "live_home_prob": live_prob,
    }


def poll_live_matches(db: Session, provider: StatsProvider, now: datetime | None = None) -> dict:
    """Poll every match currently in its live window. Never raises."""
    matches = matches_in_live_window(db, now=now)
    polled = sum(1 for m in matches if poll_match(db, m, provider, now=now) is not None)
    return {"candidates": len(matches), "polled": polled}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest pipeline/sports/nrl_live_poll_test.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/sports/nrl_live_poll.py pipeline/sports/nrl_live_poll_test.py
git commit -m "feat(nrl): live-match poller (time-windowed, reuses frozen pre-game prob)"
```

---

### Task 5: Internal refresh-live endpoint + scheduled workflow

Mirrors the existing football `POST /api/internal/refresh-live` token-guarded pattern (`backend/app/api/internal.py`), and `refresh-live.yml`'s cron-with-internal-loop schedule design, for NRL.

**Files:**
- Modify: `backend/app/api/internal.py`
- Test: `backend/tests/test_nrl_internal_live.py`
- Create: `.github/workflows/nrl-live-refresh.yml`

**Interfaces:**
- Consumes: `poll_live_matches` (Task 4).
- Produces: `POST /api/internal/nrl-refresh-live` → `{"status": "ok", "live": {"candidates": int, "polled": int}}`.

- [ ] **Step 1: Write the failing endpoint tests**

```python
# backend/tests/test_nrl_internal_live.py
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app


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


def test_nrl_refresh_live_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "")
    client = _client()
    try:
        assert client.post("/api/internal/nrl-refresh-live").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_nrl_refresh_live_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        r = client.post("/api/internal/nrl-refresh-live", headers={"X-Recompute-Token": "wrong"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_nrl_refresh_live_ok_with_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client = _client()
    try:
        r = client.post("/api/internal/nrl-refresh-live", headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["live"] == {"candidates": 0, "polled": 0}
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_nrl_internal_live.py -v`
Expected: FAIL — `404` on the two token-gated assertions (route doesn't exist yet)

- [ ] **Step 3: Add the endpoint**

Open `backend/app/api/internal.py`. Insert the following after the existing `refresh_live` endpoint (right before `@router.get("/stats")`):

```python
@router.post("/nrl-refresh-live")
def nrl_refresh_live(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Poll every in-window NRL match's live state via StatsProvider.fetch_live
    and update nrl_live_state/nrl_live_events. Safe to call every minute; a
    scheduled workflow does so during NRL match windows (Thu-Sun AEST, plus
    the occasional Monday game -- see .github/workflows/nrl-live-refresh.yml)."""
    _require_token(x_recompute_token)
    from pipeline.sports.nrl_live_poll import poll_live_matches
    # WAVE 2 RECONCILIATION: swap for the real provider from
    # pipeline.sports.nrl_stats once merged. Until then this safely no-ops
    # (no fixtures configured) -- see pipeline/sports/nrl_stats_shim.py.
    from pipeline.sports.nrl_stats_shim import RecordedFixtureStatsProvider

    summary = poll_live_matches(db, RecordedFixtureStatsProvider())
    cache.clear()
    return {"status": "ok", "live": summary}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest backend/tests/test_nrl_internal_live.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Create the scheduled workflow**

```yaml
# .github/workflows/nrl-live-refresh.yml
# NRL live layer: poll live scores + in-play win probability during NRL
# match windows (Thu-Sun AEST rounds, with an extra Monday slot for the
# occasional Monday game). POSTs to the token-guarded
# /api/internal/nrl-refresh-live, which no-ops instantly for any match
# outside its own live window (see pipeline/sports/nrl_live_poll.py's
# matches_in_live_window) -- so a spurious tick or a slightly-off
# day-of-week filter costs nothing but one HTTP call.
#
# GitHub's minimum schedule interval is 5 minutes; this workflow uses 15 to
# keep Action-minutes modest and loops internally at ~1-minute cadence to
# cover the gap to the next tick, exactly like refresh-live.yml does for
# the football vertical.
#
# Day-of-week filtering uses UTC (cron's native clock), which can be off by
# one calendar day from AEST at the edges (AEST is UTC+10/+11) -- harmless
# here since the endpoint itself is the real gate; this filter only trims
# obviously-idle days (Tue/Wed AEST).
#
# SETUP (one time) -- same two secrets as refresh-live.yml:
#   - API_URL          the deployed API base
#   - RECOMPUTE_TOKEN  same value as the backend's RECOMPUTE_TOKEN env var
name: nrl-live-refresh

on:
  schedule:
    - cron: "*/15 * * * 0,1,4,5,6"   # Sun,Mon,Thu,Fri,Sat (UTC) -- NRL round window
  workflow_dispatch: {}

concurrency:
  group: nrl-live-refresh
  cancel-in-progress: false

jobs:
  poll:
    runs-on: ubuntu-latest
    steps:
      - name: Poll /api/internal/nrl-refresh-live (~1-min cadence across the 15-min window)
        env:
          API_URL: ${{ secrets.API_URL }}
          RECOMPUTE_TOKEN: ${{ secrets.RECOMPUTE_TOKEN }}
        run: |
          set -u
          if [ -z "${API_URL:-}" ] || [ -z "${RECOMPUTE_TOKEN:-}" ]; then
            echo "API_URL / RECOMPUTE_TOKEN secrets not set -- skipping."
            exit 0
          fi
          ok=0
          for i in $(seq 1 14); do
            code=$(curl -sS -o /tmp/nrl_live.json -w "%{http_code}" -m 60 \
              -X POST "${API_URL%/}/api/internal/nrl-refresh-live" \
              -H "X-Recompute-Token: ${RECOMPUTE_TOKEN}" || echo 000)
            echo "[$i/14] HTTP ${code} $(cat /tmp/nrl_live.json 2>/dev/null || true)"
            if [ "${code}" -ge 200 ] && [ "${code}" -lt 300 ]; then ok=1; fi
            if [ "$i" -lt 14 ]; then sleep 55; fi
          done
          if [ "${ok}" != 1 ]; then
            echo "All NRL live pings failed this run (transient API error or misconfig)."
            exit 1
          fi
```

- [ ] **Step 6: Verify the YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/nrl-live-refresh.yml'))"`
Expected: no output (success)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/internal.py backend/tests/test_nrl_internal_live.py .github/workflows/nrl-live-refresh.yml
git commit -m "feat(nrl): token-guarded live-refresh endpoint + 15-min scheduled poller"
```

---

### Task 6: Live read endpoint — `GET /api/nrl/matches/{id}/live`

Reads whatever Task 4's poller has persisted; never calls a `StatsProvider` itself (must stay fast under board traffic). Handles `pre`/`live`/`final` gracefully, including matches that have never been polled.

**Files:**
- Create: `backend/app/api/nrl_live.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_nrl_live_api.py`

**Interfaces:**
- Consumes: `NrlLiveState`, `NrlLiveEvent` (Task 1), `SportMatch`, `SportPrediction` (existing).
- Produces: `GET /api/nrl/matches/{id}/live` → `{status, minute, score_home, score_away, live_home_prob, events: [{minute, type, team, player, prob_after}]}` — exact spec contract, no extra top-level keys.

- [ ] **Step 1: Write the failing endpoint tests**

```python
# backend/tests/test_nrl_live_api.py
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction


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
    return TestClient(app), TestingSession


def test_live_404_for_unknown_match():
    client, _ = _client()
    try:
        assert client.get("/api/nrl/matches/999/live").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_live_pre_state_before_kickoff_with_no_poll_yet():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        now = datetime.now(timezone.utc)
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="scheduled",
                        kickoff_utc=now + timedelta(days=2))
        db.add(m); db.flush()
        db.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                p_home=0.62, p_draw=0.01, p_away=0.37))
        db.commit()

        body = client.get(f"/api/nrl/matches/{m.id}/live").json()
        assert body["status"] == "pre"
        assert body["score_home"] is None
        assert body["live_home_prob"] == 0.62
        assert body["events"] == []
        assert "odds" not in body and "value" not in body
    finally:
        app.dependency_overrides.clear()


def test_live_state_reads_persisted_poll_and_events():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        now = datetime.now(timezone.utc)
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="scheduled",
                        kickoff_utc=now - timedelta(minutes=20))
        db.add(m); db.flush()
        db.add(NrlLiveState(match_id=m.id, status="live", minute=20,
                             score_home=6, score_away=0, live_home_prob=0.81))
        db.add(NrlLiveEvent(match_id=m.id, minute=12, type="score", team="home",
                             player=None, prob_after=0.75))
        db.commit()

        body = client.get(f"/api/nrl/matches/{m.id}/live").json()
        assert body["status"] == "live"
        assert body["score_home"] == 6
        assert len(body["events"]) == 1
        assert body["events"][0]["team"] == "home"
    finally:
        app.dependency_overrides.clear()


def test_live_final_state_from_finished_match_without_ever_being_polled():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="finished",
                        score_home=24, score_away=10)
        db.add(m); db.commit()

        body = client.get(f"/api/nrl/matches/{m.id}/live").json()
        assert body["status"] == "final"
        assert body["score_home"] == 24 and body["score_away"] == 10
        assert body["live_home_prob"] == 1.0
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_nrl_live_api.py -v`
Expected: FAIL — 404s where 200s are expected (router doesn't exist yet)

- [ ] **Step 3: Implement the endpoint**

```python
# backend/app/api/nrl_live.py
"""Live layer read endpoint (Wave 3): GET /api/nrl/matches/{id}/live.

Reads whatever pipeline.sports.nrl_live_poll has persisted (NrlLiveState /
NrlLiveEvent); never calls a StatsProvider itself -- all provider calls
happen in the poller so this endpoint stays fast under board traffic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction

router = APIRouter(prefix="/api/nrl", tags=["nrl-live"])

MATCH_MINUTES = 80
_WINDOW_AHEAD = timedelta(minutes=5)
_MATCH_DURATION = timedelta(minutes=110)


def _pregame_prob(db: Session, match_id: int) -> float:
    latest = (
        db.query(SportPrediction)
        .filter_by(match_id=match_id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    return latest.p_home if latest is not None else 0.5


@router.get("/matches/{match_id}/live")
def nrl_match_live(match_id: int, db: Session = Depends(get_db)):
    match = db.query(SportMatch).filter_by(id=match_id, sport="nrl").one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail={
            "code": "no_nrl_match", "message": "No NRL match with that id",
        })

    state = db.query(NrlLiveState).filter_by(match_id=match_id).one_or_none()
    now = datetime.now(timezone.utc)
    in_window = (
        match.kickoff_utc is not None
        and match.kickoff_utc - _WINDOW_AHEAD <= now <= match.kickoff_utc + _MATCH_DURATION
    )

    if state is not None:
        status, minute = state.status, state.minute
        score_home, score_away = state.score_home, state.score_away
        live_home_prob = state.live_home_prob
    elif match.status == "finished":
        status, minute = "final", MATCH_MINUTES
        score_home, score_away = match.score_home, match.score_away
        live_home_prob = 1.0 if (score_home or 0) > (score_away or 0) else 0.0
    elif in_window:
        status, minute = "live", 0
        score_home, score_away = 0, 0
        live_home_prob = _pregame_prob(db, match_id)
    else:
        status, minute = "pre", None
        score_home, score_away = None, None
        live_home_prob = _pregame_prob(db, match_id)

    events = (
        db.query(NrlLiveEvent)
        .filter_by(match_id=match_id)
        .order_by(NrlLiveEvent.minute.asc(), NrlLiveEvent.id.asc())
        .all()
    )

    return {
        "status": status,
        "minute": minute,
        "score_home": score_home,
        "score_away": score_away,
        "live_home_prob": live_home_prob,
        "events": [
            {"minute": e.minute, "type": e.type, "team": e.team,
             "player": e.player, "prob_after": e.prob_after}
            for e in events
        ],
    }
```

Register the router in `backend/app/main.py`. Change:

```python
from app.api import (
    auth, brackets, groups, internal, knockout, leaderboard, markets, market_record, match_picks,
    matches, model_record, movers, predictions, prob_history, sports, teams,
)
```

to:

```python
from app.api import (
    auth, brackets, groups, internal, knockout, leaderboard, markets, market_record, match_picks,
    matches, model_record, movers, nrl_live, predictions, prob_history, sports, teams,
)
```

and add, next to the existing `app.include_router(sports.router)` line:

```python
app.include_router(nrl_live.router)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest backend/tests/test_nrl_live_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/nrl_live.py backend/app/main.py backend/tests/test_nrl_live_api.py
git commit -m "feat(nrl): GET /api/nrl/matches/{id}/live with graceful pre/live/final states"
```

---

### Task 7: Try-scorer projection model (depends on Wave 2's `nrl_try_events`)

Empirical anytime-try frequency (last-10 games weighted 2x) blended with a position prior and an opponent position-concession rate. **Probabilities only — no odds, no value badges.** Uses the `NrlTryEvent` reconciliation shim (see policy note above the task list) since Wave 2 may not have merged.

**Files:**
- Create: `backend/app/models/nrl_wave2_shim.py`
- Create: `pipeline/sports/nrl_scorer_model.py`
- Test: `pipeline/sports/nrl_scorer_model_test.py`

**Interfaces:**
- Consumes: `NrlTeamList` (Task 1), `SportMatch` (existing).
- Produces:
  - `backend/app/models/nrl_wave2_shim.py`: `NrlTryEvent(id, match_id, team, player, minute, score_home, score_away)`.
  - `pipeline/sports/nrl_scorer_model.py`: `player_empirical_rate(last10_tries, tries_season, games_season) -> float`, `position_prior(db, position) -> float`, `opponent_concession_rate(db, opponent_team, position) -> float`, `project_p_anytime(empirical, position_prior_rate, opponent_rate) -> float`, `project_scorer(db, opponent_team, position, last10_tries, tries_season, games_season) -> float` (used by Task 8).

- [ ] **Step 1: Create the NrlTryEvent shim (no test — a plain table-shape duplicate)**

```python
# backend/app/models/nrl_wave2_shim.py
"""WAVE 2 RECONCILIATION SHIM — see pipeline/sports/nrl_stats_shim.py's
module docstring for the general policy. This file duplicates ONLY the
nrl_try_events table shape Wave 2 owns (backend/app/models/__init__.py will
gain the real NrlTryEvent class once feat/nrl-match-intel-w2 merges), so
Wave 3's try-scorer model and tests can run against the spec's frozen
schema before that merge lands.

MERGE INSTRUCTIONS for the integrator: once Wave 2's real NrlTryEvent
exists in app.models, replace every
`from app.models.nrl_wave2_shim import NrlTryEvent` in this branch
(pipeline/sports/nrl_scorer_model.py, backend/app/api/nrl_players.py, and
their tests) with `from app.models import NrlTryEvent`, confirm the column
set matches field-for-field, then delete this file. Deliberately NOT
imported from backend/app/models/__init__.py or added to its __all__, and
NOT paired with an Alembic migration -- it must never be registered twice
on the same Base if Wave 2's version also lands, and the real table is
Wave 2's migration to own.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NrlTryEvent(Base):
    __tablename__ = "nrl_try_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    player: Mapped[str] = mapped_column(String(120))
    minute: Mapped[int] = mapped_column(Integer)
    score_home: Mapped[int] = mapped_column(Integer)
    score_away: Mapped[int] = mapped_column(Integer)
```

- [ ] **Step 2: Write the failing scorer-model tests**

```python
# pipeline/sports/nrl_scorer_model_test.py
import math

from app.models import NrlTeamList, SportMatch
from app.models.nrl_wave2_shim import NrlTryEvent
from pipeline.sports.nrl_scorer_model import (
    opponent_concession_rate, player_empirical_rate, position_prior,
    project_p_anytime, project_scorer,
)


def test_player_empirical_rate_uses_last10_only_when_no_older_games():
    rate = player_empirical_rate([1, 0, 1, 0, 0], tries_season=2, games_season=5)
    assert rate == 2 / 5


def test_player_empirical_rate_weights_recent_games_double():
    last10 = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]  # 5 scored of 10
    rate = player_empirical_rate(last10, tries_season=10, games_season=20)
    older_rate = 1 - math.exp(-5 / 10)
    expected = (2 * 5 + 10 * older_rate) / (2 * 10 + 10)
    assert abs(rate - expected) < 1e-9


def test_player_empirical_rate_handles_zero_games():
    assert player_empirical_rate([], tries_season=0, games_season=0) == 0.0


def _seed_try_history(db):
    m1 = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="finished",
                     score_home=20, score_away=10)
    m2 = SportMatch(sport="nrl", season=2026, round=2, match_no=1, status="finished",
                     score_home=18, score_away=6)
    db.add_all([m1, m2]); db.flush()
    db.add_all([
        NrlTeamList(match_id=m1.id, team="Broncos", jersey=2, player="A. Wing", position="WG"),
        NrlTeamList(match_id=m1.id, team="Storm", jersey=13, player="B. Lock", position="LK"),
        NrlTeamList(match_id=m2.id, team="Broncos", jersey=2, player="A. Wing", position="WG"),
        NrlTeamList(match_id=m2.id, team="Roosters", jersey=9, player="C. Hooker", position="HK"),
    ])
    db.add_all([
        NrlTryEvent(match_id=m1.id, team="Broncos", player="A. Wing", minute=10, score_home=4, score_away=0),
        NrlTryEvent(match_id=m2.id, team="Broncos", player="A. Wing", minute=20, score_home=4, score_away=0),
    ])
    db.commit()


def test_position_prior_falls_back_when_no_tagged_history(db_session):
    assert position_prior(db_session, "FB") == 0.55


def test_position_prior_uses_tagged_history_when_present(db_session):
    _seed_try_history(db_session)
    rate = position_prior(db_session, "WG")
    assert 0.0 < rate <= 1.0


def test_opponent_concession_rate_attributes_tries_to_the_other_team(db_session):
    _seed_try_history(db_session)
    # Storm faced Broncos in m1 and conceded a WG try; Storm doesn't appear
    # in m2, so its rate reflects only m1.
    assert opponent_concession_rate(db_session, "Storm", "WG") == 1.0


def test_opponent_concession_rate_falls_back_to_position_prior_when_unseen(db_session):
    _seed_try_history(db_session)
    assert opponent_concession_rate(db_session, "Sea Eagles", "FB") == position_prior(db_session, "FB")


def test_project_p_anytime_is_clamped_to_unit_interval():
    assert project_p_anytime(1.5, 1.5, 1.5) == 1.0
    assert project_p_anytime(-1.0, -1.0, -1.0) == 0.0


def test_project_scorer_blends_all_three_signals(db_session):
    _seed_try_history(db_session)
    p = project_scorer(db_session, opponent_team="Storm", position="WG",
                        last10_tries=[1, 0, 1], tries_season=2, games_season=3)
    assert 0.0 <= p <= 1.0
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest pipeline/sports/nrl_scorer_model_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_scorer_model'`

- [ ] **Step 4: Implement the scorer model**

```python
# pipeline/sports/nrl_scorer_model.py
"""Try-scorer projection model (Wave 3).

Empirical anytime-try frequency, blended with a position prior and an
opponent position-concession rate. Outputs PROBABILITIES ONLY -- no odds,
no value badges (program-wide constraint).

WAVE 2 DEPENDENCY: reads history from the shimmed NrlTryEvent
(backend/app/models/nrl_wave2_shim.py) until Wave 2 merges its real
nrl_try_events table -- see that module's docstring for the swap-over.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.models import NrlTeamList
from app.models.nrl_wave2_shim import NrlTryEvent

# Fallback anytime-try-per-game priors by position, used until enough
# nrl_team_lists-tagged try history accumulates to compute a real one (team
# lists only start being ingested this wave -- older nrl_try_events rows
# have no position tag yet). Ballpark NRL figures: fullback/wing/centre
# score often, forwards rarely.
FALLBACK_POSITION_PRIOR = {
    "FB": 0.55, "WG": 0.60, "CE": 0.45, "FE": 0.25, "HB": 0.20,
    "HK": 0.12, "PR": 0.10, "2R": 0.15, "LK": 0.18,
}
DEFAULT_PRIOR = 0.20  # unrecognised/unknown position code

W_EMPIRICAL = 0.5
W_POSITION_PRIOR = 0.3
W_OPPONENT_CONCESSION = 0.2


def player_empirical_rate(last10_tries: list[int], tries_season: int, games_season: int) -> float:
    """Fraction of games with >=1 try, with the last 10 games weighted 2x
    relative to earlier games in the season.

    Games before the last-10 window don't have individual try counts in the
    scorers payload (only last10 does) -- their "scored at least once" rate
    is approximated from the season aggregate via a Poisson-occupancy
    estimate (1 - e^-rate), the standard way to turn a per-game try RATE
    into a "scored at least once" PROBABILITY when only the total is known.
    """
    recent_n = len(last10_tries)
    recent_scored = sum(1 for t in last10_tries if t >= 1)
    older_games = max(games_season - recent_n, 0)

    if older_games <= 0:
        return recent_scored / recent_n if recent_n else 0.0

    recent_tries = sum(last10_tries)
    older_tries = max(tries_season - recent_tries, 0)
    older_scored_rate = 1 - math.exp(-older_tries / older_games)

    weighted_scored = 2 * recent_scored + older_games * older_scored_rate
    weighted_games = 2 * recent_n + older_games
    return weighted_scored / weighted_games if weighted_games else 0.0


def position_prior(db: Session, position: str) -> float:
    """League-wide anytime-try signal for `position`: share of
    nrl_team_lists rows at that position that are matched by a
    (match_id, team, player)-joined try event. Falls back to
    FALLBACK_POSITION_PRIOR when no team-list row at that position has been
    tagged yet (a simple relative-frequency signal, not a per-game rate --
    precise enough to blend, not precise enough to stand alone)."""
    total_tagged = db.query(NrlTeamList.id).filter(NrlTeamList.position == position).count()
    if total_tagged == 0:
        return FALLBACK_POSITION_PRIOR.get(position, DEFAULT_PRIOR)

    tries_at_position = (
        db.query(NrlTryEvent.id)
        .join(
            NrlTeamList,
            (NrlTeamList.match_id == NrlTryEvent.match_id)
            & (NrlTeamList.team == NrlTryEvent.team)
            & (NrlTeamList.player == NrlTryEvent.player),
        )
        .filter(NrlTeamList.position == position)
        .count()
    )
    if tries_at_position == 0:
        return FALLBACK_POSITION_PRIOR.get(position, DEFAULT_PRIOR)
    return min(tries_at_position / total_tagged, 1.0)


def _match_team_pairs(db: Session) -> dict[int, list[str]]:
    """match_id -> distinct team names appearing in that match's team list."""
    pairs: dict[int, list[str]] = {}
    for match_id, team in db.query(NrlTeamList.match_id, NrlTeamList.team).distinct():
        pairs.setdefault(match_id, [])
        if team not in pairs[match_id]:
            pairs[match_id].append(team)
    return pairs


def opponent_concession_rate(db: Session, opponent_team: str, position: str) -> float:
    """Rate at which `opponent_team` has conceded a try to `position`, among
    team-list-tagged matches where `opponent_team` faced the scoring team.
    Falls back to the league-wide position_prior when `opponent_team` has no
    tagged concession history yet (team-list tagging only starts this wave)."""
    pairs = _match_team_pairs(db)
    tries = (
        db.query(NrlTryEvent.match_id, NrlTryEvent.team, NrlTeamList.position)
        .join(
            NrlTeamList,
            (NrlTeamList.match_id == NrlTryEvent.match_id)
            & (NrlTeamList.team == NrlTryEvent.team)
            & (NrlTeamList.player == NrlTryEvent.player),
        )
        .all()
    )
    faced = conceded = 0
    for match_id, scoring_team, pos in tries:
        other = next((t for t in pairs.get(match_id, []) if t != scoring_team), None)
        if other != opponent_team:
            continue
        faced += 1
        if pos == position:
            conceded += 1
    if faced == 0:
        return position_prior(db, position)
    return conceded / faced


def project_p_anytime(
    empirical: float, position_prior_rate: float, opponent_rate: float,
    w_empirical: float = W_EMPIRICAL, w_position: float = W_POSITION_PRIOR,
    w_opponent: float = W_OPPONENT_CONCESSION,
) -> float:
    """Blend the three signals into a single probability, clamped to [0,1]."""
    p = w_empirical * empirical + w_position * position_prior_rate + w_opponent * opponent_rate
    return max(0.0, min(1.0, p))


def project_scorer(
    db: Session, opponent_team: str, position: str,
    last10_tries: list[int], tries_season: int, games_season: int,
) -> float:
    empirical = player_empirical_rate(last10_tries, tries_season, games_season)
    prior = position_prior(db, position)
    concession = opponent_concession_rate(db, opponent_team, position)
    return project_p_anytime(empirical, prior, concession)
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest pipeline/sports/nrl_scorer_model_test.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/nrl_wave2_shim.py pipeline/sports/nrl_scorer_model.py pipeline/sports/nrl_scorer_model_test.py
git commit -m "feat(nrl): try-scorer projection model (empirical + position + opponent blend)"
```

---

### Task 8: Scorers endpoint — `GET /api/nrl/matches/{id}/scorers`

**Files:**
- Create: `backend/app/api/nrl_players.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_nrl_scorers_api.py`

**Interfaces:**
- Consumes: `NrlTeamList` (Task 1), `NrlTryEvent` (Task 7 shim), `project_scorer` (Task 7), `SportMatch`, `SportTeam` (existing).
- Produces: `GET /api/nrl/matches/{id}/scorers` → bare JSON array of `{player, jersey, position, unit, tries_season, games_season, last10: [{round, tries}], p_anytime, team}` — every spec'd field present verbatim, plus an additive `team: "home"|"away"` (the spec's array has no per-entry team discriminator, but jersey numbers repeat across both teams, so the frontend can't otherwise split the two team columns — see module docstring).

- [ ] **Step 1: Write the failing endpoint tests**

```python
# backend/tests/test_nrl_scorers_api.py
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import NrlTeamList, SportMatch, SportTeam
from app.models.nrl_wave2_shim import NrlTryEvent


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
    return TestClient(app), TestingSession


def test_scorers_404_for_unknown_match():
    client, _ = _client()
    try:
        assert client.get("/api/nrl/matches/999/scorers").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_scorers_returns_bare_array_with_team_field_no_odds():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        home = SportTeam(sport="nrl", name="Broncos")
        away = SportTeam(sport="nrl", name="Storm")
        db.add_all([home, away]); db.flush()
        m = SportMatch(sport="nrl", season=2026, round=3, match_no=1, status="scheduled",
                        home_team_id=home.id, away_team_id=away.id)
        db.add(m); db.flush()
        db.add(NrlTeamList(match_id=m.id, team="Broncos", jersey=2, player="A. Wing", position="WG"))
        db.add(NrlTryEvent(match_id=m.id, team="Broncos", player="A. Wing",
                            minute=10, score_home=4, score_away=0))
        db.commit()

        r = client.get(f"/api/nrl/matches/{m.id}/scorers")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert body[0]["player"] == "A. Wing"
        assert body[0]["team"] == "home"
        assert 0.0 <= body[0]["p_anytime"] <= 1.0
        assert "odds" not in body[0] and "value" not in body[0]
    finally:
        app.dependency_overrides.clear()


def test_scorers_empty_list_when_no_team_list_yet():
    client, TestingSession = _client()
    try:
        db = TestingSession()
        m = SportMatch(sport="nrl", season=2026, round=3, match_no=2, status="scheduled")
        db.add(m); db.commit()
        r = client.get(f"/api/nrl/matches/{m.id}/scorers")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_nrl_scorers_api.py -v`
Expected: FAIL — 404 where 200 is expected (router doesn't exist yet)

- [ ] **Step 3: Implement the endpoint**

```python
# backend/app/api/nrl_players.py
"""Try-scorer projections (Wave 3): GET /api/nrl/matches/{id}/scorers.

Combines this match's nrl_team_lists (real, Wave-3-owned) with try-scorer
history (nrl_try_events, currently the Wave 2 reconciliation shim) via
pipeline.sports.nrl_scorer_model. Probabilities only -- no odds, no value
badges (program-wide constraint).

Returns a BARE ARRAY (the spec's frozen contract), not an object -- so
there is no room for a top-level disclaimer key here (the page's footer
disclaimer already covers every NRL page, per Global Constraints). Each
entry adds one field beyond the spec's literal list: "team" ("home" |
"away"), purely additive and necessary since jersey numbers repeat across
both teams and the spec's array has no other way to split them.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlTeamList, SportMatch, SportTeam
from app.models.nrl_wave2_shim import NrlTryEvent
from pipeline.sports.nrl_scorer_model import project_scorer

router = APIRouter(prefix="/api/nrl", tags=["nrl-players"])

LAST_N_ROUNDS = 10
UNIT_BY_POSITION = {
    "FB": "outside backs", "WG": "outside backs", "CE": "outside backs",
    "FE": "halves", "HB": "halves", "HK": "hooker",
}
DEFAULT_UNIT = "forwards"


def _unit_for(position: str) -> str:
    return UNIT_BY_POSITION.get(position, DEFAULT_UNIT)


def _last10_for(db: Session, team: str, player: str, before_round: int | None) -> list[dict]:
    q = (
        db.query(SportMatch.round, NrlTryEvent.id)
        .join(NrlTryEvent, NrlTryEvent.match_id == SportMatch.id)
        .filter(NrlTryEvent.team == team, NrlTryEvent.player == player)
    )
    if before_round is not None:
        q = q.filter(SportMatch.round < before_round)
    rows = q.order_by(SportMatch.round.desc()).limit(LAST_N_ROUNDS).all()
    by_round: dict[int, int] = defaultdict(int)
    for round_no, _id in rows:
        by_round[round_no] += 1
    return [{"round": r, "tries": n} for r, n in sorted(by_round.items())]


@router.get("/matches/{match_id}/scorers")
def nrl_match_scorers(match_id: int, db: Session = Depends(get_db)) -> list[dict]:
    match = db.query(SportMatch).filter_by(id=match_id, sport="nrl").one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail={
            "code": "no_nrl_match", "message": "No NRL match with that id",
        })

    home_name = db.query(SportTeam.name).filter_by(id=match.home_team_id).scalar() \
        if match.home_team_id is not None else None
    away_name = db.query(SportTeam.name).filter_by(id=match.away_team_id).scalar() \
        if match.away_team_id is not None else None

    scorers: list[dict] = []
    for entry in db.query(NrlTeamList).filter_by(match_id=match_id).all():
        if entry.team == away_name:
            side, opponent = "away", home_name
        else:
            side, opponent = "home", away_name  # best-effort default if names don't line up yet

        last10 = _last10_for(db, entry.team, entry.player, before_round=match.round)
        tries_last10 = [row["tries"] for row in last10]
        games_season = (
            db.query(SportMatch.id)
            .join(NrlTeamList, NrlTeamList.match_id == SportMatch.id)
            .filter(NrlTeamList.team == entry.team, NrlTeamList.player == entry.player,
                    SportMatch.season == match.season)
            .count()
        )
        tries_season = (
            db.query(NrlTryEvent.id)
            .join(SportMatch, SportMatch.id == NrlTryEvent.match_id)
            .filter(NrlTryEvent.team == entry.team, NrlTryEvent.player == entry.player,
                    SportMatch.season == match.season)
            .count()
        )
        p_anytime = (
            project_scorer(db, opponent_team=opponent, position=entry.position,
                            last10_tries=tries_last10, tries_season=tries_season,
                            games_season=games_season)
            if opponent else 0.0
        )
        scorers.append({
            "player": entry.player, "jersey": entry.jersey, "position": entry.position,
            "unit": _unit_for(entry.position), "tries_season": tries_season,
            "games_season": games_season, "last10": last10, "p_anytime": p_anytime,
            "team": side,
        })
    return scorers
```

Register in `backend/app/main.py`. Change the import line from Task 6's version to:

```python
from app.api import (
    auth, brackets, groups, internal, knockout, leaderboard, markets, market_record, match_picks,
    matches, model_record, movers, nrl_live, nrl_players, predictions, prob_history, sports, teams,
)
```

and add, next to `app.include_router(nrl_live.router)`:

```python
app.include_router(nrl_players.router)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest backend/tests/test_nrl_scorers_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/nrl_players.py backend/app/main.py backend/tests/test_nrl_scorers_api.py
git commit -m "feat(nrl): GET /api/nrl/matches/{id}/scorers (probabilities only)"
```

---

### Task 9: UI — Live section (client island, 60s polling, pinned when in progress)

**Before starting this task:** merge latest `origin/main` into this branch (`git fetch origin && git merge origin/main`) — Waves 1 and 2 should have merged by now, and Wave 1 owns `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (exporting `IntelSection[]`) plus the page shell that renders it, which do not exist as of Task 1–8. If the merged `IntelSection` type or the page's rendering container differs from the `{id, label, render}` shape and the "sections rendered as stacked cards" layout assumed below, adapt this task's edits to match reality — do not edit any Wave 1 component file, only append.

**Files:**
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/sections/LiveSection.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/sections/LiveSectionClient.tsx`
- Modify: `frontend/lib/api.ts` (append 2 functions)
- Modify: `frontend/lib/types.ts` (append 2 types)
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (append 1 import + 1 array entry — file created by Wave 1)
- Test: `frontend/app/nrl/match/[season]/[round]/[no]/sections/LiveSection.test.tsx`

**Interfaces:**
- Consumes: `useFetch<T>(fetcher, deps, pollMs?, initial?)` from `frontend/lib/useFetch.ts` (existing), `pct()` from `frontend/lib/format.ts` (existing), `getServer`/`getJson`/`CLIENT_BASE` pattern from `frontend/lib/api.ts` (existing).
- Produces: `getNrlLiveServer(matchId) -> Promise<NrlLive | null>`, `getNrlLiveClient(matchId) -> Promise<NrlLive>`, `LiveSection({matchId, home, away}) -> Promise<JSX.Element | null>` (the `sections.ts` entry point).

- [ ] **Step 1: Add types**

Append to `frontend/lib/types.ts`:

```ts
export type NrlLiveEvent = {
  minute: number;
  type: string;
  team: "home" | "away";
  player: string | null;
  prob_after: number;
};

export type NrlLive = {
  status: "pre" | "live" | "final";
  minute: number | null;
  score_home: number | null;
  score_away: number | null;
  live_home_prob: number;
  events: NrlLiveEvent[];
};
```

- [ ] **Step 2: Add fetchers**

Append to `frontend/lib/api.ts`, near the other `getNrl*` functions:

```ts
export async function getNrlLiveServer(matchId: number): Promise<NrlLive | null> {
  return getServer<NrlLive>(`/api/nrl/matches/${matchId}/live`, 15);
}

export async function getNrlLiveClient(matchId: number): Promise<NrlLive> {
  return getJson<NrlLive>(`/api/nrl/matches/${matchId}/live`);
}
```

Add `NrlLive` to the existing `import type { ... } from "@/lib/types"` line at the top of the file.

- [ ] **Step 3: Write the failing component test**

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/sections/LiveSection.test.tsx
import { render, screen } from "@testing-library/react";
import { LiveSection } from "./LiveSection";
import { getNrlLiveClient, getNrlLiveServer } from "@/lib/api";
import type { NrlLive } from "@/lib/types";

jest.mock("@/lib/api");
const mockLiveServer = getNrlLiveServer as jest.MockedFunction<typeof getNrlLiveServer>;
const mockLiveClient = getNrlLiveClient as jest.MockedFunction<typeof getNrlLiveClient>;

afterEach(() => jest.resetAllMocks());

it("renders nothing before kickoff", async () => {
  const pre: NrlLive = { status: "pre", minute: null, score_home: null, score_away: null,
                          live_home_prob: 0.6, events: [] };
  mockLiveServer.mockResolvedValue(pre);
  mockLiveClient.mockResolvedValue(pre);
  const result = await LiveSection({ matchId: 1, home: "Broncos", away: "Storm" });
  expect(result).toBeNull();
});

it("renders the live banner and score while in progress", async () => {
  const live: NrlLive = {
    status: "live", minute: 42, score_home: 12, score_away: 6, live_home_prob: 0.71,
    events: [{ minute: 10, type: "score", team: "home", player: null, prob_after: 0.55 }],
  };
  mockLiveServer.mockResolvedValue(live);
  mockLiveClient.mockResolvedValue(live);
  render(await LiveSection({ matchId: 1, home: "Broncos", away: "Storm" }));
  expect(screen.getByText("71%")).toBeInTheDocument();
  expect(screen.getByText(/12–6/)).toBeInTheDocument();
});

it("renders a Final card with no live badge once the match ends", async () => {
  const final: NrlLive = { status: "final", minute: 80, score_home: 24, score_away: 10,
                            live_home_prob: 1.0, events: [] };
  mockLiveServer.mockResolvedValue(final);
  mockLiveClient.mockResolvedValue(final);
  render(await LiveSection({ matchId: 1, home: "Broncos", away: "Storm" }));
  expect(screen.getByText("Final")).toBeInTheDocument();
  expect(screen.queryByText(/Live ·/)).not.toBeInTheDocument();
});

it("never renders odds or value badges", async () => {
  const live: NrlLive = { status: "live", minute: 5, score_home: 0, score_away: 0,
                           live_home_prob: 0.5, events: [] };
  mockLiveServer.mockResolvedValue(live);
  mockLiveClient.mockResolvedValue(live);
  render(await LiveSection({ matchId: 1, home: "Broncos", away: "Storm" }));
  expect(screen.queryByText(/odds/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/value/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd frontend && npx jest "app/nrl/match/[season]/[round]/[no]/sections/LiveSection.test.tsx"`
Expected: FAIL — cannot find module `./LiveSection`

- [ ] **Step 5: Implement the client component**

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/sections/LiveSectionClient.tsx
"use client";

import { getNrlLiveClient } from "@/lib/api";
import { pct } from "@/lib/format";
import { useFetch } from "@/lib/useFetch";
import type { NrlLive } from "@/lib/types";

const POLL_MS = 60_000;

/** Client island: polls /live every 60s. Pins a compact sticky banner to
 *  the top of the viewport while status === "live" -- self-contained
 *  (fixed positioning, no reliance on sections.ts array order), so "live
 *  pinned first" holds regardless of where Wave 1's page places this
 *  section in the DOM. */
export function LiveSectionClient({
  matchId, home, away, initial,
}: { matchId: number; home: string; away: string; initial: NrlLive }) {
  const finishedAtRender = initial.status === "final";
  const state = useFetch<NrlLive>(
    () => getNrlLiveClient(matchId),
    [matchId],
    finishedAtRender ? undefined : POLL_MS,
    initial,
  );
  const live = state.status === "success" ? state.data : initial;
  const isLive = live.status === "live";

  return (
    <>
      {isLive && (
        <div
          className="sticky top-14 z-40 mb-4 flex items-center justify-between gap-3 rounded-xl border border-border bg-surface/95 px-4 py-2 text-sm backdrop-blur"
          aria-live="polite"
        >
          <span className="flex items-center gap-1.5 font-semibold text-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
            LIVE {live.minute}&apos;
          </span>
          <span className="tabular-nums text-foreground">
            {home} {live.score_home}–{live.score_away} {away}
          </span>
          <span className="font-bold tabular-nums text-lime-deep">{pct(live.live_home_prob)}</span>
        </div>
      )}
      <section className="glass rounded-2xl p-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-bold text-foreground">{isLive ? "Live" : "Final"}</h2>
          {isLive && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-loss">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
              Live &middot; {live.minute}&apos;
            </span>
          )}
        </div>
        <div className="flex items-center justify-center gap-6">
          <TeamScore name={home} score={live.score_home} />
          <span className="font-display text-2xl font-extrabold tabular-nums text-muted">&ndash;</span>
          <TeamScore name={away} score={live.score_away} />
        </div>
        <p className="mt-4 text-center text-sm font-semibold text-lime-deep">
          {home} win chance &middot; {pct(live.live_home_prob)}
        </p>
        {live.events.length > 0 && (
          <ul className="mt-5 space-y-1.5 border-t border-border pt-4 text-sm">
            {live.events.map((e, i) => (
              <li key={i} className="flex items-center justify-between gap-2">
                <span className="text-muted">
                  {e.minute}&apos; {e.team === "home" ? home : away}
                  {e.player ? ` — ${e.player}` : ""}
                </span>
                <span className="tabular-nums text-foreground">{pct(e.prob_after)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function TeamScore({ name, score }: { name: string; score: number | null }) {
  return (
    <div className="flex flex-col items-center gap-1 text-center">
      <span className="font-display text-sm font-bold">{name}</span>
      <span className="font-display text-2xl font-extrabold tabular-nums">{score ?? "–"}</span>
    </div>
  );
}
```

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/sections/LiveSection.tsx
import { getNrlLiveServer } from "@/lib/api";
import { LiveSectionClient } from "./LiveSectionClient";

/** sections.ts entry point (server component): SSR's the initial live
 *  state (short 15s ISR revalidate) and hands off to the client island for
 *  60s polling. Renders nothing before kickoff -- graceful "pre" state. */
export async function LiveSection({
  matchId, home, away,
}: { matchId: number; home: string; away: string }) {
  const initial = await getNrlLiveServer(matchId).catch(() => null);
  if (!initial || initial.status === "pre") return null;
  return <LiveSectionClient matchId={matchId} home={home} away={away} initial={initial} />;
}
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd frontend && npx jest "app/nrl/match/[season]/[round]/[no]/sections/LiveSection.test.tsx"`
Expected: PASS (4 tests). If a worker SIGSEGV occurs, rerun once (known flake per Global Constraints).

- [ ] **Step 7: Wire into `sections.ts`**

Open `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (Wave 1's file). Add an import near the top:

```ts
import { LiveSection } from "./sections/LiveSection";
```

and append to the exported `IntelSection[]` array:

```ts
{ id: "live", label: "Live", render: LiveSection },
```

Adapt the exact prop names passed through to match whatever `IntelSectionProps` Wave 1 actually defined (this task assumes `matchId`, `home`, `away` are available to every section — if Wave 1's props differ, wrap `LiveSection` in a small adapter here rather than editing Wave 1's file).

- [ ] **Step 8: Full frontend build check**

Run: `cd frontend && npm run build`
Expected: build succeeds (all `fetch` calls fall back via `.catch(() => null)`, so this must pass with no backend running).

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/app/nrl/match/\[id\]/sections/LiveSection.tsx frontend/app/nrl/match/\[id\]/sections/LiveSectionClient.tsx frontend/app/nrl/match/\[id\]/sections/LiveSection.test.tsx frontend/app/nrl/match/\[id\]/sections.ts
git reset frontend/node_modules
git commit -m "feat(nrl): live section UI (60s polling, pinned banner, graceful pre/final)"
```

---

### Task 10: UI — Scorers section

**Before starting this task:** same merge-`origin/main` precondition as Task 9.

**Files:**
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/sections/ScorersSection.tsx`
- Modify: `frontend/lib/api.ts` (append 1 function)
- Modify: `frontend/lib/types.ts` (append 1 type)
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (append 1 import + 1 array entry)
- Test: `frontend/app/nrl/match/[season]/[round]/[no]/sections/ScorersSection.test.tsx`

**Interfaces:**
- Consumes: `pct()` from `frontend/lib/format.ts` (existing), `getServer` pattern from `frontend/lib/api.ts` (existing).
- Produces: `getNrlScorersServer(matchId) -> Promise<NrlScorer[] | null>`, `ScorersSection({matchId}) -> Promise<JSX.Element | null>` (the `sections.ts` entry point).

- [ ] **Step 1: Add the type**

Append to `frontend/lib/types.ts`:

```ts
export type NrlScorer = {
  player: string;
  jersey: number;
  position: string;
  unit: string;
  tries_season: number;
  games_season: number;
  last10: { round: number; tries: number }[];
  p_anytime: number;
  team: "home" | "away";
};
```

- [ ] **Step 2: Add the fetcher**

Append to `frontend/lib/api.ts`:

```ts
export async function getNrlScorersServer(matchId: number): Promise<NrlScorer[] | null> {
  return getServer<NrlScorer[]>(`/api/nrl/matches/${matchId}/scorers`, 60);
}
```

Add `NrlScorer` to the file's `import type { ... } from "@/lib/types"` line.

- [ ] **Step 3: Write the failing component test**

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/sections/ScorersSection.test.tsx
import { render, screen } from "@testing-library/react";
import { ScorersSection } from "./ScorersSection";
import { getNrlScorersServer } from "@/lib/api";
import type { NrlScorer } from "@/lib/types";

jest.mock("@/lib/api");
const mockScorers = getNrlScorersServer as jest.MockedFunction<typeof getNrlScorersServer>;

afterEach(() => jest.resetAllMocks());

const scorer = (over: Partial<NrlScorer> = {}): NrlScorer => ({
  player: "A. Wing", jersey: 2, position: "WG", unit: "outside backs",
  tries_season: 12, games_season: 15, last10: [{ round: 14, tries: 1 }],
  p_anytime: 0.42, team: "home", ...over,
});

it("renders home and away columns with anytime-try chance, no odds", async () => {
  mockScorers.mockResolvedValue([
    scorer(), scorer({ player: "B. Centre", team: "away", p_anytime: 0.31 }),
  ]);
  render(await ScorersSection({ matchId: 1 }));
  expect(screen.getByText("A. Wing")).toBeInTheDocument();
  expect(screen.getByText("B. Centre")).toBeInTheDocument();
  expect(screen.getByText("42%")).toBeInTheDocument();
  expect(screen.queryByText(/odds/i)).not.toBeInTheDocument();
});

it("renders nothing when the endpoint has no data yet", async () => {
  mockScorers.mockResolvedValue(null);
  const result = await ScorersSection({ matchId: 1 });
  expect(result).toBeNull();
});

it("renders nothing when the team list is empty", async () => {
  mockScorers.mockResolvedValue([]);
  const result = await ScorersSection({ matchId: 1 });
  expect(result).toBeNull();
});
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd frontend && npx jest "app/nrl/match/[season]/[round]/[no]/sections/ScorersSection.test.tsx"`
Expected: FAIL — cannot find module `./ScorersSection`

- [ ] **Step 5: Implement the component**

```tsx
// frontend/app/nrl/match/[season]/[round]/[no]/sections/ScorersSection.tsx
import { getNrlScorersServer } from "@/lib/api";
import { pct } from "@/lib/format";
import type { NrlScorer } from "@/lib/types";

const TOP_N = 6;

/** sections.ts entry point (server component, no client polling needed --
 *  scorer projections don't change minute to minute). Probabilities only:
 *  no odds, no value badges (program-wide constraint). */
export async function ScorersSection({ matchId }: { matchId: number }) {
  const scorers = await getNrlScorersServer(matchId).catch(() => null);
  if (!scorers || scorers.length === 0) return null;

  const home = scorers.filter((s) => s.team === "home");
  const away = scorers.filter((s) => s.team === "away");

  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Try-scorer chances</h2>
      <div className="grid gap-5 sm:grid-cols-2">
        <TeamScorers players={home} />
        <TeamScorers players={away} />
      </div>
    </section>
  );
}

function TeamScorers({ players }: { players: NrlScorer[] }) {
  const top = [...players].sort((a, b) => b.p_anytime - a.p_anytime).slice(0, TOP_N);
  if (top.length === 0) {
    return <p className="text-sm text-muted">No team list yet.</p>;
  }
  return (
    <ul className="space-y-1.5">
      {top.map((p) => (
        <li key={`${p.jersey}-${p.player}`} className="flex items-center justify-between gap-2 text-sm">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0 text-[11px] font-semibold text-muted">{p.position}</span>
            <span className="truncate text-foreground">{p.player}</span>
          </span>
          <span className="shrink-0 font-display font-bold tabular-nums text-lime-deep">
            {pct(p.p_anytime)}
          </span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd frontend && npx jest "app/nrl/match/[season]/[round]/[no]/sections/ScorersSection.test.tsx"`
Expected: PASS (3 tests). Rerun once on a worker SIGSEGV.

- [ ] **Step 7: Wire into `sections.ts`**

Open `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts`. Add an import:

```ts
import { ScorersSection } from "./sections/ScorersSection";
```

and append to the exported array (after the `live` entry from Task 9, or wherever the array's ordering convention places it — appending is the only requirement):

```ts
{ id: "scorers", label: "Scorers", render: ScorersSection },
```

Same adaptation note as Task 9 Step 7 if `IntelSectionProps` differs from the assumed `{matchId}` shape.

- [ ] **Step 8: Full frontend build + test suite check**

Run: `cd frontend && npm run build && npx jest`
Expected: build succeeds; full jest suite passes (rerun `npx jest` once if a worker SIGSEGV appears, per Global Constraints).

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/app/nrl/match/\[id\]/sections/ScorersSection.tsx frontend/app/nrl/match/\[id\]/sections/ScorersSection.test.tsx frontend/app/nrl/match/\[id\]/sections.ts
git reset frontend/node_modules
git commit -m "feat(nrl): scorers section UI (probabilities only, no odds)"
```

---

## After Task 10

Open the PR from `feat/nrl-match-intel-w3` against `main` (merge order is W1 → W2 → W3 — confirm both have merged before this branch's PR lands). Remove the worktree:

```bash
cd "/Users/macbookpro/Projects/FIFA WC26 Prediction"
git worktree remove /tmp/nrl-intel-w3
```

Flag the two `WAVE 2 RECONCILIATION SHIM` files (`pipeline/sports/nrl_stats_shim.py`, `backend/app/models/nrl_wave2_shim.py`) explicitly in the PR description so the reviewer merging this last performs the swap-over documented in each file's docstring before (or immediately after) merging.
