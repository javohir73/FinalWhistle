# Availability-record Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the availability twin's live evidence at a token-gated `GET /api/internal/availability-record`, computed on read from frozen `Prediction` rows.

**Architecture:** Extract the DB-gathering from the existing availability CLI into a reusable `availability_record(db)` that scores the twin vs the published forecast via the unchanged pure `benchmark_availability`; add one internal endpoint that lazy-imports and returns it, mirroring `shadow_record`. No persistence, no migration.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest (FastAPI `TestClient` + in-memory SQLite).

**Design spec:** `docs/superpowers/specs/2026-07-04-availability-record-endpoint-design.md`

## Global Constraints

- **No Alembic migration.** `prediction_results` is unchanged (odds-twin-only). The availability record is compute-on-read; nothing is persisted.
- **Internal-only, token-gated.** Reuse `_require_token` from `internal.py`: fail-closed **503** if `RECOMPUTE_TOKEN` unset, **401** on mismatch. Never public; nothing auto-promotes (FR-4.6/4.8).
- **Do NOT modify** `ml/evaluation/availability_benchmark.py::benchmark_availability` — reuse it exactly. It returns `{n_matches, production, availability, diff_log_loss, diff_ci95, availability_win_rate}`; `production`/`availability` are `compute_metrics` dicts = `{log_loss, brier, accuracy, n}`.
- **Machine-readable verdict strings** (exact values): `availability_beats_published` (CI hi < 0), `published_beats_availability` (CI lo > 0), `no_credible_difference` (straddles 0), `insufficient` (no data).
- **Honest-empty shape** (exact): `{"n_matches": 0, "verdict": "insufficient", "production": None, "availability": None, "diff_log_loss": None, "diff_ci95": None, "availability_win_rate": None}`.
- `AVAILABILITY_MODEL_VERSION = "poisson-elo-v0.3+avail"` — import it, never hardcode.
- **Tests never hit the network** and use in-memory SQLite (the `_client()` pattern from `backend/tests/test_shadow_record_api.py`).
- **Venv:** the worktree has no `.venv`. Before running tests: `ln -sfn "/Users/macbookpro/Projects/FIFA WC26 Prediction/.venv" .venv` (it is NOT gitignored — never `git add` it; stage only the named source/test files).

---

## File Structure

- `pipeline/run_availability_benchmark.py` — **modify.** Add `_verdict(...)` + `availability_record(db)`; refactor `main()` into a thin printer over it.
- `pipeline/run_availability_benchmark_test.py` — **create.** Unit tests for `availability_record(db)`.
- `backend/app/api/internal.py` — **modify.** Add the `GET /availability-record` endpoint.
- `backend/tests/test_availability_record.py` — **create.** Endpoint tests (cloned from `test_shadow_record_api.py`).

---

## Task 1: Extract `availability_record(db)` and thin the CLI

**Files:**
- Modify: `pipeline/run_availability_benchmark.py`
- Test: `pipeline/run_availability_benchmark_test.py`

**Interfaces:**
- Consumes: `benchmark_availability(prod_probs, avail_probs, labels) -> dict` (`ml/evaluation/availability_benchmark.py`); the existing `_latest(db, match_id, *, avail)` helper; `AVAILABILITY_MODEL_VERSION`.
- Produces: `availability_record(db) -> dict` — the `benchmark_availability` payload plus a `"verdict"` string, or the honest-empty dict. Consumed by Task 2's endpoint and by `main()`.

- [ ] **Step 1: Write the failing tests** (`pipeline/run_availability_benchmark_test.py`)

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Prediction, Team, Tournament
from ml.evaluation.availability_benchmark import benchmark_availability
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION
from pipeline.run_availability_benchmark import availability_record

_EMPTY = {"n_matches": 0, "verdict": "insufficient", "production": None,
          "availability": None, "diff_log_loss": None, "diff_ci95": None,
          "availability_win_rate": None}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _finished(db, wc, home, away, sh, sa):
    m = Match(tournament_id=wc.id, stage="group", status="finished",
              team_home_id=home.id, team_away_id=away.id, score_home=sh, score_away=sa)
    db.add(m); db.flush()
    return m


def _pred(db, m, mv, probs, *, is_shadow):
    db.add(Prediction(match_id=m.id, model_version=mv,
                      prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                      predicted_score_home=2, predicted_score_away=0, is_shadow=is_shadow))
    db.flush()


def _fixture(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    return wc, home, away


def test_scores_matches_with_both_rows():
    db = _session()
    wc, home, away = _fixture(db)
    m = _finished(db, wc, home, away, 2, 0)  # home win
    _pred(db, m, "poisson-elo-v0.2", (0.55, 0.25, 0.20), is_shadow=False)   # published
    _pred(db, m, AVAILABILITY_MODEL_VERSION, (0.70, 0.18, 0.12), is_shadow=True)  # twin, surer on H
    db.commit()

    rec = availability_record(db)
    direct = benchmark_availability([(0.55, 0.25, 0.20)], [(0.70, 0.18, 0.12)], ["H"])
    assert {k: rec[k] for k in direct} == direct          # same numbers as calling the scorer directly
    assert rec["verdict"] == "availability_beats_published"  # twin surer on the actual winner


def test_excludes_match_missing_twin():
    db = _session()
    wc, home, away = _fixture(db)
    m = _finished(db, wc, home, away, 1, 0)
    _pred(db, m, "poisson-elo-v0.2", (0.5, 0.3, 0.2), is_shadow=False)  # published only, no twin
    db.commit()
    assert availability_record(db) == _EMPTY


def test_honest_empty_with_no_data():
    assert availability_record(_session()) == _EMPTY
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/run_availability_benchmark_test.py -q`
Expected: FAIL — `ImportError: cannot import name 'availability_record'`.

- [ ] **Step 3: Implement `availability_record` + `_verdict`, refactor `main()`**

In `pipeline/run_availability_benchmark.py`, keep the existing imports and `_latest` helper. Add above `main()`:

```python
def _verdict(diff_ci95) -> str:
    lo, hi = diff_ci95
    if hi < 0:
        return "availability_beats_published"
    if lo > 0:
        return "published_beats_availability"
    return "no_credible_difference"


def availability_record(db) -> dict:
    """Paired availability-twin-vs-published record over finished matches.

    Compute-on-read over frozen Prediction rows (no persistence). Returns the
    benchmark_availability payload plus a machine-readable verdict, or the
    honest-empty dict when no finished match yet carries BOTH a published
    prediction and an availability twin."""
    prod_probs, avail_probs, labels = [], [], []
    finished = (db.query(Match)
                .filter(Match.status == "finished",
                        Match.score_home.isnot(None), Match.score_away.isnot(None))
                .all())
    for m in finished:
        prod = _latest(db, m.id, avail=False)
        avail = _latest(db, m.id, avail=True)
        if prod is None or avail is None:
            continue
        label = "H" if m.score_home > m.score_away else ("A" if m.score_home < m.score_away else "D")
        prod_probs.append((prod.prob_home_win, prod.prob_draw, prod.prob_away_win))
        avail_probs.append((avail.prob_home_win, avail.prob_draw, avail.prob_away_win))
        labels.append(label)
    if not labels:
        return {"n_matches": 0, "verdict": "insufficient", "production": None,
                "availability": None, "diff_log_loss": None, "diff_ci95": None,
                "availability_win_rate": None}
    res = benchmark_availability(prod_probs, avail_probs, labels)
    res["verdict"] = _verdict(res["diff_ci95"])
    return res
```

Replace the body of `main()` (everything inside the `try:`) with a thin printer over the record:

```python
def main() -> None:
    db = SessionLocal()
    try:
        rec = availability_record(db)
        if rec["n_matches"] == 0:
            print("No finished matches yet carry both a published prediction and an "
                  "availability twin. Nothing to benchmark.")
            return
        lo, hi = rec["diff_ci95"]
        print(f"=== Availability twin vs published ({rec['n_matches']} matches) ===")
        print(f"  production   log-loss: {rec['production']['log_loss']:.4f}")
        print(f"  availability log-loss: {rec['availability']['log_loss']:.4f}")
        print(f"  paired mean LL diff (avail - prod): {rec['diff_log_loss']:+.4f}  "
              f"CI95 [{lo:+.4f}, {hi:+.4f}]")
        print(f"  availability win rate: {rec['availability_win_rate']:.1%}")
        print(f"  verdict: {rec['verdict']}")
    finally:
        db.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/run_availability_benchmark_test.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/run_availability_benchmark.py pipeline/run_availability_benchmark_test.py
git commit -m "feat(availability-record): extract availability_record(db) from the CLI"
```

---

## Task 2: Add the token-gated internal endpoint

**Files:**
- Modify: `backend/app/api/internal.py`
- Test: `backend/tests/test_availability_record.py`

**Interfaces:**
- Consumes: `availability_record(db)` (Task 1); `_require_token` and `router` (already in `internal.py`).
- Produces: `GET /api/internal/availability-record` returning the availability record dict.

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_availability_record.py`)

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, Team, Tournament
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION

_EMPTY = {"n_matches": 0, "verdict": "insufficient", "production": None,
          "availability": None, "diff_log_loss": None, "diff_ci95": None,
          "availability_win_rate": None}


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
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


def _seed_pair(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    m = Match(tournament_id=wc.id, stage="group", status="finished",
              team_home_id=home.id, team_away_id=away.id, score_home=2, score_away=0)
    db.add(m); db.flush()
    for mv, probs, sh in (("poisson-elo-v0.2", (0.55, 0.25, 0.20), False),
                          (AVAILABILITY_MODEL_VERSION, (0.70, 0.18, 0.12), True)):
        db.add(Prediction(match_id=m.id, model_version=mv,
                          prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                          predicted_score_home=2, predicted_score_away=0, is_shadow=sh))
    db.commit()


def test_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "")
    client, _ = _client()
    try:
        assert client.get("/api/internal/availability-record").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        assert client.get("/api/internal/availability-record").status_code == 401
        assert client.get("/api/internal/availability-record",
                          headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_returns_paired_comparison(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        _seed_pair(TestingSession())
        r = client.get("/api/internal/availability-record",
                       headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        body = r.json()
        assert body["n_matches"] == 1
        assert body["verdict"] == "availability_beats_published"
        assert body["availability"]["log_loss"] < body["production"]["log_loss"]
    finally:
        app.dependency_overrides.clear()


def test_is_honest_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        body = client.get("/api/internal/availability-record",
                          headers={"X-Recompute-Token": "secret"}).json()
        assert body == _EMPTY
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_availability_record.py -q`
Expected: FAIL — the 200/empty tests fail with 404 (route not registered yet).

- [ ] **Step 3: Implement the endpoint**

Append to `backend/app/api/internal.py` (after `shadow_record`):

```python
@router.get("/availability-record")
def availability_record_endpoint(
    db: Session = Depends(get_db),
    x_recompute_token: str | None = Header(default=None),
):
    """Availability twin vs published forecast, paired on finished matches — the
    availability signal's ONLY evidence path (it is live-only; no backtest gate).
    Token-guarded and internal: the input to the MANUAL promotion decision
    (FR-4.8), nothing here auto-promotes. Compute-on-read over frozen Prediction
    rows — no persistence, no prediction_results row (that stays odds-only)."""
    _require_token(x_recompute_token)
    # Lazy import (call-time) mirrors this module's other pipeline imports and
    # avoids the app->pipeline cycle at load.
    from pipeline.run_availability_benchmark import availability_record

    return availability_record(db)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_availability_record.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Full backend/ml/pipeline suite + commit**

Run: `.venv/bin/python -m pytest backend ml pipeline -q`
Expected: PASS (all green, including the two new test files; nothing else changed).

```bash
git add backend/app/api/internal.py backend/tests/test_availability_record.py
git commit -m "feat(availability-record): token-gated GET /api/internal/availability-record"
```

---

## Self-Review (completed)

- **Spec coverage:** `availability_record(db)` extraction + verdict + honest-empty → Task 1; endpoint mirroring shadow_record (token gate, lazy import) → Task 2; both test sets → Tasks 1 & 2. No migration / no `prediction_results` change / internal-only / endpoint-only all honored. All spec sections covered.
- **Placeholder scan:** none — every step has real, runnable code and exact commands.
- **Type consistency:** `availability_record(db) -> dict` defined in Task 1 is imported and returned in Task 2; the honest-empty dict and verdict strings are identical across both test files and the implementation; `benchmark_availability` keys (`production`/`availability`/`diff_log_loss`/`diff_ci95`/`availability_win_rate`) match the response assertions; `AVAILABILITY_MODEL_VERSION` imported, never hardcoded.
