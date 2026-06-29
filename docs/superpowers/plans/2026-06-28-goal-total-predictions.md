# Goal-total Predictions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-team goal bands, match over/under, and both-teams-to-score markets to the match prediction card, derived from the already-stored Poisson rates.

**Architecture:** A pure `goal_markets()` helper marginalizes the normalized Dixon-Coles score grid (built by the existing `score_matrix`). The serializer computes it on read from each `Prediction`'s stored `lambda_home/lambda_away/rho` and attaches a nullable block to `PredictionOut`. The frontend renders a "Goals" card, hidden when the block is null. No DB migration, no pipeline rerun.

**Tech Stack:** Python (FastAPI, Pydantic, SQLAlchemy, pytest), TypeScript (Next.js App Router, React, Jest + Testing Library).

## Global Constraints

- **No DB migration, no pipeline rerun.** Markets are derived at serve time from already-stored fields; do not add columns or touch `build_payload`/`run_pipeline`.
- **Same distribution as the predicted score.** Build markets from `score_matrix(lam_home, lam_away, rho=rho)`, normalized by total mass (the grid is un-normalized) — never a separate model.
- **Markets shown:** per-team `to_score` (≥1) / `p2` (≥2) / `p3` (≥3) / `p4` (≥4); totals `over_1_5/2_5/3_5`; `btts`. No clean-sheet market.
- **Display rule:** the "4+ goals" row appears only when `p4 ≥ 0.10`. Totals card shows Over 2.5 and Over 3.5. All percentages via the existing `pct()` formatter.
- **Nullable end-to-end:** `goal_markets` is `None`/`null` when `lambda_home` or `lambda_away` is missing (legacy rows); the card is hidden then. A missing `rho` defaults to `0` (plain Poisson) and still yields markets.
- `MAX_GOALS = 10` (existing grid cap in `ml/models/poisson.py`).

---

### Task 1: `goal_markets()` pure helper (ml)

**Files:**
- Modify: `ml/models/poisson.py` (add `goal_markets` after `score_matrix`)
- Test: `ml/models/poisson_test.py`

**Interfaces:**
- Consumes: existing `score_matrix(lam_home, lam_away, max_goals=MAX_GOALS, rho=0.0)` and `MAX_GOALS` from the same module.
- Produces: `goal_markets(lam_home: float | None, lam_away: float | None, rho: float | None = 0.0, max_goals: int = MAX_GOALS) -> dict | None`. The dict shape is exactly:
  ```python
  {"home": {"to_score": float, "p2": float, "p3": float, "p4": float},
   "away": {"to_score": float, "p2": float, "p3": float, "p4": float},
   "total": {"over_1_5": float, "over_2_5": float, "over_3_5": float},
   "btts": float}
  ```
  All values rounded to 4 dp. Returns `None` when `lam_home` or `lam_away` is `None`.

- [ ] **Step 1: Write the failing tests**

Append to `ml/models/poisson_test.py`:

```python
def test_goal_markets_none_when_rates_missing():
    from ml.models.poisson import goal_markets
    assert goal_markets(None, 1.0) is None
    assert goal_markets(1.0, None) is None


def test_goal_markets_bands_are_probabilities_and_monotonic():
    from ml.models.poisson import goal_markets
    gm = goal_markets(2.0, 0.5, rho=0.0)
    for side in ("home", "away"):
        b = gm[side]
        assert 0.0 <= b["p4"] <= b["p3"] <= b["p2"] <= b["to_score"] <= 1.0
    t = gm["total"]
    assert 1.0 >= t["over_1_5"] >= t["over_2_5"] >= t["over_3_5"] >= 0.0
    # BTTS cannot exceed either side's chance to score.
    assert gm["btts"] <= gm["home"]["to_score"]
    assert gm["btts"] <= gm["away"]["to_score"]


def test_goal_markets_known_lambda_matches_poisson_marginals():
    import math
    from ml.models.poisson import goal_markets
    gm = goal_markets(2.0, 0.5, rho=0.0)
    # rho=0 => independent Poisson; P(>=1) = 1 - e^-lambda (grid truncation negligible).
    assert abs(gm["home"]["to_score"] - (1 - math.exp(-2.0))) < 0.01
    assert abs(gm["away"]["to_score"] - (1 - math.exp(-0.5))) < 0.01
    # Independent => BTTS ~= P(home>=1) * P(away>=1).
    assert abs(gm["btts"] - (1 - math.exp(-2.0)) * (1 - math.exp(-0.5))) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/models/poisson_test.py -k goal_markets -v`
Expected: FAIL with `ImportError: cannot import name 'goal_markets'`.

- [ ] **Step 3: Implement `goal_markets`**

In `ml/models/poisson.py`, add directly after the `score_matrix` function:

```python
def goal_markets(
    lam_home: float | None,
    lam_away: float | None,
    rho: float | None = 0.0,
    max_goals: int = MAX_GOALS,
) -> dict | None:
    """Per-team goal bands, match totals and both-teams-to-score, marginalized
    from the NORMALIZED Dixon-Coles score grid. Same distribution that yields the
    predicted score, so the numbers stay consistent. Returns None when a rate is
    missing (legacy predictions). All probabilities rounded to 4 dp."""
    if lam_home is None or lam_away is None:
        return None
    matrix = score_matrix(lam_home, lam_away, max_goals=max_goals, rho=rho or 0.0)
    total = sum(sum(row) for row in matrix)
    if total <= 0.0:
        return None
    p = [[matrix[h][a] / total for a in range(max_goals + 1)] for h in range(max_goals + 1)]
    home_goals = [sum(p[h]) for h in range(max_goals + 1)]
    away_goals = [sum(p[h][a] for h in range(max_goals + 1)) for a in range(max_goals + 1)]

    def at_least(dist: list[float], n: int) -> float:
        return round(sum(dist[n:]), 4)

    def total_ge(m: int) -> float:
        return round(
            sum(p[h][a] for h in range(max_goals + 1) for a in range(max_goals + 1) if h + a >= m),
            4,
        )

    btts = round(
        sum(p[h][a] for h in range(1, max_goals + 1) for a in range(1, max_goals + 1)), 4
    )
    return {
        "home": {"to_score": at_least(home_goals, 1), "p2": at_least(home_goals, 2),
                 "p3": at_least(home_goals, 3), "p4": at_least(home_goals, 4)},
        "away": {"to_score": at_least(away_goals, 1), "p2": at_least(away_goals, 2),
                 "p3": at_least(away_goals, 3), "p4": at_least(away_goals, 4)},
        "total": {"over_1_5": total_ge(2), "over_2_5": total_ge(3), "over_3_5": total_ge(4)},
        "btts": btts,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest ml/models/poisson_test.py -k goal_markets -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ml/models/poisson.py ml/models/poisson_test.py
git commit -m "feat(ml): goal_markets() — per-team bands, totals, BTTS from the score grid"
```

---

### Task 2: Serializer + schema expose `goal_markets`

**Files:**
- Modify: `backend/app/schemas/__init__.py` (add out-models; add field to `PredictionOut`)
- Modify: `backend/app/serializers.py` (import helper; build the block in `prediction_to_out`)
- Test: `backend/tests/test_goal_markets.py` (create)

**Interfaces:**
- Consumes: `goal_markets(...)` from Task 1; the stored `Prediction.lambda_home/lambda_away/rho`.
- Produces: `PredictionOut.goal_markets: GoalMarketsOut | None`, where `GoalMarketsOut` has `home: TeamGoalBandsOut`, `away: TeamGoalBandsOut`, `total: GoalTotalsOut`, `btts: float`; `TeamGoalBandsOut` has `to_score/p2/p3/p4: float`; `GoalTotalsOut` has `over_1_5/over_2_5/over_3_5: float`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_goal_markets.py`:

```python
from app import serializers
from app.models import Match, Prediction, Team


def _setup(db):
    h, a = Team(name="Argentina"), Team(name="Cape Verde")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True,
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    p = Prediction(match_id=m.id, model_version="v",
                   prob_home_win=0.7, prob_draw=0.2, prob_away_win=0.1,
                   lambda_home=2.5, lambda_away=0.4, rho=-0.1)
    db.add(p); db.commit()
    return m, p


def test_prediction_out_includes_goal_markets(db_session):
    m, p = _setup(db_session)
    out = serializers.prediction_to_out(db_session, m, p)
    assert out.goal_markets is not None
    gm = out.goal_markets
    assert 0.0 <= gm.btts <= 1.0
    assert gm.home.to_score >= gm.home.p2 >= gm.home.p3 >= gm.home.p4
    assert gm.total.over_1_5 >= gm.total.over_2_5 >= gm.total.over_3_5


def test_goal_markets_null_when_rates_missing(db_session):
    m, p = _setup(db_session)
    p.lambda_home = None
    db_session.commit()
    out = serializers.prediction_to_out(db_session, m, p)
    assert out.goal_markets is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_goal_markets.py -v`
Expected: FAIL — `PredictionOut` has no `goal_markets` attribute (validation/`AttributeError`).

- [ ] **Step 3: Add the schema out-models**

In `backend/app/schemas/__init__.py`, add immediately before `class PredictionOut(BaseModel):`:

```python
class TeamGoalBandsOut(BaseModel):
    to_score: float
    p2: float
    p3: float
    p4: float


class GoalTotalsOut(BaseModel):
    over_1_5: float
    over_2_5: float
    over_3_5: float


class GoalMarketsOut(BaseModel):
    home: TeamGoalBandsOut
    away: TeamGoalBandsOut
    total: GoalTotalsOut
    btts: float
```

Then, inside `class PredictionOut`, add this field on the line after `disclaimer: str`:

```python
    goal_markets: GoalMarketsOut | None = None
```

- [ ] **Step 4: Build the block in the serializer**

In `backend/app/serializers.py`, add to the imports near the top (with the other `ml`/`app` imports):

```python
from ml.models.poisson import goal_markets as _goal_markets
```

Add this helper above `def prediction_to_out`:

```python
def _goal_markets_out(lam_home, lam_away, rho) -> schemas.GoalMarketsOut | None:
    gm = _goal_markets(lam_home, lam_away, rho)
    if gm is None:
        return None
    return schemas.GoalMarketsOut(
        home=schemas.TeamGoalBandsOut(**gm["home"]),
        away=schemas.TeamGoalBandsOut(**gm["away"]),
        total=schemas.GoalTotalsOut(**gm["total"]),
        btts=gm["btts"],
    )
```

In `prediction_to_out`, add this keyword argument to the `schemas.PredictionOut(...)` call, on the line after `disclaimer=DISCLAIMER,`:

```python
        goal_markets=_goal_markets_out(pred.lambda_home, pred.lambda_away, pred.rho),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_goal_markets.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the backend suite to check no regressions**

Run: `.venv/bin/python -m pytest backend ml -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/serializers.py backend/tests/test_goal_markets.py
git commit -m "feat(api): expose goal_markets on PredictionOut (computed on read)"
```

---

### Task 3: Frontend types + `GoalMarkets` component

**Files:**
- Modify: `frontend/lib/types.ts` (add market types; add field to `Prediction`)
- Create: `frontend/components/GoalMarkets.tsx`
- Test: `frontend/components/__tests__/goalMarkets.test.tsx` (create)

**Interfaces:**
- Consumes: `pct` from `@/lib/format`.
- Produces: `GoalMarkets` types (`TeamGoalBands`, `GoalTotals`, `GoalMarkets`) and a `GoalMarkets` React component with props `{ home: string; away: string; markets: GoalMarketsData }` (default export not used — named export `GoalMarkets`).

- [ ] **Step 1: Add the TypeScript types**

In `frontend/lib/types.ts`, add above `export interface Prediction {`:

```typescript
export interface TeamGoalBands {
  to_score: number;
  p2: number;
  p3: number;
  p4: number;
}
export interface GoalTotals {
  over_1_5: number;
  over_2_5: number;
  over_3_5: number;
}
export interface GoalMarkets {
  home: TeamGoalBands;
  away: TeamGoalBands;
  total: GoalTotals;
  btts: number;
}
```

Then add this property inside `export interface Prediction`, on the line after `disclaimer: string;`:

```typescript
  goal_markets: GoalMarkets | null;
```

- [ ] **Step 2: Write the failing component test**

Create `frontend/components/__tests__/goalMarkets.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { GoalMarkets } from "@/components/GoalMarkets";
import type { GoalMarkets as GoalMarketsData } from "@/lib/types";

function markets(p4 = 0.4): GoalMarketsData {
  return {
    home: { to_score: 0.86, p2: 0.6, p3: 0.45, p4 },
    away: { to_score: 0.39, p2: 0.12, p3: 0.03, p4: 0.01 },
    total: { over_1_5: 0.78, over_2_5: 0.55, over_3_5: 0.3 },
    btts: 0.34,
  };
}

it("renders per-team bands, totals and BTTS", () => {
  render(<GoalMarkets home="Argentina" away="Cape Verde" markets={markets()} />);
  expect(screen.getByText("Argentina")).toBeInTheDocument();
  expect(screen.getByText("Cape Verde")).toBeInTheDocument();
  expect(screen.getByText("Over 2.5")).toBeInTheDocument();
  expect(screen.getByText("Both score")).toBeInTheDocument();
});

it("shows the 4+ band only when notable (p4 >= 0.10)", () => {
  const { rerender } = render(
    <GoalMarkets home="Argentina" away="Cape Verde" markets={markets(0.4)} />,
  );
  expect(screen.getByText("4+ goals")).toBeInTheDocument();

  rerender(<GoalMarkets home="Argentina" away="Cape Verde" markets={markets(0.02)} />);
  expect(screen.queryByText("4+ goals")).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/goalMarkets.test.tsx`
Expected: FAIL — cannot find module `@/components/GoalMarkets`.

- [ ] **Step 4: Implement the component**

Create `frontend/components/GoalMarkets.tsx`:

```tsx
import { pct } from "@/lib/format";
import type { GoalMarkets as GoalMarketsData, TeamGoalBands } from "@/lib/types";

/** Below this, the "4+ goals" row is hidden to keep even contests uncluttered. */
const NOTABLE_4PLUS = 0.1;

/** Goal-total markets for a match: per-team bands + match over/under + BTTS.
 *  All numbers come from the same Poisson distribution as the predicted score. */
export function GoalMarkets({
  home,
  away,
  markets,
}: {
  home: string;
  away: string;
  markets: GoalMarketsData;
}) {
  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Goals</h2>
      <div className="grid gap-5 sm:grid-cols-2">
        <TeamBands team={home} bands={markets.home} />
        <TeamBands team={away} bands={markets.away} />
      </div>
      <div className="mt-5 grid grid-cols-3 gap-2 border-t border-border pt-4">
        <Stat label="Over 2.5" value={markets.total.over_2_5} />
        <Stat label="Over 3.5" value={markets.total.over_3_5} />
        <Stat label="Both score" value={markets.btts} />
      </div>
    </section>
  );
}

function TeamBands({ team, bands }: { team: string; bands: TeamGoalBands }) {
  const rows: [string, number][] = [
    ["To score", bands.to_score],
    ["2+ goals", bands.p2],
    ["3+ goals", bands.p3],
  ];
  if (bands.p4 >= NOTABLE_4PLUS) rows.push(["4+ goals", bands.p4]);
  return (
    <div>
      <p className="mb-2 font-display text-sm font-bold">{team}</p>
      <ul className="space-y-1.5">
        {rows.map(([label, v]) => (
          <li key={label} className="flex items-center justify-between text-sm">
            <span className="text-muted">{label}</span>
            <span className="font-display font-bold tabular-nums text-lime-deep">{pct(v)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl bg-win/[0.06] px-2 py-3 text-center">
      <p className="font-display text-lg font-extrabold tabular-nums text-lime-deep">{pct(value)}</p>
      <p className="mt-0.5 text-[11px] font-semibold text-muted">{label}</p>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx jest components/__tests__/goalMarkets.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/types.ts frontend/components/GoalMarkets.tsx frontend/components/__tests__/goalMarkets.test.tsx
git commit -m "feat(web): GoalMarkets component + Prediction goal_markets type"
```

---

### Task 4: Render `GoalMarkets` on the match page

**Files:**
- Modify: `frontend/app/match/[id]/page.tsx` (import + render in the overview, hidden when null)
- Test: `frontend/app/match/[id]/page.test.tsx` (update fixture; add render case)

**Interfaces:**
- Consumes: the `GoalMarkets` component (Task 3) and `Prediction.goal_markets` (Task 3).
- Produces: nothing downstream.

- [ ] **Step 1: Update the existing test fixture and add a render test**

In `frontend/app/match/[id]/page.test.tsx`, the existing `const prediction: Prediction = {...}` literal is now missing the required `goal_markets` field. Add to that literal, on the line after `disclaimer: "...",`:

```tsx
  goal_markets: null,
```

Then add this test after the `"server-renders teams, probabilities, reasons and odds stub"` test:

```tsx
it("renders the Goals section when goal_markets is present", async () => {
  mockGet.mockResolvedValue({
    ...prediction,
    goal_markets: {
      home: { to_score: 0.86, p2: 0.6, p3: 0.45, p4: 0.38 },
      away: { to_score: 0.39, p2: 0.12, p3: 0.03, p4: 0.01 },
      total: { over_1_5: 0.78, over_2_5: 0.55, over_3_5: 0.3 },
      btts: 0.34,
    },
  });
  render(await MatchDetailPage({ params: Promise.resolve({ id: "1" }) }));
  expect(screen.getByText("Goals")).toBeInTheDocument();
  expect(screen.getByText("Over 2.5")).toBeInTheDocument();
});

it("omits the Goals section when goal_markets is null", async () => {
  mockGet.mockResolvedValue({ ...prediction, goal_markets: null });
  render(await MatchDetailPage({ params: Promise.resolve({ id: "1" }) }));
  expect(screen.queryByText("Goals")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify the new render test fails**

Run: `cd frontend && npx jest "app/match/\[id\]/page.test.tsx" -t "Goals"`
Expected: FAIL — "Goals" is not in the document (section not rendered yet).

- [ ] **Step 3: Render the component**

In `frontend/app/match/[id]/page.tsx`, add to the imports (with the other component imports):

```tsx
import { GoalMarkets } from "@/components/GoalMarkets";
```

In the `overview={ ... }` JSX of `<MatchTabs>`, add this block immediately after the closing `</section>` of the "Why" card (the section that renders `<ReasonsList>` and `<FeatureImportanceChart>`), and before the `{summary && ( ... Your prediction ... )}` block:

```tsx
            {/* Goals — per-team bands, over/under and BTTS (hidden until predicted). */}
            {p.goal_markets && (
              <GoalMarkets home={home} away={away} markets={p.goal_markets} />
            )}
```

- [ ] **Step 4: Run the match-page tests to verify they pass**

Run: `cd frontend && npx jest "app/match/\[id\]/page.test.tsx"`
Expected: PASS (all cases, including the two new "Goals" tests).

- [ ] **Step 5: Run the full frontend suite + typecheck**

Run: `cd frontend && npx jest && npx tsc --noEmit`
Expected: all tests pass; tsc exits 0.

- [ ] **Step 6: Commit**

```bash
git add "frontend/app/match/[id]/page.tsx" "frontend/app/match/[id]/page.test.tsx"
git commit -m "feat(web): show Goals markets on the match page"
```

---

## Self-Review

**Spec coverage:** per-team bands (Task 1 helper + Task 3 display) ✓; match over/under (Task 1 `total`, Task 3 Stat) ✓; BTTS (Task 1 `btts`, Task 3) ✓; no clean sheet ✓; compute-on-read serializer, no migration (Task 2) ✓; nullable + hidden card (Tasks 2-4) ✓; 4+ display rule `p4 ≥ 0.10` (Task 3 `NOTABLE_4PLUS`) ✓; same distribution via `score_matrix` normalized (Task 1) ✓; tests at ml/serializer/component/page layers ✓.

**Placeholder scan:** none — every step has complete code and exact commands.

**Type consistency:** dict keys (`to_score/p2/p3/p4`, `over_1_5/over_2_5/over_3_5`, `btts`) are identical across the Python helper (Task 1), Pydantic models (Task 2), TS interfaces (Task 3), and fixtures (Tasks 3-4). Component prop name `markets` matches between definition (Task 3) and call site (Task 4). `goal_markets` field name matches Python ↔ schema ↔ TS.
