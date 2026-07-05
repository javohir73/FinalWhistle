# Market Comparison (model vs closing line) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the model-vs-market (closing-line) comparison live on the `/methodology` page via a new compute-on-read `GET /api/model/market-record`, and enable the odds capture that feeds it.

**Architecture:** Extract the DB-benchmark body of `run_market_benchmark.run_live` into a reusable `market_record(db)` returning the page-ready `MarketBenchmark` payload (honest-empty when nothing benchmarkable). A new public, cached endpoint lazy-imports it. The existing methodology "vs market" section moves into a pure `MarketComparison` component fed by a server fetch instead of a static JSON import. Odds capture is turned on by adding a human-set `API_FOOTBALL_API_KEY` to prod config.

**Tech Stack:** FastAPI + SQLAlchemy, pytest; Next.js App Router + TypeScript + Tailwind, Jest + @testing-library/react.

**Design spec:** `docs/superpowers/specs/2026-07-05-market-comparison-design.md`.

## Global Constraints

- **Reuse the existing benchmark core** — no change to `benchmark()`, `result_to_json()`, `_verdict()`, or the `Odds` schema. `market_record(db)` only *moves* `run_live`'s DB logic.
- **Honest-empty, not fake data** — when nothing is benchmarkable the payload is `status: "pending"` with `null` metrics; never invent numbers.
- **Honest framing** — the dataset label is "final pre-kickoff consensus we captured," NOT "closing line." No competitor naming (Polymarket/Kalshi).
- **No secret in code** — `render.yaml`/`refresh.yml` only *reference* `API_FOOTBALL_API_KEY`; the value is set by the human in Render + GitHub secrets with a freshly rotated key. Turning capture on is a **stop-gate** action.
- **Payload shape is fixed** by the frontend `MarketBenchmark` type: `status, dataset, n_matches, updated_at, model, market, diff_log_loss, diff_ci95, model_win_rate, mean_edge, verdict`.
- **Venv/commands:** backend `PYTHONPATH=backend:. .venv/bin/python -m pytest …`; frontend `cd frontend && npm test -- <pattern>` and `npm run typecheck` (node_modules already installed).

---

### Task 1: Backend — `market_record(db)` extraction

**Files:**
- Modify: `pipeline/run_market_benchmark.py`
- Test: `pipeline/run_market_benchmark_test.py` (create)

**Interfaces:**
- Consumes: `benchmark`, `result_to_json`, `MatchedMatch` (`ml/evaluation/market_benchmark.py`); ORM `Match`, `Odds`, `Prediction`, `Team`.
- Produces: `market_record(db) -> dict` — the `MarketBenchmark`-shaped payload (`status: "ready"` with metrics, or the honest-empty `status: "pending"` dict). `run_live` reduced to a thin CLI over it.

- [ ] **Step 1: Write the failing tests.** Create `pipeline/run_market_benchmark_test.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Odds, Prediction, Team, Tournament
from pipeline.run_market_benchmark import market_record


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _finished_match(db, wc, home, away, ko):
    m = Match(tournament_id=wc.id, team_home_id=home.id, team_away_id=away.id,
              stage="group", status="finished", score_home=2, score_away=0, kickoff_utc=ko)
    db.add(m); db.flush()
    return m


def test_market_record_scores_matches_with_odds_and_prediction():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = _finished_match(db, wc, home, away, ko)
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)))
    db.add(Odds(match_id=m.id, bookmaker="median",
                odds_home=1.6, odds_draw=3.8, odds_away=6.0,
                implied_prob_home=0.60, implied_prob_draw=0.26, implied_prob_away=0.14,
                captured_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)))
    db.commit()

    rec = market_record(db)
    assert rec["status"] == "ready"
    assert rec["n_matches"] == 1
    assert rec["model"] is not None and rec["market"] is not None
    assert isinstance(rec["diff_ci95"], list) and len(rec["diff_ci95"]) == 2
    assert rec["verdict"]  # a non-empty verdict string
    assert "closing line" not in (rec["dataset"] or "").lower()  # honest label


def test_market_record_is_honest_empty_without_odds():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = _finished_match(db, wc, home, away, ko)
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)))
    db.commit()  # no Odds row -> nothing benchmarkable

    rec = market_record(db)
    assert rec["status"] == "pending"
    assert rec["n_matches"] == 0
    assert rec["model"] is None and rec["market"] is None
    assert rec["diff_ci95"] is None and rec["verdict"] is None
```

- [ ] **Step 2: Run to verify they fail.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/run_market_benchmark_test.py -v`
Expected: FAIL — `ImportError: cannot import name 'market_record'`.

- [ ] **Step 3: Add `market_record(db)` and thin `run_live`.** In `pipeline/run_market_benchmark.py`, add a module-level honest-empty constant just after the `log = logging.getLogger(__name__)` line:

```python
_EMPTY_MARKET_RECORD = {
    "status": "pending", "dataset": None, "n_matches": 0, "updated_at": None,
    "model": None, "market": None, "diff_log_loss": None, "diff_ci95": None,
    "model_win_rate": None, "mean_edge": None, "verdict": None,
}
```

Add `market_record(db)` (holds the current `run_live` DB loop; label is honest, NOT "closing line"):

```python
def market_record(db) -> dict:
    """Model-vs-market comparison from the live DB, page-ready. Honest-empty
    (status='pending') when no finished match has both a pre-kickoff prediction
    and a captured odds snapshot. Pure of HTTP."""
    from app.models import Match, Odds, Prediction, Team
    from ml.evaluation.market_benchmark import MatchedMatch, benchmark, result_to_json

    id_to_name = {t.id: t.name for t in db.query(Team).all()}
    finished = (
        db.query(Match)
        .filter(Match.status == "finished")
        .filter(Match.team_home_id.isnot(None), Match.team_away_id.isnot(None))
        .order_by(Match.kickoff_utc.asc())
        .all()
    )

    matched: list[MatchedMatch] = []
    skipped_no_odds = skipped_no_pred = 0
    for m in finished:
        odds_q = db.query(Odds).filter(
            Odds.match_id == m.id, Odds.implied_prob_home.isnot(None)
        )
        if m.kickoff_utc is not None:
            odds_q = odds_q.filter(Odds.captured_at <= m.kickoff_utc)
        o = odds_q.order_by(Odds.captured_at.desc()).first()
        if o is None:
            skipped_no_odds += 1
            continue

        pred_q = db.query(Prediction).filter(
            Prediction.match_id == m.id, Prediction.is_shadow.is_(False)
        )
        if m.kickoff_utc is not None:
            pred_q = pred_q.filter(Prediction.created_at <= m.kickoff_utc)
        p = pred_q.order_by(Prediction.created_at.desc()).first()
        if p is None:
            skipped_no_pred += 1
            continue

        sh = m.score_home_90 if m.score_home_90 is not None else m.score_home
        sa = m.score_away_90 if m.score_away_90 is not None else m.score_away
        if sh is None or sa is None:
            continue
        label = "H" if sh > sa else ("A" if sh < sa else "D")
        matched.append(MatchedMatch(
            date=(m.kickoff_utc or datetime.now(timezone.utc)).date(),
            home=id_to_name.get(m.team_home_id, str(m.team_home_id)),
            away=id_to_name.get(m.team_away_id, str(m.team_away_id)),
            model_probs=(p.prob_home_win, p.prob_draw, p.prob_away_win),
            market_probs=(o.implied_prob_home, o.implied_prob_draw, o.implied_prob_away),
            label=label,
        ))

    log.info(
        "market record: finished=%d benchmarked=%d no_odds=%d no_pred=%d",
        len(finished), len(matched), skipped_no_odds, skipped_no_pred,
    )
    if not matched:
        return dict(_EMPTY_MARKET_RECORD)
    result = benchmark(matched)
    return result_to_json(
        result,
        "WC26 live (final pre-kickoff consensus we captured)",
        datetime.now(timezone.utc).isoformat(),
    )
```

Now replace the body of `run_live` (keep its signature `def run_live(emit_json: str | None = None) -> int:`) with a thin driver:

```python
def run_live(emit_json: str | None = None) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set")
        return 1
    db = sessionmaker(bind=create_engine(url, future=True), future=True)()

    rec = market_record(db)
    log.info("status=%s n_matches=%s verdict=%s",
             rec["status"], rec["n_matches"], rec.get("verdict"))
    if emit_json:
        with open(emit_json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, indent=2))
        log.info("wrote benchmark JSON -> %s", emit_json)
    return 0 if rec["status"] == "ready" else 1
```

(`json`, `os`, `datetime`, `timezone` are already imported at the top of the module. `_write_json` and `run_historical` are unchanged.)

- [ ] **Step 4: Run to verify they pass.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/run_market_benchmark_test.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit.**

```bash
git add pipeline/run_market_benchmark.py pipeline/run_market_benchmark_test.py
git commit -m "feat(market-record): extract market_record(db) from run_live (honest-empty when unbenchmarkable)"
```

---

### Task 2: Backend — public `GET /api/model/market-record`

**Files:**
- Create: `backend/app/api/market_record.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_market_record_api.py` (create)

**Interfaces:**
- Consumes: `market_record(db)` (Task 1, lazy-imported); `app.cache.cache`; `app.db.get_db`.
- Produces: `GET /api/model/market-record` → the `MarketBenchmark` payload, cached.

- [ ] **Step 1: Write the failing endpoint tests.** Create `backend/tests/test_market_record_api.py`:

```python
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Odds, Prediction, Team, Tournament


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
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


def test_market_record_empty_is_pending(client):
    c, _ = client
    r = c.get("/api/model/market-record")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["n_matches"] == 0
    assert body["model"] is None


def test_market_record_ready_when_benchmarkable(client):
    c, TestingSession = client
    db = TestingSession()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = Match(tournament_id=wc.id, team_home_id=home.id, team_away_id=away.id,
              stage="group", status="finished", score_home=2, score_away=0, kickoff_utc=ko)
    db.add(m); db.flush()
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)))
    db.add(Odds(match_id=m.id, bookmaker="median",
                odds_home=1.6, odds_draw=3.8, odds_away=6.0,
                implied_prob_home=0.60, implied_prob_draw=0.26, implied_prob_away=0.14,
                captured_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)))
    db.commit()

    body = c.get("/api/model/market-record").json()
    assert body["status"] == "ready"
    assert body["n_matches"] == 1
    assert body["verdict"]
```

- [ ] **Step 2: Run to verify they fail.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/test_market_record_api.py -v`
Expected: FAIL — 404 (route not mounted).

- [ ] **Step 3: Create the router.** Create `backend/app/api/market_record.py`:

```python
"""Public model-vs-market endpoint: the live closing-line comparison.

Compute-on-read over the captured Odds + pre-kickoff Prediction rows, mirroring
GET /api/model/record. Lazy-imports the pipeline so the app package does not
depend on pipeline at import time (same pattern as
/api/internal/availability-record).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.cache import cache
from app.db import get_db

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/market-record")
def market_record_endpoint(db: Session = Depends(get_db)):
    cached = cache.get("model:market-record")
    if cached is not None:
        return cached
    from pipeline.run_market_benchmark import market_record

    out = market_record(db)
    cache.set("model:market-record", out)
    return out
```

- [ ] **Step 4: Mount it.** In `backend/app/main.py`, add `market_record` to the `from app.api import (…)` block (the line listing `model_record`), and add the include next to the model_record one:

```python
app.include_router(model_record.router)
app.include_router(market_record.router)
```

- [ ] **Step 5: Run to verify they pass.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/test_market_record_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit.**

```bash
git add backend/app/api/market_record.py backend/app/main.py backend/tests/test_market_record_api.py
git commit -m "feat(market-record): public cached GET /api/model/market-record"
```

---

### Task 3: Frontend — live methodology comparison

**Files:**
- Modify: `frontend/lib/types.ts` (add `MarketBenchmark`)
- Modify: `frontend/lib/api.ts` (add `getMarketRecordServer`)
- Create: `frontend/components/MarketComparison.tsx`
- Create: `frontend/components/__tests__/marketComparison.test.tsx`
- Modify: `frontend/app/methodology/page.tsx` (async fetch + render the component)
- Delete: `frontend/lib/market-benchmark-data.json`

**Interfaces:**
- Consumes: `getMarketRecordServer(): Promise<MarketBenchmark | null>`.
- Produces: `MarketComparison({ bench }: { bench: MarketBenchmark })`.

- [ ] **Step 1: Add the `MarketBenchmark` type.** In `frontend/lib/types.ts`, append:

```typescript
export interface MarketBenchmark {
  status: string; // "pending" | "ready"
  dataset: string | null;
  n_matches: number;
  updated_at: string | null;
  model: { log_loss: number; brier: number; accuracy: number } | null;
  market: { log_loss: number; brier: number; accuracy: number } | null;
  diff_log_loss: number | null;
  diff_ci95: [number, number] | null;
  model_win_rate: number | null;
  mean_edge: number | null;
  verdict: string | null;
}
```

- [ ] **Step 2: Add the server fetcher.** In `frontend/lib/api.ts`, next to `getModelRecordServer`, add (and add `MarketBenchmark` to the existing `import … from "./types"`):

```typescript
export const getMarketRecordServer = () =>
  getServer<MarketBenchmark>("/api/model/market-record", 300);
```

- [ ] **Step 3: Write the failing component test.** Create `frontend/components/__tests__/marketComparison.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MarketComparison } from "@/components/MarketComparison";
import type { MarketBenchmark } from "@/lib/types";

const pending: MarketBenchmark = {
  status: "pending", dataset: null, n_matches: 0, updated_at: null,
  model: null, market: null, diff_log_loss: null, diff_ci95: null,
  model_win_rate: null, mean_edge: null, verdict: null,
};

const ready: MarketBenchmark = {
  status: "ready", dataset: "WC26 live (final pre-kickoff consensus we captured)",
  n_matches: 20, updated_at: "2026-07-05T00:00:00+00:00",
  model: { log_loss: 0.98, brier: 0.59, accuracy: 0.6 },
  market: { log_loss: 0.95, brier: 0.57, accuracy: 0.62 },
  diff_log_loss: 0.03, diff_ci95: [-0.01, 0.07], model_win_rate: 0.45, mean_edge: -0.01,
  verdict: "NO CREDIBLE DIFFERENCE (CI straddles 0)",
};

it("shows the pending copy before any benchmarked match", () => {
  render(<MarketComparison bench={pending} />);
  expect(screen.getByText(/results publish here after the first benchmarked match day/i)).toBeInTheDocument();
  expect(screen.queryByText(/Model vs\.? market/i)).not.toBeInTheDocument();
});

it("shows the comparison table and verdict when ready", () => {
  render(<MarketComparison bench={ready} />);
  expect(screen.getByText(/No credible difference/i)).toBeInTheDocument();
  expect(screen.getByText(/20 matches/)).toBeInTheDocument();
  expect(screen.getByText(/final pre-kickoff consensus/i)).toBeInTheDocument();
});
```

- [ ] **Step 4: Run to verify it fails.**

Run: `cd frontend && npm test -- marketComparison`
Expected: FAIL — cannot resolve `@/components/MarketComparison`.

- [ ] **Step 5: Implement `MarketComparison`.** Create `frontend/components/MarketComparison.tsx` (moves the existing methodology market section; self-contained — own rows + verdict badge):

```tsx
import type { MarketBenchmark } from "@/lib/types";

const fmt = (n: number) => n.toFixed(3);

export function MarketComparison({ bench }: { bench: MarketBenchmark }) {
  if (bench.status !== "ready" || !bench.model || !bench.market) {
    return (
      <div className="glass mt-4 rounded-2xl p-6">
        <p className="text-sm leading-relaxed text-muted">
          Beating naive baselines is the entry bar; the{" "}
          <strong className="text-foreground/80">market&apos;s final pre-kickoff consensus</strong>{" "}
          — the sharpest public forecast there is, with its margin removed — is the real one.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Every WC26 prediction is logged{" "}
          <strong className="text-foreground/80">pre-kickoff, next to the consensus odds we captured</strong>,
          so the two are scored on exactly the same matches. Results publish here after the
          first benchmarked match day.
        </p>
      </div>
    );
  }

  const modelWins = bench.diff_log_loss !== null && bench.diff_log_loss < 0;
  return (
    <div className="mt-4 space-y-5">
      <p className="text-sm leading-relaxed text-muted">
        The market&apos;s final pre-kickoff consensus we captured — margin removed — is the
        sharpest public forecast there is. Each WC26 prediction is logged pre-kickoff next to
        those odds, so both are scored on exactly the same matches.
      </p>
      <VerdictBadge verdict={bench.verdict ?? ""} />
      <div className="glass rounded-2xl p-4 sm:p-5">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="font-display font-bold">Model vs. market</h3>
          <span className="text-xs text-muted">{bench.n_matches} matches</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider text-muted">
                <th className="px-2 pb-2 text-left font-medium">Predictor</th>
                <th className="px-2 pb-2 text-right font-medium" title="Lower is better">Log-loss</th>
                <th className="px-2 pb-2 text-right font-medium" title="Lower is better">Brier</th>
                <th className="px-2 pb-2 text-right font-medium" title="Higher is better">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              <MetricRow label="FinalWhistle model" m={bench.model} highlight={modelWins} />
              <MetricRow label="Market consensus" m={bench.market} highlight={!modelWins} />
            </tbody>
          </table>
        </div>
      </div>
      {bench.diff_log_loss !== null && bench.diff_ci95 && (
        <p className="text-xs leading-relaxed text-muted">
          Paired mean log-loss difference (model − market):{" "}
          <span className="tabular-nums text-foreground/80">
            {bench.diff_log_loss >= 0 ? "+" : ""}{bench.diff_log_loss.toFixed(4)}
          </span>{" "}
          (95% CI{" "}
          <span className="tabular-nums text-foreground/80">
            [{bench.diff_ci95[0].toFixed(4)}, {bench.diff_ci95[1].toFixed(4)}]
          </span>
          ). {bench.dataset}. Updated {bench.updated_at}.
        </p>
      )}
    </div>
  );
}

function MetricRow({
  label, m, highlight,
}: {
  label: string;
  m: { log_loss: number; brier: number; accuracy: number };
  highlight: boolean;
}) {
  return (
    <tr className={`border-t border-border/50 ${highlight ? "bg-win/[0.06]" : ""}`}>
      <td className={`px-2 py-2.5 font-medium ${highlight ? "text-lime-deep" : ""}`}>{label}</td>
      <td className="px-2 text-right tabular-nums">{fmt(m.log_loss)}</td>
      <td className="px-2 text-right tabular-nums text-muted">{fmt(m.brier)}</td>
      <td className="px-2 text-right tabular-nums text-muted">{Math.round(m.accuracy * 100)}%</td>
    </tr>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const modelWins = verdict.startsWith("MODEL BEATS MARKET");
  const marketWins = verdict.startsWith("MARKET BEATS MODEL");
  const label = modelWins ? "Model beats market"
    : marketWins ? "Market beats model" : "No credible difference";
  const cls = modelWins ? "bg-win/[0.06] text-lime-deep ring-1 ring-win/40"
    : marketWins ? "border-gold/20 bg-gold/[0.04] text-gold ring-1 ring-gold/30"
    : "chip text-muted";
  return (
    <div className={`glass inline-flex items-center rounded-full px-4 py-1.5 text-sm font-bold ${cls}`}>
      {label}
    </div>
  );
}
```

- [ ] **Step 6: Run to verify the component test passes.**

Run: `cd frontend && npm test -- marketComparison`
Expected: PASS (2 tests).

- [ ] **Step 7: Repoint the methodology page.** In `frontend/app/methodology/page.tsx`:
  1. Remove `import rawBenchmark from "@/lib/market-benchmark-data.json";` and the local `MarketBenchmark` interface + `const bench = rawBenchmark as MarketBenchmark;`.
  2. Add imports: `import { getMarketRecordServer } from "@/lib/api";` and `import { MarketComparison } from "@/components/MarketComparison";` and `import type { MarketBenchmark } from "@/lib/types";`.
  3. Make the component async and fetch the record at the top:

```tsx
export default async function MethodologyPage() {
  const beatsBaselines = data.years.filter((y) => bestLogLoss(y) === "model").length;
  const PENDING: MarketBenchmark = {
    status: "pending", dataset: null, n_matches: 0, updated_at: null,
    model: null, market: null, diff_log_loss: null, diff_ci95: null,
    model_win_rate: null, mean_edge: null, verdict: null,
  };
  let bench: MarketBenchmark = PENDING;
  try {
    bench = (await getMarketRecordServer()) ?? PENDING;
  } catch {
    bench = PENDING;
  }
```

  4. Replace the entire `{/* Vs the market … */}` section's inner `{bench.status !== "ready" ? ( … ) : ( … )}` block with `<MarketComparison bench={bench} />` (keep the section wrapper + its `<h2>How does it compare to the market?</h2>`).
  5. Delete the now-unused local `VerdictBadge` function at the bottom of the file (moved into `MarketComparison`). Keep `Stat`, `Row`, `Term`, `fmt`, `listYears`, `bestLogLoss`.

- [ ] **Step 8: Delete the stale JSON.** Confirm nothing else imports it, then delete:

```bash
cd frontend && grep -rn "market-benchmark-data" app components lib | grep -v node_modules
rm lib/market-benchmark-data.json
```
Expected: the grep prints nothing (only the methodology import existed, now removed) before the `rm`.

- [ ] **Step 9: Typecheck, then commit.**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/MarketComparison.tsx \
        frontend/components/__tests__/marketComparison.test.tsx frontend/app/methodology/page.tsx
git rm frontend/lib/market-benchmark-data.json
git commit -m "feat(market-record): live methodology comparison via /api/model/market-record"
```

---

### Task 4: Enablement config (⚠️ STOP-GATE — no secret in code)

**Files:**
- Modify: `render.yaml`
- Modify: `.github/workflows/refresh.yml`

**Interfaces:** none (config only). Turns on `refresh_odds` in `run_pipeline` once the human sets the secret value.

- [ ] **Step 1: Reference the key in `render.yaml`.** In the backend service's `envVars:` list (next to `FOOTBALL_DATA_API_KEY`), add:

```yaml
      - key: API_FOOTBALL_API_KEY
        sync: false
```

(`sync: false` = the value is set in the Render dashboard, never committed.)

- [ ] **Step 2: Pass the key to the pipeline in `refresh.yml`.** In `.github/workflows/refresh.yml`, add `API_FOOTBALL_API_KEY` to the env of the "Run full pipeline" step (next to `DATABASE_URL` / `PYTHONPATH`):

```yaml
          API_FOOTBALL_API_KEY: ${{ secrets.API_FOOTBALL_API_KEY }}
```

- [ ] **Step 3: Validate the YAML parses (read-only).**

Run: `PYTHONPATH=backend:. .venv/bin/python -c "import yaml; yaml.safe_load(open('render.yaml')); yaml.safe_load(open('.github/workflows/refresh.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 4: Commit.**

```bash
git add render.yaml .github/workflows/refresh.yml
git commit -m "feat(market-record): wire API_FOOTBALL_API_KEY to enable odds capture (value human-set)"
```

- [ ] **Step 5: ⚠️ STOP-GATE (do NOT do this in the build; it is for the human at deploy).** Rotate the API-Football key, set `API_FOOTBALL_API_KEY` in the Render dashboard AND as a GitHub Actions secret, then the next `refresh.yml` run begins capturing odds snapshots. This spends external API quota and touches prod → present a plain-English summary and wait for an explicit "go" before doing it.

---

### Task 5: Whole-suite verification + PR

- [ ] **Step 1: Backend suite.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest backend ml pipeline -q`
Expected: all green (additive endpoint + extracted function; no existing test regresses).

- [ ] **Step 2: Frontend gate.**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: typecheck clean, lint clean, all tests pass (incl. `marketComparison`).

- [ ] **Step 3: Paste the real output** into the PR description. Open a PR (`feat/market-record` → `main`); a human merges. The PR description must note Task 4 Step 5 (rotate + set the secret) as the post-merge stop-gate activation.

---

## Self-Review

- **Spec coverage:** `market_record(db)` extraction + honest-empty + thin `run_live` (spec "Backend") → Task 1; public cached endpoint lazy-importing it + main.py mount (spec "Backend") → Task 2; `getMarketRecordServer` + `MarketBenchmark` in types + async methodology fetch + `MarketComparison` + delete static JSON + honest wording (spec "Frontend") → Task 3; enablement config with no secret in code + stop-gate (spec "Enablement") → Task 4; states/errors — pending fallback on null/throw (spec "States & errors") → Task 3 Step 7; testing (spec "Testing") → Tasks 1–3 named tests + Task 5 gate. Out-of-scope items (competitor naming, near-kickoff capture, odds-math/schema) absent by construction.
- **Placeholder scan:** none — every step has runnable code/commands.
- **Type consistency:** `market_record(db) -> dict` produced in Task 1, lazy-imported identically in Task 2; the honest-empty dict keys match the `MarketBenchmark` TS interface added in Task 3 Step 1 (`status, dataset, n_matches, updated_at, model, market, diff_log_loss, diff_ci95, model_win_rate, mean_edge, verdict`); `result_to_json` (unchanged) emits exactly those keys with `status: "ready"`; `VerdictBadge` matches on the `_verdict()` prefixes ("MODEL BEATS MARKET" / "MARKET BEATS MODEL") the backend actually emits; `getMarketRecordServer` returns `MarketBenchmark | null` and the page coerces `null → PENDING`.
