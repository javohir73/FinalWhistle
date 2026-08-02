# NRL Live Score Header Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an automatically refreshing live score and match minute in the NRL match-detail hero while sharing one live-feed poll with the existing Live section.

**Architecture:** Add a client-side `LiveMatchProvider` around the match-detail page. It performs the page's only 30-second poll of the existing live endpoint and exposes the latest `NrlLive` payload through context. A focused `NrlMatchHero` renders pre-match, live, and final states from that context, while `LiveSection` becomes a presentation-only consumer of the same state.

**Tech Stack:** Next.js App Router, React context, TypeScript, existing `useFetch`, Jest, React Testing Library, Tailwind CSS.

## Global Constraints

- Poll `GET /api/nrl/matches/{match_id}/live` every 30 seconds; do not refresh the server page.
- Keep one poller per match-detail page; the hero and Live section must share its state.
- Preserve the existing pre-match and full-time presentation.
- During live play, show `LIVE · <minute>′`, the current score, and the label `Pre-match model pick`.
- Never fabricate a score or minute; use an en dash when the provider returns `null`.
- Keep the last successful payload when a later background poll fails.
- No backend, database, live-model, ingestion, or other fixture-card changes.
- Use test-driven development: every production change follows a failing test that fails for the intended missing behavior.

---

## File Structure

- Create `frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.tsx`: owns live polling and context.
- Create `frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.test.tsx`: proves initial/final behavior, polling, and last-good-data retention.
- Create `frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.tsx`: renders the complete hero from server match data plus shared live state.
- Create `frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.test.tsx`: proves pre-match, live, and final presentation.
- Modify `frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.tsx`: remove its poller and consume shared state.
- Modify `frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.test.tsx`: wrap with a provider harness and prove shared-state rendering.
- Modify `frontend/app/nrl/match/[season]/[round]/[no]/page.tsx`: wrap the page with the provider and replace inline hero markup.
- Modify `frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx`: update page wiring assertions and API mocks.

---

### Task 1: Shared Live-Match Provider

**Files:**
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.test.tsx`

**Interfaces:**
- Consumes: `getNrlLiveClient(matchId: number): Promise<NrlLive>` and `useFetch<T>(fetcher, deps, pollMs, initial)`.
- Produces: `LiveMatchProvider({ match, children })` and `useLiveMatch(): FetchState<NrlLive> & { retry(): void }`.

- [ ] **Step 1: Write the failing provider tests**

Create a probe that prints the context state, then cover an immediate live response and a silent failed poll that retains the previous score:

```tsx
jest.mock("@/lib/api");

const livePayload = (overrides: Partial<NrlLive> = {}): NrlLive => ({
  status: "live",
  minute: 1,
  score_home: 0,
  score_away: 0,
  live_home_prob: 0.5,
  events: [],
  ...overrides,
});

const scheduledMatch: NrlMatch = {
  id: 42, match_no: 3, kickoff_utc: "2026-08-02T04:00:00Z",
  venue: "Ocean Protect Stadium", home: "Sharks", away: "Rabbitohs",
  home_team_id: 1, away_team_id: 2, score_home: null, score_away: null,
  status: "scheduled", prediction: null,
};
const finishedMatch: NrlMatch = {
  ...scheduledMatch, status: "finished", score_home: 12, score_away: 26,
};

function Probe() {
  const state = useLiveMatch();
  if (state.status !== "success") return <span>{state.status}</span>;
  return <span>{state.data.status}:{state.data.minute}:{state.data.score_home}–{state.data.score_away}</span>;
}

it("publishes live data and keeps it when a later poll fails", async () => {
  jest.useFakeTimers();
  mockLive
    .mockResolvedValueOnce(livePayload({ minute: 18, score_home: 6, score_away: 0 }))
    .mockRejectedValueOnce(new Error("temporary outage"));

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  expect(await screen.findByText("live:18:6–0")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(screen.getByText("live:18:6–0")).toBeInTheDocument();
});

it("seeds a finished match without waiting for the endpoint", () => {
  render(<LiveMatchProvider match={finishedMatch}><Probe /></LiveMatchProvider>);
  expect(screen.getByText("final:80:12–26")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the provider tests and verify RED**

Run:

```bash
cd frontend
npx jest --runInBand --runTestsByPath './app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.test.tsx'
```

Expected: FAIL because `LiveMatchProvider` and `useLiveMatch` do not exist.

- [ ] **Step 3: Implement the minimal provider**

Create a context around the existing hook. Use `Promise.resolve` around the API call so existing auto-mocked page tests degrade safely. Seed only a known final match; do not invent a pre-match score or probability.

```tsx
"use client";

const POLL_MS = 30_000;
type LiveMatchState = FetchState<NrlLive> & { retry: () => void };
const LiveMatchContext = createContext<LiveMatchState | null>(null);

export function LiveMatchProvider({ match, children }: { match: NrlMatch; children: ReactNode }) {
  const finished = match.status === "finished";
  const initial = finished && match.score_home != null && match.score_away != null
    ? {
        status: "final" as const,
        minute: 80,
        score_home: match.score_home,
        score_away: match.score_away,
        live_home_prob: match.score_home > match.score_away ? 1 : 0,
        events: [],
      }
    : undefined;
  const state = useFetch<NrlLive>(
    () => Promise.resolve(getNrlLiveClient(match.id)),
    [match.id],
    finished ? undefined : POLL_MS,
    initial,
  );
  return <LiveMatchContext.Provider value={state}>{children}</LiveMatchContext.Provider>;
}

export function useLiveMatch() {
  const state = useContext(LiveMatchContext);
  if (!state) throw new Error("useLiveMatch must be used inside LiveMatchProvider");
  return state;
}
```

- [ ] **Step 4: Run the provider tests and verify GREEN**

Run the Step 2 command. Expected: 2 tests pass with no warnings.

- [ ] **Step 5: Commit the provider**

```bash
git add 'frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.test.tsx'
git commit -m "feat(nrl): share live match state across detail page"
```

---

### Task 2: Live-Aware Match Hero

**Files:**
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.tsx`
- Create: `frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.test.tsx`

**Interfaces:**
- Consumes: `useLiveMatch()`, `NrlMatch`, `ProbabilityBar`, `ClubBadge`, and `pct`.
- Produces: `NrlMatchHero({ match, home, away })` containing the existing matchup-card UI.

- [ ] **Step 1: Write failing hero tests for all three states**

Use the real provider with a mocked endpoint. Define `scheduledMatch` with the
existing Warriors prediction fixture and `finishedMatch` as its 12–26 final variant:

```tsx
const livePayload = (overrides: Partial<NrlLive> = {}): NrlLive => ({
  status: "live", minute: 1, score_home: 0, score_away: 0,
  live_home_prob: 0.5, events: [], ...overrides,
});

function renderHero(match: NrlMatch = scheduledMatch) {
  return render(
    <LiveMatchProvider match={match}>
      <NrlMatchHero match={match} home={match.home!} away={match.away!} />
    </LiveMatchProvider>,
  );
}

it("keeps VS and the normal prediction copy before kickoff", async () => {
  mockLive.mockResolvedValue({
    ...livePayload(), status: "pre", minute: null, score_home: null, score_away: null,
  });
  renderHero();
  expect(screen.getByText("vs")).toBeInTheDocument();
  expect(screen.getByText(/Warriors to win · 67%/)).toBeInTheDocument();
});

it("shows the updating result and labels the prediction as pre-match while live", async () => {
  mockLive.mockResolvedValue(livePayload({ minute: 42, score_home: 12, score_away: 6 }));
  renderHero();
  expect(await screen.findByRole("status", { name: /live match/i })).toHaveTextContent("LIVE · 42′");
  expect(screen.getByText("12–6")).toBeInTheDocument();
  expect(screen.getByText(/Pre-match model pick · Warriors 67%/)).toBeInTheDocument();
  expect(screen.queryByText(/ML model margin/)).not.toBeInTheDocument();
});

it("preserves the full-time score and model verdict", () => {
  renderHero(finishedMatch);
  expect(screen.getByText("Full time")).toBeInTheDocument();
  expect(screen.getByText("12–26")).toBeInTheDocument();
  expect(screen.getByText(/Called it/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the hero tests and verify RED**

Run:

```bash
cd frontend
npx jest --runInBand --runTestsByPath './app/nrl/match/[season]/[round]/[no]/NrlMatchHero.test.tsx'
```

Expected: FAIL because `NrlMatchHero` does not exist.

- [ ] **Step 3: Implement `NrlMatchHero` by moving the existing hero intact**

Move the matchup `section`, `TeamCol`, and `marginLabel` helper from `page.tsx` into the new client component. Determine the display state as follows:

```tsx
const liveState = state.status === "success" ? state.data : null;
const isLive = liveState?.status === "live";
const isFinal = liveState?.status === "final" || match.status === "finished";
const scoreHome = isLive || liveState?.status === "final" ? liveState.score_home : match.score_home;
const scoreAway = isLive || liveState?.status === "final" ? liveState.score_away : match.score_away;
const score = scoreHome != null && scoreAway != null ? `${scoreHome}–${scoreAway}` : "–";
```

Render the live badge with an accessible status and omit the minute when null:

```tsx
{isLive && (
  <p className="mb-4 text-center">
    <span role="status" aria-label="Live match" className="inline-flex ... text-loss">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
      LIVE{liveState.minute != null ? ` · ${liveState.minute}′` : ""}
    </span>
  </p>
)}
```

For live prediction copy, render exactly:

```tsx
Pre-match model pick · {favoured} {pct(favouredProb)}
```

Show expected margin only in the pre-match state. Preserve the existing `ProbabilityBar`, full-time verdict, links, classes, and disclaimer behavior.

- [ ] **Step 4: Run the hero tests and verify GREEN**

Run the Step 2 command. Expected: all three tests pass.

- [ ] **Step 5: Commit the hero**

```bash
git add 'frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.test.tsx'
git commit -m "feat(nrl): show live result in match hero"
```

---

### Task 3: Make the Live Section Consume Shared State

**Files:**
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.tsx`
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.test.tsx`

**Interfaces:**
- Consumes: `useLiveMatch()` from Task 1 and `LiveSectionClient`.
- Produces: a presentation-only `LiveSection` with no direct API call or interval.

- [ ] **Step 1: Rewrite one test to fail unless the section uses provider state**

Remove the section's direct `getNrlLiveClient` mock. Use the real provider with the
same `livePayload` and `scheduledMatch` factories from Task 1; one provider request
must supply the section:

```tsx
it("renders the shared live payload without starting another request", async () => {
  mockLive.mockResolvedValue(livePayload({ minute: 42, score_home: 12, score_away: 6 }));
  render(
    <LiveMatchProvider match={scheduledMatch}>
      <LiveSection detail={detail} probHistory={null} />
    </LiveMatchProvider>,
  );
  expect(await screen.findByRole("status", { name: /live score/i })).toHaveTextContent(
    "Wests Tigers 12–6 Warriors",
  );
  expect(mockLive).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run the Live section test and verify RED**

Run:

```bash
cd frontend
npx jest --runInBand --runTestsByPath './app/nrl/match/[season]/[round]/[no]/LiveSection.test.tsx'
```

Expected: FAIL because `LiveSection` still calls `getNrlLiveClient` and does not consume the harness state.

- [ ] **Step 3: Replace polling logic with context consumption**

Reduce `LiveSection` to:

```tsx
export default function LiveSection({ detail }: IntelSectionProps) {
  const state = useLiveMatch();
  if (state.status === "error") {
    return <div className="glass rounded-2xl p-6 text-sm text-muted">Live updates are unavailable right now.</div>;
  }
  if (state.status !== "success" || state.data.status === "pre") return null;
  return (
    <LiveSectionClient
      home={detail.match.home ?? "Home"}
      away={detail.match.away ?? "Away"}
      live={state.data}
    />
  );
}
```

Remove `getNrlLiveClient`, `useFetch`, `NrlLive`, `POLL_MS`, and final-state seeding from this file.

- [ ] **Step 4: Run the Live section tests and verify GREEN**

Run the Step 2 command. Expected: all Live section tests pass.

- [ ] **Step 5: Commit the Live section refactor**

```bash
git add 'frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.test.tsx'
git commit -m "refactor(nrl): reuse shared live feed in match intel"
```

---

### Task 4: Wire the Provider and Hero into the Match Page

**Files:**
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/page.tsx`
- Modify: `frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx`

**Interfaces:**
- Consumes: `LiveMatchProvider` from Task 1 and `NrlMatchHero` from Task 2.
- Produces: the existing route with one provider wrapping both the hero and `MatchIntelClient`.

- [ ] **Step 1: Add a failing page integration test**

Mock `getNrlLiveClient` to resolve a live payload, render the server page, and wait for the hero result:

```tsx
it("updates the match hero from the shared live endpoint", async () => {
  mockLive.mockResolvedValue({
    status: "live", minute: 42, score_home: 12, score_away: 6,
    live_home_prob: 0.71, events: [],
  });
  render(await NrlMatchDetailPage({ params: params() }));
  expect(await screen.findByText("12–6")).toBeInTheDocument();
  expect(screen.getByRole("status", { name: /live match/i })).toHaveTextContent("42′");
});
```

In `beforeEach`, make the default live mock resolve a `pre` payload so existing page tests do not receive undefined from the blanket API mock.

- [ ] **Step 2: Run the page test and verify RED**

Run:

```bash
cd frontend
npx jest --runInBand --runTestsByPath './app/nrl/match/[season]/[round]/[no]/page.test.tsx'
```

Expected: FAIL because the page has no provider or live-aware hero.

- [ ] **Step 3: Wire the page and remove migrated inline code**

Import `LiveMatchProvider` and `NrlMatchHero`. Wrap the existing page content:

```tsx
return (
  <LiveMatchProvider match={match}>
    <div className="fade-up mx-auto max-w-2xl space-y-6">
      {/* existing route header and LocalKickoff */}
      <NrlMatchHero match={match} home={home} away={away} />
      {/* existing pending card, MatchIntelClient, ladder, disclaimer */}
    </div>
  </LiveMatchProvider>
);
```

Delete only the hero-specific calculations and markup now owned by `NrlMatchHero`:
`finished`, `hasScore`, `favoured`, `favouredProb`, `called`, the matchup `section`,
`TeamCol`, and `marginLabel`. Keep page loading, metadata, pending-prediction card,
ladder, and disclaimer unchanged.

- [ ] **Step 4: Run all focused match-detail tests**

Run:

```bash
cd frontend
npx jest --runInBand --runTestsByPath \
  './app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.test.tsx' \
  './app/nrl/match/[season]/[round]/[no]/NrlMatchHero.test.tsx' \
  './app/nrl/match/[season]/[round]/[no]/LiveSection.test.tsx' \
  './app/nrl/match/[season]/[round]/[no]/page.test.tsx'
```

Expected: all focused tests pass with no unhandled promise or React `act()` warnings introduced by this change.

- [ ] **Step 5: Commit page integration**

```bash
git add 'frontend/app/nrl/match/[season]/[round]/[no]/page.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx'
git commit -m "feat(nrl): wire live score into match detail header"
```

---

### Task 5: Full Frontend Verification

**Files:**
- Verify only; modify files only to fix failures caused by Tasks 1–4.

**Interfaces:**
- Consumes: completed Tasks 1–4.
- Produces: fresh evidence that the frontend compiles, lints, and passes its full suite.

- [ ] **Step 1: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: exit 0 with no TypeScript errors.

- [ ] **Step 2: Run lint**

```bash
cd frontend && npm run lint
```

Expected: exit 0 with no new warnings or errors.

- [ ] **Step 3: Run the full frontend test suite**

```bash
cd frontend && npm test -- --runInBand
```

Expected: all suites pass; record the exact suite/test counts.

- [ ] **Step 4: Verify the diff and scope**

```bash
git diff --check
git status --short
git diff origin/main...HEAD --stat
```

Expected: no whitespace errors; only the spec, plan, provider, hero, Live section,
and page files are changed; no backend or unrelated files appear.

- [ ] **Step 5: Commit any verification-only fixes**

If Tasks 1–4 already pass without fixes, do not create an empty commit. Otherwise:

```bash
git add \
  'frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/LiveMatchProvider.test.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/NrlMatchHero.test.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/LiveSection.test.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/page.tsx' \
  'frontend/app/nrl/match/[season]/[round]/[no]/page.test.tsx'
git commit -m "fix(nrl): close live score verification findings"
```
