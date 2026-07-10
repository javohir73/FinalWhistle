# NRL Match Intelligence — Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Wave 1 of the NRL Match Intelligence program — a margin+total prediction model, a rich per-match detail endpoint, 5,000-run finals (top-8/top-4/minor-premiership) projections, a deterministic prose preview generator, a "Match Intelligence" match page with an extensible section-slot architecture, `/nrl/round/[n]` round pages, and Top-8%/Top-4% ladder columns — on branch `feat/nrl-match-intel-w1`, with no new external data dependency.

**Architecture:** Extends the existing NRL vertical (`sport="nrl"` rows in `SportMatch`/`SportPrediction`, `ml.sports.nrl.model`'s Elo engine) rather than replacing it. A new, independently-fit margin+total regression (`ml/models/nrl_model_params.json`, version `nrl-elo-v0.2`) and a template-based prose generator are stamped onto `SportPrediction` at `nrl_predict --generate` time. A new backend module (`backend/app/api/nrl_intel.py`) exposes the rich per-match detail, finals projections, and an NRL probability-history endpoint. The frontend reuses and extends the **already-shipped** `/nrl/match/[season]/[round]/[no]/` detail page (see "Routing decision" below) with a client-island section renderer (`MatchIntelClient.tsx`) driven by an ordered `sections.ts` array, so Waves 2/3 can append sections (`stats`/`matchup`, `scorers`/`live`) by adding one array entry + one component file each, with zero edits to any Wave 1 component.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Alembic / numpy (already a backend dependency) on the backend; Next.js App Router (server components + `"use client"` islands), TypeScript, Tailwind (Midnight theme tokens) on the frontend; pytest + Jest/RTL for tests.

## Routing decision (read before touching any frontend file)

The spec's "Shared architecture" section describes a new route at `frontend/app/nrl/match/[id]/`. **This plan deliberately does not create that folder.** The repo already ships a fully built, tested NRL match detail page at `frontend/app/nrl/match/[season]/[round]/[no]/page.tsx` (committed on `main` in `118d2d8`), and every existing link into it — `SportMatchCard.tsx`, `frontend/app/nrl/team/[id]/page.tsx`, and their Jest tests — is hard-coded to the `/nrl/match/{season}/{round}/{match_no}` URL shape. A sibling `[id]/page.tsx` folder directly under `frontend/app/nrl/match/` would collide with Next.js's rule that dynamic segments at the same filesystem level must share one param name (`id` vs `season` is a hard build error), and repointing every existing link would touch several already-shipped, already-tested surfaces for no user-facing benefit.

Resolution: **keep the existing URL** (`/nrl/match/{season}/{round}/{match_no}`) and **extend the existing page file**. The frozen backend contract (`GET /api/nrl/matches/{id}`, and Wave 2/3's `/api/nrl/matches/{id}/stats` etc.) is still implemented **exactly as specified** — the numeric `id` is `SportMatch.id`, added to the existing `/api/nrl/matches` payload (Task 5/6 below) so the page can resolve `season/round/match_no → id` from data it already fetches, then call the new `{id}`-keyed endpoints. Every JSON contract in this plan matches the spec field-for-field; only the page's *folder name* differs from the spec's literal wording.

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

## Setup (before Task 1)

This plan assumes you are already inside the mandatory isolated worktree (per the program spec):

```bash
git worktree add /tmp/nrl-match-intel-w1 -b feat/nrl-match-intel-w1 origin/main
cd /tmp/nrl-match-intel-w1
ln -s "$(pwd)/../../frontend/node_modules" frontend/node_modules 2>/dev/null || true
# If the symlink target above doesn't resolve in your setup, symlink from the
# primary checkout's frontend/node_modules instead — any existing install is fine.
cat > frontend/.env.local <<'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
git reset frontend/node_modules
```

Run `cd backend && ../.venv/bin/alembic heads` (or `.venv/bin/alembic -c backend/alembic.ini heads` from repo root, depending on your venv layout) before Task 1 and confirm the single head is still `b3c4d5e6f7a9`. If it isn't (main moved), rebase Task 1's migration's `down_revision` onto the new head.

---

### Task 1: Schema — margin/total/preview columns + `nrl_projections` table

**Files:**
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/d2e3f4a5b6c7_nrl_match_intel_w1.py`
- Test: `backend/tests/test_nrl_intel_schema.py`

**Interfaces:**
- Produces: `SportPrediction.predicted_margin: float | None`, `SportPrediction.predicted_total: float | None`, `SportPrediction.preview_text: str | None` (new, additive columns — the pre-existing `expected_margin` column is untouched). `NrlProjection` ORM class (`app.models.NrlProjection`): `id, team: str, top8: float, top4: float, minor_premiership: float, computed_at: datetime`.
- Consumes: nothing (first task).

- [ ] **Step 1: Write the failing schema test**

Create `backend/tests/test_nrl_intel_schema.py`:

```python
"""Round-trip tests for Wave 1's schema additions: three new columns on
sport_predictions (predicted_margin, predicted_total, preview_text) and the
nrl_projections table. Uses the same local in-memory SQLite pattern as
backend/tests/test_sports_api.py -- Base.metadata.create_all picks up the
model changes directly, so these tests fail until app/models/__init__.py is
updated (no alembic run needed for SQLite-backed tests)."""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import NrlProjection, SportMatch, SportPrediction, SportTeam


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_sport_prediction_round_trips_margin_total_preview():
    db = _session()
    home = SportTeam(sport="nrl", name="Storm")
    away = SportTeam(sport="nrl", name="Eels")
    db.add_all([home, away]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()

    pred = SportPrediction(
        match_id=m.id, model_version="nrl-elo-v0.1",
        p_home=0.6, p_draw=0.01, p_away=0.39, expected_margin=3.0,
        predicted_margin=4.2, predicted_total=41.5,
        preview_text="Storm are the model's pick.",
    )
    db.add(pred); db.commit()

    reloaded = db.query(SportPrediction).one()
    assert reloaded.predicted_margin == 4.2
    assert reloaded.predicted_total == 41.5
    assert reloaded.preview_text == "Storm are the model's pick."


def test_sport_prediction_new_columns_are_nullable():
    db = _session()
    home = SportTeam(sport="nrl", name="Storm")
    away = SportTeam(sport="nrl", name="Eels")
    db.add_all([home, away]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()

    pred = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            p_home=0.5, p_draw=0.01, p_away=0.49, expected_margin=0.0)
    db.add(pred); db.commit()

    reloaded = db.query(SportPrediction).one()
    assert reloaded.predicted_margin is None
    assert reloaded.predicted_total is None
    assert reloaded.preview_text is None


def test_nrl_projection_round_trips():
    db = _session()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    db.add(NrlProjection(team="Storm", top8=0.91, top4=0.42, minor_premiership=0.05,
                          computed_at=now))
    db.commit()

    row = db.query(NrlProjection).one()
    assert row.team == "Storm"
    assert row.top8 == 0.91
    assert row.top4 == 0.42
    assert row.minor_premiership == 0.05
    assert row.computed_at == now
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_nrl_intel_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'NrlProjection' from 'app.models'` (or a `TypeError` on the unexpected `predicted_margin` kwarg).

- [ ] **Step 3: Add the columns and the new model**

In `backend/app/models/__init__.py`, add `Text` to the sqlalchemy import (it currently reads `from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, false, func, true,)`):

```python
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
```

Extend `SportPrediction` (currently ends at `is_shadow`):

```python
class SportPrediction(Base):
    __tablename__ = "sport_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    expected_margin: Mapped[float | None] = mapped_column(Float)
    # Wave 1 (NRL Match Intelligence): predicted_margin/predicted_total come
    # from the separately-fit ml.models.nrl_margin_total model (version
    # "nrl-elo-v0.2"), NOT from expected_margin (ml.sports.nrl.model's own
    # win-probability-model margin estimate, kept as-is so existing consumers
    # like SportMatchCard don't change shape). preview_text is the
    # deterministic prose preview, regenerated every nrl_predict --generate run.
    predicted_margin: Mapped[float | None] = mapped_column(Float)
    predicted_total: Mapped[float | None] = mapped_column(Float)
    preview_text: Mapped[str | None] = mapped_column(Text)
    # New verticals ship shadow-only until proven (mirrors predictions.is_shadow);
    # server_default so raw inserts (e.g. backfills) default true too.
    is_shadow: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
```

Add a new class directly after `SportPredictionResult` (before `ProbabilitySnapshot`):

```python
class NrlProjection(Base):
    """Finals-projection snapshot (Wave 1): one row per team, fully replaced
    each nrl-refresh run by pipeline/sports/nrl_projections.py -- delete-then-
    insert at table granularity (no unique constraint needed, unlike
    ProbabilitySnapshot's per-day key) since every refresh replaces the whole
    table atomically."""
    __tablename__ = "nrl_projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    top8: Mapped[float] = mapped_column(Float)
    top4: Mapped[float] = mapped_column(Float)
    minor_premiership: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Add `"NrlProjection"` to the `__all__` list at the bottom (after `"SportPredictionResult"`, before `"ProbabilitySnapshot"`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_nrl_intel_schema.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the Alembic migration**

Create `backend/alembic/versions/d2e3f4a5b6c7_nrl_match_intel_w1.py`:

```python
"""NRL match intelligence (Wave 1): margin/total/preview columns on
sport_predictions, and the nrl_projections finals table.

Wave 1 needs three additive columns for its own margin+total model output
(predicted_margin, predicted_total) and its deterministic prose generator
(preview_text) -- kept separate from the pre-existing expected_margin column,
which is the older Elo model's own margin estimate and stays untouched so
existing consumers (SportMatchCard, the NRL match page) don't change shape.
nrl_projections is a small, fully-replaced-each-refresh table (mirrors
probability_snapshots' delete-then-insert idiom) for the 5,000-run Monte
Carlo finals simulation: one row per team per refresh.

Revision ID: d2e3f4a5b6c7
Revises: b3c4d5e6f7a9
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "b3c4d5e6f7a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sport_predictions", sa.Column("predicted_margin", sa.Float(), nullable=True))
    op.add_column("sport_predictions", sa.Column("predicted_total", sa.Float(), nullable=True))
    op.add_column("sport_predictions", sa.Column("preview_text", sa.Text(), nullable=True))

    op.create_table(
        "nrl_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("top8", sa.Float(), nullable=False),
        sa.Column("top4", sa.Float(), nullable=False),
        sa.Column("minor_premiership", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_nrl_projections_team", "nrl_projections", ["team"])


def downgrade() -> None:
    op.drop_index("ix_nrl_projections_team", table_name="nrl_projections")
    op.drop_table("nrl_projections")
    op.drop_column("sport_predictions", "preview_text")
    op.drop_column("sport_predictions", "predicted_total")
    op.drop_column("sport_predictions", "predicted_margin")
```

There is no automated test for the migration file itself (this repo's test suite always runs against `Base.metadata.create_all` on ephemeral SQLite — see every file under `backend/tests/`); the schema behavior is already covered by Step 1-4's tests. As a manual sanity check only (skip if you have no local Postgres/DATABASE_URL configured):

Run: `cd backend && ../.venv/bin/alembic upgrade head`
Expected: no errors; ends on revision `d2e3f4a5b6c7`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/d2e3f4a5b6c7_nrl_match_intel_w1.py backend/tests/test_nrl_intel_schema.py
git commit -m "feat: add nrl margin/total/preview columns and nrl_projections table"
```

---

### Task 2: Margin + total model — fitting script and loader

**Files:**
- Create: `ml/models/nrl_margin_total.py`
- Create: `pipeline/sports/nrl_margin_total_fit.py`
- Test: `ml/models/nrl_margin_total_test.py`
- Test: `pipeline/sports/nrl_margin_total_fit_test.py`

**Interfaces:**
- Consumes: `ml.sports.nrl.model.{regress_season, update}`, `ml.sports.nrl.params.load_nrl_params` (existing).
- Produces: `NrlMarginTotalParams` dataclass (`version, margin_coef_elo_diff, margin_intercept, expected_total`); `load_margin_total_params() -> NrlMarginTotalParams`; `save_margin_total_params(params) -> None`; `predict_margin_total(elo_home, elo_away, p=None) -> tuple[float, float]` (returns `(predicted_margin, predicted_total)`, home-minus-away sign convention). `collect_training_rows(matches) -> list[tuple[float, float]]`, `fit_margin(rows) -> tuple[float, float]`, `fit_expected_total(matches_by_season) -> float` — used by Task 3 (`nrl_predict.py` imports `predict_margin_total`/`load_margin_total_params`).

- [ ] **Step 1: Write the failing loader test**

Create `ml/models/nrl_margin_total_test.py`:

```python
"""Tests for the Wave 1 margin+total params loader (ml/models/nrl_margin_total.py)."""
import json

import ml.models.nrl_margin_total as mod
from ml.models.nrl_margin_total import (
    NrlMarginTotalParams,
    load_margin_total_params,
    predict_margin_total,
    save_margin_total_params,
)


def test_missing_file_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_PARAMS_FILE", tmp_path / "absent.json")
    assert load_margin_total_params() == NrlMarginTotalParams()


def test_invalid_json_falls_back_to_defaults(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    f.write_text("not json")
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    assert load_margin_total_params() == NrlMarginTotalParams()


def test_missing_field_falls_back_to_defaults(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"version": "nrl-elo-v0.2"}))  # no margin_coef_elo_diff etc.
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    assert load_margin_total_params() == NrlMarginTotalParams()


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    tuned = NrlMarginTotalParams(
        version="nrl-elo-v0.2", margin_coef_elo_diff=0.0512,
        margin_intercept=4.6, expected_total=39.8,
    )
    save_margin_total_params(tuned)
    assert load_margin_total_params() == tuned


def test_saved_file_is_indented_json_with_trailing_newline(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    save_margin_total_params(NrlMarginTotalParams())
    text = f.read_text()
    assert text.endswith("\n")
    assert "  " in text


def test_predict_margin_total_applies_intercept_and_slope():
    p = NrlMarginTotalParams(version="nrl-elo-v0.2", margin_coef_elo_diff=0.05,
                              margin_intercept=4.0, expected_total=40.0)
    margin, total = predict_margin_total(1550.0, 1500.0, p)
    assert margin == 0.05 * 50 + 4.0
    assert total == 40.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest ml/models/nrl_margin_total_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.models.nrl_margin_total'`

- [ ] **Step 3: Write the loader**

Create `ml/models/nrl_margin_total.py`:

```python
"""Loader for Wave 1's NRL margin+total model (predicted_margin/predicted_total
on SportPrediction). Mirrors ml/sports/nrl/params.py's load/save pattern:
pipeline/sports/nrl_margin_total_fit.py's least-squares fit writes this file;
everything that serves predicted_margin/predicted_total loads through
load_margin_total_params so a missing/corrupt file never breaks serving --
it falls back to NrlMarginTotalParams()'s hand-set v0.1 defaults, exactly
like ml.sports.nrl.params falls back to NrlParams().

Distinct from ml/sports/nrl/params.py (the win-probability Elo model): that
module tunes NrlParams (k, home_adv in Elo points, margin_slope -- the
existing `expected_margin` field's source). This module fits a SEPARATE
margin+total regression (predicted_margin/predicted_total, version
"nrl-elo-v0.2") that Wave 1 adds to the detail endpoint and the prose preview.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_PARAMS_FILE = Path(__file__).with_name("nrl_model_params.json")


@dataclass(frozen=True)
class NrlMarginTotalParams:
    version: str = "nrl-elo-v0.1"
    margin_coef_elo_diff: float = 0.045  # points per Elo-diff point (matches
                                          # ml.sports.nrl.model's own margin_slope
                                          # default until the real fit runs)
    margin_intercept: float = 4.0        # fitted home advantage, in POINTS
    expected_total: float = 40.0         # recency-weighted league scoring mean


def load_margin_total_params() -> NrlMarginTotalParams:
    """Load fitted params from nrl_model_params.json, or the v0.1 defaults if
    missing, corrupt, or missing a field."""
    try:
        data = json.loads(_PARAMS_FILE.read_text())
        return NrlMarginTotalParams(
            version=data.get("version", NrlMarginTotalParams().version),
            margin_coef_elo_diff=float(data["margin_coef_elo_diff"]),
            margin_intercept=float(data["margin_intercept"]),
            expected_total=float(data["expected_total"]),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return NrlMarginTotalParams()


def save_margin_total_params(params: NrlMarginTotalParams) -> None:
    _PARAMS_FILE.write_text(json.dumps(asdict(params), indent=2) + "\n")


def predict_margin_total(
    elo_home: float, elo_away: float, p: NrlMarginTotalParams | None = None
) -> tuple[float, float]:
    """Return (predicted_margin, predicted_total) for a fixture's pre-match
    Elo ratings. predicted_margin is home-minus-away points (same sign
    convention as SportMatch.score_home - score_away and the existing
    `expected_margin` field); predicted_total does not depend on Elo."""
    p = p or load_margin_total_params()
    margin = p.margin_coef_elo_diff * (elo_home - elo_away) + p.margin_intercept
    return margin, p.expected_total
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest ml/models/nrl_margin_total_test.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write the failing fitting-script test**

Create `pipeline/sports/nrl_margin_total_fit_test.py`:

```python
"""Tests for pipeline/sports/nrl_margin_total_fit.py -- the least-squares
margin~elo_diff+home_advantage fit and the recency-weighted total mean."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_margin_total_fit import (
    collect_training_rows,
    fit_expected_total,
    fit_margin,
)


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t); db.flush()
    return t


def _match(db, home, away, season, no, kickoff, score_home, score_away):
    m = SportMatch(sport="nrl", season=season, round=1, match_no=no,
                   kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                   score_home=score_home, score_away=score_away, status="finished")
    db.add(m); db.flush()
    return m


def test_fit_margin_recovers_a_known_linear_relationship():
    """Construct (elo_diff, margin) pairs that exactly satisfy
    margin = 0.04 * elo_diff + 3.0, then check OLS recovers those coefficients."""
    rows = [(d, 0.04 * d + 3.0) for d in (-200.0, -100.0, 0.0, 100.0, 200.0, 300.0)]
    coef, intercept = fit_margin(rows)
    assert abs(coef - 0.04) < 1e-9
    assert abs(intercept - 3.0) < 1e-9


def test_fit_margin_empty_input_returns_zeros():
    assert fit_margin([]) == (0.0, 0.0)


def test_collect_training_rows_uses_pre_match_elo_not_post_match(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    k1 = datetime(2017, 3, 1, tzinfo=timezone.utc)
    k2 = datetime(2017, 3, 8, tzinfo=timezone.utc)
    _match(db_session, home, away, 2017, 1, k1, 30, 10)   # home blowout win
    _match(db_session, home, away, 2017, 2, k2, 10, 30)   # away blowout win
    db_session.commit()

    matches = db_session.query(SportMatch).all()
    rows = collect_training_rows(matches)

    assert len(rows) == 2
    # Both teams start at 1500 -> the FIRST match's elo_diff must be 0
    # regardless of that match's own (leaked) result.
    assert rows[0][0] == 0.0
    assert rows[0][1] == 20.0  # 30 - 10
    # The second match's elo_diff reflects the FIRST match's outcome only.
    assert rows[1][0] != 0.0
    assert rows[1][1] == -20.0  # 10 - 30


def test_fit_expected_total_weights_latest_season_2to1():
    by_season = {
        2024: [SimpleNamespace(score_home=20, score_away=20)],  # total 40
        2025: [SimpleNamespace(score_home=25, score_away=25)],  # total 50
    }
    total = fit_expected_total(by_season)
    assert abs(total - ((2 * 50 + 40) / 3)) < 1e-9


def test_fit_expected_total_single_season_uses_its_mean():
    by_season = {2025: [SimpleNamespace(score_home=20, score_away=24)]}
    assert fit_expected_total(by_season) == 44.0


def test_fit_expected_total_no_data_falls_back_to_default():
    from ml.models.nrl_margin_total import NrlMarginTotalParams
    assert fit_expected_total({}) == NrlMarginTotalParams().expected_total
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_margin_total_fit_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_margin_total_fit'`

- [ ] **Step 7: Write the fitting script**

Create `pipeline/sports/nrl_margin_total_fit.py`:

```python
"""Fit the NRL margin+total model (Wave 1): expected margin as elo_diff +
home advantage via ordinary least squares over every completed 2017-2025
nrl match, expected total as a recency-weighted (2:1) league scoring mean
over the two most recent seasons present. Writes the result to
ml/models/nrl_model_params.json via ml.models.nrl_margin_total.save_margin_total_params.

Independent of ml/sports/nrl/model.py's own margin_slope (the win-probability
Elo model's built-in margin estimate, used for the existing `expected_margin`
field) -- this is a separate, explicitly-fit model (version "nrl-elo-v0.2")
stamped onto SportPrediction.predicted_margin/predicted_total by
pipeline/sports/nrl_predict.py's generate().

CLI: PYTHONPATH=backend:. python -m pipeline.sports.nrl_margin_total_fit
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models import SportMatch
from ml.models.nrl_margin_total import NrlMarginTotalParams, save_margin_total_params
from ml.sports.nrl.model import regress_season, update
from ml.sports.nrl.params import load_nrl_params

log = logging.getLogger(__name__)

SPORT = "nrl"
MIN_SEASON = 2017
MAX_SEASON = 2025


def _kickoff_key(m: SportMatch) -> tuple:
    return (m.kickoff_utc is None, m.kickoff_utc or datetime.min, m.id)


def collect_training_rows(matches: list[SportMatch]) -> list[tuple[float, float]]:
    """Replay Elo chronologically (mirrors pipeline.sports.nrl_predict._current_elos)
    and return (pre_match_elo_diff, actual_margin) pairs for every match in
    [MIN_SEASON, MAX_SEASON] -- pre-match state only, never post-match, so the
    regression never leaks the outcome it's predicting."""
    params = load_nrl_params()
    ordered = sorted(matches, key=_kickoff_key)
    elos: dict[int, float] = {}
    current_season: int | None = None
    rows: list[tuple[float, float]] = []

    for m in ordered:
        if current_season is not None and m.season != current_season:
            elos = regress_season(elos, params)
        current_season = m.season

        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        if MIN_SEASON <= m.season <= MAX_SEASON:
            rows.append((elo_home - elo_away, float(m.score_home - m.score_away)))

        new_home, new_away = update(elo_home, elo_away, m.score_home, m.score_away, params)
        elos[m.home_team_id] = new_home
        elos[m.away_team_id] = new_away

    return rows


def fit_margin(rows: list[tuple[float, float]]) -> tuple[float, float]:
    """Least squares margin ~ elo_diff + home_advantage. Returns
    (margin_coef_elo_diff, margin_intercept); the intercept is the fitted
    home-advantage in POINTS. Design matrix X = [elo_diff, 1]."""
    if not rows:
        return 0.0, 0.0
    elo_diffs = np.array([r[0] for r in rows], dtype=float)
    margins = np.array([r[1] for r in rows], dtype=float)
    X = np.column_stack([elo_diffs, np.ones_like(elo_diffs)])
    coef, *_ = np.linalg.lstsq(X, margins, rcond=None)
    return float(coef[0]), float(coef[1])


def fit_expected_total(matches_by_season: dict) -> float:
    """Recency-weighted league scoring mean: the two most recent seasons
    present, most-recent weighted 2:1 over the second-most-recent. Falls back
    to a single season's mean (weight 1) if only one is present, or the
    NrlMarginTotalParams default if none."""
    seasons = sorted(matches_by_season)
    if not seasons:
        return NrlMarginTotalParams().expected_total

    def season_mean(season) -> float | None:
        totals = [
            m.score_home + m.score_away for m in matches_by_season[season]
            if m.score_home is not None and m.score_away is not None
        ]
        return sum(totals) / len(totals) if totals else None

    latest = season_mean(seasons[-1])
    if latest is None:
        return NrlMarginTotalParams().expected_total
    if len(seasons) < 2:
        return latest
    prev = season_mean(seasons[-2])
    if prev is None:
        return latest
    return (2 * latest + prev) / 3


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal

    db: Session = SessionLocal()
    try:
        finished = (
            db.query(SportMatch)
            .filter(SportMatch.sport == SPORT, SportMatch.status == "finished")
            .all()
        )
        if not finished:
            log.warning("no finished nrl matches in the DB -- nothing to fit")
            return 1

        rows = collect_training_rows(finished)
        coef, intercept = fit_margin(rows)

        by_season: dict[int, list[SportMatch]] = {}
        for m in finished:
            by_season.setdefault(m.season, []).append(m)
        expected_total = fit_expected_total(by_season)

        params = NrlMarginTotalParams(
            version="nrl-elo-v0.2",
            margin_coef_elo_diff=coef,
            margin_intercept=intercept,
            expected_total=expected_total,
        )
        save_margin_total_params(params)
        log.info(
            "fit %d matches: margin_coef_elo_diff=%.5f margin_intercept=%.2f expected_total=%.2f",
            len(rows), coef, intercept, expected_total,
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_margin_total_fit_test.py -v`
Expected: PASS (6 tests)

- [ ] **Step 9: Produce the committed params file**

If your environment has network access and a DB you can write to, ingest history and run the fit for real so `ml/models/nrl_model_params.json` ships with genuinely fitted numbers (mirrors how `ml/sports/nrl/params.json`'s checked-in values were produced):

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_ingest --seasons 2017 2026
PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_margin_total_fit
```

Expected: `ml/models/nrl_model_params.json` is created/updated with `"version": "nrl-elo-v0.2"` and real numbers (sanity check: `margin_coef_elo_diff` positive, `expected_total` roughly 30-50). If your sandbox has no network/DB access, skip this step — `load_margin_total_params()`'s v0.1 defaults keep everything downstream working, and whoever runs the `nrl-refresh` pipeline in an environment with real data can run this command later; commit whatever `ml/models/nrl_model_params.json` state you have (present or absent) as-is.

- [ ] **Step 10: Commit**

```bash
git add ml/models/nrl_margin_total.py ml/models/nrl_margin_total_test.py \
        pipeline/sports/nrl_margin_total_fit.py pipeline/sports/nrl_margin_total_fit_test.py
git add ml/models/nrl_model_params.json 2>/dev/null || true
git commit -m "feat: fit NRL margin+total model (nrl-elo-v0.2) with loader"
```

---

### Task 3: Form helper + prose preview generator + wire into `nrl_predict`

**Files:**
- Create: `pipeline/sports/nrl_form.py`
- Create: `ml/models/nrl_preview.py`
- Modify: `pipeline/sports/nrl_predict.py`
- Test: `pipeline/sports/nrl_form_test.py`
- Test: `ml/models/nrl_preview_test.py`
- Modify: `pipeline/sports/nrl_predict_test.py`

**Interfaces:**
- Consumes: Task 2's `ml.models.nrl_margin_total.{predict_margin_total, load_margin_total_params}`.
- Produces: `pipeline.sports.nrl_form.last_n_results(db, team_id, n=5, before=None) -> list[dict]` (each `{round, opponent_id, for, against, result, kickoff_utc}`), `pipeline.sports.nrl_form.form_averages(results) -> dict` (`{avg_for, avg_against, avg_margin}`) — Task 5's `backend/app/api/nrl_intel.py` imports both. `ml.models.nrl_preview.build_preview(**kwargs) -> str`. `SportPrediction` rows written by `generate()` now always carry `predicted_margin`, `predicted_total`, `preview_text`.

- [ ] **Step 1: Write the failing form-helper test**

Create `pipeline/sports/nrl_form_test.py`:

```python
"""Tests for pipeline/sports/nrl_form.py -- shared 'last N finished results
for one team' helper used by both the offline preview generator
(nrl_predict.py) and the online detail endpoint (nrl_intel.py)."""
from datetime import datetime, timezone

from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_form import form_averages, last_n_results


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t); db.flush()
    return t


def _match(db, home, away, no, kickoff, sh, sa, round_=1, status="finished"):
    m = SportMatch(sport="nrl", season=2026, round=round_, match_no=no,
                   kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                   score_home=sh, score_away=sa, status=status)
    db.add(m); db.flush()
    return m


def test_last_n_results_orders_most_recent_first_and_limits(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    for i in range(1, 8):
        _match(db_session, home, away, i, datetime(2026, 1, i, tzinfo=timezone.utc), 20, 10)
    db_session.commit()

    results = last_n_results(db_session, home.id, n=5)

    assert len(results) == 5
    assert [r["kickoff_utc"].day for r in results] == [7, 6, 5, 4, 3]
    assert all(r["result"] == "W" for r in results)


def test_last_n_results_computes_correct_side_perspective(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), 10, 24)
    db_session.commit()

    away_results = last_n_results(db_session, away.id, n=5)
    assert away_results[0]["for"] == 24
    assert away_results[0]["against"] == 10
    assert away_results[0]["result"] == "W"
    assert away_results[0]["opponent_id"] == home.id


def test_last_n_results_before_excludes_later_matches(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    m1 = _match(db_session, home, away, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), 20, 10)
    m2 = _match(db_session, home, away, 2, datetime(2026, 1, 8, tzinfo=timezone.utc), 12, 30)
    db_session.commit()

    results = last_n_results(db_session, home.id, n=5, before=m2)
    assert len(results) == 1
    assert results[0]["for"] == 20


def test_last_n_results_skips_unfinished_matches(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), None, None,
           status="scheduled")
    db_session.commit()
    assert last_n_results(db_session, home.id) == []


def test_form_averages_computes_rounded_means():
    results = [
        {"for": 20, "against": 10}, {"for": 10, "against": 20}, {"for": 30, "against": 12},
    ]
    avgs = form_averages(results)
    assert avgs["avg_for"] == round((20 + 10 + 30) / 3, 1)
    assert avgs["avg_against"] == round((10 + 20 + 12) / 3, 1)
    assert avgs["avg_margin"] == round(((20 - 10) + (10 - 20) + (30 - 12)) / 3, 1)


def test_form_averages_empty_is_zeroed():
    assert form_averages([]) == {"avg_for": 0.0, "avg_against": 0.0, "avg_margin": 0.0}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_form_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_form'`

- [ ] **Step 3: Write the form helper**

Create `pipeline/sports/nrl_form.py`:

```python
"""Shared 'last N finished results for one NRL team' helper. Used by both the
offline preview-text generator (pipeline/sports/nrl_predict.py) and the
online match-detail endpoint (backend/app/api/nrl_intel.py) so the two never
disagree on what "recent form" means.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import SportMatch

SPORT = "nrl"


def _kickoff_key(m: SportMatch) -> tuple:
    return (m.kickoff_utc is None, m.kickoff_utc or datetime.min, m.id)


def last_n_results(
    db: Session, team_id: int, n: int = 5, before: SportMatch | None = None
) -> list[dict]:
    """Most recent `n` FINISHED matches for `team_id`, most recent first. Each
    row: {round, opponent_id, for, against, result: "W"|"L"|"D", kickoff_utc}.
    `before`: when given, only matches strictly earlier than its kickoff
    (falls back to id ordering for same/null kickoff) are eligible -- lets a
    fixture compute its own pre-match form without seeing itself or later
    matches.
    """
    matches = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT,
            SportMatch.status == "finished",
            SportMatch.score_home.isnot(None),
            SportMatch.score_away.isnot(None),
            or_(SportMatch.home_team_id == team_id, SportMatch.away_team_id == team_id),
        )
        .all()
    )
    if before is not None:
        cutoff = _kickoff_key(before)
        matches = [m for m in matches if _kickoff_key(m) < cutoff]
    matches.sort(key=_kickoff_key, reverse=True)
    matches = matches[:n]

    out = []
    for m in matches:
        was_home = m.home_team_id == team_id
        sf, sa = (m.score_home, m.score_away) if was_home else (m.score_away, m.score_home)
        result = "W" if sf > sa else "L" if sf < sa else "D"
        out.append({
            "round": m.round,
            "opponent_id": m.away_team_id if was_home else m.home_team_id,
            "for": sf,
            "against": sa,
            "result": result,
            "kickoff_utc": m.kickoff_utc,
        })
    return out


def form_averages(results: list[dict]) -> dict:
    """avg_for/avg_against/avg_margin over `results` (empty -> zeros)."""
    if not results:
        return {"avg_for": 0.0, "avg_against": 0.0, "avg_margin": 0.0}
    n = len(results)
    total_for = sum(r["for"] for r in results)
    total_against = sum(r["against"] for r in results)
    return {
        "avg_for": round(total_for / n, 1),
        "avg_against": round(total_against / n, 1),
        "avg_margin": round((total_for - total_against) / n, 1),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_form_test.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write the failing preview-generator test**

Create `ml/models/nrl_preview_test.py`:

```python
"""Tests for the deterministic NRL prose preview generator (no LLM at
runtime -- pure string formatting from model numbers)."""
from ml.models.nrl_preview import build_preview


def _preview(**overrides):
    base = dict(
        home="Storm", away="Eels", p_home=0.63, p_away=0.37,
        elo_home=1560.0, elo_away=1490.0,
        home_form_summary="4W-1L in their last 5",
        away_form_summary="2W-3L in their last 5",
        predicted_margin=6.5, predicted_total=41.0,
    )
    base.update(overrides)
    return build_preview(**base)


def test_returns_three_paragraphs():
    text = _preview()
    paragraphs = text.split("\n\n")
    assert len(paragraphs) == 3


def test_names_the_favourite_and_probability():
    text = _preview()
    assert "Storm" in text.split("\n\n")[0]
    assert "63%" in text.split("\n\n")[0]


def test_names_the_elo_leader_and_gap():
    text = _preview()
    assert "70" in text.split("\n\n")[1]  # 1560 - 1490
    assert "Storm" in text.split("\n\n")[1]


def test_includes_both_form_summaries():
    text = _preview()
    p2 = text.split("\n\n")[1]
    assert "4W-1L in their last 5" in p2
    assert "2W-3L in their last 5" in p2


def test_margin_and_total_paragraph():
    text = _preview()
    p3 = text.split("\n\n")[2]
    assert "Storm by 6.5" in p3
    assert "41" in p3


def test_negative_margin_credits_the_away_side():
    text = _preview(predicted_margin=-3.2)
    p3 = text.split("\n\n")[2]
    assert "Eels by 3.2" in p3


def test_zero_margin_reads_as_dead_level():
    text = _preview(predicted_margin=0.0)
    p3 = text.split("\n\n")[2]
    assert "dead-level" in p3
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest ml/models/nrl_preview_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.models.nrl_preview'`

- [ ] **Step 7: Write the preview generator**

Create `ml/models/nrl_preview.py`:

```python
"""Deterministic prose preview generator for the NRL Match Intelligence page
(Wave 1). No LLM at runtime -- three short paragraphs built purely from the
model's own numbers (favourite + probability, Elo gap, form lines, predicted
margin/total). Regenerated every nrl_predict --generate run and stamped onto
SportPrediction.preview_text (see pipeline/sports/nrl_predict.py).
"""
from __future__ import annotations


def build_preview(
    *,
    home: str,
    away: str,
    p_home: float,
    p_away: float,
    elo_home: float,
    elo_away: float,
    home_form_summary: str,
    away_form_summary: str,
    predicted_margin: float,
    predicted_total: float,
) -> str:
    """Three short paragraphs, joined by a blank line. Pure function of the
    inputs -- no DB/network access, so it's trivially unit-testable and safe
    to call from any pipeline step."""
    favourite = home if p_home >= p_away else away
    fav_prob = max(p_home, p_away)
    elo_gap = abs(elo_home - elo_away)
    elo_leader = home if elo_home >= elo_away else away
    elo_trailer = away if elo_leader == home else home

    p1 = (
        f"{favourite} are the model's pick, given a {round(fav_prob * 100)}% "
        f"chance heading into this one."
    )
    p2 = (
        f"{elo_leader} carry the bigger Elo rating, {round(elo_gap)} points clear "
        f"of {elo_trailer}. {home}: {home_form_summary}. {away}: {away_form_summary}."
    )
    side = home if predicted_margin > 0 else away if predicted_margin < 0 else None
    margin_txt = (
        f"{side} by {abs(round(predicted_margin, 1))}" if side else "a dead-level margin"
    )
    p3 = (
        f"The model's number: {margin_txt}, with a total of "
        f"{round(predicted_total)} points across both sides."
    )
    return "\n\n".join([p1, p2, p3])
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest ml/models/nrl_preview_test.py -v`
Expected: PASS (7 tests)

- [ ] **Step 9: Write the failing wiring test**

Append to `pipeline/sports/nrl_predict_test.py` (after the existing tests, before `PARAMS = NrlParams()` usage elsewhere — just add at the end of the file):

```python
# ---- generate: Wave 1 margin/total/preview stamping ----

def test_generate_stamps_predicted_margin_total_and_preview(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
           status="finished", score_home=20, score_away=16)
    _match(db_session, home, away, 2026, 2, _kickoff(2026, 3, 8), status="scheduled")

    generate(db_session, PARAMS)

    # Only the scheduled fixture gets a prediction row (the finished match is
    # frozen and never written to) -- one row, so the latest by id is it.
    row = db_session.query(SportPrediction).order_by(SportPrediction.id.desc()).first()
    assert row.predicted_margin is not None
    assert row.predicted_total is not None
    assert row.preview_text is not None
    assert "\n\n" in row.preview_text
    assert home_or_away_name_present(row.preview_text)


def home_or_away_name_present(text: str) -> bool:
    return "Broncos" in text or "Storm" in text


def test_generate_preview_text_survives_a_team_with_no_prior_form(db_session):
    """A brand-new matchup (no finished history for either side) must still
    produce a preview -- last_n_results returns [] and the summary degrades
    gracefully rather than raising."""
    home = _team(db_session, "Dolphins")
    away = _team(db_session, "Titans")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1), status="scheduled")

    generate(db_session, PARAMS)

    row = db_session.query(SportPrediction).one()
    assert row.preview_text is not None
    assert "no recent form on record" in row.preview_text
```

- [ ] **Step 10: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_predict_test.py -v -k "predicted_margin_total_and_preview or no_prior_form"`
Expected: FAIL — `AssertionError: assert None is not None` (columns not yet populated)

- [ ] **Step 11: Wire the new modules into `generate()`**

In `pipeline/sports/nrl_predict.py`, add imports (after the existing `from ml.sports.nrl.params import load_nrl_params` line):

```python
from ml.models.nrl_margin_total import load_margin_total_params, predict_margin_total
from ml.models.nrl_preview import build_preview
from pipeline.sports.nrl_form import last_n_results
```

Replace `_write_prediction`'s `db.add(SportPrediction(...))` call with:

```python
    db.add(SportPrediction(
        match_id=match.id,
        model_version=params.version,
        p_home=out["p_home"],
        p_draw=out["p_draw"],
        p_away=out["p_away"],
        expected_margin=out["expected_margin"],
        predicted_margin=out.get("predicted_margin"),
        predicted_total=out.get("predicted_total"),
        preview_text=out.get("preview_text"),
        is_shadow=True,
    ))
```

Replace the body of `generate()` with:

```python
def generate(db: Session, params: NrlParams | None = None) -> int:
    """Predict every scheduled nrl match from current Elo state. Returns the
    number of SportPrediction rows written this run (0 on a no-op re-run)."""
    params = params or load_nrl_params()
    elos = _current_elos(db)
    synced = _sync_team_elos(db, elos)
    if synced:
        log.info("elo sync: %d team rating(s) updated", synced)

    scheduled = (
        db.query(SportMatch)
        .filter_by(sport=SPORT, status="scheduled")
        .all()
    )
    if not scheduled:
        db.commit()
        return 0

    team_names = dict(
        db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all()
    )
    mt_params = load_margin_total_params()

    written = 0
    for m in scheduled:
        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        out = predict(elo_home, elo_away, params)
        predicted_margin, predicted_total = predict_margin_total(elo_home, elo_away, mt_params)

        home_name = team_names.get(m.home_team_id, "Home")
        away_name = team_names.get(m.away_team_id, "Away")
        home_form = last_n_results(db, m.home_team_id, before=m) if m.home_team_id else []
        away_form = last_n_results(db, m.away_team_id, before=m) if m.away_team_id else []
        preview_text = build_preview(
            home=home_name, away=away_name,
            p_home=out["p_home"], p_away=out["p_away"],
            elo_home=elo_home, elo_away=elo_away,
            home_form_summary=_form_summary(home_form),
            away_form_summary=_form_summary(away_form),
            predicted_margin=predicted_margin, predicted_total=predicted_total,
        )
        out["predicted_margin"] = predicted_margin
        out["predicted_total"] = predicted_total
        out["preview_text"] = preview_text

        if _write_prediction(db, m, params, out):
            written += 1

    db.commit()
    return written


def _form_summary(results: list[dict]) -> str:
    if not results:
        return "no recent form on record"
    w = sum(1 for r in results if r["result"] == "W")
    losses = sum(1 for r in results if r["result"] == "L")
    draws = sum(1 for r in results if r["result"] == "D")
    parts = [f"{w}W"]
    if losses:
        parts.append(f"{losses}L")
    if draws:
        parts.append(f"{draws}D")
    return f"{'-'.join(parts)} in their last {len(results)}"
```

- [ ] **Step 12: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_predict_test.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 13: Run the full pipeline test suite**

Run: `.venv/bin/python -m pytest pipeline ml backend -v`
Expected: PASS (no regressions)

- [ ] **Step 14: Commit**

```bash
git add pipeline/sports/nrl_form.py pipeline/sports/nrl_form_test.py \
        ml/models/nrl_preview.py ml/models/nrl_preview_test.py \
        pipeline/sports/nrl_predict.py pipeline/sports/nrl_predict_test.py
git commit -m "feat: stamp predicted_margin/predicted_total/preview_text on nrl predictions"
```

---

### Task 4: Finals projections Monte Carlo

**Files:**
- Create: `pipeline/sports/nrl_projections.py`
- Modify: `.github/workflows/nrl-refresh.yml`
- Test: `pipeline/sports/nrl_projections_test.py`

**Interfaces:**
- Consumes: `pipeline.sports.nrl_predict._current_elos` (existing), `ml.sports.nrl.model.predict`, `ml.sports.nrl.params.load_nrl_params`, `app.models.NrlProjection` (Task 1).
- Produces: `pipeline.sports.nrl_projections.simulate(team_ids, starting, remaining, elos, params, n_runs=5000, rng=None) -> dict[int, dict]` (pure — `{team_id: {"top8": float, "top4": float, "minor_premiership": float}}`), `run(db, season=None, n_runs=5000, rng=None) -> int` (writes `NrlProjection` rows, returns count written) — Task 5's `/api/nrl/projections` endpoint reads the `NrlProjection` rows this writes.

- [ ] **Step 1: Write the failing test**

Create `pipeline/sports/nrl_projections_test.py`:

```python
"""Tests for the Wave 1 finals-projections Monte Carlo
(pipeline/sports/nrl_projections.py)."""
import random
from datetime import datetime, timezone

from app.models import NrlProjection, SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams
from pipeline.sports.nrl_projections import run, simulate

PARAMS = NrlParams()


def test_simulate_with_no_remaining_fixtures_is_deterministic():
    """No remaining matches -> every run ranks the SAME starting standings,
    so each team's top8/top4/minor_premiership must be exactly 0.0 or 1.0."""
    team_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    starting = {t: {"points": (10 - t) * 2, "diff": (10 - t) * 10} for t in team_ids}
    probs = simulate(team_ids, starting, remaining=[], elos={}, params=PARAMS, n_runs=50)

    # Team 1 has the most points -> always rank 1 -> minor premiers every run.
    assert probs[1]["minor_premiership"] == 1.0
    assert probs[1]["top8"] == 1.0
    assert probs[1]["top4"] == 1.0
    # Team 9 has the fewest points -> always last (rank 9) -> never top 8.
    assert probs[9]["top8"] == 0.0
    assert probs[9]["minor_premiership"] == 0.0


def test_simulate_heavy_favourite_wins_minor_premiership_almost_always():
    """With only 2 teams, top8/top4 are trivially 1.0 for both (any rank in a
    2-team field is <= 8 and <= 4) -- minor_premiership (rank == 1) is the
    only metric that's actually selective between exactly two candidates."""
    team_ids = [1, 2]
    starting = {1: {"points": 0, "diff": 0}, 2: {"points": 0, "diff": 0}}
    elos = {1: 1900.0, 2: 1100.0}  # enormous gap -> team 1 wins almost every sim
    remaining = [
        SportMatch(id=1, sport="nrl", season=2026, round=20, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled")
    ]
    probs = simulate(team_ids, starting, remaining, elos, PARAMS,
                      n_runs=500, rng=random.Random(42))
    assert probs[1]["minor_premiership"] > 0.95
    assert probs[1]["top8"] == 1.0  # trivial in a 2-team field, sanity check only


def test_simulate_zero_runs_returns_zeroed_counts():
    probs = simulate([1, 2], {}, [], {}, PARAMS, n_runs=0)
    assert probs == {1: {"top8": 0, "top4": 0, "minor_premiership": 0},
                      2: {"top8": 0, "top4": 0, "minor_premiership": 0}}


def test_run_writes_and_replaces_projection_rows(db_session):
    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db_session.add_all([a, b]); db_session.flush()
    db_session.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                              kickoff_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id,
                              status="finished", score_home=20, score_away=10))
    db_session.add(SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                              kickoff_utc=datetime(2026, 3, 8, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.commit()

    n = run(db_session, season=2026, n_runs=25, rng=random.Random(1))
    assert n == 2
    rows = db_session.query(NrlProjection).all()
    assert {r.team for r in rows} == {"Storm", "Eels"}
    assert all(0.0 <= r.top8 <= 1.0 for r in rows)

    # Re-run must REPLACE, not accumulate.
    run(db_session, season=2026, n_runs=25, rng=random.Random(2))
    assert db_session.query(NrlProjection).count() == 2


def test_run_with_no_nrl_data_writes_nothing(db_session):
    assert run(db_session) == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_projections_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.sports.nrl_projections'`

- [ ] **Step 3: Write the projections module**

Create `pipeline/sports/nrl_projections.py`:

```python
"""Wave 1 finals projections: 5,000-run Monte Carlo of remaining nrl
fixtures, seeded from the CURRENT ladder + Elo state, producing
top8/top4/minor-premiership probabilities per team. Delete-then-insert into
nrl_projections each run (mirrors pipeline.prob_snapshots' _replace_day
idiom, at table granularity) so a re-run stays idempotent. A `nrl-refresh`
pipeline step (see .github/workflows/nrl-refresh.yml).

CLI: PYTHONPATH=backend:. python -m pipeline.sports.nrl_projections
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import NrlProjection, SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams, predict
from ml.sports.nrl.params import load_nrl_params
from pipeline.sports.nrl_predict import _current_elos

log = logging.getLogger(__name__)

SPORT = "nrl"
N_RUNS = 5000


def _ladder_from(matches) -> dict[int, dict]:
    """Points + points-diff for every team across `matches` (FINISHED only;
    2 pts/win, 1/draw -- same rule as backend.app.api.sports.nrl_ladder).
    Pure -- takes an iterable of SportMatch, not a DB session."""
    table: dict[int, dict] = {}

    def row(team_id: int) -> dict:
        return table.setdefault(team_id, {"points": 0, "diff": 0})

    for m in matches:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        if m.score_home is None or m.score_away is None:
            continue
        h, a = row(m.home_team_id), row(m.away_team_id)
        h["diff"] += m.score_home - m.score_away
        a["diff"] += m.score_away - m.score_home
        if m.score_home > m.score_away:
            h["points"] += 2
        elif m.score_home < m.score_away:
            a["points"] += 2
        else:
            h["points"] += 1
            a["points"] += 1
    return table


def simulate(
    team_ids: list[int],
    starting: dict[int, dict],
    remaining: list[SportMatch],
    elos: dict[int, float],
    params: NrlParams,
    n_runs: int = N_RUNS,
    rng: random.Random | None = None,
) -> dict[int, dict]:
    """Return {team_id: {"top8": p, "top4": p, "minor_premiership": p}} across
    `n_runs` simulated completions of `remaining`. Pure -- no DB access, so the
    Monte Carlo core is unit-testable without a database."""
    rng = rng or random.Random()
    counts = {t: {"top8": 0, "top4": 0, "minor_premiership": 0} for t in team_ids}
    if n_runs == 0 or not team_ids:
        return counts

    for _ in range(n_runs):
        points = {t: starting.get(t, {}).get("points", 0) for t in team_ids}
        diff = {t: starting.get(t, {}).get("diff", 0) for t in team_ids}

        for m in remaining:
            if m.home_team_id not in points or m.away_team_id not in points:
                continue
            elo_home = elos.get(m.home_team_id, 1500.0)
            elo_away = elos.get(m.away_team_id, 1500.0)
            out = predict(elo_home, elo_away, params)
            roll = rng.random()
            if roll < out["p_home"]:
                outcome = "home"
            elif roll < out["p_home"] + out["p_draw"]:
                outcome = "draw"
            else:
                outcome = "away"

            if outcome == "draw":
                points[m.home_team_id] += 1
                points[m.away_team_id] += 1
                continue

            # Margin sampling for points-differential tie-breaks only -- never
            # written back as a real score.
            margin = max(1.0, abs(rng.gauss(out["expected_margin"], params.margin_sigma)))
            if outcome == "home":
                points[m.home_team_id] += 2
                diff[m.home_team_id] += margin
                diff[m.away_team_id] -= margin
            else:
                points[m.away_team_id] += 2
                diff[m.away_team_id] += margin
                diff[m.home_team_id] -= margin

        ranked = sorted(team_ids, key=lambda t: (-points[t], -diff[t], t))
        for rank, t in enumerate(ranked, start=1):
            if rank <= 8:
                counts[t]["top8"] += 1
            if rank <= 4:
                counts[t]["top4"] += 1
            if rank == 1:
                counts[t]["minor_premiership"] += 1

    return {t: {k: v / n_runs for k, v in c.items()} for t, c in counts.items()}


def _replace_projections(db: Session, rows: list[NrlProjection]) -> int:
    db.query(NrlProjection).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def run(
    db: Session, season: int | None = None, n_runs: int = N_RUNS,
    rng: random.Random | None = None,
) -> int:
    """Compute + store finals projections for `season` (latest if omitted).
    Returns the number of team rows written (0 if no nrl data)."""
    if season is None:
        latest = (
            db.query(SportMatch.season)
            .filter(SportMatch.sport == SPORT)
            .order_by(SportMatch.season.desc())
            .first()
        )
        if latest is None:
            return 0
        season = latest[0]

    season_matches = (
        db.query(SportMatch)
        .filter(SportMatch.sport == SPORT, SportMatch.season == season)
        .all()
    )
    team_ids = sorted({
        tid for m in season_matches for tid in (m.home_team_id, m.away_team_id) if tid is not None
    })
    if not team_ids:
        return 0

    teams = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.sport == SPORT, SportTeam.id.in_(team_ids)).all()
    )
    starting = _ladder_from(m for m in season_matches if m.status == "finished")
    remaining = [m for m in season_matches if m.status == "scheduled"]
    elos = _current_elos(db)
    params = load_nrl_params()

    probs = simulate(team_ids, starting, remaining, elos, params, n_runs=n_runs, rng=rng)
    now = datetime.now(timezone.utc)
    out_rows = [
        NrlProjection(
            team=teams.get(t, "Unknown"),
            top8=probs[t]["top8"], top4=probs[t]["top4"],
            minor_premiership=probs[t]["minor_premiership"],
            computed_at=now,
        )
        for t in team_ids
    ]
    return _replace_projections(db, out_rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        n = run(db)
        log.info("nrl projections: %d team row(s) written", n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/sports/nrl_projections_test.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire into the `nrl-refresh` pipeline step**

In `.github/workflows/nrl-refresh.yml`, add a new step after "Generate frozen shadow predictions + grade finished matches":

```yaml
      - name: Generate frozen shadow predictions + grade finished matches
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.sports.nrl_predict --generate --grade
      - name: Compute finals projections (Monte Carlo)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.sports.nrl_projections
```

- [ ] **Step 6: Commit**

```bash
git add pipeline/sports/nrl_projections.py pipeline/sports/nrl_projections_test.py .github/workflows/nrl-refresh.yml
git commit -m "feat: add 5000-run finals projections Monte Carlo to nrl-refresh"
```

---

### Task 5: Backend detail endpoint, projections endpoint, NRL prob-history

**Files:**
- Create: `backend/app/api/nrl_intel.py`
- Modify: `backend/app/api/sports.py`
- Modify: `backend/app/api/movers.py` (see Note below — deferred to Task 8; skip here)
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_nrl_intel_api.py`

**Interfaces:**
- Consumes: `pipeline.sports.nrl_form.{last_n_results, form_averages}` (Task 3), `app.models.{NrlProjection, ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam}`.
- Produces: `GET /api/nrl/matches/{id}` → `{ match, prediction, form, h2h, factors }` (contract below), `GET /api/nrl/projections` → `{ computed_at, teams: [...] }`, `GET /api/nrl/matches/{id}/prob-history` → `{ match_id, points, disclaimer }`. `nrl_matches()` and `nrl_team()`'s `match_ref()` in `sports.py` now include `"id"` in every match dict — Task 6's frontend types/fetchers and Task 6's page consume this.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_nrl_intel_api.py`:

```python
"""GET /api/nrl/matches/{id}, GET /api/nrl/projections,
GET /api/nrl/matches/{id}/prob-history -- Wave 1's rich match-detail surface.
Mirrors test_sports_api.py's fixture style."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    NrlProjection, ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam,
)


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
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _team(db, name, elo=None):
    t = SportTeam(sport="nrl", name=name, elo_rating=elo)
    db.add(t); db.flush()
    return t


def test_match_detail_404s_for_unknown_id(client):
    c, _ = client
    r = c.get("/api/nrl/matches/999")
    assert r.status_code == 404


def test_match_detail_returns_prediction_form_h2h_factors(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm", elo=1560.0)
    away = _team(db, "Eels", elo=1490.0)
    third = _team(db, "Titans")

    # Prior meeting between these two exact sides (h2h).
    db.add(SportMatch(sport="nrl", season=2025, round=10, match_no=50,
                      kickoff_utc=datetime(2025, 6, 1, tzinfo=timezone.utc),
                      home_team_id=home.id, away_team_id=away.id,
                      score_home=24, score_away=12, status="finished"))
    # Home team's prior form -- against a DIFFERENT opponent, so it doesn't
    # also count as a head-to-head meeting between home and away.
    db.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                      kickoff_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
                      home_team_id=home.id, away_team_id=third.id,
                      score_home=20, score_away=10, status="finished"))
    m = SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                   kickoff_utc=datetime(2026, 3, 8, tzinfo=timezone.utc),
                   venue="AAMI Park", home_team_id=home.id, away_team_id=away.id,
                   status="scheduled")
    db.add(m); db.flush()
    db.add(SportPrediction(
        match_id=m.id, model_version="nrl-elo-v0.1",
        p_home=0.62, p_draw=0.01, p_away=0.37,
        expected_margin=5.0, predicted_margin=6.1, predicted_total=41.0,
        preview_text="Storm are the model's pick.",
    ))
    db.commit()

    r = c.get(f"/api/nrl/matches/{m.id}")
    assert r.status_code == 200
    body = r.json()

    assert body["match"]["id"] == m.id
    assert body["match"]["home"] == "Storm"
    assert body["match"]["away"] == "Eels"

    pred = body["prediction"]
    assert pred["home_prob"] == pytest.approx(0.62)
    assert pred["away_prob"] == pytest.approx(0.37)
    assert pred["draw_prob"] == pytest.approx(0.01)
    assert pred["predicted_margin"] == pytest.approx(6.1)
    assert pred["predicted_total"] == pytest.approx(41.0)
    assert pred["preview_text"] == "Storm are the model's pick."
    assert pred["model_version"] == "nrl-elo-v0.1"

    assert len(body["form"]["home"]["last5"]) == 1
    assert body["form"]["home"]["last5"][0]["result"] == "W"
    assert body["form"]["home"]["avg_margin"] == 10.0

    assert len(body["h2h"]) == 1
    assert body["h2h"][0]["score_home"] == 24

    keys = {f["key"] for f in body["factors"]}
    assert keys == {"elo_gap", "form_composite", "home_advantage"}
    weights = {f["key"]: f["weight"] for f in body["factors"]}
    assert weights["elo_gap"] == pytest.approx(0.5)
    assert weights["form_composite"] == pytest.approx(0.3)
    assert weights["home_advantage"] == pytest.approx(0.2)
    home_adv = next(f for f in body["factors"] if f["key"] == "home_advantage")
    assert home_adv["favors"] == "home"
    elo_gap = next(f for f in body["factors"] if f["key"] == "elo_gap")
    assert elo_gap["favors"] == "home"  # Storm's elo_rating (1560) > Eels' (1490)


def test_match_detail_handles_no_prediction_yet(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.commit()

    r = c.get(f"/api/nrl/matches/{m.id}")
    assert r.status_code == 200
    assert r.json()["prediction"] is None


def test_projections_empty_when_none_computed(client):
    c, _ = client
    r = c.get("/api/nrl/projections")
    assert r.status_code == 200
    body = r.json()
    assert body["teams"] == []
    assert body["computed_at"] is None


def test_projections_returns_seeded_rows(client):
    c, TestingSession = client
    db = TestingSession()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    db.add(NrlProjection(team="Storm", top8=0.95, top4=0.4, minor_premiership=0.1,
                         computed_at=now))
    db.commit()

    body = c.get("/api/nrl/projections").json()
    assert body["computed_at"] is not None
    assert body["teams"] == [
        {"team": "Storm", "top8": 0.95, "top4": 0.4, "minor_premiership": 0.1}
    ]


def test_prob_history_404s_for_unknown_match(client):
    c, _ = client
    assert c.get("/api/nrl/matches/999/prob-history").status_code == 404


def test_prob_history_returns_snapshots_for_the_match(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()
    db.add_all([
        ProbabilitySnapshot(sport="nrl", entity_id=home.id, market="win_match",
                            ref_id=m.id, prob=0.55, snapshot_date=date(2026, 7, 1)),
        ProbabilitySnapshot(sport="nrl", entity_id=away.id, market="win_match",
                            ref_id=m.id, prob=0.44, snapshot_date=date(2026, 7, 1)),
        ProbabilitySnapshot(sport="nrl", entity_id=home.id, market="win_match",
                            ref_id=m.id, prob=0.61, snapshot_date=date(2026, 7, 2)),
        ProbabilitySnapshot(sport="nrl", entity_id=away.id, market="win_match",
                            ref_id=m.id, prob=0.38, snapshot_date=date(2026, 7, 2)),
    ])
    db.commit()

    body = c.get(f"/api/nrl/matches/{m.id}/prob-history").json()
    assert len(body["points"]) == 2
    assert body["points"][0]["date"] == "2026-07-01"
    assert body["points"][0]["p_home"] == pytest.approx(0.55)
    assert body["points"][1]["p_home"] == pytest.approx(0.61)
    assert "disclaimer" in body


def test_matches_endpoint_now_includes_match_id(client):
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.commit()

    body = c.get("/api/nrl/matches", params={"season": 2026}).json()
    assert body["rounds"][0]["matches"][0]["id"] == m.id
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_nrl_intel_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.nrl_intel'` (and the last test fails with `KeyError: 'id'`)

- [ ] **Step 3: Add `id` to the existing `/matches` and `/teams/{id}` payloads**

In `backend/app/api/sports.py`, in `nrl_matches()`, add `"id": m.id,` as the first key of the per-match dict:

```python
        rounds.setdefault(m.round, []).append({
            "id": m.id,
            "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue,
            "home": home_name,
            "away": away_name,
            "home_team_id": m.home_team_id,
            "away_team_id": m.away_team_id,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "status": m.status,
            "prediction": pred_out,
        })
```

In `nrl_team()`'s `match_ref()` helper, add `"id": m.id,` as the first key:

```python
    def match_ref(m: SportMatch) -> dict:
        was_home = m.home_team_id == team_id
        opp_id = m.away_team_id if was_home else m.home_team_id
        return {
            "id": m.id,
            "round": m.round,
            "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue,
            "opponent": names.get(opp_id),
            "opponent_id": opp_id,
            "was_home": was_home,
        }
```

- [ ] **Step 4: Write `nrl_intel.py`**

Create `backend/app/api/nrl_intel.py`:

```python
"""NRL Match Intelligence (Wave 1): per-match detail (prediction, form, h2h,
factors), finals projections, and NRL probability history. A separate router
from app.api.sports (same /api/nrl prefix, different paths -- mirrors how
football splits /api/matches across matches.py and prob_history.py).
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlProjection, ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam
from pipeline.sports.nrl_form import form_averages, last_n_results

router = APIRouter(prefix="/api/nrl", tags=["nrl-intel"])

SPORT = "nrl"
_DISCLAIMER = "For analytics and entertainment only. Not betting advice."


def _team_form_block(db: Session, team_id: int, before: SportMatch) -> dict:
    results = last_n_results(db, team_id, n=5, before=before)
    names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all())
    last5 = [
        {"round": r["round"], "opponent": names.get(r["opponent_id"], "Unknown"),
         "result": r["result"], "for": r["for"], "against": r["against"]}
        for r in results
    ]
    return {"last5": last5, **form_averages(results)}


def _head_to_head(db: Session, home_id: int, away_id: int, exclude_match_id: int,
                   limit: int = 5) -> list[dict]:
    rows = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT, SportMatch.status == "finished",
            SportMatch.score_home.isnot(None), SportMatch.score_away.isnot(None),
            SportMatch.id != exclude_match_id,
            or_(
                (SportMatch.home_team_id == home_id) & (SportMatch.away_team_id == away_id),
                (SportMatch.home_team_id == away_id) & (SportMatch.away_team_id == home_id),
            ),
        )
        .all()
    )
    rows.sort(key=lambda m: (m.kickoff_utc is None, m.kickoff_utc or datetime.min, m.id),
              reverse=True)
    rows = rows[:limit]
    names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all())
    out = []
    for m in rows:
        winner = ("home" if m.score_home > m.score_away
                  else "away" if m.score_away > m.score_home else "draw")
        out.append({
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "home": names.get(m.home_team_id, "Unknown"),
            "away": names.get(m.away_team_id, "Unknown"),
            "score_home": m.score_home, "score_away": m.score_away, "winner": winner,
        })
    return out


def _composite(form: dict) -> float:
    results = form["last5"]
    win_rate = (sum(1 for r in results if r["result"] == "W") / len(results)) if results else 0.5
    return win_rate * 0.6 + (form["avg_margin"] / 40.0) * 0.4


def _build_factors(home: SportTeam, away: SportTeam, home_form: dict, away_form: dict) -> list[dict]:
    elo_home = home.elo_rating if home.elo_rating is not None else 1500.0
    elo_away = away.elo_rating if away.elo_rating is not None else 1500.0
    elo_favors = "home" if elo_home >= elo_away else "away"
    form_favors = "home" if _composite(home_form) >= _composite(away_form) else "away"

    return [
        {"key": "elo_gap", "label": "Elo rating gap", "weight": 0.5, "favors": elo_favors},
        {"key": "form_composite", "label": "Recent form", "weight": 0.3, "favors": form_favors},
        {"key": "home_advantage", "label": "Home advantage", "weight": 0.2, "favors": "home"},
    ]


@router.get("/matches/{match_id}")
def nrl_match_detail(match_id: int, db: Session = Depends(get_db)):
    m = db.get(SportMatch, match_id)
    if m is None or m.sport != SPORT:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found", "message": f"No NRL match {match_id}",
        })

    home = db.get(SportTeam, m.home_team_id) if m.home_team_id else None
    away = db.get(SportTeam, m.away_team_id) if m.away_team_id else None

    match_out = {
        "id": m.id, "season": m.season, "round": m.round, "match_no": m.match_no,
        "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
        "venue": m.venue, "home": home.name if home else None, "away": away.name if away else None,
        "home_team_id": m.home_team_id, "away_team_id": m.away_team_id,
        "score_home": m.score_home, "score_away": m.score_away, "status": m.status,
    }

    pred = (
        db.query(SportPrediction).filter_by(match_id=m.id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    prediction_out = None
    if pred is not None:
        prediction_out = {
            "home_prob": pred.p_home, "away_prob": pred.p_away, "draw_prob": pred.p_draw,
            "predicted_margin": pred.predicted_margin, "predicted_total": pred.predicted_total,
            "model_version": pred.model_version, "preview_text": pred.preview_text,
        }

    home_form = _team_form_block(db, m.home_team_id, before=m) if m.home_team_id else None
    away_form = _team_form_block(db, m.away_team_id, before=m) if m.away_team_id else None

    factors: list[dict] = []
    if home is not None and away is not None and home_form is not None and away_form is not None:
        factors = _build_factors(home, away, home_form, away_form)

    h2h = (
        _head_to_head(db, m.home_team_id, m.away_team_id, exclude_match_id=m.id)
        if (m.home_team_id and m.away_team_id) else []
    )

    return {
        "match": match_out,
        "prediction": prediction_out,
        "form": {"home": home_form, "away": away_form},
        "h2h": h2h,
        "factors": factors,
    }


@router.get("/projections")
def nrl_projections(db: Session = Depends(get_db)):
    rows = db.query(NrlProjection).order_by(NrlProjection.top8.desc()).all()
    computed_at = rows[0].computed_at if rows else None
    return {
        "computed_at": computed_at.isoformat() if computed_at else None,
        "teams": [
            {"team": r.team, "top8": r.top8, "top4": r.top4,
             "minor_premiership": r.minor_premiership}
            for r in rows
        ],
    }


@router.get("/matches/{match_id}/prob-history")
def nrl_prob_history(match_id: int, db: Session = Depends(get_db)):
    m = db.get(SportMatch, match_id)
    if m is None or m.sport != SPORT:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found", "message": f"No NRL match {match_id}",
        })

    rows = (
        db.query(ProbabilitySnapshot)
        .filter(ProbabilitySnapshot.sport == SPORT, ProbabilitySnapshot.market == "win_match",
                ProbabilitySnapshot.ref_id == match_id)
        .order_by(ProbabilitySnapshot.snapshot_date.asc())
        .all()
    )
    by_day: dict[date, dict[int, float]] = {}
    for r in rows:
        by_day.setdefault(r.snapshot_date, {})[r.entity_id] = r.prob

    points = []
    for day, by_entity in sorted(by_day.items()):
        p_home = by_entity.get(m.home_team_id)
        p_away = by_entity.get(m.away_team_id)
        if p_home is None and p_away is None:
            continue
        p_draw = round(1.0 - p_home - p_away, 6) if p_home is not None and p_away is not None else None
        points.append({"date": day.isoformat(), "p_home": p_home, "p_draw": p_draw, "p_away": p_away})

    return {"match_id": match_id, "points": points, "disclaimer": _DISCLAIMER}
```

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, add `nrl_intel` to the import and register it:

```python
from app.api import (
    auth, brackets, groups, internal, knockout, leaderboard, markets, market_record, match_picks,
    matches, model_record, movers, nrl_intel, predictions, prob_history, sports, teams,
)
```

```python
app.include_router(sports.router)
app.include_router(nrl_intel.router)
app.include_router(movers.router)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_nrl_intel_api.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Run the existing NRL API tests to check for regressions**

Run: `.venv/bin/python -m pytest backend/tests/test_sports_api.py backend/tests/test_nrl_ladder_api.py backend/tests/test_nrl_team_api.py -v`
Expected: PASS (the added `id` fields are additive; no existing assertion checks the full dict shape with strict equality)

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/nrl_intel.py backend/app/api/sports.py backend/app/main.py backend/tests/test_nrl_intel_api.py
git commit -m "feat: add nrl match detail, projections and prob-history endpoints"
```

---

### Task 6: Match Intelligence page — types, fetchers, sections, components

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/OverviewSection.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/FormSection.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/ModelSection.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/MatchIntelClient.tsx`
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/page.tsx`
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx`
- Modify: `frontend/app/nrl/team/[id]/page.test.tsx`
- Modify: `frontend/components/__tests__/sportMatchCard.test.tsx`
- Test: `frontend/app/nrl/match/[season]/[round]/[no]/sections.test.ts`

**Interfaces:**
- Consumes: Task 5's `GET /api/nrl/matches/{id}`, `GET /api/nrl/matches/{id}/prob-history`.
- Produces: `IntelSectionProps = { detail: NrlMatchDetail; probHistory: NrlProbHistory | null }`, `IntelSection = { id: string; label: string; render: ComponentType<IntelSectionProps> }`, `sections: IntelSection[]` (Wave 2/3 append entries here + new component files — no edits to `MatchIntelClient.tsx`, `OverviewSection.tsx`, `FormSection.tsx`, or `ModelSection.tsx`). `getNrlMatchDetailServer(id)`, `getNrlProjectionsServer()`, `getNrlProbHistoryServer(id)` in `frontend/lib/api.ts`.

- [ ] **Step 1: Add the new types**

In `frontend/lib/types.ts`, add `id: number` to `NrlMatch` and `NrlTeamMatchRef`:

```ts
export interface NrlMatch {
  id: number;
  match_no: number;
  kickoff_utc: string | null;
  venue: string | null;
  home: string | null;
  away: string | null;
  home_team_id: number | null;
  away_team_id: number | null;
  score_home: number | null;
  score_away: number | null;
  status: string;
  prediction: NrlPrediction | null;
}
```

```ts
export interface NrlTeamMatchRef {
  id: number;
  round: number | null;
  match_no: number;
  kickoff_utc: string | null;
  venue: string | null;
  opponent: string | null;
  opponent_id: number | null;
  was_home: boolean;
}
```

Append the Wave 1 match-intelligence types at the end of the file:

```ts
/** /api/nrl/matches/{id} -- Wave 1 match intelligence detail. */
export interface NrlMatchInfo {
  id: number;
  season: number;
  round: number | null;
  match_no: number;
  kickoff_utc: string | null;
  venue: string | null;
  home: string | null;
  away: string | null;
  home_team_id: number | null;
  away_team_id: number | null;
  score_home: number | null;
  score_away: number | null;
  status: string;
}
export interface NrlMatchDetailPrediction {
  home_prob: number;
  away_prob: number;
  draw_prob: number;
  predicted_margin: number | null;
  predicted_total: number | null;
  model_version: string;
  preview_text: string | null;
}
export interface NrlFormResult {
  round: number | null;
  opponent: string;
  result: "W" | "L" | "D";
  for: number;
  against: number;
}
export interface NrlTeamForm {
  last5: NrlFormResult[];
  avg_for: number;
  avg_against: number;
  avg_margin: number;
}
export interface NrlMeeting {
  kickoff_utc: string | null;
  home: string;
  away: string;
  score_home: number;
  score_away: number;
  winner: "home" | "away" | "draw";
}
export interface NrlFactor {
  key: string;
  label: string;
  weight: number;
  favors: "home" | "away";
}
export interface NrlMatchDetail {
  match: NrlMatchInfo;
  prediction: NrlMatchDetailPrediction | null;
  form: { home: NrlTeamForm | null; away: NrlTeamForm | null };
  h2h: NrlMeeting[];
  factors: NrlFactor[];
}

/** GET /api/nrl/projections */
export interface NrlProjectionRow {
  team: string;
  top8: number;
  top4: number;
  minor_premiership: number;
}
export interface NrlProjectionsResponse {
  computed_at: string | null;
  teams: NrlProjectionRow[];
}

/** GET /api/nrl/matches/{id}/prob-history */
export interface NrlProbHistoryPoint {
  date: string | null;
  p_home: number | null;
  p_draw: number | null;
  p_away: number | null;
}
export interface NrlProbHistory {
  match_id: number;
  points: NrlProbHistoryPoint[];
  disclaimer: string;
}
```

- [ ] **Step 1b: Fix the now-broken `NrlMatch`/`NrlTeamMatchRef` fixtures in existing tests**

`NrlMatch` now requires `id: number`, and `NrlTeamMatchRef` (and everything that extends it — `NrlTeamResult`, `NrlTeamFixture`) does too. Two existing test files hand-build object literals of those types and would otherwise fail `npm run build`'s type-check, even though neither is otherwise touched by this task.

In `frontend/components/__tests__/sportMatchCard.test.tsx`, add `id: 3,` as the first field of the `match: NrlMatch` object literal (right before `match_no: 3,`):

```tsx
const match: NrlMatch = {
  id: 3,
  match_no: 3,
  kickoff_utc: "2026-07-11T09:35:00+00:00",
  ...
```

Run: `cd frontend && npx jest components/__tests__/sportMatchCard.test.tsx`
Expected: PASS (unchanged behavior — the card's href logic doesn't read `match.id`)

In `frontend/app/nrl/team/[id]/page.test.tsx`, add an `id` field to each of the five affected object literals:

```tsx
    biggest_win: {
      id: 5201, round: 7, match_no: 52, kickoff_utc: null, venue: null,
      opponent: "Titans", opponent_id: 6, was_home: true,
      score_for: 44, score_against: 6, result: "W", model_called: null,
    },
    biggest_loss: {
      id: 5202, round: 2, match_no: 12, kickoff_utc: null, venue: null,
      opponent: "Storm", opponent_id: 5, was_home: false,
      score_for: 10, score_against: 32, result: "L", model_called: null,
    },
  },
  results: [
    {
      id: 5203, round: 18, match_no: 130, kickoff_utc: "2026-07-04T09:35:00+00:00",
      venue: "Go Media Stadium", opponent: "Broncos", opponent_id: 1,
      was_home: true, score_for: 24, score_against: 12, result: "W",
      model_called: true,
    },
    {
      id: 5204, round: 17, match_no: 121, kickoff_utc: "2026-06-27T07:00:00+00:00",
      venue: "Suncorp Stadium", opponent: "Dolphins", opponent_id: 4,
      was_home: false, score_for: 20, score_against: 18, result: "W",
      model_called: null,
    },
  ],
  upcoming: [
    {
      id: 5205, round: 19, match_no: 134, kickoff_utc: "2026-07-10T10:00:00+00:00",
      venue: "Campbelltown Sports Stadium", opponent: "Wests Tigers",
      opponent_id: 17, was_home: false, win_prob: 0.672,
    },
  ],
```

Run: `cd frontend && npx jest app/nrl/team/\\[id\\]/page.test.tsx`
Expected: PASS (unchanged behavior — this step is purely a type-shape fix, no assertions reference `id`)

- [ ] **Step 2: Add the new server fetchers**

In `frontend/lib/api.ts`, extend the type import list:

```ts
import type {
  Goalscorers,
  Group,
  KnockoutBracket,
  LadderResponse,
  LeaderboardRow,
  MarketBenchmark,
  MatchLineups,
  MatchSummary,
  ModelRecord,
  MoversResponse,
  NrlMatchDetail,
  NrlMatchesResponse,
  NrlProbHistory,
  NrlProjectionsResponse,
  NrlRecord,
  NrlTeamProfile,
  Prediction,
  ProbHistory,
  Team,
  TeamProfile,
  TournamentOdds,
} from "./types";
```

Append after `getNrlRecordServer`:

```ts
export const getNrlMatchDetailServer = (id: number | string) =>
  getServer<NrlMatchDetail>(`/api/nrl/matches/${id}`, 300);
export const getNrlProjectionsServer = () =>
  getServer<NrlProjectionsResponse>("/api/nrl/projections", 300);
export const getNrlProbHistoryServer = (id: number | string) =>
  getServer<NrlProbHistory>(`/api/nrl/matches/${id}/prob-history`, 300);
```

- [ ] **Step 3 — REMOVED (controller reconciliation): keep the page's existing `<LocalKickoff>`**

The already-shipped NRL detail page renders kickoff + venue via the user-selectable
`<LocalKickoff>` component. That behavior is retained (Warriors fans see NZ time); the
Global Constraint's intent — never render raw UTC — is already satisfied by it. Do NOT
add a `sydneyKickoff` helper and do NOT modify `frontend/lib/datetime.ts`.

- [ ] **Step 4: Write the failing sections test**

Create `frontend/app/nrl/match/[season]/[round]/[no]/sections.test.ts`:

```ts
import { sections } from "./sections";

it("ships overview, form and model in that order", () => {
  expect(sections.map((s) => s.id)).toEqual(["overview", "form", "model"]);
});

it("every section has a label and a render component", () => {
  for (const s of sections) {
    expect(typeof s.label).toBe("string");
    expect(s.label.length).toBeGreaterThan(0);
    expect(typeof s.render).toBe("function");
  }
});
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `cd frontend && npx jest app/nrl/match/\\[season\\]/\\[round\\]/\\[no\\]/sections.test.ts`
Expected: FAIL — cannot find module `./sections`

- [ ] **Step 6: Write the three section components**

Create `frontend/app/nrl/match/[season]/[round]/[no]/OverviewSection.tsx`:

```tsx
import type { IntelSectionProps } from "./sections";

export function OverviewSection({ detail, probHistory }: IntelSectionProps) {
  const preview = detail.prediction?.preview_text ?? null;
  const points = probHistory?.points ?? [];

  return (
    <div className="glass rounded-2xl p-6">
      <h2 className="mb-3 font-display text-lg font-bold text-foreground">Overview</h2>
      {preview ? (
        preview.split("\n\n").map((para, i) => (
          <p key={i} className="mb-3 text-sm leading-relaxed text-foreground last:mb-0">
            {para}
          </p>
        ))
      ) : (
        <p className="text-sm text-muted">Preview not available yet.</p>
      )}
      {points.length >= 2 && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
            Forecast movement
          </p>
          <ForecastLine points={points} />
        </div>
      )}
    </div>
  );
}

function ForecastLine({ points }: { points: { p_home: number | null }[] }) {
  const values = points.map((p) => p.p_home).filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const w = 240;
  const h = 48;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - 4 - ((v - min) / span) * (h - 8)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-12 w-full" aria-hidden="true">
      <polyline points={pts} fill="none" strokeWidth="2" className="stroke-lime-deep" />
    </svg>
  );
}
```

Create `frontend/app/nrl/match/[season]/[round]/[no]/FormSection.tsx`:

```tsx
import { ClubBadge } from "@/components/ClubBadge";
import type { NrlTeamForm } from "@/lib/types";
import type { IntelSectionProps } from "./sections";

const RESULT_TONE: Record<string, string> = {
  W: "bg-win/15 text-lime-deep",
  D: "bg-draw/15 text-amber-ink",
  L: "bg-loss/15 text-loss",
};

export function FormSection({ detail }: IntelSectionProps) {
  const { home, away } = detail.form;
  const { home: homeName, away: awayName } = detail.match;

  return (
    <div className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Form &amp; head-to-head</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <TeamForm name={homeName} form={home} />
        <TeamForm name={awayName} form={away} />
      </div>

      {detail.h2h.length > 0 && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
            Last {detail.h2h.length} meetings
          </p>
          <ul className="space-y-1.5 text-sm">
            {detail.h2h.map((meeting, i) => (
              <li key={i} className="flex items-center justify-between text-muted">
                <span>{meeting.home} vs {meeting.away}</span>
                <span className="font-semibold tabular-nums text-foreground">
                  {meeting.score_home}–{meeting.score_away}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TeamForm({ name, form }: { name: string | null; form: NrlTeamForm | null }) {
  if (!form) return null;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <ClubBadge name={name} size={22} />
        <span className="font-display text-sm font-semibold">{name ?? "TBC"}</span>
      </div>
      <div className="flex gap-1">
        {form.last5.map((r, i) => (
          <span
            key={i}
            title={`Rd ${r.round ?? "?"} vs ${r.opponent}: ${r.for}–${r.against}`}
            className={`grid h-6 w-6 place-items-center rounded-md text-[11px] font-bold ${RESULT_TONE[r.result]}`}
          >
            {r.result}
          </span>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">
        Avg {form.avg_for}–{form.avg_against} · margin{" "}
        {form.avg_margin > 0 ? "+" : ""}
        {form.avg_margin}
      </p>
    </div>
  );
}
```

Create `frontend/app/nrl/match/[season]/[round]/[no]/ModelSection.tsx`:

```tsx
import Link from "next/link";
import type { IntelSectionProps } from "./sections";

export function ModelSection({ detail }: IntelSectionProps) {
  const { prediction, match } = detail;
  if (!prediction) {
    return (
      <div className="glass rounded-2xl p-6 text-center text-sm text-muted">
        Model breakdown lands once the prediction is frozen.
      </div>
    );
  }
  const confidence = Math.max(prediction.home_prob, prediction.away_prob);

  return (
    <div className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Model</h2>

      <p className="text-xs font-semibold uppercase tracking-wider text-muted">Elo comparison</p>
      <EloBars homeProb={prediction.home_prob} awayProb={prediction.away_prob}
               home={match.home} away={match.away} />

      {detail.factors.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
            What&apos;s driving this
          </p>
          <div className="space-y-2">
            {detail.factors.map((f) => (
              <div key={f.key} className="flex items-center gap-2">
                <span className="w-32 shrink-0 text-xs text-muted">{f.label}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <i
                    className={f.favors === "home" ? "block h-full bg-win" : "block h-full bg-loss"}
                    style={{ width: `${Math.round(f.weight * 100)}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs font-semibold tabular-nums text-foreground">
                  {Math.round(f.weight * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="mt-5 border-t border-border pt-4 text-xs leading-relaxed text-muted">
        Confidence {Math.round(confidence * 100)}% · model {prediction.model_version} ·{" "}
        <Link href="/nrl/record" className="font-semibold text-lime-deep">
          Full model record →
        </Link>
      </p>
    </div>
  );
}

function EloBars({
  homeProb, awayProb, home, away,
}: {
  homeProb: number; awayProb: number; home: string | null; away: string | null;
}) {
  const total = homeProb + awayProb || 1;
  const homePct = Math.round((homeProb / total) * 100);
  return (
    <div className="mt-2">
      <div className="flex h-3 overflow-hidden rounded-full bg-surface-2">
        <i className="block h-full bg-win" style={{ width: `${homePct}%` }} />
        <i className="block h-full bg-loss" style={{ width: `${100 - homePct}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-muted">
        <span>{home ?? "Home"}</span>
        <span>{away ?? "Away"}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Write `sections.ts`**

Create `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts`:

```ts
import type { ComponentType } from "react";
import type { NrlMatchDetail, NrlProbHistory } from "@/lib/types";
import { OverviewSection } from "./OverviewSection";
import { FormSection } from "./FormSection";
import { ModelSection } from "./ModelSection";

/** Props every Match Intelligence section component receives. Wave 1 ships
 *  overview/form/model; Wave 2 appends stats/matchup, Wave 3 appends
 *  scorers/live -- each a new entry below + a new self-contained component
 *  file, with NO edits to any Wave 1 section component. */
export interface IntelSectionProps {
  detail: NrlMatchDetail;
  probHistory: NrlProbHistory | null;
}

export type IntelSection = { id: string; label: string; render: ComponentType<IntelSectionProps> };

export const sections: IntelSection[] = [
  { id: "overview", label: "Overview", render: OverviewSection },
  { id: "form", label: "Form & H2H", render: FormSection },
  { id: "model", label: "Model", render: ModelSection },
];
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd frontend && npx jest app/nrl/match/\\[season\\]/\\[round\\]/\\[no\\]/sections.test.ts`
Expected: PASS (2 tests). If it fails with a worker SIGSEGV, rerun once (known flake per Global Constraints).

- [ ] **Step 9: Write the client island**

Create `frontend/app/nrl/match/[season]/[round]/[no]/MatchIntelClient.tsx`:

```tsx
"use client";

import { useState } from "react";
import { sections } from "./sections";
import type { NrlMatchDetail, NrlProbHistory } from "@/lib/types";

/** Sticky section-pill nav + section renderer, driven entirely by the
 *  `sections` array -- Waves 2/3 extend the page by appending to that array,
 *  never by editing this file. */
export function MatchIntelClient({
  detail,
  probHistory,
}: {
  detail: NrlMatchDetail;
  probHistory: NrlProbHistory | null;
}) {
  const [active, setActive] = useState(sections[0]?.id ?? "");

  return (
    <div className="space-y-6">
      {detail.prediction?.predicted_total != null && (
        <div className="flex justify-center">
          <span className="rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-bold tabular-nums text-foreground">
            <span className="mr-1.5 font-semibold text-muted">Predicted total</span>
            <span>{Math.round(detail.prediction.predicted_total)} pts</span>
          </span>
        </div>
      )}

      <nav
        aria-label="Match sections"
        className="sticky top-0 z-10 -mx-4 flex gap-1 overflow-x-auto bg-background/95 px-4 py-2 backdrop-blur"
      >
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            onClick={() => setActive(s.id)}
            className={
              active === s.id
                ? "shrink-0 rounded-full bg-win/15 px-3 py-1.5 text-xs font-semibold text-lime-deep"
                : "shrink-0 rounded-full bg-surface-2 px-3 py-1.5 text-xs font-semibold text-muted hover:text-foreground"
            }
          >
            {s.label}
          </a>
        ))}
      </nav>

      {sections.map((s) => {
        const Section = s.render;
        return (
          <section key={s.id} id={s.id} className="scroll-mt-16">
            <Section detail={detail} probHistory={probHistory} />
          </section>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 10: Write the failing page-wiring test**

In `frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx`, add the new mocks (extend the existing `jest.mock`/mock-constant block at the top) and two new tests. Replace the top of the file through `afterEach` with:

```tsx
/** NRL match detail page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlMatchDetailPage from "./page";
import {
  getNrlLadderServer, getNrlMatchDetailServer, getNrlProbHistoryServer, getNrlRoundServer,
} from "@/lib/api";
import type { NrlMatch, NrlMatchDetail, NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockRound = getNrlRoundServer as jest.MockedFunction<typeof getNrlRoundServer>;
const mockLadder = getNrlLadderServer as jest.MockedFunction<typeof getNrlLadderServer>;
const mockDetail = getNrlMatchDetailServer as jest.MockedFunction<typeof getNrlMatchDetailServer>;
const mockProbHistory = getNrlProbHistoryServer as jest.MockedFunction<typeof getNrlProbHistoryServer>;

const match: NrlMatch = {
  id: 42,
  match_no: 3,
  kickoff_utc: "2026-07-11T09:35:00+00:00",
  venue: "Leichhardt Oval",
  home: "Wests Tigers",
  away: "Warriors",
  home_team_id: 17,
  away_team_id: 16,
  score_home: null,
  score_away: null,
  status: "scheduled",
  prediction: {
    p_home: 0.311,
    p_draw: 0.017,
    p_away: 0.672,
    expected_margin: -5.5,
    model_version: "nrl-elo-v0.1",
    created_at: "2026-07-06T00:00:00Z",
    is_shadow: true,
  },
};

const detail: NrlMatchDetail = {
  match: {
    id: 42, season: 2026, round: 19, match_no: 3,
    kickoff_utc: match.kickoff_utc, venue: match.venue,
    home: match.home, away: match.away,
    home_team_id: match.home_team_id, away_team_id: match.away_team_id,
    score_home: null, score_away: null, status: "scheduled",
  },
  prediction: {
    home_prob: 0.311, away_prob: 0.672, draw_prob: 0.017,
    predicted_margin: -6.0, predicted_total: 42.0,
    model_version: "nrl-elo-v0.1",
    preview_text: "Warriors are the model's pick.\n\nWarriors carry the bigger Elo rating.\n\nThe model's number: Warriors by 6.0.",
  },
  form: {
    home: { last5: [], avg_for: 0, avg_against: 0, avg_margin: 0 },
    away: { last5: [], avg_for: 0, avg_against: 0, avg_margin: 0 },
  },
  h2h: [],
  factors: [
    { key: "elo_gap", label: "Elo rating gap", weight: 0.5, favors: "away" },
    { key: "form_composite", label: "Recent form", weight: 0.3, favors: "away" },
    { key: "home_advantage", label: "Home advantage", weight: 0.2, favors: "home" },
  ],
};

const roundPayload = (m: NrlMatch): NrlMatchesResponse => ({
  season: 2026,
  rounds: [{ round: 19, matches: [m] }],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
});

const params = (season = "2026", round = "19", no = "3") =>
  Promise.resolve({ season, round, no });

beforeEach(() => {
  mockRound.mockResolvedValue(roundPayload(match));
  mockLadder.mockResolvedValue(null);
  mockDetail.mockResolvedValue(null);
  mockProbHistory.mockResolvedValue(null);
});
afterEach(() => jest.resetAllMocks());
```

Then append two new tests at the end of the file (after the last existing `it(...)` block):

```tsx
it("renders the Match Intelligence sections when the detail endpoint has data", async () => {
  mockDetail.mockResolvedValue(detail);
  render(await NrlMatchDetailPage({ params: params() }));

  // "Overview"/"Model" each appear twice (the sticky-nav pill AND the
  // section's own <h2>) -- query by heading role so the assertion is
  // unambiguous. "Form & H2H" is pill-only text (the section's own heading
  // reads "Form & head-to-head"), so plain getByText is unambiguous there.
  expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
  expect(screen.getByText("Form & H2H")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Model" })).toBeInTheDocument();
  expect(screen.getByText(/Warriors are the model's pick/)).toBeInTheDocument();
  expect(screen.getByText(/Predicted total/)).toBeInTheDocument();
  expect(screen.getByText("42 pts")).toBeInTheDocument();
});

it("renders without the Match Intelligence sections when the detail endpoint is unavailable", async () => {
  render(await NrlMatchDetailPage({ params: params() }));

  expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
  // The existing matchup content still renders (backward compatible).
  expect(screen.getByText(/Warriors to win · 67%/)).toBeInTheDocument();
});
```

- [ ] **Step 11: Run the test to verify it fails**

Run: `cd frontend && npx jest app/nrl/match/\\[season\\]/\\[round\\]/\\[no\\]/page.test.tsx`
Expected: FAIL — `getNrlMatchDetailServer`/`getNrlProbHistoryServer` not exported from the mocked module yet is fine (they exist from Step 2), but the page doesn't call them yet, so "Overview"/"Predicted total" assertions fail.

- [ ] **Step 12: Wire the page**

In `frontend/app/nrl/match/[season]/[round]/[no]/page.tsx`, add `export const revalidate = 300;` after the imports, add the new imports, and fetch + render the intelligence layer. Update the import block:

```tsx
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getNrlLadderServer, getNrlMatchDetailServer, getNrlProbHistoryServer, getNrlRoundServer,
} from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct } from "@/lib/format";
import { ClubBadge } from "@/components/ClubBadge";
import { LadderTable } from "@/components/LadderTable";
import { ShareButton } from "@/components/ShareButton";
import { MatchIntelClient } from "./MatchIntelClient";
import type { NrlMatch } from "@/lib/types";

export const revalidate = 300;
```

Keep the existing `<LocalKickoff iso={match.kickoff_utc} venue={match.venue} />` line inside `NrlMatchDetailPage` unchanged (controller reconciliation: viewer-local kickoff behavior is retained).

Replace the `NrlMatchDetailPage` function body's data-loading section (the two lines `const [found, ladder] = ...` through `if (!found) notFound();`) with:

```tsx
  const [found, ladder] = await Promise.all([
    loadMatch(ids.season, ids.round, ids.no),
    // Ladder context is secondary — a hiccup must not take down the page.
    getNrlLadderServer().catch(() => null),
  ]);
  if (!found) notFound();
  const { match, disclaimer } = found;

  // Match Intelligence sections are additive — a hiccup must not take down
  // the existing matchup/ladder content above. `match.id` comes straight out
  // of the round payload just fetched by loadMatch (NrlMatch now carries the
  // SportMatch id), so this needs no extra round lookup.
  const [detail, probHistory] = await Promise.all([
    getNrlMatchDetailServer(match.id).catch(() => null),
    getNrlProbHistoryServer(match.id).catch(() => null),
  ]);
```

Add the `MatchIntelClient` render right after the existing "ML model prediction on the way" conditional block (`{!p && !finished && (...)}`) and before the "Season context" `<section>`:

```tsx
      {detail && (
        <MatchIntelClient detail={detail} probHistory={probHistory} />
      )}
```

(KickoffVenue helper removed by controller reconciliation — `<LocalKickoff>` already renders kickoff + venue.)

- [ ] **Step 13: Run the test to verify it passes**

Run: `cd frontend && npx jest app/nrl/match/\\[season\\]/\\[round\\]/\\[no\\]/page.test.tsx`
Expected: PASS (all 9 tests: 7 existing + 2 new). If a worker SIGSEGV occurs, rerun once.

- [ ] **Step 14: Run the full frontend test suite and build**

Run: `cd frontend && npx jest`
Expected: PASS (rerun once if a worker SIGSEGV flake occurs)

Run: `cd frontend && npm run build`
Expected: build succeeds (no backend running — every new fetch path uses `.catch(() => null)`)

- [ ] **Step 15: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts \
        "frontend/app/nrl/match/[season]/[round]/[no]/sections.ts" \
        "frontend/app/nrl/match/[season]/[round]/[no]/sections.test.ts" \
        "frontend/app/nrl/match/[season]/[round]/[no]/OverviewSection.tsx" \
        "frontend/app/nrl/match/[season]/[round]/[no]/FormSection.tsx" \
        "frontend/app/nrl/match/[season]/[round]/[no]/ModelSection.tsx" \
        "frontend/app/nrl/match/[season]/[round]/[no]/MatchIntelClient.tsx" \
        "frontend/app/nrl/match/[season]/[round]/[no]/page.tsx" \
        "frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx" \
        "frontend/app/nrl/team/[id]/page.test.tsx" \
        frontend/components/__tests__/sportMatchCard.test.tsx
git commit -m "feat: Match Intelligence sections on the NRL match detail page"
```

---

### Task 7: Round pages `/nrl/round/[n]`

**Files:**
- Create: `frontend/app/nrl/round/[n]/page.tsx`
- Create: `frontend/app/nrl/round/[n]/page.test.tsx`

**Interfaces:**
- Consumes: `getNrlMatchesServer()` (existing, `frontend/lib/api.ts`), `SportMatchCard` (existing, unmodified).
- Produces: route `/nrl/round/[n]` — no new exports consumed elsewhere.

- [ ] **Step 1: Write the failing test**

Create `frontend/app/nrl/round/[n]/page.test.tsx`:

```tsx
/** NRL round page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlRoundPage from "./page";
import { getNrlMatchesServer } from "@/lib/api";
import type { NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockMatches = getNrlMatchesServer as jest.MockedFunction<typeof getNrlMatchesServer>;

const fixtures: NrlMatchesResponse = {
  season: 2026,
  rounds: [
    { round: 18, matches: [] },
    {
      round: 19,
      matches: [{
        id: 42, match_no: 3, kickoff_utc: "2026-07-11T09:35:00+00:00",
        venue: "Leichhardt Oval", home: "Wests Tigers", away: "Warriors",
        home_team_id: 17, away_team_id: 16, score_home: null, score_away: null,
        status: "scheduled", prediction: null,
      }],
    },
    { round: 20, matches: [] },
  ],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const params = (n = "19") => Promise.resolve({ n });

afterEach(() => jest.resetAllMocks());

it("renders the round heading and its fixtures", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params() }));

  expect(screen.getByText("Round 19")).toBeInTheDocument();
  expect(screen.getByText("Wests Tigers")).toBeInTheDocument();
});

it("links to the previous and next rounds", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params() }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).toContain("/nrl/round/18");
  expect(links).toContain("/nrl/round/20");
});

it("hides the previous link on the first round", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params("18") }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).not.toContain("/nrl/round/17");
  expect(links).toContain("/nrl/round/19");
});

it("calls notFound() for a round the API doesn't have", async () => {
  mockMatches.mockResolvedValue(fixtures);
  await expect(NrlRoundPage({ params: params("99") })).rejects.toThrow();
});

it("calls notFound() for a non-numeric round without hitting the API", async () => {
  await expect(NrlRoundPage({ params: params("abc") })).rejects.toThrow();
  expect(mockMatches).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx jest app/nrl/round/\\[n\\]/page.test.tsx`
Expected: FAIL — cannot find module `./page`

- [ ] **Step 3: Write the page**

Create `frontend/app/nrl/round/[n]/page.tsx`:

```tsx
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlMatchesServer } from "@/lib/api";
import { SportMatchCard } from "@/components/SportMatchCard";
import { APP_NAME } from "@/lib/constants";

export const revalidate = 300;

function parseRound(n: string): number | null {
  return /^\d+$/.test(n) ? Number(n) : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ n: string }>;
}): Promise<Metadata> {
  const { n } = await params;
  const round = parseRound(n);
  if (round == null) return { title: `NRL round — ${APP_NAME}` };
  return {
    title: `NRL round ${round} — ${APP_NAME}`,
    alternates: { canonical: `/nrl/round/${round}` },
  };
}

export default async function NrlRoundPage({
  params,
}: {
  params: Promise<{ n: string }>;
}) {
  const { n } = await params;
  const round = parseRound(n);
  if (round == null) notFound();

  const fixtures = await getNrlMatchesServer().catch(() => null);
  if (!fixtures) notFound();

  const roundNumbers = fixtures.rounds
    .map((r) => r.round)
    .filter((r): r is number => r != null)
    .sort((a, b) => a - b);
  const current = fixtures.rounds.find((r) => r.round === round);
  if (!current) notFound();

  const idx = roundNumbers.indexOf(round);
  const prevRound = idx > 0 ? roundNumbers[idx - 1] : null;
  const nextRound = idx >= 0 && idx < roundNumbers.length - 1 ? roundNumbers[idx + 1] : null;

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-extrabold">Round {round}</h1>
        <span className="text-sm text-muted">Season {fixtures.season}</span>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm">
        {prevRound != null ? (
          <Link href={`/nrl/round/${prevRound}`} className="font-semibold text-lime-deep">
            ← Round {prevRound}
          </Link>
        ) : (
          <span />
        )}
        {nextRound != null ? (
          <Link href={`/nrl/round/${nextRound}`} className="font-semibold text-lime-deep">
            Round {nextRound} →
          </Link>
        ) : (
          <span />
        )}
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {current.matches.map((m) => (
          <SportMatchCard
            key={m.match_no}
            match={m}
            eyebrow={`Round ${round}`}
            season={fixtures.season}
            round={round}
          />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx jest app/nrl/round/\\[n\\]/page.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/nrl/round/[n]/page.tsx" "frontend/app/nrl/round/[n]/page.test.tsx"
git commit -m "feat: add NRL round pages with prev/next navigation"
```

---

### Task 8: Ladder projections columns + movers link-through

**Files:**
- Modify: `frontend/components/LadderTable.tsx`
- Modify: `frontend/app/nrl/ladder/page.tsx`
- Modify: `backend/app/api/movers.py`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/components/MoversPanel.tsx`
- Test: `frontend/components/__tests__/ladderTable.test.tsx`
- Test: `backend/tests/test_movers_api.py`
- Test: `frontend/components/__tests__/moversPanel.test.tsx`

**Interfaces:**
- Consumes: Task 5's `GET /api/nrl/projections` via `getNrlProjectionsServer()` (Task 6).
- Produces: `LadderTable`'s new optional `projections?: Record<string, { top8: number; top4: number }>` prop; `Mover.match_url: string | null` (new field on the existing `GET /api/movers` response, populated for `sport=nrl` `win_match` rows only).

- [ ] **Step 1: Write the failing LadderTable test**

Append to `frontend/components/__tests__/ladderTable.test.tsx`:

```tsx
it("shows Top 8%/Top 4% columns when projections are provided", () => {
  render(
    <LadderTable
      rows={rows}
      projections={{ Panthers: { top8: 0.97, top4: 0.55 }, Rabbitohs: { top8: 0.62, top4: 0.1 } }}
    />,
  );
  expect(screen.getByText("Top 8%")).toBeInTheDocument();
  expect(screen.getByText("97%")).toBeInTheDocument();
  expect(screen.getByText("55%")).toBeInTheDocument();
});

it("hides the projections columns when the projections table is empty", () => {
  render(<LadderTable rows={rows} projections={{}} />);
  expect(screen.queryByText("Top 8%")).not.toBeInTheDocument();
});

it("hides the projections columns when no projections prop is passed", () => {
  render(<LadderTable rows={rows} />);
  expect(screen.queryByText("Top 8%")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/ladderTable.test.tsx`
Expected: FAIL — `Top 8%` text not found (prop not yet supported)

- [ ] **Step 3: Update `LadderTable`**

Replace the full contents of `frontend/components/LadderTable.tsx`:

```tsx
import Link from "next/link";
import { ClubBadge } from "@/components/ClubBadge";
import type { LadderRow } from "@/lib/types";

/** Standings table modeled on GroupTable; top-8 (finals) rows get the lime tint.
 *  Each club cell links through to its profile page. `projections` (Wave 1
 *  finals Monte Carlo, keyed by team name) adds Top 8%/Top 4% columns --
 *  hidden entirely when omitted or empty. */
export function LadderTable({
  rows,
  compact = false,
  projections,
}: {
  rows: LadderRow[];
  compact?: boolean;
  projections?: Record<string, { top8: number; top4: number }>;
}) {
  const shown = compact ? rows.slice(0, 4) : rows;
  const showProjections = !compact && !!projections && Object.keys(projections).length > 0;

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
          <th className="py-1.5 pr-2 font-semibold">Club</th>
          <th className="py-1.5 text-right font-semibold">P</th>
          {!compact && <th className="py-1.5 text-right font-semibold">W–L–D</th>}
          <th className="py-1.5 text-right font-semibold">Diff</th>
          <th className="py-1.5 text-right font-semibold">Pts</th>
          {showProjections && (
            <>
              <th className="py-1.5 text-right font-semibold">Top 8%</th>
              <th className="py-1.5 text-right font-semibold">Top 4%</th>
            </>
          )}
        </tr>
      </thead>
      <tbody>
        {shown.map((r) => {
          const proj = projections?.[r.name];
          return (
            <tr key={r.team_id}
                className={r.rank <= 8 ? "border-t border-border bg-win/[0.06]" : "border-t border-border"}>
              <td className="flex items-center gap-2 py-2 pr-2">
                <span className="w-5 text-xs tabular-nums text-muted">{r.rank}</span>
                <Link
                  href={`/nrl/team/${r.team_id}`}
                  className="flex min-w-0 items-center gap-2 underline-offset-2 hover:underline"
                >
                  <ClubBadge name={r.name} size={20} />
                  <span className="font-medium">{r.name}</span>
                </Link>
              </td>
              <td className="py-2 text-right tabular-nums">{r.played}</td>
              {!compact && (
                <td className="py-2 text-right tabular-nums">{r.wins}–{r.losses}–{r.draws}</td>
              )}
              <td className="py-2 text-right tabular-nums">{r.diff > 0 ? `+${r.diff}` : r.diff}</td>
              <td className="py-2 text-right font-bold tabular-nums">{r.points}</td>
              {showProjections && (
                <>
                  <td className="py-2 text-right tabular-nums text-muted">
                    {proj ? `${Math.round(proj.top8 * 100)}%` : "—"}
                  </td>
                  <td className="py-2 text-right tabular-nums text-muted">
                    {proj ? `${Math.round(proj.top4 * 100)}%` : "—"}
                  </td>
                </>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx jest components/__tests__/ladderTable.test.tsx`
Expected: PASS (4 tests: 1 existing + 3 new)

- [ ] **Step 5: Wire projections into the ladder page**

Replace `frontend/app/nrl/ladder/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlLadderServer, getNrlProjectionsServer } from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL ladder — FinalWhistle" };

export default async function NrlLadderPage() {
  const [ladder, projections] = await Promise.all([
    getNrlLadderServer().catch(() => null),
    getNrlProjectionsServer().catch(() => null),
  ]);
  if (!ladder) notFound();

  const projectionsByTeam = Object.fromEntries(
    (projections?.teams ?? []).map((t) => [t.team, { top8: t.top8, top4: t.top4 }]),
  );

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">
        NRL ladder · Season {ladder.season}
      </h1>
      <p className="mt-1 text-sm text-muted">Top 8 qualify for the finals.</p>
      <div className="glass mt-6 rounded-2xl p-4">
        <LadderTable rows={ladder.rows} projections={projectionsByTeam} />
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Write the failing movers backend test**

Append to `backend/tests/test_movers_api.py` (add `SportMatch, SportTeam` to the existing `from app.models import ...` line):

```python
from app.models import ProbabilitySnapshot, SportMatch, SportTeam, Team
```

```python
def test_nrl_win_match_movers_include_a_match_url():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Storm")
    eels = SportTeam(sport="nrl", name="Eels")
    db.add_all([storm, eels]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=5, match_no=12,
                   home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m); db.flush()
    d1, d2 = date(2026, 7, 8), date(2026, 7, 9)
    db.add_all([
        ProbabilitySnapshot(sport="nrl", entity_id=storm.id, market="win_match",
                            ref_id=m.id, prob=0.55, snapshot_date=d1),
        ProbabilitySnapshot(sport="nrl", entity_id=storm.id, market="win_match",
                            ref_id=m.id, prob=0.63, snapshot_date=d2),
    ])
    db.commit()

    body = client.get("/api/movers?sport=nrl").json()
    row = next(r for r in body["movers"] if r["entity_id"] == storm.id)
    assert row["match_url"] == "/nrl/match/2026/5/12"
    app.dependency_overrides.clear()


def test_nrl_movers_without_a_round_have_no_match_url():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Storm")
    eels = SportTeam(sport="nrl", name="Eels")
    db.add_all([storm, eels]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=None, match_no=12,
                   home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m); db.flush()
    db.add(ProbabilitySnapshot(sport="nrl", entity_id=storm.id, market="win_match",
                               ref_id=m.id, prob=0.55, snapshot_date=date(2026, 7, 9)))
    db.commit()

    body = client.get("/api/movers?sport=nrl").json()
    row = next(r for r in body["movers"] if r["entity_id"] == storm.id)
    assert row["match_url"] is None
    app.dependency_overrides.clear()


def test_football_movers_have_null_match_url():
    client, db = _client()
    usa = Team(name="United States", country_code="USA")
    db.add(usa); db.flush()
    db.add(ProbabilitySnapshot(sport="football", entity_id=usa.id, market="make_knockout",
                               prob=0.4, snapshot_date=date(2026, 7, 9)))
    db.commit()

    body = client.get("/api/movers?sport=football").json()
    assert body["movers"][0]["match_url"] is None
    app.dependency_overrides.clear()
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_movers_api.py -v -k match_url`
Expected: FAIL — `KeyError: 'match_url'`

- [ ] **Step 8: Add `match_url` to the movers endpoint**

In `backend/app/api/movers.py`, update the import line:

```python
from app.models import ProbabilitySnapshot, SportMatch, SportTeam, Team
```

`ref_id` needs to survive from `by_key` into `items` so the endpoint can resolve it to a URL. Replace the `items.append({...})` line inside the `for (entity_id, market, ref_id), by_day in by_key.items():` loop:

```python
        items.append({"entity_id": entity_id, "market": market, "ref_id": ref_id,
                      "prob": prob, "delta": delta, "series": series})
```

Replace the block from `model = SportTeam if sport == "nrl" else Team` to the end of the function:

```python
    model = SportTeam if sport == "nrl" else Team
    names = dict(
        db.query(model.id, model.name)
        .filter(model.id.in_([m["entity_id"] for m in items]))
        .all()
    ) if items else {}

    match_urls: dict[int, str] = {}
    if sport == "nrl":
        ref_ids = {
            m["ref_id"] for m in items
            if m["market"] == "win_match" and m["ref_id"] is not None
        }
        if ref_ids:
            for sm in db.query(SportMatch).filter(SportMatch.id.in_(ref_ids)).all():
                if sm.round is not None:
                    match_urls[sm.id] = f"/nrl/match/{sm.season}/{sm.round}/{sm.match_no}"

    for m in items:
        m["name"] = names.get(m["entity_id"], "Unknown")
        m["match_url"] = match_urls.get(m["ref_id"]) if sport == "nrl" else None
        del m["ref_id"]  # internal only -- keep the public shape unchanged otherwise

    return {
        "sport": sport,
        "as_of": latest.isoformat(),
        "movers": items,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_movers_api.py -v`
Expected: PASS (5 tests: 2 existing + 3 new)

- [ ] **Step 10: Update the frontend `Mover` type and `MoversPanel`**

In `frontend/lib/types.ts`, update `Mover`:

```ts
/** Daily probability swing row from GET /api/movers (spec 2026-07-09). */
export interface Mover {
  entity_id: number;
  name: string;
  market: string;
  prob: number;
  delta: number | null;
  series: number[];
  /** NRL win_match rows only: the match's detail-page URL, or null when the
   *  match has no round yet (TBC fixture) or for football rows. */
  match_url: string | null;
}
```

- [ ] **Step 11: Write the failing MoversPanel test**

Create `frontend/components/__tests__/moversPanel.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MoversPanel } from "@/components/MoversPanel";
import { getMovers } from "@/lib/api";
import type { Mover } from "@/lib/types";

jest.mock("@/lib/api");
const mockGetMovers = getMovers as jest.MockedFunction<typeof getMovers>;

const movers: Mover[] = [
  {
    entity_id: 16, name: "Warriors", market: "win_match",
    prob: 0.63, delta: 0.02, series: [0.6, 0.63], match_url: "/nrl/match/2026/19/3",
  },
];

afterEach(() => jest.resetAllMocks());

it("links an NRL win_match row to its match detail page", async () => {
  mockGetMovers.mockResolvedValue({
    sport: "nrl", as_of: "2026-07-10", movers,
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  });
  render(<MoversPanel sport="nrl" />);

  await waitFor(() => expect(screen.getByText("Warriors")).toBeInTheDocument());
  expect(screen.getByRole("link", { name: /Warriors/ })).toHaveAttribute(
    "href", "/nrl/match/2026/19/3",
  );
});

it("renders a plain row when match_url is null", async () => {
  mockGetMovers.mockResolvedValue({
    sport: "nrl", as_of: "2026-07-10",
    movers: [{ ...movers[0], match_url: null }],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  });
  render(<MoversPanel sport="nrl" />);

  await waitFor(() => expect(screen.getByText("Warriors")).toBeInTheDocument());
  expect(screen.queryByRole("link", { name: /Warriors/ })).not.toBeInTheDocument();
});
```

- [ ] **Step 12: Run the test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/moversPanel.test.tsx`
Expected: FAIL — no link found (row not yet wrapped)

- [ ] **Step 13: Wire the link into `MoversPanel`**

In `frontend/components/MoversPanel.tsx`, add the `Link` import (already imported) and replace the `<ul>` block's row markup:

```tsx
        <ul>
          {movers.map((m) => {
            const up = (m.delta ?? 0) >= 0;
            const rowInner = (
              <>
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
              </>
            );
            return (
              <li
                key={`${m.entity_id}-${m.market}`}
                className="flex items-center gap-3 border-t border-white/10 py-2.5 first:border-t-0"
              >
                {m.match_url ? (
                  <Link href={m.match_url} className="flex flex-1 items-center gap-3">
                    {rowInner}
                  </Link>
                ) : (
                  <div className="flex flex-1 items-center gap-3">{rowInner}</div>
                )}
              </li>
            );
          })}
        </ul>
```

- [ ] **Step 14: Run the test to verify it passes**

Run: `cd frontend && npx jest components/__tests__/moversPanel.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 15: Run the full test suites**

Run: `.venv/bin/python -m pytest backend ml pipeline -v`
Expected: PASS

Run: `cd frontend && npx jest`
Expected: PASS (rerun once if a worker SIGSEGV flake occurs)

Run: `cd frontend && npm run build`
Expected: build succeeds

- [ ] **Step 16: Commit**

```bash
git add frontend/components/LadderTable.tsx frontend/components/__tests__/ladderTable.test.tsx \
        frontend/app/nrl/ladder/page.tsx backend/app/api/movers.py backend/tests/test_movers_api.py \
        frontend/lib/types.ts frontend/components/MoversPanel.tsx \
        frontend/components/__tests__/moversPanel.test.tsx
git commit -m "feat: ladder finals projection columns and movers link-through"
```

---

### Task 9: Extend the e2e smoke workflow

**Files:**
- Modify: `.github/workflows/smoke.yml`

**Interfaces:**
- Consumes: nothing new (checks are plain `curl` calls against deployed URLs).
- Produces: nothing consumed by other tasks (last task in the wave).

- [ ] **Step 1: Add the new checks**

In `.github/workflows/smoke.yml`, extend the `check` call list (after the existing `check "$SITE/match/1/opengraph-image" "image/png"` line, before `exit $fail`):

```yaml
          check "$API/api/health" "application/json"
          check "$SITE/"
          check "$SITE/matches"
          check "$SITE/brackets"
          check "$SITE/my-bracket"
          check "$SITE/match/1"
          check "$SITE/team/1"
          check "$SITE/groups/1"
          check "$SITE/match/1/opengraph-image" "image/png"
          check "$API/api/nrl/matches" "application/json"
          check "$API/api/nrl/projections" "application/json"
          check "$SITE/nrl"
          check "$SITE/nrl/matches"
          check "$SITE/nrl/ladder"
          check "$SITE/nrl/round/1"

          exit $fail
```

This checks the new backend endpoints respond (`/api/nrl/matches`, `/api/nrl/projections`) and that the new/extended frontend surfaces render (`/nrl`, `/nrl/matches`, `/nrl/ladder`, `/nrl/round/1`). `/nrl/round/1` may 404 pre-season (no round 1 fixtures loaded yet) — that's an acceptable known gap for the schedule-triggered smoke run; if it proves noisy in practice, drop that one line rather than loosen the `check` function's pass criteria.

- [ ] **Step 2: Validate the YAML**

Run: `cd "/Users/macbookpro/Projects/FIFA WC26 Prediction" && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml'))" 2>/dev/null || python3 -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml'))"`
Expected: no output (valid YAML); if `yaml` isn't installed, visually re-check indentation instead — every new `check` line must be indented exactly like its neighbors.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/smoke.yml
git commit -m "test: extend the e2e smoke workflow for NRL match intelligence"
```

---

## Self-review notes (completed by the plan author)

- **Spec coverage:** All seven Wave 1 bullets are covered — margin+total model (Task 2), detail endpoint with factors (Task 5), finals projections Monte Carlo (Task 4), prose preview (Task 3), Match Intelligence page with hero/sticky nav/Overview/Form/Model (Task 6), round pages (Task 7), ladder projection columns (Task 8). Schema work is factored into its own Task 1 since both Task 3 and Task 4 depend on it. `nrl_matches`'s and `nrl_team`'s additive `id` fields (needed by every frontend task) are done in Task 5 alongside the endpoint that most needs them.
- **Placeholder scan:** No `TBD`/`TODO`/"add appropriate handling" language; every step has runnable code. The one deliberately-untested aspect (Task 2 Step 9, running the fit script against real data) is explicitly framed as optional/best-effort with a stated fallback, not a placeholder.
- **Type consistency:** `IntelSectionProps`/`IntelSection` (Task 6) match the spec's TS contract verbatim. `NrlMatchDetail`/`NrlProjectionsResponse`/`NrlProbHistory` field names match the API responses byte-for-byte across Tasks 5-6. `last_n_results`/`form_averages` (Task 3) are consumed with the same signature in Task 5. `predict_margin_total`/`load_margin_total_params` (Task 2) are consumed with the same signature in Task 3.
