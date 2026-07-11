# WC26 Match Writeup + Signal Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Fable-style four-section narrative writeup to every WC26 match prediction (deterministic template, no LLM), and make the odds-blend signal promotable with one command behind an inert `use_odds` flag plus an automated daily gate readout.

**Architecture:** A pure generator (`ml/explain/writeup.py`) turns the fields `build_payload()` already computes into `{case_home, case_away, call, caveat}` prose that structurally cannot contradict the numbers; it persists as a JSON column on `Prediction`, flows through `PredictionOut`, and renders in a new `MatchWriteup` component. The odds blend is factored into a shared `_odds_anchored()` helper used by both the shadow twin and a new production path gated on `use_odds: false`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / alembic / pytest; Next.js App Router / TypeScript / Jest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-07-11-wc26-writeup-and-signal-readiness-design.md`

## Global Constraints

- Production output with all new flags at defaults (`use_odds: false`) must be **bit-identical** to today. A regression test proves it.
- The writeup generator is **pure and deterministic**: no clock, no randomness, no DB access inside `ml/explain/writeup.py`. It never raises; it returns `None` on thin inputs.
- `model_params.json` `version` stays `"poisson-elo-v0.5"`; `use_odds` ships `false`; `w_odds` stays `0.35` (armed, shadow-only). **No promotion in this work.**
- Do not rename anything `pitchprophet-*`; the repo is private — push nothing to public destinations.
- Match each file's existing idiom: rich docstrings with FR/spec references, comment density, naming.
- Test commands: Python `.venv/bin/python -m pytest <path> -v` from the repo root; frontend `cd frontend && npx jest <file>`; full gate `make test` (root).
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Work happens on the current branch `feat/wc26-writeup-and-signal-readiness`. Task 1's commit is later split out as PR 1 (see Shipping Sequence).

---

### Task 1: Alembic migration — `predictions.writeup` column (PR 1 payload)

**Files:**
- Create: `backend/alembic/versions/<generated>_add_writeup_to_predictions.py`

**Interfaces:**
- Consumes: current alembic head `50c535d906b5` (add_nrl_team_lists_and_live_tables).
- Produces: a new head migration adding a nullable JSON `writeup` column to `predictions`. **No ORM/model change in this task** — the column must reach prod (via `refresh.yml`) before any code reads it (CLAUDE.md migration sequencing).

- [ ] **Step 1: Generate the revision skeleton**

Run from repo root:
```bash
cd backend && ../.venv/bin/alembic revision -m "add writeup to predictions" && cd ..
```
Expected: prints the path of a new file under `backend/alembic/versions/`. Note the generated `revision` id.

- [ ] **Step 2: Fill in the migration**

Replace the generated file's body so it reads (keep the generated `revision` id line exactly as generated; `down_revision` must be `"50c535d906b5"`):

```python
"""add writeup to predictions

Fable-style narrative sections for the match page (spec:
docs/superpowers/specs/2026-07-11-wc26-writeup-and-signal-readiness-design.md).
Nullable JSON — rows written before this feature simply have no writeup.
Migration-only PR: no code reads the column until it exists in prod
(CLAUDE.md migration sequencing).

Revision ID: <generated — do not edit>
Revises: 50c535d906b5
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated — do not edit>"
down_revision = "50c535d906b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("writeup", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "writeup")
```

- [ ] **Step 3: Verify the chain**

Run: `cd backend && ../.venv/bin/alembic heads && cd ..`
Expected: exactly one head — the new revision id.

- [ ] **Step 4: Run the Python suite (must be untouched)**

Run: `.venv/bin/python -m pytest`
Expected: PASS, same count as before this task.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/*add_writeup_to_predictions.py
git commit -m "feat(db): add predictions.writeup column (migration only)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Writeup generator — `ml/explain/writeup.py`

**Files:**
- Create: `ml/explain/writeup.py`
- Test: `ml/explain/writeup_test.py`

**Interfaces:**
- Consumes: `ml.features.build_features.MatchFeatures` (fields: `elo_home, elo_away, elo_diff, strength_source_home, strength_source_away, fifa_rank_diff, form_home, form_away, form_diff, goals_for_avg_home, goals_for_avg_away, is_home_host, h2h, data_points_home, data_points_away`).
- Produces (Tasks 3 depends on these exact names):
  - `WriteupInputs` frozen dataclass (fields below)
  - `build_writeup(w: WriteupInputs) -> dict | None` returning `{"case_home": str, "case_away": str, "call": str, "caveat": str}` or `None`
  - `one_in(p: float) -> str` phrasing helper

- [ ] **Step 1: Write the failing tests**

Create `ml/explain/writeup_test.py`:

```python
"""Tests for the Fable-style writeup generator: four labelled sections of
deterministic prose that structurally cannot contradict the stored numbers."""
from ml.explain.writeup import WriteupInputs, build_writeup, one_in
from ml.features.build_features import MatchFeatures


def _features(**overrides) -> MatchFeatures:
    base = dict(
        elo_home=2010.0, elo_away=1890.0, elo_diff=120.0,
        strength_source_home="elo", strength_source_away="elo",
        fifa_rank_diff=10, form_home=20.0, form_away=8.0, form_diff=12.0,
        goals_for_avg_home=2.2, goals_for_avg_away=1.0, is_home_host=False,
        h2h={"matches": 5, "a_wins": 4, "draws": 1, "b_wins": 0},
        data_points_home=10, data_points_away=10,
    )
    base.update(overrides)
    return MatchFeatures(**base)


def _inputs(**overrides) -> WriteupInputs:
    base = dict(
        home_name="England", away_name="Norway",
        prob_home=0.50, prob_draw=0.26, prob_away=0.24,
        score_home=2, score_away=1, score_prob=0.11,
        stage="quarterfinal", confidence="Medium", feats=_features(),
    )
    base.update(overrides)
    return WriteupInputs(**base)


def test_returns_all_four_nonempty_sections():
    w = build_writeup(_inputs())
    assert set(w) == {"case_home", "case_away", "call", "caveat"}
    assert all(isinstance(v, str) and v for v in w.values())


def test_deterministic():
    assert build_writeup(_inputs()) == build_writeup(_inputs())


def test_call_names_the_argmax_side_and_the_scoreline():
    w = build_writeup(_inputs())
    assert w["call"].startswith("England to win")
    assert "50%" in w["call"]
    assert "2–1" in w["call"]
    assert "11%" in w["call"]


def test_call_phrases_a_draw_argmax_as_too_close_to_call():
    w = build_writeup(_inputs(prob_home=0.30, prob_draw=0.40, prob_away=0.30,
                              score_home=1, score_away=1))
    assert w["call"].startswith("Too close to call")
    assert "40%" in w["call"]


def test_caveat_states_the_actual_draw_probability():
    w = build_writeup(_inputs())
    assert "26%" in w["caveat"]
    assert "one in 4" in w["caveat"]
    # Knockout stage → extra-time framing.
    assert "extra time" in w["caveat"].lower()


def test_caveat_flags_open_games_and_thin_data():
    w = build_writeup(_inputs(prob_home=0.40, prob_draw=0.30, prob_away=0.30,
                              confidence="Low", stage="group"))
    assert "open game" in w["caveat"]
    assert "thin" in w["caveat"]


def test_knockout_block_adds_advance_odds_to_the_call():
    ko = {"p_advance_home": 0.58, "p_advance_away": 0.42,
          "p_extra_time": 0.26, "p_shootout": 0.12,
          "paths": {"home": {"win_90": 0.5, "win_et": 0.05, "win_pens": 0.03},
                    "away": {"win_90": 0.24, "win_et": 0.1, "win_pens": 0.08}}}
    w = build_writeup(_inputs(knockout=ko))
    assert "58%" in w["call"]
    assert "England advance" in w["call"]


def test_market_agreement_lands_in_the_favourites_case():
    w = build_writeup(_inputs(market=(0.52, 0.26, 0.22)))
    assert "market agrees" in w["case_home"]
    assert "market agrees" not in w["case_away"]


def test_opponent_absences_strengthen_the_other_sides_case():
    w = build_writeup(_inputs(players_out_away=["Quansah", "Guehi"]))
    assert "Quansah" in w["case_home"]
    assert "Quansah" not in w["case_away"]


def test_none_on_thin_inputs_and_never_raises():
    assert build_writeup(_inputs(score_home=None, score_away=None, score_prob=None)) is None
    # Degenerate but non-None inputs must still produce text, not raise.
    bare = _inputs(feats=_features(form_diff=None, goals_for_avg_home=None,
                                   goals_for_avg_away=None,
                                   h2h={"matches": 0, "a_wins": 0, "draws": 0, "b_wins": 0}))
    assert build_writeup(bare) is not None


def test_one_in_phrasing():
    assert one_in(0.26) == "roughly one in 4"
    assert one_in(0.5) == "roughly one in 2"
    assert one_in(0.0) == "next to no chance"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/explain/writeup_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.explain.writeup'`

- [ ] **Step 3: Implement the generator**

Create `ml/explain/writeup.py`:

```python
"""Fable-style match writeup: four labelled sections of deterministic prose.

Presentation only. Every sentence is templated from a model field, so the text
can never disagree with the numbers it rides with — the model stays the brain,
this is the voice (spec: docs/superpowers/specs/
2026-07-11-wc26-writeup-and-signal-readiness-design.md). Pure function of its
inputs: no LLM, no randomness, no clock, no DB. Missing signals drop their
sentence; inputs too thin to say anything honest return None (the frontend
hides the section).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ml.features.build_features import MatchFeatures


def one_in(p: float) -> str:
    """'roughly one in N' for a probability (N = round(1/p))."""
    if p <= 0:
        return "next to no chance"
    return f"roughly one in {max(1, round(1 / p))}"


def _pct(p: float) -> str:
    return f"{round(p * 100)}%"


@dataclass(frozen=True)
class WriteupInputs:
    """Everything build_payload already computes, as plain values."""
    home_name: str
    away_name: str
    prob_home: float
    prob_draw: float
    prob_away: float
    score_home: int | None
    score_away: int | None
    score_prob: float | None
    stage: str                      # "group" or a knockout stage
    confidence: str                 # "High" | "Medium" | "Low"
    feats: MatchFeatures
    knockout: dict | None = None    # ml/models/knockout.py to_payload() shape
    market: tuple[float, float, float] | None = None  # implied (H, D, A) triple
    players_out_home: list[str] = field(default_factory=list)
    players_out_away: list[str] = field(default_factory=list)


def build_writeup(w: WriteupInputs) -> dict | None:
    """The four sections, or None when the prediction is too thin to narrate."""
    if w.score_home is None or w.score_away is None or w.score_prob is None:
        return None
    return {
        "case_home": _case(w, side="home"),
        "case_away": _case(w, side="away"),
        "call": _call(w),
        "caveat": _caveat(w),
    }


def _case(w: WriteupInputs, side: str) -> str:
    """One side's argument: a guaranteed probability sentence, then evidence in
    PRIORITY order — the match-specific signals (opponent absences, market
    lean) outrank the structural edges (Elo, form, goals, history, host),
    because the structural ones already live in the reasons list. Capped at 4
    sentences total, so priority decides what survives, not template order."""
    name = w.home_name if side == "home" else w.away_name
    opp = w.away_name if side == "home" else w.home_name
    p_win = w.prob_home if side == "home" else w.prob_away
    f = w.feats
    sentences = [f"The model gives {name} a {_pct(p_win)} chance of winning in 90 minutes."]

    elo_edge = f.elo_diff if side == "home" else -f.elo_diff
    if elo_edge >= 20:
        own = f.elo_home if side == "home" else f.elo_away
        other = f.elo_away if side == "home" else f.elo_home
        strength = "clearly the stronger side" if elo_edge >= 150 else "the stronger side"
        sentences.append(f"{name} rate as {strength} on Elo ({own:.0f} vs {other:.0f}).")

    opp_out = w.players_out_away if side == "home" else w.players_out_home
    if opp_out:
        listed = ", ".join(opp_out[:3])
        sentences.append(f"{opp}'s problems help the case — they are missing {listed}.")

    if w.market is not None:
        m_idx = max(range(3), key=lambda i: w.market[i])  # 0=H 1=D 2=A
        if m_idx == (0 if side == "home" else 2):
            sentences.append(
                f"The betting market agrees, making {name} favourites at {_pct(w.market[m_idx])}.")

    if f.form_diff is not None:
        form_edge = f.form_diff if side == "home" else -f.form_diff
        if form_edge >= 2:
            sentences.append(f"{name} also arrive in the better recent form.")

    if f.goals_for_avg_home is not None and f.goals_for_avg_away is not None:
        own_avg = f.goals_for_avg_home if side == "home" else f.goals_for_avg_away
        opp_avg = f.goals_for_avg_away if side == "home" else f.goals_for_avg_home
        if own_avg - opp_avg >= 0.5:
            sentences.append(
                f"They have been scoring more freely — {own_avg:.1f} a game to {opp}'s {opp_avg:.1f}.")

    own_wins = f.h2h["a_wins"] if side == "home" else f.h2h["b_wins"]
    opp_wins = f.h2h["b_wins"] if side == "home" else f.h2h["a_wins"]
    if f.h2h["matches"] > 0 and own_wins > opp_wins:
        sentences.append(
            f"History leans their way too: {own_wins} wins in the last {f.h2h['matches']} meetings.")

    if side == "home" and f.is_home_host:
        sentences.append(f"And {name} play this one at home as a tournament host.")

    return " ".join(sentences[:4])


def _call(w: WriteupInputs) -> str:
    """The headline: always the argmax outcome, so it structurally cannot
    contradict the served triple; the scoreline is the grid's own argmax and is
    reported as such (it may legitimately differ from the W/D/L lean)."""
    probs = {"home": w.prob_home, "draw": w.prob_draw, "away": w.prob_away}
    top = max(probs, key=lambda k: probs[k])
    score = f"{w.score_home}–{w.score_away}"
    if top == "draw":
        text = (f"Too close to call — the draw is the single most likely outcome at "
                f"{_pct(w.prob_draw)}, and {score} the most likely scoreline "
                f"(about {_pct(w.score_prob)}).")
    else:
        winner = w.home_name if top == "home" else w.away_name
        text = (f"{winner} to win — {_pct(probs[top])} in 90 minutes, with {score} the "
                f"single most likely scoreline (about {_pct(w.score_prob)}).")
    if w.knockout:
        adv_h = w.knockout["p_advance_home"]
        adv_a = w.knockout["p_advance_away"]
        favored, p_adv = (w.home_name, adv_h) if adv_h >= adv_a else (w.away_name, adv_a)
        text += (f" Over the full tie, {favored} advance in {_pct(p_adv)} of simulations, "
                 f"and there is a {_pct(w.knockout['p_extra_time'])} chance it goes past 90 minutes.")
    return text


def _caveat(w: WriteupInputs) -> str:
    """The honest bit: the draw stated plainly, openness, the upset chance,
    and a thin-data warning whenever confidence is Low."""
    if w.stage != "group":
        sentences = [
            f"A draw after 90 minutes is live at {one_in(w.prob_draw)} ({_pct(w.prob_draw)}), "
            f"so extra time or penalties would not shock."]
    else:
        sentences = [f"The draw is live at {one_in(w.prob_draw)} ({_pct(w.prob_draw)})."]
    if max(w.prob_home, w.prob_draw, w.prob_away) < 0.45:
        sentences.append("No outcome clears 45% — this is a genuinely open game.")
    underdog, p_up = ((w.away_name, w.prob_away) if w.prob_home >= w.prob_away
                      else (w.home_name, w.prob_home))
    sentences.append(f"{underdog} win outright in {_pct(p_up)} of the model's scenarios.")
    if w.confidence == "Low":
        sentences.append("The data behind this one is thin, so treat the numbers with extra care.")
    return " ".join(sentences)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest ml/explain/writeup_test.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/explain/writeup.py ml/explain/writeup_test.py
git commit -m "feat(ml): deterministic Fable-style writeup generator

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Persist the writeup — ORM column + pipeline wiring

**Files:**
- Modify: `backend/app/models/__init__.py` (Prediction class, after `top_features` around line 290)
- Modify: `pipeline/generate_predictions.py` (imports; `build_payload` before its return; the returned payload dict; `_write_prediction`)
- Test: `pipeline/writeup_pipeline_test.py` (create)

**Interfaces:**
- Consumes: `build_writeup(WriteupInputs) -> dict | None` and `WriteupInputs` from `ml.explain.writeup` (Task 2); existing `_latest_odds(db, match_id)`, `availability_for_match(db, match)` (returns `(off_home, off_away, expl_home, expl_away)` or None; each `expl` dict has a `players_out` list of dicts with a `name` key).
- Produces: `Prediction.writeup: Mapped[dict | None]` ORM column; payload key `"writeup"`; production rows persist it, shadow rows always store `None`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/writeup_pipeline_test.py`:

```python
"""Writeup persistence through the prediction pipeline: production rows carry
the four-section narrative; shadow twins stay lean (the writeup is
presentation, twins are internal-only and never rendered)."""
from app.models import Prediction, Team
from pipeline.generate_predictions import generate_predictions
from pipeline.ingest.wc26_structure import load_structure

MV = "poisson-elo-v0.1"


def _seed(db):
    load_structure(db)
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()
    generate_predictions(db, MV, n_sims=120, tournament_sims=50)


def test_production_rows_carry_a_writeup(db_session):
    _seed(db_session)
    prods = db_session.query(Prediction).filter(Prediction.is_shadow.is_(False)).all()
    assert prods
    for p in prods:
        assert p.writeup is not None
        assert set(p.writeup) == {"case_home", "case_away", "call", "caveat"}
        assert all(isinstance(v, str) and v for v in p.writeup.values())


def test_writeup_call_agrees_with_the_stored_triple(db_session):
    _seed(db_session)
    p = db_session.query(Prediction).filter(Prediction.is_shadow.is_(False)).first()
    top = max(p.prob_home_win, p.prob_draw, p.prob_away_win)
    if top == p.prob_draw:
        assert p.writeup["call"].startswith("Too close to call")
    else:
        assert p.writeup["call"].endswith(".") and " to win — " in p.writeup["call"]


def test_shadow_rows_stay_lean(db_session):
    _seed(db_session)
    shadows = db_session.query(Prediction).filter(Prediction.is_shadow.is_(True)).all()
    assert shadows
    assert all(s.writeup is None for s in shadows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/writeup_pipeline_test.py -v`
Expected: FAIL — `AttributeError` / `TypeError` around `writeup` (no such column/attribute).

- [ ] **Step 3: Add the ORM column**

In `backend/app/models/__init__.py`, inside `class Prediction`, directly after the `top_features` line:

```python
    # Fable-style narrative sections (ml/explain/writeup.py): {case_home,
    # case_away, call, caveat}. Deterministic template over THIS row's numbers —
    # presentation only, never an input to anything. NULL for shadow twins
    # (internal-only, never rendered) and rows written before the feature.
    writeup: Mapped[dict | None] = mapped_column(JSON)
```

- [ ] **Step 4: Wire generation into `build_payload` and persistence into `_write_prediction`**

In `pipeline/generate_predictions.py`:

(a) Add to the imports block (alphabetical, next to the other `ml.explain` import):

```python
from ml.explain.writeup import WriteupInputs, build_writeup
```

(b) In `build_payload()`, immediately after the `knockout` block (after the `if match.stage != "group":` block ends, before the `return {` statement), insert:

```python
    # Fable-style writeup (presentation only): templated from the SAME values
    # this payload serves, so the prose can never disagree with the numbers.
    # Market/availability context is optional colour — absent signals just
    # drop their sentence (ml/explain/writeup.py).
    market = None
    odds_row = _latest_odds(db, match.id)
    if odds_row is not None and None not in (
        odds_row.implied_prob_home, odds_row.implied_prob_draw, odds_row.implied_prob_away
    ):
        market = (odds_row.implied_prob_home, odds_row.implied_prob_draw,
                  odds_row.implied_prob_away)
    players_out_home: list[str] = []
    players_out_away: list[str] = []
    avail = availability_for_match(db, match)
    if avail is not None:
        _, _, expl_home, expl_away = avail
        players_out_home = [pl["name"] for pl in expl_home["players_out"]]
        players_out_away = [pl["name"] for pl in expl_away["players_out"]]
    writeup = build_writeup(WriteupInputs(
        home_name=home.name, away_name=away.name,
        prob_home=p_home, prob_draw=p_draw, prob_away=p_away,
        score_home=pred.score_home, score_away=pred.score_away,
        score_prob=pred.score_prob,
        stage=match.stage, confidence=confidence, feats=feats,
        knockout=knockout, market=market,
        players_out_home=players_out_home, players_out_away=players_out_away,
    ))
```

(c) In the returned payload dict, add one entry after `"top_features": factors,`:

```python
        "writeup": writeup,
```

(d) In `_write_prediction()`, in the `Prediction(...)` constructor, after `top_features=payload["top_features"],` add:

```python
            # Shadow twins spread the production payload, so they'd inherit its
            # writeup — null it: twins are internal-only and never rendered.
            writeup=payload.get("writeup") if not is_shadow else None,
```

- [ ] **Step 5: Run the new test, then the full Python suite**

Run: `.venv/bin/python -m pytest pipeline/writeup_pipeline_test.py -v`
Expected: 3 passed.
Run: `.venv/bin/python -m pytest`
Expected: all pass (existing payload-shape tests may need `"writeup"` added to any exact-keys assertion — if one fails, extend its expected key set; that is the only acceptable existing-test edit).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/__init__.py pipeline/generate_predictions.py pipeline/writeup_pipeline_test.py
git commit -m "feat(pipeline): generate and persist the match writeup on production predictions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Serve the writeup — schema + serializer

**Files:**
- Modify: `backend/app/schemas/__init__.py` (new `WriteupOut` before `PredictionOut`; new field on `PredictionOut`)
- Modify: `backend/app/serializers.py` (`prediction_to_out`, around line 151–188)
- Test: `backend/tests/test_writeup_serializer.py` (create)

**Interfaces:**
- Consumes: `Prediction.writeup` (Task 3).
- Produces: `PredictionOut.writeup: WriteupOut | None` with fields `case_home, case_away, call, caveat` (all `str`) — the frontend type in Task 5 mirrors this exactly.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_writeup_serializer.py`:

```python
"""prediction_to_out carries the stored writeup through to the API contract,
null-safe for pre-feature rows (writeup is NULL there)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Prediction, Team, Tournament
from app.serializers import prediction_to_out

WRITEUP = {
    "case_home": "The model gives England a 50% chance of winning in 90 minutes.",
    "case_away": "The model gives Norway a 24% chance of winning in 90 minutes.",
    "call": "England to win — 50% in 90 minutes, with 2–1 the single most likely scoreline (about 11%).",
    "caveat": "A draw after 90 minutes is live at roughly one in 4 (26%).",
}


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, writeup):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="England"), Team(name="Norway")
    db.add_all([wc, home, away])
    db.flush()
    m = Match(tournament_id=wc.id, stage="quarterfinal", status="scheduled",
              team_home_id=home.id, team_away_id=away.id)
    db.add(m)
    db.flush()
    pred = Prediction(match_id=m.id, model_version="poisson-elo-v0.5",
                      prob_home_win=0.5, prob_draw=0.26, prob_away_win=0.24,
                      predicted_score_home=2, predicted_score_away=1,
                      predicted_score_prob=0.11, writeup=writeup)
    db.add(pred)
    db.commit()
    return m, pred


def test_prediction_out_includes_writeup():
    db = _session()
    m, pred = _seed(db, WRITEUP)
    out = prediction_to_out(db, m, pred)
    assert out.writeup is not None
    assert out.writeup.case_home == WRITEUP["case_home"]
    assert out.writeup.call == WRITEUP["call"]
    assert out.writeup.caveat == WRITEUP["caveat"]


def test_prediction_out_writeup_is_null_safe():
    db = _session()
    m, pred = _seed(db, None)
    assert prediction_to_out(db, m, pred).writeup is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_writeup_serializer.py -v`
Expected: FAIL — `PredictionOut` has no `writeup` attribute.

- [ ] **Step 3: Add schema + serializer passthrough**

In `backend/app/schemas/__init__.py`, directly before `class PredictionOut`:

```python
class WriteupOut(BaseModel):
    """Fable-style narrative sections (ml/explain/writeup.py — deterministic
    template). Presentation of the stored numbers only; every sentence derives
    from a model field, so the prose can never disagree with the payload."""
    case_home: str
    case_away: str
    call: str
    caveat: str
```

In `PredictionOut`, after `knockout: KnockoutOut | None = None`:

```python
    writeup: WriteupOut | None = None
```

In `backend/app/serializers.py` `prediction_to_out(...)`, after the `knockout=...` line:

```python
        writeup=schemas.WriteupOut(**pred.writeup) if pred.writeup else None,
```

- [ ] **Step 4: Run the test, then the backend suite**

Run: `.venv/bin/python -m pytest backend/tests/test_writeup_serializer.py backend/tests -v`
Expected: new tests pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/serializers.py backend/tests/test_writeup_serializer.py
git commit -m "feat(api): serve prediction writeup in PredictionOut

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Render the writeup — frontend type, component, page

**Files:**
- Modify: `frontend/lib/types.ts` (new `Writeup` interface; new field on `Prediction`)
- Create: `frontend/components/MatchWriteup.tsx`
- Modify: `frontend/app/match/[id]/page.tsx` (import + first element of the overview tab)
- Test: `frontend/components/__tests__/matchWriteup.test.tsx` (create)

**Interfaces:**
- Consumes: `PredictionOut.writeup` (Task 4) — `{case_home, case_away, call, caveat}` strings or null.
- Produces: `MatchWriteup({home, away, writeup})` component, null-safe (renders nothing without a writeup).

- [ ] **Step 1: Write the failing test**

Create `frontend/components/__tests__/matchWriteup.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MatchWriteup } from "@/components/MatchWriteup";

const writeup = {
  case_home: "The model gives England a 50% chance of winning in 90 minutes.",
  case_away: "The model gives Norway a 24% chance of winning in 90 minutes.",
  call: "England to win — 50% in 90 minutes, with 2–1 the single most likely scoreline (about 11%).",
  caveat: "A draw after 90 minutes is live at roughly one in 4 (26%).",
};

test("renders all four labelled sections", () => {
  render(<MatchWriteup home="England" away="Norway" writeup={writeup} />);
  expect(screen.getByText("The case for England")).toBeInTheDocument();
  expect(screen.getByText("The case for Norway")).toBeInTheDocument();
  expect(screen.getByText("The call")).toBeInTheDocument();
  expect(screen.getByText("The honest caveat")).toBeInTheDocument();
  expect(screen.getByText(/2–1 the single most likely scoreline/)).toBeInTheDocument();
});

test("renders nothing without a writeup", () => {
  const { container } = render(
    <MatchWriteup home="England" away="Norway" writeup={null} />,
  );
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/matchWriteup.test.tsx`
Expected: FAIL — cannot resolve `@/components/MatchWriteup`.

- [ ] **Step 3: Add the type, the component, and the page integration**

In `frontend/lib/types.ts`, directly before `export interface Prediction {`:

```ts
/** Fable-style narrative writeup (deterministic template, generated by the
 *  model pipeline). Presentation of the numbers on this prediction only. */
export interface Writeup {
  case_home: string;
  case_away: string;
  call: string;
  caveat: string;
}
```

In `export interface Prediction`, after `knockout?: KnockoutAdvance | null;`:

```ts
  writeup?: Writeup | null;
```

Create `frontend/components/MatchWriteup.tsx`:

```tsx
import type { Writeup } from "@/lib/types";

/** Fable-style narrative writeup: the case for each side, the call, and the
 *  honest caveat. Deterministic prose generated by the pipeline from the same
 *  numbers this page displays — never an independent opinion. Renders nothing
 *  until the prediction carries a writeup (pre-feature rows have none). */
export function MatchWriteup({
  home,
  away,
  writeup,
}: {
  home: string;
  away: string;
  writeup: Writeup | null | undefined;
}) {
  if (!writeup) return null;
  const sections: Array<{ heading: string; body: string }> = [
    { heading: `The case for ${home}`, body: writeup.case_home },
    { heading: `The case for ${away}`, body: writeup.case_away },
    { heading: "The call", body: writeup.call },
    { heading: "The honest caveat", body: writeup.caveat },
  ];
  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">The breakdown</h2>
      <div className="space-y-4">
        {sections.map((s) => (
          <div key={s.heading}>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
              {s.heading}
            </h3>
            <p className="text-sm leading-relaxed text-foreground">{s.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

In `frontend/app/match/[id]/page.tsx`:
- Add to the component imports (alphabetical with the others):
  ```tsx
  import { MatchWriteup } from "@/components/MatchWriteup";
  ```
- Inside `<MatchTabs overview={<div className="space-y-6">`, insert as the FIRST child (before the `{/* Why ... */}` section):
  ```tsx
            {/* The breakdown — Fable-style narrative writeup (pipeline-generated,
                deterministic; hidden for pre-feature predictions). */}
            <MatchWriteup home={home} away={away} writeup={p.writeup} />
  ```

- [ ] **Step 4: Run the frontend gate**

Run: `cd frontend && npx jest components/__tests__/matchWriteup.test.tsx && npm run typecheck && npm run lint`
Expected: tests pass, typecheck clean, lint clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/types.ts frontend/components/MatchWriteup.tsx "frontend/app/match/[id]/page.tsx" frontend/components/__tests__/matchWriteup.test.tsx
git commit -m "feat(frontend): The breakdown — Fable-style writeup on the match page

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

**Spec note (availability path, resolved at planning time):** the spec's "verify the availability serving path" item is CLOSED — `build_payload()` already honors `use_availability` in production (`pipeline/generate_predictions.py:322-329`, sharing `_availability_adjusted` with the twin). No task needed.

### Task 6: `use_odds` — shared odds anchor + inert production serving path

**Files:**
- Modify: `ml/models/params.py` (new field + `load_params` line)
- Modify: `ml/models/model_params.json` (add `"use_odds": false`)
- Modify: `pipeline/generate_predictions.py` (new `_odds_anchored` helper; hook in `build_payload`; refactor `write_shadow_prediction` to use the helper)
- Test: `pipeline/odds_serving_test.py` (create)

**Interfaces:**
- Consumes: existing `_latest_odds`, `market_lambda_total`, `blend_lambda_total`, `predict_from_lambdas`, `effective_gap`, `_host_adv`.
- Produces: `ModelParams.use_odds: bool = False`; `_odds_anchored(db, match, lambda_home, lambda_away, strengths, params) -> MatchPrediction | None` in `pipeline/generate_predictions.py` (Task 7's promote script flips the flag).

- [ ] **Step 1: Write the failing tests**

Create `pipeline/odds_serving_test.py`:

```python
"""Production odds-serving path (spec Part 2): OFF is bit-identical (the null
guarantee the promotion gate depends on); ON serves exactly the anchored math
the shadow twin has been logging (_odds_anchored is shared by both paths)."""
from dataclasses import replace

import pipeline.generate_predictions as gp
from app.models import Match, Prediction, Team
from ml.models.params import DEFAULT_PARAMS
from pipeline.ingest.wc26_structure import load_structure

MV = "poisson-elo-v0.1"


def _seed(db):
    load_structure(db)
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _first_match(db):
    return (db.query(Match)
            .filter(Match.stage == "group", Match.team_home_id.isnot(None))
            .order_by(Match.id).first())


# _store_odds: seed one Odds row for the match. Copy the Odds(...) constructor
# call VERBATIM from pipeline/shadow_predictions_test.py::
# test_shadow_blends_lambda_total_toward_market (same fields, same idiom) —
# that test is the source of truth for a valid market snapshot.
def _store_odds(db, match):
    raise NotImplementedError("copy the Odds seeding from shadow_predictions_test")


def test_use_odds_off_is_bit_identical(db_session):
    """w_odds armed but use_odds False (today's shipped state): the served
    payload must not move even with a market snapshot stored."""
    _seed(db_session)
    m = _first_match(db_session)
    _store_odds(db_session, m)
    armed = gp.build_payload(db_session, m, MV,
                             params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=False))
    plain = gp.build_payload(db_session, m, MV,
                             params=replace(DEFAULT_PARAMS, w_odds=0.0, use_odds=False))
    assert armed["probabilities"] == plain["probabilities"]
    assert armed["lambda_home"] == plain["lambda_home"]
    assert armed["lambda_away"] == plain["lambda_away"]


def test_use_odds_on_moves_the_served_lambdas(db_session):
    _seed(db_session)
    m = _first_match(db_session)
    _store_odds(db_session, m)
    plain = gp.build_payload(db_session, m, MV,
                             params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=False))
    served = gp.build_payload(db_session, m, MV,
                              params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=True))
    assert (served["lambda_home"], served["lambda_away"]) != (
        plain["lambda_home"], plain["lambda_away"])


def test_use_odds_without_stored_odds_is_a_no_op(db_session):
    _seed(db_session)
    m = _first_match(db_session)  # no Odds row seeded
    on = gp.build_payload(db_session, m, MV,
                          params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=True))
    off = gp.build_payload(db_session, m, MV,
                           params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=False))
    assert on["probabilities"] == off["probabilities"]


def test_shadow_twin_mirrors_production_after_promotion(db_session, monkeypatch):
    """Post-promotion the twin must COPY production, not re-anchor already
    anchored lambdas (double blend) — record continuity for the null test."""
    _seed(db_session)
    m = _first_match(db_session)
    _store_odds(db_session, m)
    promoted = replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=True)
    monkeypatch.setattr(gp, "load_params", lambda: promoted)
    gp.generate_predictions(db_session, MV, n_sims=120, tournament_sims=50)
    prod = (db_session.query(Prediction)
            .filter_by(match_id=m.id, is_shadow=False).one())
    shad = (db_session.query(Prediction)
            .filter_by(match_id=m.id, is_shadow=True,
                       model_version=gp.SHADOW_MODEL_VERSION).one())
    assert (prod.prob_home_win, prod.prob_draw, prod.prob_away_win) == (
        shad.prob_home_win, shad.prob_draw, shad.prob_away_win)
    assert (prod.lambda_home, prod.lambda_away) == (shad.lambda_home, shad.lambda_away)
```

Then replace `_store_odds`'s `raise NotImplementedError(...)` with the copied `db.add(Odds(...)); db.commit()` from `pipeline/shadow_predictions_test.py::test_shadow_blends_lambda_total_toward_market` (add `Odds` to the imports). If `generate_predictions` takes params some other way than module-level `load_params` (check its body at line ~871), inject `promoted` the same way that file's existing tests do.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/odds_serving_test.py -v`
Expected: FAIL — `ModelParams` has no field `use_odds`.

- [ ] **Step 3: Implement**

(a) `ml/models/params.py` — in `ModelParams`, directly after the `use_availability` field:

```python
    # Market-odds anchoring in the PRODUCTION lambdas: False (the shipped
    # default) keeps serving bit-identical — w_odds > 0 alone only arms the
    # shadow twin (SHADOW_MODEL_VERSION). Flipped by pipeline/promote_blend.py
    # --use-odds once the shadow gate clears (docs/RUNBOOK-WC26-ENDGAME.md).
    use_odds: bool = False
```

In `load_params()`, after the `use_availability=...` line:

```python
        use_odds=bool(data.get("use_odds", False)),
```

(b) `ml/models/model_params.json` — add after the `"use_availability"` entry (keep formatting):

```json
  "use_odds": false,
```

(c) `pipeline/generate_predictions.py` — add the shared helper directly above `write_shadow_prediction`:

```python
def _odds_anchored(
    db: Session, match: Match, lambda_home: float, lambda_away: float,
    strengths: dict[int, float], params: ModelParams,
):
    """Market-anchored re-prediction of a lambda pair (FR-4.3), or None when no
    usable market total is stored. The ONE implementation shared by the shadow
    twin and the production path (use_odds), so promotion serves exactly the
    math the twin has been validating — never a reimplementation of it."""
    odds = _latest_odds(db, match.id)
    if odds is None:
        return None
    market_total = market_lambda_total(
        odds_over25=odds.odds_over25, odds_under25=odds.odds_under25,
        odds_home=odds.odds_home, odds_draw=odds.odds_draw, odds_away=odds.odds_away,
    )
    if market_total is None:
        return None
    lam_h, lam_a = blend_lambda_total(lambda_home, lambda_away, market_total, params.w_odds)
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    return predict_from_lambdas(
        lam_h, lam_a, rho=params.rho, temperature=params.temperature,
        calibrator=params.calibrator,
        eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
    )
```

(d) In `build_payload()`, directly after the `if params.use_availability:` block (before the booster/`wdl_blend` block), insert:

```python
    # Market-odds anchoring in the SERVED lambdas (the shadow twin's signal,
    # promoted): opt-in via model_params.json ("use_odds": false — the shipped
    # default — keeps this a strict no-op even while w_odds arms the twin).
    # Shares _odds_anchored with write_shadow_prediction, so promotion serves
    # exactly the math the twin has been logging.
    if params.use_odds and params.w_odds > 0:
        anchored = _odds_anchored(
            db, match, pred.lambda_home, pred.lambda_away, strengths, params)
        if anchored is not None:
            pred = anchored
```

(e) Refactor `write_shadow_prediction` to use the helper and to mirror production post-promotion. Replace its body from `shadow = payload` down to the final `_write_prediction(...)` with:

```python
    shadow = payload
    # Post-promotion (use_odds) the production payload already carries the
    # anchor; re-anchoring here would double-blend. The twin then mirrors
    # production exactly — record continuity, same as the pre-arming null.
    if params.w_odds > 0.0 and not params.use_odds:
        pred = _odds_anchored(
            db, match, payload["lambda_home"], payload["lambda_away"], strengths, params)
        if pred is not None:
            shadow = {
                **payload,
                "probabilities": {
                    "home_win": round(pred.prob_home_win, 4),
                    "draw": round(pred.prob_draw, 4),
                    "away_win": round(pred.prob_away_win, 4),
                },
                "predicted_score": {
                    "home": pred.score_home,
                    "away": pred.score_away,
                    "probability": round(pred.score_prob, 4),
                },
                "lambda_home": round(pred.lambda_home, 4),
                "lambda_away": round(pred.lambda_away, 4),
            }
    _write_prediction(db, match, shadow, SHADOW_MODEL_VERSION, is_shadow=True)
```

Keep the existing docstring, adding one line: `Post-promotion (params.use_odds) the twin copies production — the anchor already lives in the served lambdas.`

- [ ] **Step 4: Run the new tests, then the full Python suite**

Run: `.venv/bin/python -m pytest pipeline/odds_serving_test.py pipeline/shadow_predictions_test.py -v`
Expected: all pass — the refactor must not break the existing shadow tests.
Run: `.venv/bin/python -m pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ml/models/params.py ml/models/model_params.json pipeline/generate_predictions.py pipeline/odds_serving_test.py
git commit -m "feat(model): inert use_odds production serving path via shared _odds_anchored

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `promote_blend.py --use-odds`

**Files:**
- Modify: `pipeline/promote_blend.py`
- Test: `pipeline/promote_blend_test.py` (extend)

**Interfaces:**
- Consumes: `ModelParams.use_odds` (Task 6).
- Produces: `promoted_params(params, w_odds, use_availability, version, *, use_odds=False)` — keyword-only so existing positional callers keep working; CLI flag `--use-odds`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/promote_blend_test.py` (match its existing imports; add `pytest` if absent):

```python
def test_use_odds_requires_positive_weight():
    with pytest.raises(ValueError):
        promoted_params(load_params(), 0.0, True, "poisson-elo-v0.6", use_odds=True)


def test_use_odds_flips_the_serving_flag():
    p = promoted_params(load_params(), 0.35, False, "poisson-elo-v0.6", use_odds=True)
    assert p.use_odds is True
    assert p.w_odds == 0.35
    assert p.version == "poisson-elo-v0.6"


def test_use_odds_defaults_off():
    p = promoted_params(load_params(), 0.35, False, "poisson-elo-v0.6")
    assert p.use_odds is False
```

(If the file imports `promoted_params` differently, follow its idiom.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/promote_blend_test.py -v`
Expected: new tests FAIL — unexpected keyword `use_odds`.

- [ ] **Step 3: Implement**

In `pipeline/promote_blend.py`:

(a) Change the signature and body of `promoted_params`:

```python
def promoted_params(params: ModelParams, w_odds: float, use_availability: bool,
                    version: str, *, use_odds: bool = False) -> ModelParams:
    """The promoted engine: same params with the blend legs flipped on.

    ``use_odds`` flips the PRODUCTION serving path (generate_predictions
    _odds_anchored) — w_odds alone only arms the shadow twin."""
    if w_odds > W_ODDS_CAP:
        raise ValueError(f"w_odds {w_odds} exceeds cap {W_ODDS_CAP} (market is never primary)")
    if w_odds < 0:
        raise ValueError(f"w_odds must be >= 0, got {w_odds}")
    if use_odds and w_odds <= 0:
        raise ValueError("--use-odds requires w_odds > 0 (nothing to serve)")
    if w_odds == 0 and not use_availability:
        raise ValueError("nothing to promote: w_odds is 0 and use_availability is False")
    return replace(params, w_odds=w_odds, use_availability=use_availability,
                   use_odds=use_odds, version=version)
```

(b) In `main()`, add after the `--use-availability` argument:

```python
    parser.add_argument("--use-odds", action="store_true",
                        help="flip the PRODUCTION odds-serving path, not just the shadow arm")
```

and change the `promoted_params` call to:

```python
    shipped = promoted_params(load_params(), args.w_odds, args.use_availability,
                              args.version, use_odds=args.use_odds)
```

(c) Update the module docstring Usage line to:

```
    PYTHONPATH=backend:. python -m pipeline.promote_blend --w-odds 0.35 [--use-odds] [--use-availability] [--ship]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/promote_blend_test.py -v`
Expected: all pass (old + new).

- [ ] **Step 5: Commit**

```bash
git add pipeline/promote_blend.py pipeline/promote_blend_test.py
git commit -m "feat(promotion): --use-odds flips the production serving path

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `avg_log_loss` in the shadow-record endpoint

**Files:**
- Modify: `backend/app/api/internal.py` (`shadow_record`'s `aggregate()`, around line 237–245)
- Test: `backend/tests/test_shadow_record_api.py` (extend)

**Interfaces:**
- Consumes: `PredictionResult.log_loss` (existing column, nullable on old rows).
- Produces: each of `production` / `shadow` / `production_full_record` gains `"avg_log_loss": float | None` — Task 9's workflow gate reads `.shadow.n`, `.production.avg_log_loss`, `.shadow.avg_log_loss`.

- [ ] **Step 1: Extend the tests (write failing first)**

In `backend/tests/test_shadow_record_api.py`:

(a) In `_seed_results`'s `result(...)` helper, make log loss distinguishable: change the `PredictionResult(...)` call's `log_loss=0.5` to `log_loss=0.5 if not shadow else 0.4`.

(b) In `test_shadow_record_compares_production_and_shadow`, after the `avg_brier` assertion add:

```python
        assert prod["avg_log_loss"] == 0.5 and shad["avg_log_loss"] == 0.4
```

(c) In `test_shadow_record_is_honest_when_empty`, update the exact-dict assertion to include the new key:

```python
        assert body["production"] == {"n": 0, "exact_hits": 0, "winner_acc": None,
                                      "avg_brier": None, "avg_log_loss": None,
                                      "model_versions": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_shadow_record_api.py -v`
Expected: FAIL — `KeyError: 'avg_log_loss'`.

- [ ] **Step 3: Implement**

In `backend/app/api/internal.py`, inside `shadow_record`'s `aggregate()`, after the `avg_brier` entry:

```python
            # The runbook's promotion gate criterion is avg LOG LOSS (>=30
            # pairs AND the twin ahead) — Brier alone can't answer it. Old
            # rows may predate the column; average over the non-null values.
            "avg_log_loss": (
                round(sum(lls) / len(lls), 4)
                if (lls := [r.log_loss for r in rows if r.log_loss is not None])
                else None
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_shadow_record_api.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/internal.py backend/tests/test_shadow_record_api.py
git commit -m "feat(api): avg_log_loss in shadow-record — the gate's actual criterion

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Scheduled gate readout + runbook update

**Files:**
- Modify: `.github/workflows/shadow-record.yml`
- Modify: `docs/RUNBOOK-WC26-ENDGAME.md`

**Interfaces:**
- Consumes: `avg_log_loss` fields (Task 8); existing `API_URL` / `RECOMPUTE_TOKEN` secrets.
- Produces: daily 07:30 UTC run writing **GATE MET / GATE NOT MET (n=X/30, Δ log-loss=Y)** to the job summary. Read-only — no DB writes, no auto-promotion.

- [ ] **Step 1: Rewrite the workflow**

Replace `.github/workflows/shadow-record.yml` with:

```yaml
# Read-only evidence pull for the MANUAL shadow-promotion decision (FR-4.8):
# prints the production-vs-shadow record and the availability-twin record from
# the token-guarded internal endpoints, and evaluates the promotion gate
# (>=30 scored shadow pairs AND the twin ahead on avg log loss — see
# docs/RUNBOOK-WC26-ENDGAME.md) into the job summary. Writes nothing;
# NOTHING here auto-promotes. Same secrets as refresh-live / ops-flag-internal:
#   API_URL          e.g. https://pitchprophet-api.onrender.com
#   RECOMPUTE_TOKEN  same value as the backend's RECOMPUTE_TOKEN env var
name: shadow-record

on:
  workflow_dispatch: {}
  schedule:
    - cron: "30 7 * * *"  # daily, after the 06:00 UTC refresh has scored new pairs

jobs:
  readout:
    runs-on: ubuntu-latest
    steps:
      - name: GET shadow-record + availability-record, evaluate the gate
        env:
          API_URL: ${{ secrets.API_URL }}
          RECOMPUTE_TOKEN: ${{ secrets.RECOMPUTE_TOKEN }}
        run: |
          set -euo pipefail
          if [ -z "${API_URL:-}" ] || [ -z "${RECOMPUTE_TOKEN:-}" ]; then
            echo "API_URL / RECOMPUTE_TOKEN secrets not set — cannot call the API." >&2
            exit 1
          fi
          echo "== shadow-record (production vs odds-anchored twin, paired matches) =="
          SHADOW=$(curl -sfS -H "X-Recompute-Token: ${RECOMPUTE_TOKEN}" \
            "${API_URL}/api/internal/shadow-record")
          echo "$SHADOW" | jq .
          echo
          echo "== availability-record (availability twin vs published forecast) =="
          curl -sfS -H "X-Recompute-Token: ${RECOMPUTE_TOKEN}" \
            "${API_URL}/api/internal/availability-record" | jq .

          # Promotion gate (RUNBOOK-WC26-ENDGAME.md): >=30 scored shadow pairs
          # AND the odds-anchored twin ahead of production on avg log loss.
          N=$(echo "$SHADOW" | jq -r '.shadow.n')
          PROD_LL=$(echo "$SHADOW" | jq -r '.production.avg_log_loss')
          SHAD_LL=$(echo "$SHADOW" | jq -r '.shadow.avg_log_loss')
          STATUS="GATE NOT MET"
          DELTA="n/a"
          if [ "$PROD_LL" != "null" ] && [ "$SHAD_LL" != "null" ]; then
            DELTA=$(jq -n --argjson p "$PROD_LL" --argjson s "$SHAD_LL" '($p - $s) * 10000 | round / 10000')
            if [ "$N" -ge 30 ] && [ "$(jq -n --argjson p "$PROD_LL" --argjson s "$SHAD_LL" '$s < $p')" = "true" ]; then
              STATUS="GATE MET"
            fi
          fi
          {
            echo "## Odds-blend promotion gate"
            echo
            echo "**${STATUS}** — n=${N}/30, Δ avg log-loss (production − shadow) = ${DELTA}"
            echo
            echo "Gate: ≥30 scored shadow pairs AND the twin ahead on avg log loss (Δ > 0)."
            echo "When met, promotion stays MANUAL:"
            echo '`PYTHONPATH=backend:. python -m pipeline.promote_blend --w-odds 0.35 --use-odds --ship` via PR (stop gate).'
          } >> "$GITHUB_STEP_SUMMARY"
          echo "${STATUS} — n=${N}/30, delta=${DELTA}"
```

- [ ] **Step 2: Validate the YAML**

Run: `.venv/bin/python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/shadow-record.yml').read_text()); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Update the runbook**

In `docs/RUNBOOK-WC26-ENDGAME.md`, find the section describing the shadow gate / readout procedure and update it to state (adapting to the doc's existing voice and structure — read it first):

1. The readout now runs automatically every day at 07:30 UTC via `shadow-record.yml` (manual dispatch still works) and writes **GATE MET / GATE NOT MET (n=X/30, Δ avg log-loss)** to the workflow job summary — no more manual curls to check status.
2. The promotion command, once the summary says GATE MET, is now:
   `PYTHONPATH=backend:. python -m pipeline.promote_blend --w-odds 0.35 --use-odds --ship`
   (`--use-odds` flips the production serving path added 2026-07-11; `w_odds` alone only arms the twin). Ship it via PR through the stop gate — promotion stays a manual owner decision.

- [ ] **Step 4: Run the full Python suite (unchanged code paths)**

Run: `.venv/bin/python -m pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/shadow-record.yml docs/RUNBOOK-WC26-ENDGAME.md
git commit -m "feat(ops): daily shadow-record readout with GATE MET/NOT MET summary

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Full gate

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test gate**

Run from repo root: `make test`
Expected: Python suite AND frontend suite both pass. Paste the tail of the output as evidence.

- [ ] **Step 2: Frontend static gate**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean.

- [ ] **Step 3: Confirm bit-identical defaults one more time**

Run: `git diff main -- ml/models/model_params.json`
Expected: the ONLY change is the added `"use_odds": false` line — `version` still `poisson-elo-v0.5`, `w_odds` still `0.35`.

---

## Shipping Sequence (orchestrator only — every merge/dispatch is stop-gated)

1. **PR 1 — migration first.** `git branch feat/writeup-migration <sha-of-Task-1-commit>` and push it; open a PR titled "migration: predictions.writeup column". After CI is green → **stop gate**: summary + explicit "go" → merge.
2. **Dispatch `refresh.yml`** (applies `alembic upgrade head` to prod) — **stop gate**. Confirm the run succeeds before anything else merges.
3. **PR 2 — everything else.** Merge/rebase `main` into `feat/wc26-writeup-and-signal-readiness`, push, open the PR. CI green → **stop gate** → merge. Render auto-deploys the backend; Vercel the frontend.
4. **Verify prod:** `GET /api/health`; then an upcoming match payload (`/api/predictions/{id}`) — after the next refresh run it must contain a `writeup` whose numbers match its `probabilities`; view `/match/{id}` on the live site and confirm "The breakdown" renders. (Writeups appear as the daily refresh regenerates predictions for still-scheduled matches; frozen pre-kickoff rows keep `writeup: null` by design.)
5. Watch the first scheduled `shadow-record` run's job summary for the gate line.
