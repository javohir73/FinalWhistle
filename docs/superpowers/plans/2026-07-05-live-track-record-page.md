# Live Track Record Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `/record` page that illustrates the model's live, audited World Cup record — winner accuracy, exact-score %, avg Brier/log-loss, live calibration, and best/worst calls — each headline rate shown with its 95% confidence interval and sample size.

**Architecture:** Reuse the existing audited `GET /api/model/record` as the single source of truth. One small backend addition puts a Wilson 95% CI on the two rates. The frontend adds a pure presentational `RecordView` component and an async server page that fetches the record and renders it, reusing the existing `CalibrationChart` and glass-card styling. Discovery is via the home-page strip (now a link), a link from `/methodology`, and active-state nesting under the existing "You" nav hub — no new nav tab (the IA is a fixed five tabs).

**Tech Stack:** FastAPI + SQLAlchemy (backend), pytest; Next.js App Router + TypeScript + Tailwind + recharts (frontend), Jest + @testing-library/react.

**Design spec:** `docs/superpowers/specs/2026-07-05-live-track-record-page-design.md`.

## Global Constraints

- **Single source of truth.** The page consumes `GET /api/model/record` only; it computes no metrics of its own. Anything shown must be reproducible from that endpoint.
- **Production record only.** The endpoint already filters `PredictionResult.is_shadow.is_(False)`; do not change that. Shadow twins stay behind `/api/internal/*`.
- **Always show `rate · 95% CI · n`** — never a bare percentage. No gating on small `n`; the interval carries the caution, plus a light note when `n < 30`.
- **No overclaim.** Keep the endpoint's "not betting advice" disclaimer; surface misses alongside wins; link to `/methodology` for the historical back-tests.
- **Out of scope:** market/competitor comparison; any new metric the endpoint doesn't already return; changes to how the record is computed.
- **Reuse, don't reinvent:** `CalibrationChart` (`components/CalibrationChart.tsx`), the glass-card / `Stat` visual language from `app/methodology/page.tsx`, and `getModelRecordServer()` (`lib/api.ts:118`).
- **Venv (backend tests):** the worktree shares the main checkout's venv. Run backend tests with `PYTHONPATH=backend:. .venv/bin/python -m pytest …`. Frontend: `cd frontend && npm test -- <pattern>` and `npm run typecheck`.

---

### Task 1: Backend — Wilson 95% CI on the audited record

**Files:**
- Modify: `backend/app/api/model_record.py`
- Test: `backend/tests/test_model_record_api.py` (extend)

**Interfaces:**
- Produces: `wilson_ci95(successes: int, n: int) -> tuple[float, float] | None` (rounded to 4 dp, `None` when `n <= 0`). Three new payload fields on `GET /api/model/record`: `winner_accuracy_ci95: [float, float] | null`, `exact_score_rate: float | null`, `exact_score_ci95: [float, float] | null`.

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_model_record_api.py`:

```python
from app.api.model_record import wilson_ci95


def test_wilson_ci95_known_values():
    lo, hi = wilson_ci95(8, 10)          # 80% of 10
    assert lo == pytest.approx(0.490, abs=0.01)
    assert hi == pytest.approx(0.943, abs=0.01)
    assert wilson_ci95(0, 0) is None      # empty -> None
    lo0, _ = wilson_ci95(0, 20)           # 0 successes -> lower bound pinned at 0
    assert lo0 == 0.0
    _, hi_all = wilson_ci95(20, 20)       # all correct -> upper bound below 1
    assert hi_all < 1.0


def test_record_includes_confidence_intervals(client):
    c, TestingSession = client
    db = TestingSession()
    mex = Team(name="Mexico", country_code="MX", confederation="CONCACAF")
    rsa = Team(name="South Africa", country_code="ZA", confederation="CAF")
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    db.add_all([wc, mex, rsa])
    db.flush()
    m = Match(tournament_id=wc.id, team_home_id=mex.id, team_away_id=rsa.id,
              stage="group", status="finished", score_home=2, score_away=0)
    db.add(m); db.flush()
    p = Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                   prob_home_win=0.81, prob_draw=0.12, prob_away_win=0.07,
                   predicted_score_home=2, predicted_score_away=0)
    db.add(p); db.flush()
    db.add(PredictionResult(
        match_id=m.id, prediction_id=p.id, model_version="poisson-elo-v0.1",
        actual_score_home=2, actual_score_away=0, outcome="home",
        winner_correct=True, exact_score_correct=True,
        prob_assigned=0.81, brier=0.05, log_loss=0.21, goal_error=0,
    ))
    db.commit()

    body = c.get("/api/model/record").json()
    assert body["exact_score_rate"] == pytest.approx(1.0)
    assert isinstance(body["winner_accuracy_ci95"], list) and len(body["winner_accuracy_ci95"]) == 2
    lo, hi = body["winner_accuracy_ci95"]
    assert 0.0 <= lo <= hi <= 1.0
    assert isinstance(body["exact_score_ci95"], list)


def test_empty_record_ci_fields_are_null(client):
    c, _ = client
    body = c.get("/api/model/record").json()
    assert body["evaluated_matches"] == 0
    assert body["winner_accuracy_ci95"] is None
    assert body["exact_score_rate"] is None
    assert body["exact_score_ci95"] is None
```

- [ ] **Step 2: Run to verify they fail.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/test_model_record_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'wilson_ci95'` (and the empty-branch/new-field assertions fail).

- [ ] **Step 3: Add the helper.** In `backend/app/api/model_record.py`, add `import math` at the top (near `from __future__ import annotations`), and this helper just below the `_OUTCOME_IDX` constant:

```python
def wilson_ci95(successes: int, n: int) -> tuple[float, float] | None:
    """95% Wilson score interval for a binomial proportion. None when n == 0.

    Wilson (not normal-approx) so the interval stays inside [0, 1] and behaves
    at the extremes (0 or all correct) and on small samples — exactly the cases
    this page must render honestly.
    """
    if n <= 0:
        return None
    z = 1.959963984540054  # 97.5th percentile of the standard normal
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))
```

- [ ] **Step 4: Populate the fields — empty branch.** In `model_record`, inside the `if n == 0:` dict (the honest-empty `out`), add three keys next to `"winner_accuracy": None,`:

```python
        "winner_accuracy": None,
        "winner_accuracy_ci95": None,
        "exact_score_rate": None,
        "exact_score_ci95": None,
```

- [ ] **Step 5: Populate the fields — non-empty branch.** In the populated `out` dict, next to `"winner_accuracy": round(winners / n, 4),` add:

```python
        "winner_accuracy": round(winners / n, 4),
        "winner_accuracy_ci95": wilson_ci95(winners, n),
        "exact_score_rate": round(exacts / n, 4),
        "exact_score_ci95": wilson_ci95(exacts, n),
```

- [ ] **Step 6: Run to verify they pass.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/test_model_record_api.py -v`
Expected: PASS (all existing + 3 new tests).

- [ ] **Step 7: Commit.**

```bash
git add backend/app/api/model_record.py backend/tests/test_model_record_api.py
git commit -m "feat(record): Wilson 95% CI + exact_score_rate on /api/model/record"
```

---

### Task 2: Frontend — RecordView component + `/record` page

**Files:**
- Modify: `frontend/lib/types.ts` (extend `ModelRecord`)
- Create: `frontend/components/RecordView.tsx`
- Create: `frontend/components/__tests__/recordView.test.tsx`
- Create: `frontend/app/record/page.tsx`

**Interfaces:**
- Consumes: `getModelRecordServer(): Promise<ModelRecord | null>` (`lib/api.ts:118`); `CalibrationChart({ bins })` (`components/CalibrationChart.tsx`); `cn` (`lib/utils`); `APP_NAME` (`lib/constants`).
- Produces: `RecordView({ record }: { record: ModelRecord })` (default-exported presentational component in `components/RecordView.tsx`); the `/record` route.

- [ ] **Step 1: Extend the `ModelRecord` type.** In `frontend/lib/types.ts`, add three fields to the `ModelRecord` interface (after `winner_accuracy`):

```typescript
export interface ModelRecord {
  evaluated_matches: number;
  winner_accuracy: number | null;
  winner_accuracy_ci95: [number, number] | null;
  exact_score_rate: number | null;
  exact_score_ci95: [number, number] | null;
  winners_correct: number;
  exact_score_hits: number;
  avg_brier: number | null;
  avg_log_loss: number | null;
  calibration: CalibrationPoint[];
  best_calls: ModelRecordEntry[];
  biggest_misses: ModelRecordEntry[];
  last_updated: string | null;
  model_version: string;
  disclaimer: string;
}
```

- [ ] **Step 2: Write the failing component tests.** Create `frontend/components/__tests__/recordView.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { RecordView } from "@/components/RecordView";
import type { ModelRecord } from "@/lib/types";

// recharts + ResponsiveContainer needs layout jsdom lacks; the chart has its own
// test, so stub it here and assert the section renders.
jest.mock("@/components/CalibrationChart", () => ({
  CalibrationChart: () => <div data-testid="calibration-chart" />,
}));

const base: ModelRecord = {
  evaluated_matches: 48,
  winner_accuracy: 0.58,
  winner_accuracy_ci95: [0.44, 0.71],
  exact_score_rate: 0.125,
  exact_score_ci95: [0.05, 0.25],
  winners_correct: 28,
  exact_score_hits: 6,
  avg_brier: 0.59,
  avg_log_loss: 0.98,
  calibration: [{ mean_predicted: 0.5, empirical_freq: 0.52, count: 20 }],
  best_calls: [
    { match_id: 1, label: "Mexico 2–0 South Africa", predicted_score: null,
      prob_assigned: 0.81, winner_correct: true, exact_score_correct: true, brier: 0.05, log_loss: 0.21 },
  ],
  biggest_misses: [
    { match_id: 2, label: "Germany 1–2 Japan", predicted_score: null,
      prob_assigned: 0.7, winner_correct: false, exact_score_correct: false, brier: 0.9, log_loss: 1.6 },
  ],
  last_updated: "2026-07-05T00:00:00",
  model_version: "poisson-elo-v0.1",
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

it("shows winner accuracy with its CI and sample size", () => {
  render(<RecordView record={base} />);
  expect(screen.getByText(/58%/)).toBeInTheDocument();
  expect(screen.getByText(/95% CI 44–71%/)).toBeInTheDocument();
  expect(screen.getByText(/n=48/)).toBeInTheDocument();
});

it("renders the honest empty state at n=0 with no CI", () => {
  render(<RecordView record={{
    ...base, evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
    exact_score_rate: null, exact_score_ci95: null, winners_correct: 0, exact_score_hits: 0,
    best_calls: [], biggest_misses: [],
  }} />);
  expect(screen.getByText(/No matches scored yet/)).toBeInTheDocument();
  expect(screen.queryByText(/95% CI/)).not.toBeInTheDocument();
});

it("flags a small sample under 30", () => {
  render(<RecordView record={{ ...base, evaluated_matches: 12 }} />);
  expect(screen.getByText(/Small sample \(12 matches\)/)).toBeInTheDocument();
});

it("surfaces both best calls and biggest misses", () => {
  render(<RecordView record={base} />);
  expect(screen.getByText(/Mexico 2–0 South Africa/)).toBeInTheDocument();
  expect(screen.getByText(/Germany 1–2 Japan/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run to verify they fail.**

Run: `cd frontend && npm test -- recordView`
Expected: FAIL — cannot resolve `@/components/RecordView`.

- [ ] **Step 4: Implement `RecordView`.** Create `frontend/components/RecordView.tsx`:

```tsx
import Link from "next/link";
import { CalibrationChart } from "@/components/CalibrationChart";
import { cn } from "@/lib/utils";
import type { ModelRecord, ModelRecordEntry } from "@/lib/types";

const SMALL_SAMPLE = 30;
const pct = (x: number) => `${Math.round(x * 100)}%`;

/** "58% · 95% CI 44–71% · n=48" — the interval IS the honesty. */
function rateLine(rate: number | null, ci: [number, number] | null, n: number): string {
  if (rate == null || ci == null) return "—";
  return `${pct(rate)} · 95% CI ${pct(ci[0])}–${pct(ci[1])} · n=${n}`;
}

export function RecordView({ record }: { record: ModelRecord }) {
  if (record.evaluated_matches === 0) {
    return (
      <section className="glass rounded-2xl p-6 text-center">
        <h2 className="font-display text-lg font-bold">No matches scored yet</h2>
        <p className="mt-2 text-sm text-muted">
          This fills in as WC26 fixtures finish — every prediction is graded on the
          score after it's played, never adjusted with hindsight.
        </p>
      </section>
    );
  }

  const n = record.evaluated_matches;

  return (
    <div className="space-y-8">
      {/* Hero honesty row */}
      <section className="grid gap-4 sm:grid-cols-2">
        <StatCI title="Winner accuracy" line={rateLine(record.winner_accuracy, record.winner_accuracy_ci95, n)} />
        <StatCI
          title="Exact scores"
          line={rateLine(record.exact_score_rate, record.exact_score_ci95, n)}
          sub={`${record.exact_score_hits} of ${n} scorelines exact`}
        />
      </section>
      {n < SMALL_SAMPLE && (
        <p className="text-center text-xs text-gold">
          Small sample ({n} matches) — treat these with caution; the intervals are wide.
        </p>
      )}

      {/* Sharpness */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">How sharp are the probabilities?</h2>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Metric label="Avg log-loss" value={record.avg_log_loss}
                  gloss="Rewards being confident and right; punishes confident and wrong. Lower is better." />
          <Metric label="Avg Brier" value={record.avg_brier}
                  gloss="Average squared error of the probabilities. Lower is better." />
        </div>
      </section>

      {/* Calibration */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Is a “60%” really 60%?</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Every call binned by its stated probability, against how often it actually happened.
          An honest forecast hugs the dashed line. Noisy while the sample is small.
        </p>
        <div className="mt-5">
          <CalibrationChart bins={record.calibration} />
        </div>
        <p className="mt-3 text-xs text-muted">Based on {n} scored matches (all win/draw/loss calls).</p>
      </section>

      {/* Best calls / biggest misses */}
      <section className="grid gap-6 sm:grid-cols-2">
        <CallList title="Best calls" entries={record.best_calls} tone="win" />
        <CallList title="Biggest misses" entries={record.biggest_misses} tone="gold" />
      </section>

      {/* Footer */}
      <section className="glass rounded-2xl p-6 text-xs leading-relaxed text-muted">
        <p>
          Model {record.model_version}
          {record.last_updated ? ` · updated ${record.last_updated}` : ""}.
        </p>
        <p className="mt-1">{record.disclaimer}</p>
        <p className="mt-2">
          Historical back-tests and how the forecast is built:{" "}
          <Link href="/methodology" className="text-lime-deep underline-offset-2 hover:underline">Methodology</Link>.
        </p>
      </section>
    </div>
  );
}

function StatCI({ title, line, sub }: { title: string; line: string; sub?: string }) {
  return (
    <div className="glass rounded-2xl bg-win/[0.06] p-6 text-center">
      <div className="text-xs uppercase tracking-wider text-muted">{title}</div>
      <div className="mt-2 font-display text-lg font-bold tabular-nums text-foreground">{line}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Metric({ label, value, gloss }: { label: string; value: number | null; gloss: string }) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-2xl font-extrabold tabular-nums text-lime-deep">
          {value != null ? value.toFixed(3) : "—"}
        </span>
        <span className="text-xs text-muted">{label}</span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-muted">{gloss}</p>
    </div>
  );
}

function CallList({ title, entries, tone }: { title: string; entries: ModelRecordEntry[]; tone: "win" | "gold" }) {
  return (
    <div className="glass rounded-2xl p-5">
      <h3 className="font-display font-bold">{title}</h3>
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-muted">None yet.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm">
          {entries.map((e) => (
            <li key={e.match_id} className="flex items-baseline justify-between gap-3">
              <span className="text-foreground/90">{e.label}</span>
              <span className={cn("shrink-0 tabular-nums", tone === "win" ? "text-lime-deep" : "text-gold")}>
                {e.prob_assigned != null ? pct(e.prob_assigned) : "—"} {e.winner_correct ? "✓" : "✗"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

Note: `ModelRecordEntry.predicted_score` is intentionally not rendered — the backend returns it as a string (`"2-0"`) but the TS type declares an object; that pre-existing mismatch is out of scope, so this view avoids it and shows label + assigned probability + a ✓/✗.

- [ ] **Step 5: Run to verify the component tests pass.**

Run: `cd frontend && npm test -- recordView`
Expected: PASS (4 tests).

- [ ] **Step 6: Create the page.** Create `frontend/app/record/page.tsx`:

```tsx
import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getModelRecordServer } from "@/lib/api";
import { RecordView } from "@/components/RecordView";

export const metadata: Metadata = {
  title: `Track record — ${APP_NAME}`,
  description:
    "The model's live, audited World Cup record: winner accuracy, exact scores, and calibration — each shown with its sample size and 95% confidence interval.",
};

export default async function RecordPage() {
  let record = null;
  try {
    record = await getModelRecordServer();
  } catch {
    record = null;
  }

  return (
    <article className="fade-up mx-auto max-w-2xl space-y-8">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          Track <span className="text-lime-deep">record</span>
        </h1>
        <p className="mt-3 text-muted">
          How the forecasts have actually held up on WC26 — every call graded pre-kickoff
          and shown with its sample size and 95% confidence interval, wins and misses alike.
        </p>
      </header>
      {record ? (
        <RecordView record={record} />
      ) : (
        <section className="glass rounded-2xl p-6 text-center text-sm text-muted">
          The record is temporarily unavailable — please check back shortly.
        </section>
      )}
    </article>
  );
}
```

- [ ] **Step 7: Typecheck, then commit.**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

```bash
git add frontend/lib/types.ts frontend/components/RecordView.tsx \
        frontend/components/__tests__/recordView.test.tsx frontend/app/record/page.tsx
git commit -m "feat(record): live Track Record page (RecordView + /record route)"
```

---

### Task 3: Frontend — discovery (home strip, methodology link, nav active state)

**Files:**
- Modify: `frontend/app/HomeExperience.tsx` (make the record strip a link)
- Modify: `frontend/app/methodology/page.tsx` (add a live-record link)
- Modify: `frontend/components/SiteNav.tsx` (add `/record` to the "You" hub prefixes)
- Modify: `frontend/components/BottomNav.tsx` (same)
- Test: `frontend/components/__tests__/bottomNav.test.tsx` (extend)

**Interfaces:**
- Consumes: the `/record` route from Task 2. No new exports.

- [ ] **Step 1: Write the failing nav test.** In `frontend/components/__tests__/bottomNav.test.tsx`, add `["/record", "You"]` to the `it.each([...])` table (the block that asserts the active tab per path), e.g. after the `["/methodology", "You"]` row:

```tsx
  ["/methodology", "You"],
  ["/record", "You"], // the live track record nests under the You hub
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd frontend && npm test -- bottomNav`
Expected: FAIL — on `/record` no tab is active yet (`current()` does not contain "You").

- [ ] **Step 3: Add `/record` to both navs' "You" hub.** In `frontend/components/BottomNav.tsx`, the `TABS` entry with `label: "You"` — extend its `activePrefixes`:

```tsx
    activePrefixes: ["/about", "/methodology", "/privacy", "/terms", "/record"],
```

Make the identical change in `frontend/components/SiteNav.tsx` (the `LINKS` entry with `label: "You"`):

```tsx
    activePrefixes: ["/about", "/methodology", "/privacy", "/terms", "/record"],
```

- [ ] **Step 4: Run to verify the nav test passes.**

Run: `cd frontend && npm test -- bottomNav`
Expected: PASS (including the new `/record` row, and still exactly five tabs).

- [ ] **Step 5: Make the home-page strip a link.** In `frontend/app/HomeExperience.tsx`, replace the AI-record strip (the `{record && record.evaluated_matches > 0 && ( <p …>AI record so far…</p> )}` block) with a linked version:

```tsx
      {/* ===== AI record so far (real, verified track record) ===== */}
      {record && record.evaluated_matches > 0 && (
        <p className="mt-8 text-center text-sm text-muted">
          AI record so far: {record.winners_correct}/{record.evaluated_matches} winners
          {" · "}
          {record.exact_score_hits} exact score{record.exact_score_hits === 1 ? "" : "s"}
          {" · "}
          <Link href="/record" className="font-semibold text-lime-deep underline-offset-2 hover:underline">
            Full track record
          </Link>
        </p>
      )}
```

(`Link` is already imported in this file.)

- [ ] **Step 6: Add a live-record link on the methodology page.** In `frontend/app/methodology/page.tsx`, in the header `<p>` (the one under the `<h1>`, ending "…The deeper metrics are below for anyone who wants them."), append a sentence linking to the live page:

```tsx
        <p className="mt-3 text-muted">
          In plain terms: how the forecasts are made, and how well they&apos;ve actually
          held up when tested against past World Cups. The deeper metrics are below for
          anyone who wants them. For the live WC26 record so far, see the{" "}
          <Link href="/record" className="text-lime-deep underline-offset-2 hover:underline">Track record</Link>.
        </p>
```

(`Link` is already imported in this file.)

- [ ] **Step 7: Typecheck + run the frontend suite.**

Run: `cd frontend && npm run typecheck && npm test`
Expected: no type errors; all tests pass (nav, recordView, existing).

- [ ] **Step 8: Commit.**

```bash
git add frontend/app/HomeExperience.tsx frontend/app/methodology/page.tsx \
        frontend/components/SiteNav.tsx frontend/components/BottomNav.tsx \
        frontend/components/__tests__/bottomNav.test.tsx
git commit -m "feat(record): link the Track Record page from home, methodology, and nav"
```

---

### Task 4: Whole-suite verification

- [ ] **Step 1: Backend suite.**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest backend ml pipeline -q`
Expected: all green (the CI addition is additive; no existing test regresses).

- [ ] **Step 2: Frontend gate.**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: typecheck clean, lint clean, all tests pass.

- [ ] **Step 3: Paste the real output** into the PR description — no success claim without it. Open a PR (`feat/track-record-page` → `main`); a human merges.

---

## Self-Review

- **Spec coverage:** Wilson CI + fields (spec "Backend — the one addition") → Task 1; dedicated `/record` page with hero honesty row / sharpness / calibration / best-worst / footer, `ModelRecord` extension, reuse of `CalibrationChart` + `getModelRecordServer` (spec "Frontend — the page") → Task 2; empty (`n=0`) and low-`n` (`n<30`) states (spec "States & errors") → Task 2 (RecordView); nav link + home-strip link (spec "Frontend — the page"; reconciled to the fixed-5-tab IA as "You"-hub nesting + home/methodology links) → Task 3; error handling (fetch failure → card) → Task 2 (page try/catch). Out-of-scope items (market comparison, new metrics) are absent by construction.
- **Placeholder scan:** none — every step has runnable code/commands.
- **Type consistency:** `wilson_ci95(successes, n) -> tuple|None` used identically in Task 1 steps; `ModelRecord` fields added in Task 2 Step 1 match the three names produced in Task 1 (`winner_accuracy_ci95`, `exact_score_rate`, `exact_score_ci95`) and consumed in `RecordView`/`rateLine`; `CalibrationChart({ bins })` fed `record.calibration` (both `CalibrationPoint[]`/`ReliabilityBin[]`, same shape); `ModelRecordEntry.predicted_score` deliberately unused (documented backend/type mismatch, out of scope).
