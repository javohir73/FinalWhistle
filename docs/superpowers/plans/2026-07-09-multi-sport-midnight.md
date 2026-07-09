# Multi-Sport Navigation + Midnight Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved design (docs/superpowers/specs/2026-07-09-multi-sport-navigation-design.md): Midnight dark theme + "Today's movers" home hero (Phase 1), then the NRL vertical behind a header sport switcher with `/nrl` routes (Phase 2).

**Architecture:** Phase 1 is a CSS-token swap (the design system is HSL vars in `globals.css`), a new `probability_snapshots` table appended daily by both pipelines, a read-only `/api/movers` endpoint, and a `MoversPanel` replacing the "Your team" hero. Phase 2 adds a per-sport nav config (`lib/sports.ts`), a `SportSwitcher`, a computed `/api/nrl/ladder` endpoint, and four `/nrl` pages consuming the existing NRL API.

**Tech Stack:** Next.js 15 App Router + React 19 + TypeScript + Tailwind 3.4 (HSL CSS-var tokens) + jest/ts-jest; FastAPI + SQLAlchemy 2.0 (`Mapped`/`mapped_column`) + Alembic + pytest.

## Global Constraints

- Token **names** in `globals.css`/`tailwind.config.ts` must not change — only values (spec: "the retheme is primarily a token swap").
- Sport identifiers are exactly `"football"` and `"nrl"` (backend `sport` column is `String(10)`).
- Every new public API response includes: `"disclaimer": "For analytics and entertainment only. Not betting advice."`
- Football routes and nav labels are unchanged: Home `/`, Matches `/matches`, Groups `/groups`, Bracket `/brackets`, You `/leaderboard`.
- NRL nav: Home `/nrl`, Matches `/nrl/matches`, Ladder `/nrl/ladder`, Record `/nrl/record`, You `/leaderboard` (shared).
- Frontend tests: `cd frontend && npx jest`; typecheck: `npm run typecheck`. Backend tests: `cd backend && python -m pytest`. Pipeline tests follow the `pipeline/**/*_test.py` naming.
- Next 15: `cookies()` is async (`await cookies()`).
- Commit after every task; prefix `feat:`/`chore:` as shown.

## File Structure

```
frontend/
  app/globals.css                 MODIFY  Midnight token values + .glass/.panel-pitch/.card-hover
  app/manifest.ts                 MODIFY  themeColor/backgroundColor → #0d1118
  app/layout.tsx                  MODIFY  themeColor metadata if present
  app/page.tsx                    MODIFY  fw_sport cookie redirect
  app/HomeExperience.tsx          MODIFY  hero → <MoversPanel/>
  app/nrl/page.tsx                CREATE  NRL home (round fixtures + mini ladder)
  app/nrl/matches/page.tsx        CREATE  all rounds
  app/nrl/ladder/page.tsx         CREATE  full ladder
  app/nrl/record/page.tsx         CREATE  model record + empty state
  components/MoversPanel.tsx      CREATE  home hero
  components/ChanceChip.tsx       CREATE  probability chip + delta
  components/Sparkline.tsx        CREATE  tiny SVG trend line
  components/SportSwitcher.tsx    CREATE  segmented control + mobile pills
  components/SiteNav.tsx          MODIFY  config-driven links + switcher
  components/BottomNav.tsx        MODIFY  config-driven tabs
  components/ClubBadge.tsx        CREATE  NRL club monogram
  components/SportMatchCard.tsx   CREATE  NRL fixture card
  components/LadderTable.tsx      CREATE  standings table
  lib/sports.ts                   CREATE  sport config + pathname helpers
  lib/api.ts                      MODIFY  movers + NRL fetchers
  lib/types.ts                    MODIFY  Mover/Nrl*/LadderRow types
  __tests__/sports.test.ts        CREATE
  __tests__/movers.test.ts        CREATE
backend/
  app/models/__init__.py          MODIFY  ProbabilitySnapshot
  alembic/versions/<new>.py       CREATE  probability_snapshots table
  app/api/movers.py               CREATE  GET /api/movers
  app/api/prob_history.py         CREATE  GET /api/matches/{id}/prob-history
  app/api/sports.py               MODIFY  GET /api/nrl/ladder
  app/main.py                     MODIFY  register new routers
  tests/test_movers_api.py        CREATE
  tests/test_prob_history_api.py  CREATE
  tests/test_nrl_ladder_api.py    CREATE
pipeline/
  prob_snapshots.py               CREATE  snapshot writers
  prob_snapshots_test.py          CREATE
  run_pipeline.py                 MODIFY  snapshot step after predictions
  sports/nrl_predict.py           MODIFY  snapshot after --generate
```

---

# Phase 1 — Midnight theme + Today's movers

Each Phase 1 task ships independently; football keeps working after every commit.

### Task 1: Midnight token swap

**Files:**
- Modify: `frontend/app/globals.css:8-28` (tokens), `:100-130` (`.glass`, `.panel-pitch`, `.card-hover`)
- Modify: `frontend/app/manifest.ts`, `frontend/app/layout.tsx` (theme color)

**Interfaces:**
- Consumes: nothing.
- Produces: Midnight token values every later component relies on (`bg-surface`, `text-lime-deep`, `bg-win/10`, `.glass`, `.panel-pitch`).

- [ ] **Step 1: Swap the `:root` token values** in `frontend/app/globals.css` (keep every name; replace values and the header comment):

```css
/* ============ "Midnight" design system ============ */
/* Premium dark market look (spec 2026-07-09). Same token names as Daylight so
   every Tailwind utility keeps working — only the values change. Daylight
   values are preserved below under .theme-daylight for rollback. */
:root {
  --background: 218 30% 7%;   /* #0d1118  page canvas (deep blue-black) */
  --surface: 223 31% 11%;     /* #141926  cards */
  --surface-2: 221 29% 15%;   /* #1b2231  insets / track / hover */
  --foreground: 213 36% 95%;  /* #eef2f7  primary ink */
  --muted: 219 14% 60%;       /* #8b95a7  secondary text */
  --border: 216 23% 15%;      /* ≈ white @ 7% over the canvas */

  --win: 85 73% 59%;          /* #a4e34a  lime — readable on dark as text too */
  --draw: 40 79% 61%;         /* #eab54e  amber */
  --loss: 347 88% 65%;        /* #f4587a  rose */
  --gold: 42 62% 48%;         /* #c79a2e */
  --accent: 85 73% 59%;       /* = win */

  --lime-deep: 85 73% 59%;    /* on dark, deep-lime text maps to bright lime */
  --amber-ink: 40 79% 61%;    /* amber text = amber fill on dark */
  --pitch: 147 44% 10%;       /* #0e2418  hero/accent panels */
}

/* Daylight rollback: apply .theme-daylight on <html> to restore the light theme. */
.theme-daylight {
  --background: 96 23% 96%; --surface: 0 0% 100%; --surface-2: 94 18% 93%;
  --foreground: 150 38% 9%; --muted: 140 7% 45%; --border: 84 20% 90%;
  --win: 84 66% 52%; --draw: 41 78% 51%; --loss: 350 84% 62%;
  --gold: 42 62% 48%; --accent: 84 66% 52%;
  --lime-deep: 108 56% 27%; --amber-ink: 43 82% 33%; --pitch: 151 51% 14%;
}
```

- [ ] **Step 2: Retune the component utilities** in the same file. Replace the `.glass`, `.panel-pitch` and `.card-hover:hover` bodies:

```css
  .glass {
    background: linear-gradient(180deg, hsl(var(--surface)), hsl(223 30% 10%));
    border: 1px solid hsl(var(--border));
    box-shadow: 0 10px 30px -18px rgba(0, 0, 0, 0.7);
  }

  .panel-pitch {
    position: relative;
    overflow: hidden;
    background: linear-gradient(150deg, hsl(147 44% 13%), hsl(var(--pitch)) 55%, hsl(147 45% 7%));
    border: 1px solid hsl(var(--win) / 0.15);
    color: #fff;
  }
  .panel-pitch::after {
    content: "";
    position: absolute;
    right: -46px;
    top: -46px;
    width: 150px;
    height: 150px;
    border-radius: 50%;
    background: radial-gradient(circle, hsl(var(--win) / 0.22), transparent 65%);
    pointer-events: none;
  }

  .card-hover:hover {
    transform: translateY(-3px);
    border-color: hsl(var(--win) / 0.4);
    box-shadow: 0 14px 32px -14px rgba(0, 0, 0, 0.75);
  }
```

The `:focus-visible` rule needs no change (it uses `--lime-deep`, which now resolves to bright lime — ≥3:1 on the dark canvas).

- [ ] **Step 3: Update the PWA/theme colors.** In `frontend/app/manifest.ts` set `theme_color`/`background_color` (whatever keys exist) to `"#0d1118"`. In `frontend/app/layout.tsx`, if a `themeColor` export/metadata exists, set it to `#0d1118` too. Find them: `grep -n "themeColor\|theme_color\|background_color" frontend/app/manifest.ts frontend/app/layout.tsx`.

- [ ] **Step 4: Verify build + visual pass**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: both succeed.
Then `npm run dev` and eyeball `/`: dark canvas, readable text everywhere, lime nav active state, hero panel glows. Check `/matches`, `/groups`, `/brackets`, `/leaderboard`, one `/match/[id]` — look for any hardcoded light colors (e.g. `bg-white`, `text-black`): `grep -rn "bg-white\|text-black\|#fff\b" frontend/app frontend/components --include="*.tsx" | grep -v panel` and fix stragglers to token classes.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/globals.css frontend/app/manifest.ts frontend/app/layout.tsx
git commit -m "feat: Midnight dark theme — token swap with Daylight rollback class"
```

### Task 2: `probability_snapshots` table

**Files:**
- Modify: `backend/app/models/__init__.py` (append after `SportPredictionResult`, ~line 757)
- Create: `backend/alembic/versions/<generated>_probability_snapshots.py`
- Test: `backend/tests/test_probability_snapshot_model.py`

**Interfaces:**
- Produces: `ProbabilitySnapshot(sport: str, entity_id: int, market: str, ref_id: int | None, prob: float, snapshot_date: date)` — used by Tasks 3–4. Markets: `make_knockout`, `win_title`, `qualify_group` (football, entity = `teams.id`), `win_match` (nrl, entity = `sport_teams.id`, `ref_id` = `sport_matches.id`).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_probability_snapshot_model.py`:

```python
"""probability_snapshots stores one row per (sport, entity, market, ref, date)."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ProbabilitySnapshot


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_snapshot_roundtrip():
    db = _session()
    db.add(ProbabilitySnapshot(
        sport="football", entity_id=1, market="win_title",
        ref_id=None, prob=0.14, snapshot_date=date(2026, 7, 9),
    ))
    db.commit()
    row = db.query(ProbabilitySnapshot).one()
    assert row.market == "win_title"
    assert row.prob == 0.14
    assert row.snapshot_date == date(2026, 7, 9)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd backend && python -m pytest tests/test_probability_snapshot_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProbabilitySnapshot'`

- [ ] **Step 3: Add the model** to `backend/app/models/__init__.py` after `SportPredictionResult` (add `Date` to the existing `sqlalchemy` imports at the top of the file):

```python
class ProbabilitySnapshot(Base):
    """Daily model-probability snapshots for movement deltas + sparklines.

    One row per (sport, entity, market, ref, day). Football entities are
    teams.id (markets: make_knockout / win_title / qualify_group); NRL
    entities are sport_teams.id with ref_id = sport_matches.id (win_match).
    """

    __tablename__ = "probability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "sport", "entity_id", "market", "ref_id", "snapshot_date",
            name="uq_prob_snapshot_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    market: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    prob: Mapped[float] = mapped_column(Float)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Also add `"ProbabilitySnapshot"` to `__all__` and `from datetime import date` alongside the existing datetime import if not present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_probability_snapshot_model.py -v`
Expected: PASS

- [ ] **Step 5: Create the Alembic migration.** Find the current head: `cd backend && alembic heads` (note the revision id). Create `backend/alembic/versions/b2c3d4e5f6a7_probability_snapshots.py`:

```python
"""probability_snapshots for movers deltas + sparklines."""
import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "<PASTE OUTPUT OF `alembic heads` HERE>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "probability_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sport", sa.String(10), nullable=False, index=True),
        sa.Column("entity_id", sa.Integer, nullable=False, index=True),
        sa.Column("market", sa.String(30), nullable=False),
        sa.Column("ref_id", sa.Integer, nullable=True),
        sa.Column("prob", sa.Float, nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "sport", "entity_id", "market", "ref_id", "snapshot_date",
            name="uq_prob_snapshot_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("probability_snapshots")
```

Verify it applies against a scratch SQLite db: `cd backend && python -m pytest tests -k probability_snapshot -v` (metadata path) — production migration runs via the refresh workflows' `alembic upgrade head`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/*probability_snapshots.py backend/tests/test_probability_snapshot_model.py
git commit -m "feat: probability_snapshots table for movers deltas"
```

### Task 3: Pipeline snapshot writers

**Files:**
- Create: `pipeline/prob_snapshots.py`
- Test: `pipeline/prob_snapshots_test.py`
- Modify: `pipeline/run_pipeline.py:91` (after the predictions step), `pipeline/sports/nrl_predict.py` (end of the `--generate` path)

**Interfaces:**
- Consumes: `ProbabilitySnapshot` (Task 2); existing `TournamentOdds`, `Standing`, `SportMatch`, `SportPrediction` models.
- Produces: `snapshot_football(db, snapshot_date=None) -> int`, `snapshot_nrl(db, snapshot_date=None) -> int` (rows written; idempotent per day).

- [ ] **Step 1: Write the failing test** — `pipeline/prob_snapshots_test.py`:

```python
"""Snapshot writers are idempotent per (sport, day) and read serving tables."""
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam, Team, TournamentOdds,
)
from pipeline.prob_snapshots import snapshot_football, snapshot_nrl


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_snapshot_football_writes_odds_markets_idempotently():
    db = _session()
    team = Team(name="Australia", code="AUS")
    db.add(team); db.flush()
    db.add(TournamentOdds(team_id=team.id, make_knockout=0.34, win_title=0.02))
    db.commit()

    day = date(2026, 7, 9)
    assert snapshot_football(db, snapshot_date=day) == 2  # make_knockout + win_title
    assert snapshot_football(db, snapshot_date=day) == 2  # re-run same day: replaced, not duplicated
    assert db.query(ProbabilitySnapshot).filter_by(sport="football").count() == 2


def test_snapshot_nrl_snapshots_upcoming_round_win_probs():
    db = _session()
    home = SportTeam(sport="nrl", name="Broncos")
    away = SportTeam(sport="nrl", name="Storm")
    db.add_all([home, away]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=19, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()
    db.add(SportPrediction(match_id=m.id, model_version="nrl-1",
                           p_home=0.39, p_draw=0.04, p_away=0.57))
    db.commit()

    n = snapshot_nrl(db, snapshot_date=date(2026, 7, 9))
    assert n == 2  # one win_match row per side
    rows = db.query(ProbabilitySnapshot).filter_by(sport="nrl").all()
    assert {(r.entity_id, round(r.prob, 2)) for r in rows} == {(home.id, 0.39), (away.id, 0.57)}
    assert all(r.market == "win_match" and r.ref_id == m.id for r in rows)
```

Note: if `Team` requires different constructor fields, check `backend/app/models/__init__.py:44-60` and use its minimal required columns.

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd "/Users/macbookpro/Projects/FIFA WC26 Prediction" && PYTHONPATH=backend:. python -m pytest pipeline/prob_snapshots_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.prob_snapshots'`

- [ ] **Step 3: Implement** `pipeline/prob_snapshots.py`:

```python
"""Daily probability snapshots (spec 2026-07-09): the movers feature's data.

Delete-then-insert per (sport, day) so pipeline re-runs stay idempotent.
Reads the already-persisted serving tables — no model computation here.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    ProbabilitySnapshot, SportMatch, SportPrediction, Standing, TournamentOdds,
)


def _replace_day(db: Session, sport: str, day: date, rows: list[ProbabilitySnapshot]) -> int:
    db.query(ProbabilitySnapshot).filter(
        ProbabilitySnapshot.sport == sport,
        ProbabilitySnapshot.snapshot_date == day,
    ).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def snapshot_football(db: Session, snapshot_date: date | None = None) -> int:
    day = snapshot_date or date.today()
    rows: list[ProbabilitySnapshot] = []
    for odds in db.query(TournamentOdds).all():
        for market, prob in (("make_knockout", odds.make_knockout),
                             ("win_title", odds.win_title)):
            if prob is not None:
                rows.append(ProbabilitySnapshot(
                    sport="football", entity_id=odds.team_id, market=market,
                    ref_id=None, prob=prob, snapshot_date=day,
                ))
    for st in db.query(Standing).filter(Standing.qualification_prob.isnot(None)).all():
        rows.append(ProbabilitySnapshot(
            sport="football", entity_id=st.team_id, market="qualify_group",
            ref_id=None, prob=st.qualification_prob, snapshot_date=day,
        ))
    return _replace_day(db, "football", day, rows)


def snapshot_nrl(db: Session, snapshot_date: date | None = None) -> int:
    day = snapshot_date or date.today()
    rows: list[ProbabilitySnapshot] = []
    matches = (
        db.query(SportMatch)
        .filter(SportMatch.sport == "nrl", SportMatch.status == "scheduled")
        .all()
    )
    for m in matches:
        pred = (
            db.query(SportPrediction)
            .filter(SportPrediction.match_id == m.id)
            .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
            .first()
        )
        if pred is None:
            continue
        if m.home_team_id is not None:
            rows.append(ProbabilitySnapshot(
                sport="nrl", entity_id=m.home_team_id, market="win_match",
                ref_id=m.id, prob=pred.p_home, snapshot_date=day,
            ))
        if m.away_team_id is not None:
            rows.append(ProbabilitySnapshot(
                sport="nrl", entity_id=m.away_team_id, market="win_match",
                ref_id=m.id, prob=pred.p_away, snapshot_date=day,
            ))
    return _replace_day(db, "nrl", day, rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. python -m pytest pipeline/prob_snapshots_test.py -v`
Expected: 2 passed

- [ ] **Step 5: Hook into both pipelines.** In `pipeline/run_pipeline.py`, directly after the predictions step (line 91: `step("predictions", ...)`), add:

```python
    from pipeline.prob_snapshots import snapshot_football
    step("prob_snapshots", lambda: snapshot_football(db))
```

In `pipeline/sports/nrl_predict.py`, find the end of the `--generate` branch (`grep -n "generate" pipeline/sports/nrl_predict.py` — after the "N prediction row(s) written" print/log), add:

```python
    from pipeline.prob_snapshots import snapshot_nrl
    n_snap = snapshot_nrl(db)
    print(f"snapshots: {n_snap} probability row(s) written")
```

(match the local session variable name used there — it may be `session` rather than `db`).

- [ ] **Step 6: Run the sports test suite to catch regressions**

Run: `PYTHONPATH=backend:. python -m pytest pipeline/prob_snapshots_test.py pipeline/sports/nrl_predict_test.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add pipeline/prob_snapshots.py pipeline/prob_snapshots_test.py pipeline/run_pipeline.py pipeline/sports/nrl_predict.py
git commit -m "feat: daily probability snapshots from both pipelines"
```

### Task 4: `GET /api/movers`

**Files:**
- Create: `backend/app/api/movers.py`
- Modify: `backend/app/main.py` (register router — mirror how `sports` is registered: `grep -n "include_router" backend/app/main.py`)
- Test: `backend/tests/test_movers_api.py`

**Interfaces:**
- Consumes: `ProbabilitySnapshot` (Task 2), `Team.name`, `SportTeam.name`.
- Produces: `GET /api/movers?sport=football|nrl&limit=3` →
  `{"sport", "as_of": "YYYY-MM-DD"|null, "movers": [{"entity_id", "name", "market", "prob", "delta": float|null, "series": [float,...]}], "disclaimer"}` — sorted by `abs(delta)` desc; `delta`/`series` need ≥2 snapshot days, else `delta` is null and movers falls back to highest `prob`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_movers_api.py`:

```python
"""Movers = biggest |Δ| between the two most recent snapshot days per key."""
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ProbabilitySnapshot, Team


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), TestingSession()


def test_movers_ranked_by_abs_delta():
    client, db = _client()
    usa = Team(name="United States", code="USA")
    bra = Team(name="Brazil", code="BRA")
    db.add_all([usa, bra]); db.flush()
    d1, d2 = date(2026, 7, 8), date(2026, 7, 9)
    db.add_all([
        ProbabilitySnapshot(sport="football", entity_id=usa.id, market="make_knockout",
                            prob=0.366, snapshot_date=d1),
        ProbabilitySnapshot(sport="football", entity_id=usa.id, market="make_knockout",
                            prob=0.39, snapshot_date=d2),
        ProbabilitySnapshot(sport="football", entity_id=bra.id, market="win_title",
                            prob=0.106, snapshot_date=d1),
        ProbabilitySnapshot(sport="football", entity_id=bra.id, market="win_title",
                            prob=0.09, snapshot_date=d2),
    ])
    db.commit()

    res = client.get("/api/movers?sport=football&limit=3")
    assert res.status_code == 200
    body = res.json()
    assert body["as_of"] == "2026-07-09"
    assert [m["name"] for m in body["movers"]] == ["United States", "Brazil"]
    top = body["movers"][0]
    assert top["market"] == "make_knockout"
    assert round(top["delta"], 3) == 0.024
    assert top["series"] == [0.366, 0.39]
    assert "Not betting advice" in body["disclaimer"]
    app.dependency_overrides.clear()


def test_movers_single_day_returns_null_deltas():
    client, db = _client()
    t = Team(name="Mexico", code="MEX")
    db.add(t); db.flush()
    db.add(ProbabilitySnapshot(sport="football", entity_id=t.id, market="win_title",
                               prob=0.05, snapshot_date=date(2026, 7, 9)))
    db.commit()

    body = client.get("/api/movers?sport=football").json()
    assert body["movers"][0]["delta"] is None
    app.dependency_overrides.clear()
```

(If `Team` requires other non-null constructor fields, supply the minimal ones per `models/__init__.py:44-60`.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_movers_api.py -v`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Implement** `backend/app/api/movers.py`:

```python
"""Movers: biggest daily probability swings, powering the home hero.

Ranking: |latest - previous| per (entity, market, ref) across the two most
recent snapshot days for the sport. With a single day of data, deltas are
null and rows fall back to highest probability (frontend hides the arrows).
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProbabilitySnapshot, SportTeam, Team

router = APIRouter(prefix="/api/movers", tags=["movers"])

_SERIES_DAYS = 7


@router.get("")
def movers(sport: str = Query(...), limit: int = Query(3, ge=1, le=20),
           db: Session = Depends(get_db)):
    if sport not in ("football", "nrl"):
        raise HTTPException(status_code=422, detail={"code": "bad_sport",
                                                     "message": "sport must be football or nrl"})

    days = [d for (d,) in (
        db.query(ProbabilitySnapshot.snapshot_date)
        .filter(ProbabilitySnapshot.sport == sport)
        .distinct().order_by(ProbabilitySnapshot.snapshot_date.desc())
        .limit(_SERIES_DAYS).all()
    )]
    if not days:
        return {"sport": sport, "as_of": None, "movers": [],
                "disclaimer": "For analytics and entertainment only. Not betting advice."}
    days_asc = sorted(days)

    rows = (
        db.query(ProbabilitySnapshot)
        .filter(ProbabilitySnapshot.sport == sport,
                ProbabilitySnapshot.snapshot_date.in_(days))
        .all()
    )
    by_key: dict[tuple, dict] = defaultdict(dict)  # key -> {date: prob}
    for r in rows:
        by_key[(r.entity_id, r.market, r.ref_id)][r.snapshot_date] = r.prob

    latest, prev = days_asc[-1], (days_asc[-2] if len(days_asc) > 1 else None)
    items = []
    for (entity_id, market, ref_id), by_day in by_key.items():
        if latest not in by_day:
            continue
        prob = by_day[latest]
        delta = (prob - by_day[prev]) if (prev is not None and prev in by_day) else None
        series = [by_day[d] for d in days_asc if d in by_day]
        items.append({"entity_id": entity_id, "market": market,
                      "prob": prob, "delta": delta, "series": series})

    items.sort(key=lambda m: (abs(m["delta"]) if m["delta"] is not None else -1, m["prob"]),
               reverse=True)
    items = items[:limit]

    model = SportTeam if sport == "nrl" else Team
    names = dict(
        db.query(model.id, model.name)
        .filter(model.id.in_([m["entity_id"] for m in items]))
        .all()
    ) if items else {}
    for m in items:
        m["name"] = names.get(m["entity_id"], "Unknown")

    return {
        "sport": sport,
        "as_of": latest.isoformat(),
        "movers": items,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

Register in `backend/app/main.py` next to the existing routers:

```python
from app.api import movers as movers_api
app.include_router(movers_api.router)
```

(match the import style already used for `sports` in that file).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_movers_api.py -v`
Expected: 2 passed. Also run `python -m pytest tests -x -q` for regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/movers.py backend/app/main.py backend/tests/test_movers_api.py
git commit -m "feat: GET /api/movers — daily probability swings"
```

### Task 5: MoversPanel replaces the "Your team" hero

**Files:**
- Modify: `frontend/lib/types.ts`, `frontend/lib/api.ts`
- Create: `frontend/components/ChanceChip.tsx`, `frontend/components/Sparkline.tsx`, `frontend/components/MoversPanel.tsx`
- Modify: `frontend/app/HomeExperience.tsx:243-260` (the `panel-pitch` "Your team" `<Link>` block)
- Test: `frontend/__tests__/movers.test.ts`

**Interfaces:**
- Consumes: `GET /api/movers` (Task 4) via `CLIENT_BASE`.
- Produces: `Mover`, `MoversResponse` types; `getMovers(sport)`; `<ChanceChip prob delta tone?>`, `<Sparkline values tone>`, `<MoversPanel sport>` — reused by Phase 2's NRL home. Also `marketLabel(market: string): string`.

- [ ] **Step 1: Write the failing test** — `frontend/__tests__/movers.test.ts` (pure helpers, no DOM):

```ts
import { marketLabel, formatDelta } from "@/components/MoversPanel";

describe("movers helpers", () => {
  it("maps market codes to reader copy", () => {
    expect(marketLabel("make_knockout")).toBe("to reach the knockouts");
    expect(marketLabel("win_title")).toBe("to win the Cup");
    expect(marketLabel("qualify_group")).toBe("to qualify from the group");
    expect(marketLabel("win_match")).toBe("to win this round");
    expect(marketLabel("anything_else")).toBe("probability");
  });

  it("formats deltas as signed percentage points, null-safe", () => {
    expect(formatDelta(0.024)).toBe("▲ 2.4");
    expect(formatDelta(-0.016)).toBe("▼ 1.6");
    expect(formatDelta(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx jest __tests__/movers.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement.** Append to `frontend/lib/types.ts`:

```ts
/** Daily probability swing row from GET /api/movers (spec 2026-07-09). */
export interface Mover {
  entity_id: number;
  name: string;
  market: string;
  prob: number;
  delta: number | null;
  series: number[];
}

export interface MoversResponse {
  sport: "football" | "nrl";
  as_of: string | null;
  movers: Mover[];
  disclaimer: string;
}
```

Append to `frontend/lib/api.ts` (after the other `getJson` fetchers, importing `MoversResponse` in the type import block):

```ts
export const getMovers = (sport: "football" | "nrl", limit = 3) =>
  getJson<MoversResponse>(`/api/movers?sport=${sport}&limit=${limit}`);
```

Create `frontend/components/Sparkline.tsx`:

```tsx
/** Tiny probability trend line. Pure SVG, no deps; hidden when <2 points. */
export function Sparkline({ values, tone }: { values: number[]; tone: "up" | "down" }) {
  if (values.length < 2) return null;
  const w = 44;
  const h = 16;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - min) / span) * (h - 4)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-4 w-11 shrink-0" aria-hidden="true">
      <polyline
        points={pts}
        fill="none"
        strokeWidth="1.6"
        className={tone === "up" ? "stroke-lime-deep" : "stroke-loss"}
      />
    </svg>
  );
}
```

Create `frontend/components/ChanceChip.tsx`:

```tsx
import { cn } from "@/lib/utils";

/** Market-style probability chip: bold % plus an optional daily delta. */
export function ChanceChip({
  prob,
  deltaText,
  tone,
}: {
  prob: number;
  deltaText: string | null;
  tone: "up" | "down" | "muted";
}) {
  return (
    <span
      className={cn(
        "min-w-[58px] rounded-lg px-2 py-1 text-right text-sm font-extrabold tabular-nums",
        tone === "up" && "bg-win/10 text-lime-deep ring-1 ring-win/20",
        tone === "down" && "bg-loss/10 text-loss ring-1 ring-loss/20",
        tone === "muted" && "bg-surface-2 text-muted",
      )}
    >
      {Math.round(prob * 100)}%
      {deltaText ? <small className="block text-[9px] font-bold">{deltaText}</small> : null}
    </span>
  );
}
```

Create `frontend/components/MoversPanel.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMovers } from "@/lib/api";
import type { Mover } from "@/lib/types";
import { ChanceChip } from "@/components/ChanceChip";
import { Sparkline } from "@/components/Sparkline";

/** Reader copy for market codes; falls back for future markets. */
export function marketLabel(market: string): string {
  switch (market) {
    case "make_knockout":
      return "to reach the knockouts";
    case "win_title":
      return "to win the Cup";
    case "qualify_group":
      return "to qualify from the group";
    case "win_match":
      return "to win this round";
    default:
      return "probability";
  }
}

/** "▲ 2.4" / "▼ 1.6" in percentage points; null with <2 snapshot days. */
export function formatDelta(delta: number | null): string | null {
  if (delta === null) return null;
  const pts = Math.abs(delta * 100).toFixed(1);
  return `${delta >= 0 ? "▲" : "▼"} ${pts}`;
}

/** Home hero (replaces the "Your team" panel, spec 2026-07-09): the three
 *  biggest probability swings since the previous model refresh. */
export function MoversPanel({ sport }: { sport: "football" | "nrl" }) {
  const [movers, setMovers] = useState<Mover[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getMovers(sport)
      .then((res) => setMovers(res.movers))
      .catch(() => setFailed(true));
  }, [sport]);

  if (failed || (movers !== null && movers.length === 0)) return null;

  return (
    <section className="panel-pitch mt-6 rounded-2xl p-5">
      <p className="font-display text-[11px] font-semibold uppercase tracking-[0.2em] text-white/60">
        Today&apos;s movers
      </p>
      {movers === null ? (
        <div className="skeleton mt-4 h-32 rounded-xl" aria-hidden="true" />
      ) : (
        <ul className="mt-2">
          {movers.map((m) => {
            const up = (m.delta ?? 0) >= 0;
            return (
              <li
                key={`${m.entity_id}-${m.market}`}
                className="flex items-center gap-3 border-t border-white/10 py-2.5 first:border-t-0"
              >
                <span className="flex-1">
                  <span className="font-display text-[15px] font-semibold text-white">
                    {m.name}
                  </span>
                  <span className="block text-[11px] font-medium text-white/45">
                    {marketLabel(m.market)}
                  </span>
                </span>
                <Sparkline values={m.series} tone={up ? "up" : "down"} />
                <ChanceChip
                  prob={m.prob}
                  deltaText={formatDelta(m.delta)}
                  tone={m.delta === null ? "muted" : up ? "up" : "down"}
                />
              </li>
            );
          })}
        </ul>
      )}
      <Link
        href={sport === "nrl" ? "/nrl/matches" : "/matches"}
        className="mt-2 inline-block text-sm font-semibold text-win"
      >
        See all movement →
      </Link>
    </section>
  );
}
```

- [ ] **Step 4: Replace the hero.** In `frontend/app/HomeExperience.tsx`, locate the "Your team" hero (`grep -n "Your team" frontend/app/HomeExperience.tsx` → the `<Link ... className="card-hover panel-pitch group mt-6 block rounded-2xl p-5">` block starting ~line 243). Replace that entire `<Link>...</Link>` element with:

```tsx
<MoversPanel sport="football" />
```

and add the import: `import { MoversPanel } from "@/components/MoversPanel";`. Do NOT remove team search / onboarding — only the hero card. If the removed block referenced now-unused variables (e.g. the followed team's odds), remove those bindings too until `npm run typecheck` is clean.

- [ ] **Step 5: Run tests + typecheck**

Run: `cd frontend && npx jest __tests__/movers.test.ts && npm run typecheck`
Expected: tests pass; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/MoversPanel.tsx frontend/components/ChanceChip.tsx frontend/components/Sparkline.tsx frontend/app/HomeExperience.tsx frontend/__tests__/movers.test.ts
git commit -m "feat: Today's movers home hero (replaces Your team panel)"
```

### Task 6: Match probability history + sparklines on match surfaces

**Files:**
- Create: `backend/app/api/prob_history.py`
- Modify: `backend/app/main.py` (register)
- Test: `backend/tests/test_prob_history_api.py`
- Modify: `frontend/lib/types.ts`, `frontend/lib/api.ts`; the Match-of-day card in `frontend/app/HomeExperience.tsx` and the match detail client (`grep -rn "ProbabilityBar" frontend/app/match` to find it)

**Interfaces:**
- Consumes: football `Prediction` history rows (`predictions` table, `is_shadow == False` — verify the column with `grep -n "is_shadow" backend/app/models/__init__.py`).
- Produces: `GET /api/matches/{match_id}/prob-history` → `{"match_id", "points": [{"date", "p_home", "p_draw", "p_away"}], "disclaimer"}` (≤7 most recent, ascending); frontend `getProbHistory(matchId)`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_prob_history_api.py`:

```python
"""prob-history returns up to 7 public prediction points, oldest first."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), TestingSession()


def test_prob_history_orders_and_caps_points():
    client, db = _client()
    m = Match()  # fill minimal non-null columns per models/__init__.py:88-155
    db.add(m); db.flush()
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(9):
        db.add(Prediction(match_id=m.id, model_version="v1",
                          p_home_win=0.4 + i * 0.01, p_draw=0.3, p_away_win=0.3 - i * 0.01,
                          created_at=base + timedelta(days=i)))
    db.commit()

    res = client.get(f"/api/matches/{m.id}/prob-history")
    assert res.status_code == 200
    pts = res.json()["points"]
    assert len(pts) == 7
    assert pts[0]["date"] < pts[-1]["date"]
    app.dependency_overrides.clear()
```

**Before running:** check the real `Prediction` column names (`sed -n '260,297p' backend/app/models/__init__.py`) — the football table may use `p_home_win/p_draw/p_away_win` or `p_home/p_draw/p_away`; align the test AND endpoint to the actual names, and add `Prediction.is_shadow == False` to the query only if the column exists. Fill `Match()` minimal non-null fields per the model.

- [ ] **Step 2: Run to verify failure** — `cd backend && python -m pytest tests/test_prob_history_api.py -v` → FAIL (404).

- [ ] **Step 3: Implement** `backend/app/api/prob_history.py`:

```python
"""Per-match public prediction history — feeds match-card sparklines."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Match, Prediction

router = APIRouter(prefix="/api/matches", tags=["matches"])

_MAX_POINTS = 7


@router.get("/{match_id}/prob-history")
def prob_history(match_id: int, db: Session = Depends(get_db)):
    if db.get(Match, match_id) is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    rows = (
        db.query(Prediction)
        .filter(Prediction.match_id == match_id)
        # add `, Prediction.is_shadow == False` here if the column exists
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(_MAX_POINTS)
        .all()
    )
    rows.reverse()
    return {
        "match_id": match_id,
        "points": [
            {
                "date": p.created_at.isoformat() if p.created_at else None,
                "p_home": p.p_home_win,  # align to actual column names (Step 1 note)
                "p_draw": p.p_draw,
                "p_away": p.p_away_win,
            }
            for p in rows
        ],
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

Register in `main.py` (same pattern as Task 4). Run: `python -m pytest tests/test_prob_history_api.py -v` → PASS.

- [ ] **Step 4: Frontend wiring.** Append to `types.ts`:

```ts
export interface ProbHistoryPoint {
  date: string | null;
  p_home: number;
  p_draw: number;
  p_away: number;
}
export interface ProbHistory {
  match_id: number;
  points: ProbHistoryPoint[];
}
```

Append to `api.ts`: `export const getProbHistory = (matchId: number) => getJson<ProbHistory>(`/api/matches/${matchId}/prob-history`);`

In the Match-of-day card (`MatchOfDayCard` inside `frontend/app/HomeExperience.tsx`) and the match detail client (found via the grep above): fetch history in a `useEffect` keyed on the match id, and render `<Sparkline values={points.map(p => p.p_home)} tone={...} />` beside the home team and the away equivalent beside the away team, exactly like `MoversPanel` does. Skip rendering when `points.length < 2` (Sparkline already returns null).

- [ ] **Step 5: Verify + commit**

Run: `cd frontend && npm run typecheck && npx jest` and `cd ../backend && python -m pytest tests -x -q`
Expected: all green.

```bash
git add backend/app/api/prob_history.py backend/app/main.py backend/tests/test_prob_history_api.py frontend/lib/types.ts frontend/lib/api.ts frontend/app/HomeExperience.tsx frontend/app/match
git commit -m "feat: prediction history endpoint + sparklines on match surfaces"
```

---

# Phase 2 — NRL vertical

### Task 7: Sport config + pathname helpers

**Files:**
- Create: `frontend/lib/sports.ts`
- Test: `frontend/__tests__/sports.test.ts`

**Interfaces:**
- Produces (used by Tasks 8, 10, 11):
  - `type SportId = "football" | "nrl"`
  - `interface SportNavLink { href: string; label: string; activePrefixes: string[] }`
  - `SPORTS: Record<SportId, { id: SportId; label: string; basePath: string; navLinks: SportNavLink[] }>`
  - `sportFromPathname(pathname: string): SportId`
  - `switchSportHref(pathname: string, target: SportId): string`

- [ ] **Step 1: Write the failing test** — `frontend/__tests__/sports.test.ts`:

```ts
import { SPORTS, sportFromPathname, switchSportHref } from "@/lib/sports";

describe("sport config", () => {
  it("detects the active sport from the pathname prefix", () => {
    expect(sportFromPathname("/")).toBe("football");
    expect(sportFromPathname("/matches")).toBe("football");
    expect(sportFromPathname("/nrl")).toBe("nrl");
    expect(sportFromPathname("/nrl/ladder")).toBe("nrl");
    expect(sportFromPathname("/nrlx")).toBe("football"); // prefix must be exact
  });

  it("maps to the equivalent page when switching, else the sport home", () => {
    expect(switchSportHref("/matches", "nrl")).toBe("/nrl/matches");
    expect(switchSportHref("/nrl/matches", "football")).toBe("/matches");
    expect(switchSportHref("/groups", "nrl")).toBe("/nrl"); // no NRL groups
    expect(switchSportHref("/nrl/ladder", "football")).toBe("/");
    expect(switchSportHref("/", "nrl")).toBe("/nrl");
  });

  it("keeps football nav unchanged and gives NRL its five links", () => {
    expect(SPORTS.football.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Groups", "Bracket", "You"]);
    expect(SPORTS.nrl.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Ladder", "Record", "You"]);
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd frontend && npx jest __tests__/sports.test.ts` → module not found.

- [ ] **Step 3: Implement** `frontend/lib/sports.ts`:

```ts
/** Per-sport navigation config (spec 2026-07-09, Template A).
 *  Adding a sport = adding an entry here; SiteNav/BottomNav derive from it. */
export type SportId = "football" | "nrl";

export interface SportNavLink {
  href: string;
  label: string;
  activePrefixes: string[];
}

export const SPORTS: Record<
  SportId,
  { id: SportId; label: string; basePath: string; navLinks: SportNavLink[] }
> = {
  football: {
    id: "football",
    label: "Football",
    basePath: "",
    navLinks: [
      { href: "/", label: "Home", activePrefixes: ["/team"] },
      { href: "/matches", label: "Matches", activePrefixes: ["/matches", "/match"] },
      { href: "/groups", label: "Groups", activePrefixes: [] },
      { href: "/brackets", label: "Bracket", activePrefixes: [] },
      {
        href: "/leaderboard",
        label: "You",
        activePrefixes: ["/about", "/methodology", "/privacy", "/terms", "/record"],
      },
    ],
  },
  nrl: {
    id: "nrl",
    label: "NRL",
    basePath: "/nrl",
    navLinks: [
      { href: "/nrl", label: "Home", activePrefixes: [] },
      { href: "/nrl/matches", label: "Matches", activePrefixes: [] },
      { href: "/nrl/ladder", label: "Ladder", activePrefixes: [] },
      { href: "/nrl/record", label: "Record", activePrefixes: [] },
      { href: "/leaderboard", label: "You", activePrefixes: [] },
    ],
  },
};

export function sportFromPathname(pathname: string): SportId {
  return pathname === "/nrl" || pathname.startsWith("/nrl/") ? "nrl" : "football";
}

/** Equivalent-page mapping between sports; falls back to the sport's home. */
const EQUIVALENTS: Array<[string, string]> = [["/matches", "/nrl/matches"]];

export function switchSportHref(pathname: string, target: SportId): string {
  const home = target === "nrl" ? "/nrl" : "/";
  for (const [foot, nrl] of EQUIVALENTS) {
    const [from, to] = target === "nrl" ? [foot, nrl] : [nrl, foot];
    if (pathname === from || pathname.startsWith(from + "/")) return to;
  }
  return home;
}
```

- [ ] **Step 4: Run tests to verify they pass** — `npx jest __tests__/sports.test.ts` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/sports.ts frontend/__tests__/sports.test.ts
git commit -m "feat: per-sport nav config + pathname helpers"
```

### Task 8: SportSwitcher + config-driven nav

**Files:**
- Create: `frontend/components/SportSwitcher.tsx`
- Modify: `frontend/components/SiteNav.tsx` (drop `LINKS`, derive from config, mount switcher), `frontend/components/BottomNav.tsx` (drop `TABS` labels/hrefs, keep icons), `frontend/app/page.tsx` (cookie redirect)

**Interfaces:**
- Consumes: `SPORTS`, `sportFromPathname`, `switchSportHref` (Task 7).
- Produces: `<SportSwitcher variant="segment" | "pills" />`; cookie `fw_sport` (`football`|`nrl`, path=/, 1y).

- [ ] **Step 1: Implement** `frontend/components/SportSwitcher.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SPORTS, sportFromPathname, switchSportHref, type SportId } from "@/lib/sports";
import { cn } from "@/lib/utils";

const ICONS: Record<SportId, React.ReactNode> = {
  football: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5l4.1 3-1.6 4.8H9.5L8 10.5z" fill="currentColor" stroke="none" />
    </>
  ),
  nrl: (
    <g transform="rotate(-38 12 12)">
      <ellipse cx="12" cy="12" rx="8.5" ry="5.2" />
      <path d="M8.5 12h7M10.3 10.5v3M12 10.5v3M13.7 10.5v3" />
    </g>
  ),
};

/** Header sport toggle (Template A). `segment` renders the desktop control,
 *  `pills` the mobile row under the header. Persists the choice in fw_sport. */
export function SportSwitcher({ variant }: { variant: "segment" | "pills" }) {
  const pathname = usePathname();
  const active = sportFromPathname(pathname);

  const remember = (id: SportId) => {
    document.cookie = `fw_sport=${id};path=/;max-age=31536000;samesite=lax`;
  };

  return (
    <div
      role="group"
      aria-label="Sport"
      className={cn(
        variant === "segment"
          ? "hidden items-center gap-0.5 rounded-full bg-surface-2 p-1 sm:flex"
          : "flex items-center gap-1.5 px-4 pb-2 pt-2 sm:hidden",
      )}
    >
      {(Object.keys(SPORTS) as SportId[]).map((id) => {
        const on = id === active;
        return (
          <Link
            key={id}
            href={switchSportHref(pathname, id)}
            onClick={() => remember(id)}
            aria-current={on ? "true" : undefined}
            className={cn(
              "inline-flex min-h-[32px] items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-semibold transition",
              on
                ? "bg-surface text-lime-deep shadow-sm ring-1 ring-win/30"
                : "text-muted hover:text-foreground",
            )}
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none"
                 stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
              {ICONS[id]}
            </svg>
            {SPORTS[id].label}
          </Link>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Make `SiteNav` config-driven.** In `frontend/components/SiteNav.tsx`: delete the local `LINKS` const (lines 17–27); add imports `import { SPORTS, sportFromPathname } from "@/lib/sports";` and `import { SportSwitcher } from "@/components/SportSwitcher";`; inside the component compute `const links = SPORTS[sportFromPathname(pathname)].navLinks;` and map over `links` instead of `LINKS`. Mount `<SportSwitcher variant="segment" />` immediately after the brand `<Link>`, and `<SportSwitcher variant="pills" />` as the last child of the `<header>` (below the `<nav>`), so mobile gets the pill row. The brand link and the `matches()` helper stay as-is.

- [ ] **Step 3: Make `BottomNav` config-driven.** In `frontend/components/BottomNav.tsx`: keep the icon JSX but re-key it by label; replace the `TABS` array with:

```tsx
const ICONS: Record<string, React.ReactNode> = {
  Home: <path d="M3 11l9-8 9 8M5 10v10h14V10" strokeLinejoin="round" strokeLinecap="round" />,
  Matches: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M8 3v4M16 3v4M3 10h18" strokeLinecap="round" />
    </>
  ),
  Groups: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  Bracket: <path d="M4 5h6v6M4 19h6v-6M10 8h5v8h-5M15 12h5" strokeLinejoin="round" strokeLinecap="round" />,
  Ladder: <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />,
  Record: <path d="M4 19l6-7 4 3 6-8" strokeLinejoin="round" strokeLinecap="round" />,
  You: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" strokeLinecap="round" />
    </>
  ),
};
```

then inside the component: `const tabs = SPORTS[sportFromPathname(pathname)].navLinks;` and render `{tabs.map((tab) => ...)}` using `ICONS[tab.label]` for the icon (import `SPORTS`, `sportFromPathname`). The `matches()` helper and markup stay.

- [ ] **Step 4: Cookie landing.** In `frontend/app/page.tsx`, at the top of the (async server) page component:

```tsx
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
// inside the component, before any fetching:
const store = await cookies();
if (store.get("fw_sport")?.value === "nrl") redirect("/nrl");
```

(`/nrl` doesn't exist until Task 10 — that's fine; nothing sets the cookie to `nrl` until the switcher renders, by which time `/nrl` exists. Ship in the same PR.)

- [ ] **Step 5: Verify + commit**

Run: `cd frontend && npm run typecheck && npx jest`
Expected: clean (football nav renders identically — same labels/hrefs from config).

```bash
git add frontend/components/SportSwitcher.tsx frontend/components/SiteNav.tsx frontend/components/BottomNav.tsx frontend/app/page.tsx
git commit -m "feat: sport switcher + config-driven nav"
```

### Task 9: `GET /api/nrl/ladder`

**Files:**
- Modify: `backend/app/api/sports.py` (append endpoint)
- Test: `backend/tests/test_nrl_ladder_api.py`

**Interfaces:**
- Consumes: `SportMatch`, `SportTeam` (finished matches only).
- Produces: `GET /api/nrl/ladder?season=` → `{"season", "rows": [{"rank", "team_id", "name", "played", "wins", "draws", "losses", "points", "diff"}], "disclaimer"}` — 2 pts/win, 1/draw; ordered by points desc, then diff desc, then name asc.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_nrl_ladder_api.py`:

```python
"""Ladder: 2/1/0 points from finished matches; points then diff ordering."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportTeam


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), TestingSession()


def test_ladder_points_and_ordering():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Storm")
    broncos = SportTeam(sport="nrl", name="Broncos")
    panthers = SportTeam(sport="nrl", name="Panthers")
    db.add_all([storm, broncos, panthers]); db.flush()

    def played(no, h, a, sh, sa):
        db.add(SportMatch(sport="nrl", season=2026, round=1, match_no=no,
                          home_team_id=h.id, away_team_id=a.id,
                          score_home=sh, score_away=sa, status="finished"))

    played(1, storm, broncos, 30, 10)    # storm win
    played(2, panthers, storm, 12, 12)   # draw
    played(3, broncos, panthers, 20, 22) # panthers win
    # scheduled matches must not count:
    db.add(SportMatch(sport="nrl", season=2026, round=2, match_no=4,
                      home_team_id=storm.id, away_team_id=panthers.id, status="scheduled"))
    db.commit()

    body = client.get("/api/nrl/ladder?season=2026").json()
    rows = body["rows"]
    assert [r["name"] for r in rows] == ["Storm", "Panthers", "Broncos"]
    assert [r["points"] for r in rows] == [3, 3, 0]      # storm diff +20 beats panthers +2
    assert rows[0]["diff"] == 20 and rows[0]["played"] == 2
    assert rows[0]["rank"] == 1
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify failure** — `cd backend && python -m pytest tests/test_nrl_ladder_api.py -v` → 404.

- [ ] **Step 3: Implement** — append to `backend/app/api/sports.py`:

```python
@router.get("/ladder")
def nrl_ladder(season: int | None = None, db: Session = Depends(get_db)):
    """Computed ladder: 2 pts/win, 1/draw, ordered by points then for-against diff."""
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
    table: dict[int, dict] = {}

    def row(team_id: int) -> dict:
        return table.setdefault(team_id, {
            "team_id": team_id, "played": 0, "wins": 0, "draws": 0,
            "losses": 0, "points": 0, "diff": 0,
        })

    for m in finished:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        h, a = row(m.home_team_id), row(m.away_team_id)
        h["played"] += 1; a["played"] += 1
        h["diff"] += m.score_home - m.score_away
        a["diff"] += m.score_away - m.score_home
        if m.score_home > m.score_away:
            h["wins"] += 1; h["points"] += 2; a["losses"] += 1
        elif m.score_home < m.score_away:
            a["wins"] += 1; a["points"] += 2; h["losses"] += 1
        else:
            h["draws"] += 1; a["draws"] += 1; h["points"] += 1; a["points"] += 1

    names = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.id.in_(table.keys())).all()
    ) if table else {}
    rows = sorted(
        ({**r, "name": names.get(r["team_id"], "Unknown")} for r in table.values()),
        key=lambda r: (-r["points"], -r["diff"], r["name"]),
    )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    return {"season": season, "rows": rows,
            "disclaimer": "For analytics and entertainment only. Not betting advice."}
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_nrl_ladder_api.py tests/test_api_endpoints.py -v` → pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/sports.py backend/tests/test_nrl_ladder_api.py
git commit -m "feat: computed NRL ladder endpoint"
```

### Task 10: NRL types, fetchers, and shared components

**Files:**
- Modify: `frontend/lib/types.ts`, `frontend/lib/api.ts`
- Create: `frontend/components/ClubBadge.tsx`, `frontend/components/SportMatchCard.tsx`, `frontend/components/LadderTable.tsx`

**Interfaces:**
- Consumes: `/api/nrl/matches`, `/api/nrl/ladder`, `/api/nrl/model/record` response shapes (Task 9 + existing `sports.py`).
- Produces (used by Task 11): `NrlMatch`, `NrlRound`, `NrlMatchesResponse`, `LadderRow`, `LadderResponse`, `NrlRecord` types; `getNrlMatchesServer(revalidate?)`, `getNrlLadderServer()`, `getNrlRecordServer()`; `<ClubBadge name/>`, `<SportMatchCard match/>`, `<LadderTable rows compact?/>`.

- [ ] **Step 1: Types** — append to `frontend/lib/types.ts`:

```ts
/** /api/nrl/* shapes (backend/app/api/sports.py). */
export interface NrlPrediction {
  p_home: number;
  p_draw: number;
  p_away: number;
  expected_margin: number | null;
  model_version: string;
  created_at: string | null;
  is_shadow: boolean;
}
export interface NrlMatch {
  match_no: number;
  kickoff_utc: string | null;
  venue: string | null;
  home: string | null;
  away: string | null;
  score_home: number | null;
  score_away: number | null;
  status: string;
  prediction: NrlPrediction | null;
}
export interface NrlRound {
  round: number | null;
  matches: NrlMatch[];
}
export interface NrlMatchesResponse {
  season: number;
  rounds: NrlRound[];
}
export interface LadderRow {
  rank: number;
  team_id: number;
  name: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  points: number;
  diff: number;
}
export interface LadderResponse {
  season: number;
  rows: LadderRow[];
}
export interface NrlRecord {
  evaluated_matches: number;
  winner_accuracy: number | null;
  winner_accuracy_ci95: [number, number] | null;
  avg_log_loss: number | null;
  avg_brier: number | null;
  best_streak: number;
  model_version: string;
  last_updated: string | null;
}
```

- [ ] **Step 2: Server fetchers** — append to `frontend/lib/api.ts` (server components fetch the backend directly, like the existing server-side fetchers; `API_URL` is already module-scoped there):

```ts
/** Server-side NRL fetchers (ISR). Pages pass these straight to components. */
async function serverGet<T>(path: string, revalidate = 300): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { next: { revalidate } });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export const getNrlMatchesServer = () => serverGet<NrlMatchesResponse>("/api/nrl/matches");
export const getNrlLadderServer = () => serverGet<LadderResponse>("/api/nrl/ladder");
export const getNrlRecordServer = () => serverGet<NrlRecord>("/api/nrl/model/record");
```

(add `NrlMatchesResponse, LadderResponse, NrlRecord` to the type import block; if a `serverGet`-style helper already exists in the file, reuse it instead of adding a second one.)

- [ ] **Step 3: ClubBadge** — `frontend/components/ClubBadge.tsx`:

```tsx
/** NRL club monogram: 3-letter code on the club's primary color. Replaces the
 *  country <Flag/> in NRL cards. Unknown clubs fall back to initials on pitch. */
const CLUBS: Record<string, { code: string; color: string }> = {
  Broncos: { code: "BRI", color: "#6b1d45" },
  Raiders: { code: "CBR", color: "#95c11f" },
  Bulldogs: { code: "CBY", color: "#00539f" },
  Sharks: { code: "CRO", color: "#00a9d8" },
  Dolphins: { code: "DOL", color: "#c41e3a" },
  Titans: { code: "GLD", color: "#009fd9" },
  "Sea Eagles": { code: "MAN", color: "#7d0025" },
  Storm: { code: "MEL", color: "#4f2683" },
  Knights: { code: "NEW", color: "#003b73" },
  Cowboys: { code: "NQL", color: "#002d61" },
  Eels: { code: "PAR", color: "#006eb5" },
  Panthers: { code: "PEN", color: "#17181a" },
  Rabbitohs: { code: "SOU", color: "#0d5442" },
  Dragons: { code: "SGI", color: "#e02627" },
  Roosters: { code: "SYD", color: "#002b5c" },
  Warriors: { code: "WAR", color: "#151f6d" },
  "Wests Tigers": { code: "WST", color: "#f68b1f" },
};

export function ClubBadge({ name, size = 24 }: { name: string | null; size?: number }) {
  const club = name ? CLUBS[name] : undefined;
  const code = club?.code ?? (name ?? "?").slice(0, 3).toUpperCase();
  return (
    <span
      aria-hidden="true"
      className="grid shrink-0 place-items-center rounded-lg font-display font-bold text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.34,
        backgroundColor: club?.color ?? "hsl(var(--pitch))",
      }}
    >
      {code}
    </span>
  );
}
```

- [ ] **Step 4: SportMatchCard** — `frontend/components/SportMatchCard.tsx`:

```tsx
import { ClubBadge } from "@/components/ClubBadge";
import { ChanceChip } from "@/components/ChanceChip";
import type { NrlMatch } from "@/lib/types";

function kickoffLabel(iso: string | null): string {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleString("en-AU", {
    weekday: "short", hour: "numeric", minute: "2-digit",
  });
}

/** NRL fixture card: club badges + market-style chance chips + W/D/L bar.
 *  Mirrors MatchCard's anatomy; the draw segment is naturally small. */
export function SportMatchCard({ match, eyebrow }: { match: NrlMatch; eyebrow: string }) {
  const p = match.prediction;
  const finished = match.status === "finished";
  return (
    <div className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {eyebrow}
        </span>
        <span className={
          finished
            ? "rounded-full bg-surface-2/70 px-2.5 py-0.5 text-[11px] font-semibold text-muted"
            : "rounded-full bg-draw/15 px-2.5 py-0.5 text-[11px] font-semibold text-amber-ink"
        }>
          {finished ? "Full time" : kickoffLabel(match.kickoff_utc)}
        </span>
      </div>

      {(["home", "away"] as const).map((side) => {
        const name = side === "home" ? match.home : match.away;
        const score = side === "home" ? match.score_home : match.score_away;
        const prob = side === "home" ? p?.p_home : p?.p_away;
        const other = side === "home" ? p?.p_away : p?.p_home;
        return (
          <div key={side} className="mt-2 flex items-center gap-2.5">
            <ClubBadge name={name} />
            <span className="flex-1 font-display text-[15px] font-semibold">
              {name ?? "TBC"}
            </span>
            {finished ? (
              <span className="text-lg font-extrabold tabular-nums">{score}</span>
            ) : prob !== undefined && other !== undefined ? (
              <ChanceChip prob={prob} deltaText={null}
                          tone={prob >= other ? "up" : "muted"} />
            ) : null}
          </div>
        );
      })}

      {p ? (
        <div className="mt-3 flex h-2 gap-0.5" aria-hidden="true">
          <i className="rounded-full bg-win" style={{ width: `${p.p_home * 100}%` }} />
          <i className="rounded-full bg-draw" style={{ width: `${p.p_draw * 100}%` }} />
          <i className="rounded-full bg-loss" style={{ width: `${p.p_away * 100}%` }} />
        </div>
      ) : null}

      {p?.expected_margin != null && !finished ? (
        <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 text-xs text-muted">
          <span>Frozen at kickoff · graded after full time</span>
          <span className="rounded-lg bg-surface-2 px-2 py-0.5 font-bold tabular-nums text-foreground">
            <span className="mr-1 font-semibold text-muted">AI</span>
            margin {p.expected_margin > 0 ? "+" : ""}{p.expected_margin.toFixed(1)}
          </span>
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 5: LadderTable** — `frontend/components/LadderTable.tsx`:

```tsx
import { ClubBadge } from "@/components/ClubBadge";
import type { LadderRow } from "@/lib/types";

/** Standings table modeled on GroupTable; top-8 (finals) rows get the lime tint. */
export function LadderTable({ rows, compact = false }: { rows: LadderRow[]; compact?: boolean }) {
  const shown = compact ? rows.slice(0, 4) : rows;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
          <th className="py-1.5 pr-2 font-semibold">Club</th>
          <th className="py-1.5 text-right font-semibold">P</th>
          {!compact && <th className="py-1.5 text-right font-semibold">W–L–D</th>}
          <th className="py-1.5 text-right font-semibold">Diff</th>
          <th className="py-1.5 text-right font-semibold">Pts</th>
        </tr>
      </thead>
      <tbody>
        {shown.map((r) => (
          <tr key={r.team_id}
              className={r.rank <= 8 ? "border-t border-border bg-win/[0.06]" : "border-t border-border"}>
            <td className="flex items-center gap-2 py-2 pr-2">
              <span className="w-5 text-xs tabular-nums text-muted">{r.rank}</span>
              <ClubBadge name={r.name} size={20} />
              <span className="font-medium">{r.name}</span>
            </td>
            <td className="py-2 text-right tabular-nums">{r.played}</td>
            {!compact && (
              <td className="py-2 text-right tabular-nums">{r.wins}–{r.losses}–{r.draws}</td>
            )}
            <td className="py-2 text-right tabular-nums">{r.diff > 0 ? `+${r.diff}` : r.diff}</td>
            <td className="py-2 text-right font-bold tabular-nums">{r.points}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 6: Verify + commit**

Run: `cd frontend && npm run typecheck`
Expected: clean.

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/ClubBadge.tsx frontend/components/SportMatchCard.tsx frontend/components/LadderTable.tsx
git commit -m "feat: NRL types, fetchers and card/ladder components"
```

### Task 11: `/nrl` pages

**Files:**
- Create: `frontend/app/nrl/page.tsx`, `frontend/app/nrl/matches/page.tsx`, `frontend/app/nrl/ladder/page.tsx`, `frontend/app/nrl/record/page.tsx`

**Interfaces:**
- Consumes: Task 10 fetchers + components; `MoversPanel` (Task 5).
- Produces: the four NRL routes from the spec.

- [ ] **Step 1: NRL home** — `frontend/app/nrl/page.tsx`:

```tsx
import type { Metadata } from "next";
import Link from "next/link";
import { getNrlLadderServer, getNrlMatchesServer } from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";
import { MoversPanel } from "@/components/MoversPanel";
import { SportMatchCard } from "@/components/SportMatchCard";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "NRL predictions — FinalWhistle",
  description: "AI match predictions, ladder and model record for the NRL season.",
};

/** NRL home: current-round fixtures + mini ladder + movers. The "current"
 *  round is the first round containing a scheduled match (else the last). */
export default async function NrlHomePage() {
  const [fixtures, ladder] = await Promise.all([
    getNrlMatchesServer(),
    getNrlLadderServer().catch(() => null),
  ]);
  const current =
    fixtures.rounds.find((r) => r.matches.some((m) => m.status === "scheduled")) ??
    fixtures.rounds[fixtures.rounds.length - 1];

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL · Season {fixtures.season}</h1>
      <p className="mt-1 text-sm text-muted">
        Round {current?.round ?? "—"} · model predictions frozen at kickoff
      </p>

      <MoversPanel sport="nrl" />

      <div className="mt-6 grid gap-4 md:grid-cols-[1fr_320px]">
        <div className="grid gap-4">
          {(current?.matches ?? []).map((m) => (
            <SportMatchCard key={m.match_no} match={m} eyebrow={`Round ${current?.round}`} />
          ))}
        </div>
        {ladder ? (
          <div className="glass h-fit rounded-2xl p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
                Ladder
              </span>
              <Link href="/nrl/ladder" className="text-xs font-semibold text-lime-deep">
                Full ladder →
              </Link>
            </div>
            <LadderTable rows={ladder.rows} compact />
          </div>
        ) : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Matches page** — `frontend/app/nrl/matches/page.tsx`:

```tsx
import type { Metadata } from "next";
import { getNrlMatchesServer } from "@/lib/api";
import { SportMatchCard } from "@/components/SportMatchCard";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL fixtures — FinalWhistle" };

export default async function NrlMatchesPage() {
  const fixtures = await getNrlMatchesServer();
  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL fixtures</h1>
      {fixtures.rounds.map((round) => (
        <section key={String(round.round)} className="mt-8">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
            Round {round.round ?? "TBC"}
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {round.matches.map((m) => (
              <SportMatchCard key={m.match_no} match={m} eyebrow={`Round ${round.round}`} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Ladder page** — `frontend/app/nrl/ladder/page.tsx`:

```tsx
import type { Metadata } from "next";
import { getNrlLadderServer } from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL ladder — FinalWhistle" };

export default async function NrlLadderPage() {
  const ladder = await getNrlLadderServer();
  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">
        NRL ladder · Season {ladder.season}
      </h1>
      <p className="mt-1 text-sm text-muted">Top 8 qualify for the finals.</p>
      <div className="glass mt-6 rounded-2xl p-4">
        <LadderTable rows={ladder.rows} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Record page** — `frontend/app/nrl/record/page.tsx`:

```tsx
import type { Metadata } from "next";
import { getNrlRecordServer } from "@/lib/api";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL model record — FinalWhistle" };

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

/** Empty state per spec: predictions are frozen but nothing is graded until
 *  the first tracked round finishes. */
export default async function NrlRecordPage() {
  const rec = await getNrlRecordServer();

  if (rec.evaluated_matches === 0) {
    return (
      <div>
        <h1 className="font-display text-2xl font-extrabold">NRL model record</h1>
        <div className="panel-pitch mt-6 rounded-2xl p-6">
          <p className="font-display text-lg font-bold">Season live — grading starts soon</p>
          <p className="mt-2 max-w-lg text-sm text-white/75">
            Predictions are frozen at kickoff and graded after full time. The record
            appears once the first tracked round completes.
          </p>
          <p className="mt-4 text-xs text-white/50">Model {rec.model_version}</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL model record</h1>
      <p className="mt-1 text-sm text-muted">
        Model {rec.model_version} · {rec.evaluated_matches} graded matches
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Winner accuracy"
              value={rec.winner_accuracy != null ? `${(rec.winner_accuracy * 100).toFixed(1)}%` : "—"} />
        <Stat label="Log loss" value={rec.avg_log_loss?.toFixed(3) ?? "—"} />
        <Stat label="Brier" value={rec.avg_brier?.toFixed(3) ?? "—"} />
        <Stat label="Best streak" value={String(rec.best_streak)} />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify + commit**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: build succeeds, `/nrl/*` routes listed in the build output. With the backend running (`cd backend && uvicorn app.main:app`), `npm run dev` and click through `/nrl`, `/nrl/matches`, `/nrl/ladder`, `/nrl/record`, and the switcher both ways.

```bash
git add frontend/app/nrl
git commit -m "feat: NRL home, matches, ladder and record pages"
```

### Task 12: Full gate + branch push

**Files:** none new.

- [ ] **Step 1: Run everything**

```bash
cd frontend && npm run typecheck && npx jest && npm run build
cd ../backend && python -m pytest tests -q
cd .. && PYTHONPATH=backend:. python -m pytest pipeline -q
```

Expected: all green.

- [ ] **Step 2: Manual smoke** — with backend + frontend running: home shows MoversPanel (or skeleton→hidden if `/api/movers` has no data yet — deltas only appear after two daily pipeline runs); switcher swaps sports; mobile viewport shows pills + re-scoped tabs; `fw_sport=nrl` cookie lands `/` on `/nrl`.

- [ ] **Step 3: Push and open a PR** titled "Multi-sport navigation (NRL) + Midnight theme" referencing the spec; note in the PR body that movers deltas populate after the second daily refresh, and that the NRL 2020 ingest dedup bug is tracked separately.

---

## Self-Review Notes

- Spec coverage: token swap + component audit (T1), snapshots (T2–T3), movers endpoint/panel (T4–T5), chips+sparklines on match surfaces (T5–T6), sport config/switcher/cookie (T7–T8), ladder endpoint (T9), NRL types/components/pages incl. record empty state (T10–T11), gates (T12). Capacitor status-bar check is manual (T1 Step 4 / T12 Step 2) — flag any webview mismatch as a follow-up.
- Known discovery points are explicit commands, not hand-waves: football `Prediction` column names (T6), `alembic heads` (T2), `include_router` style (T4), nrl_predict session variable (T3).
- Type names are consistent across tasks (`Mover`, `NrlMatch`, `LadderRow`, `SportId`); `ChanceChip`/`Sparkline` defined in T5 and reused in T10–T11.
