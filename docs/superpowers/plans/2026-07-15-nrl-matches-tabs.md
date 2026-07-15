# NRL Fixtures Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `/nrl/matches` into the WC26-style segmented Upcoming/Live/Finished view, adapted to NRL rounds.

**Architecture:** Thin SSR page + client island (mirrors `app/matches/{page,MatchesClient}`). Pure helpers derive "live" from the kickoff window (list API only knows scheduled/finished) and group matches by round per tab. The island refetches the list every 60s only while a game is in its live window.

**Tech Stack:** Next.js 15 App Router, TypeScript, Jest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-07-15-nrl-matches-tabs-design.md`.

## Global Constraints

- No API changes; no changes to `SportMatchCard`, football pages, or Origin.
- Live window: `NRL_LIVE_WINDOW_MINUTES = 120`, status-!=finished + kickoff-elapsed bound (self-healing, same rationale as football's `MAX_LIVE_MINUTES` in `frontend/lib/liveLabel.ts`).
- Tab semantics: Upcoming = scheduled & not in window (round asc, kickoff asc); Finished = finished (round desc, kickoff desc); Live = in window (kickoff asc). Live strip pinned atop the Upcoming view.
- Empty-state copy: "No upcoming fixtures yet." / "No matches are live right now." / "No finished fixtures yet."
- Frontend gates before any commit claim: `cd frontend && npm run typecheck && npm run lint && npm test`.
- Work on branch `feat/nrl-matches-tabs`. TDD: RED before GREEN.

---

### Task 1: Live-window + grouping helpers, client fetcher

**Files:**
- Create: `frontend/lib/nrlLive.ts`
- Create: `frontend/lib/__tests__/nrlLive.test.ts`
- Modify: `frontend/lib/api.ts` (one client fetcher after the origin fetchers)

**Interfaces:**
- Consumes: `NrlMatch`, `NrlRound`, `NrlMatchesResponse` from `frontend/lib/types.ts`; `getJson` (already in `api.ts`).
- Produces (Task 2 relies on these exact names):
  - `NRL_LIVE_WINDOW_MINUTES: number`
  - `isNrlLiveNow(m: Pick<NrlMatch, "status" | "kickoff_utc">, now?: Date): boolean`
  - `RoundGroup = { round: number | null; matches: NrlMatch[] }`
  - `liveNow(rounds: NrlRound[], now?: Date): { round: number | null; match: NrlMatch }[]`
  - `upcomingRounds(rounds: NrlRound[], now?: Date): RoundGroup[]`
  - `finishedRounds(rounds: NrlRound[]): RoundGroup[]`
  - `getNrlMatches(): Promise<NrlMatchesResponse>` (client-side, in `api.ts`)

- [ ] **Step 1: Write the failing tests**

`frontend/lib/__tests__/nrlLive.test.ts`:

```typescript
import {
  finishedRounds,
  isNrlLiveNow,
  liveNow,
  NRL_LIVE_WINDOW_MINUTES,
  upcomingRounds,
} from "@/lib/nrlLive";
import type { NrlMatch, NrlRound } from "@/lib/types";

const NOW = new Date("2026-07-18T07:00:00Z");

function match(over: Partial<NrlMatch>): NrlMatch {
  return {
    match_no: 1, kickoff_utc: null, venue: null, home: "A", away: "B",
    home_team_id: 1, away_team_id: 2, score_home: null, score_away: null,
    status: "scheduled", prediction: null, ...over,
  } as NrlMatch;
}

describe("isNrlLiveNow", () => {
  it("is live from kickoff until the window closes", () => {
    const m = match({ kickoff_utc: "2026-07-18T06:00:00Z" }); // 60 min ago
    expect(isNrlLiveNow(m, NOW)).toBe(true);
  });
  it("is not live before kickoff, after the window, when finished, or undated", () => {
    expect(isNrlLiveNow(match({ kickoff_utc: "2026-07-18T08:00:00Z" }), NOW)).toBe(false);
    const stale = new Date(NOW.getTime() + (NRL_LIVE_WINDOW_MINUTES + 1) * 60_000);
    expect(isNrlLiveNow(match({ kickoff_utc: "2026-07-18T07:00:00Z" }), stale)).toBe(false);
    expect(isNrlLiveNow(match({ kickoff_utc: "2026-07-18T06:00:00Z", status: "finished" }), NOW)).toBe(false);
    expect(isNrlLiveNow(match({}), NOW)).toBe(false);
  });
});

const ROUNDS: NrlRound[] = [
  { round: 19, matches: [
    match({ match_no: 1, status: "finished", kickoff_utc: "2026-07-11T05:00:00Z", score_home: 6, score_away: 32 }),
    match({ match_no: 2, status: "finished", kickoff_utc: "2026-07-12T05:00:00Z", score_home: 22, score_away: 18 }),
  ]},
  { round: 20, matches: [
    match({ match_no: 3, status: "scheduled", kickoff_utc: "2026-07-18T06:30:00Z" }), // in window (30 min ago)
    match({ match_no: 4, status: "scheduled", kickoff_utc: "2026-07-18T09:35:00Z" }),
    match({ match_no: 5, status: "scheduled", kickoff_utc: "2026-07-19T04:00:00Z" }),
  ]},
  { round: 21, matches: [
    match({ match_no: 6, status: "scheduled", kickoff_utc: "2026-07-23T09:50:00Z" }),
  ]},
];

describe("grouping", () => {
  it("liveNow returns only in-window matches, tagged with their round", () => {
    expect(liveNow(ROUNDS, NOW)).toEqual([
      { round: 20, match: expect.objectContaining({ match_no: 3 }) },
    ]);
  });
  it("upcomingRounds excludes live + finished, round asc, kickoff asc", () => {
    const groups = upcomingRounds(ROUNDS, NOW);
    expect(groups.map((g) => g.round)).toEqual([20, 21]);
    expect(groups[0].matches.map((m) => m.match_no)).toEqual([4, 5]);
  });
  it("finishedRounds is round desc, kickoff desc within", () => {
    const groups = finishedRounds(ROUNDS);
    expect(groups.map((g) => g.round)).toEqual([19]);
    expect(groups[0].matches.map((m) => m.match_no)).toEqual([2, 1]);
  });
  it("drops empty groups", () => {
    expect(finishedRounds([{ round: 22, matches: [match({})] }])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx jest lib/__tests__/nrlLive --verbose`
Expected: FAIL — cannot find module `@/lib/nrlLive`

- [ ] **Step 3: Implement `frontend/lib/nrlLive.ts`**

```typescript
import type { NrlMatch, NrlRound } from "./types";

/** NRL games run ~100 minutes wall-clock; 120 adds margin without stranding
 *  a "live" badge for hours when ingest lags. The list API only knows
 *  scheduled/finished, so liveness is derived purely from this kickoff
 *  window — self-healing, same rationale as liveLabel.MAX_LIVE_MINUTES. */
export const NRL_LIVE_WINDOW_MINUTES = 120;

export function isNrlLiveNow(
  m: Pick<NrlMatch, "status" | "kickoff_utc">,
  now: Date = new Date(),
): boolean {
  if (m.status === "finished" || !m.kickoff_utc) return false;
  const elapsedMin = (now.getTime() - new Date(m.kickoff_utc).getTime()) / 60_000;
  return elapsedMin >= 0 && elapsedMin <= NRL_LIVE_WINDOW_MINUTES;
}

export interface RoundGroup {
  round: number | null;
  matches: NrlMatch[];
}

const byKickoff = (dir: 1 | -1) => (a: NrlMatch, b: NrlMatch) =>
  dir * (a.kickoff_utc ?? "").localeCompare(b.kickoff_utc ?? "");

/** In-window matches across all rounds, kickoff asc, tagged with their round
 *  (SportMatchCard needs the round for its eyebrow and href). */
export function liveNow(
  rounds: NrlRound[],
  now: Date = new Date(),
): { round: number | null; match: NrlMatch }[] {
  return rounds
    .flatMap((r) => r.matches.filter((m) => isNrlLiveNow(m, now)).map((match) => ({ round: r.round, match })))
    .sort((a, b) => byKickoff(1)(a.match, b.match));
}

/** Scheduled and not in the live window — round asc, kickoff asc within. */
export function upcomingRounds(rounds: NrlRound[], now: Date = new Date()): RoundGroup[] {
  return rounds
    .map((r) => ({
      round: r.round,
      matches: r.matches
        .filter((m) => m.status === "scheduled" && !isNrlLiveNow(m, now))
        .sort(byKickoff(1)),
    }))
    .filter((g) => g.matches.length > 0)
    .sort((a, b) => (a.round ?? Infinity) - (b.round ?? Infinity));
}

/** Finished — round desc (latest results first), kickoff desc within. */
export function finishedRounds(rounds: NrlRound[]): RoundGroup[] {
  return rounds
    .map((r) => ({
      round: r.round,
      matches: r.matches.filter((m) => m.status === "finished").sort(byKickoff(-1)),
    }))
    .filter((g) => g.matches.length > 0)
    .sort((a, b) => (b.round ?? -Infinity) - (a.round ?? -Infinity));
}
```

- [ ] **Step 4: Add the client fetcher** — in `frontend/lib/api.ts`, directly after `getOriginRecordServer`:

```typescript
/** Client-side NRL fixtures fetch — backs the /nrl/matches island's 60s
 *  refresh while a game is in its live window. */
export const getNrlMatches = () => getJson<NrlMatchesResponse>("/api/nrl/matches");
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx jest lib/__tests__/nrlLive --verbose`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/nrlLive.ts frontend/lib/__tests__/nrlLive.test.ts frontend/lib/api.ts
git commit -m "feat(nrl): live-window + round-grouping helpers for the fixtures tabs"
```

---

### Task 2: MatchesClient island + thin page

**Files:**
- Create: `frontend/app/nrl/matches/MatchesClient.tsx`
- Create: `frontend/app/nrl/matches/MatchesClient.test.tsx`
- Modify: `frontend/app/nrl/matches/page.tsx` (replace body with thin wrapper)

**Interfaces:**
- Consumes: Task 1 helpers + `getNrlMatches`; `getNrlMatchesServer`; `SportMatchCard` (props: `match`, `eyebrow`, `season`, `round` — unchanged); `cn` from `@/lib/utils`.
- Produces: `MatchesClient({ initial }: { initial: NrlMatchesResponse })` client component.

- [ ] **Step 1: Write the failing component test**

`frontend/app/nrl/matches/MatchesClient.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { MatchesClient } from "./MatchesClient";
import type { NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api", () => ({ getNrlMatches: jest.fn() }));

const mins = (n: number) => new Date(Date.now() + n * 60_000).toISOString();

const fixtures: NrlMatchesResponse = {
  season: 2026,
  disclaimer: "d",
  rounds: [
    { round: 19, matches: [
      { match_no: 1, kickoff_utc: mins(-3 * 24 * 60), venue: null, home: "Dolphins", away: "Sharks",
        home_team_id: 1, away_team_id: 2, score_home: 0, score_away: 66, status: "finished", prediction: null },
    ]},
    { round: 20, matches: [
      { match_no: 2, kickoff_utc: mins(-30), venue: null, home: "Panthers", away: "Broncos",
        home_team_id: 3, away_team_id: 4, score_home: 12, score_away: 6, status: "scheduled", prediction: null },
      { match_no: 3, kickoff_utc: mins(60 * 24), venue: null, home: "Raiders", away: "Rabbitohs",
        home_team_id: 5, away_team_id: 6, score_home: null, score_away: null, status: "scheduled", prediction: null },
    ]},
  ],
};

it("defaults to Upcoming with the live strip pinned on top", () => {
  render(<MatchesClient initial={fixtures} />);
  expect(screen.getByText(/live now/i)).toBeInTheDocument();       // pinned strip label
  expect(screen.getByText("Panthers")).toBeInTheDocument();        // live match in strip
  expect(screen.getByText("Raiders")).toBeInTheDocument();         // upcoming below
  expect(screen.queryByText("Dolphins")).not.toBeInTheDocument();  // finished hidden
});

it("Finished tab shows results, latest round first, and hides live", () => {
  render(<MatchesClient initial={fixtures} />);
  fireEvent.click(screen.getByRole("button", { name: "Finished" }));
  expect(screen.getByText("Dolphins")).toBeInTheDocument();
  expect(screen.queryByText("Panthers")).not.toBeInTheDocument();
});

it("Live tab shows only in-window matches", () => {
  render(<MatchesClient initial={fixtures} />);
  fireEvent.click(screen.getByRole("button", { name: "Live" }));
  expect(screen.getByText("Panthers")).toBeInTheDocument();
  expect(screen.queryByText("Raiders")).not.toBeInTheDocument();
});

it("shows the per-tab empty state", () => {
  render(<MatchesClient initial={{ ...fixtures, rounds: [] }} />);
  expect(screen.getByText("No upcoming fixtures yet.")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx jest app/nrl/matches --verbose`
Expected: FAIL — cannot find module `./MatchesClient`

- [ ] **Step 3: Implement `frontend/app/nrl/matches/MatchesClient.tsx`**

Mirror the WC26 island's segmented-control markup and classes (read `frontend/app/matches/MatchesClient.tsx` — the `FILTERS.map` block — and reuse its button styling verbatim so the two pages look identical). Reference implementation:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { getNrlMatches } from "@/lib/api";
import { finishedRounds, liveNow, upcomingRounds } from "@/lib/nrlLive";
import type { NrlMatchesResponse } from "@/lib/types";
import { SportMatchCard } from "@/components/SportMatchCard";

type Filter = "Upcoming" | "Live" | "Finished";
const FILTERS: Filter[] = ["Upcoming", "Live", "Finished"];

const EMPTY: Record<Filter, string> = {
  Upcoming: "No upcoming fixtures yet.",
  Live: "No matches are live right now.",
  Finished: "No finished fixtures yet.",
};

/** Client island: segmented Upcoming/Live/Finished over the SSR-seeded
 *  fixtures. While any match is in its live window the list is refetched
 *  every 60s (scores land via the 15-min live poller); otherwise no polling. */
export function MatchesClient({ initial }: { initial: NrlMatchesResponse }) {
  const [fixtures, setFixtures] = useState(initial);
  const [filter, setFilter] = useState<Filter>("Upcoming");
  const [now, setNow] = useState(() => new Date());

  const live = useMemo(() => liveNow(fixtures.rounds, now), [fixtures, now]);

  useEffect(() => {
    if (live.length === 0) return;
    const tick = setInterval(() => {
      setNow(new Date());
      getNrlMatches().then(setFixtures).catch(() => {});
    }, 60_000);
    return () => clearInterval(tick);
  }, [live.length]);

  const groups = useMemo(
    () => (filter === "Finished" ? finishedRounds(fixtures.rounds) : upcomingRounds(fixtures.rounds, now)),
    [fixtures, filter, now],
  );

  const showStrip = filter !== "Finished" && live.length > 0;
  const empty =
    (filter === "Live" && live.length === 0) ||
    (filter !== "Live" && groups.length === 0 && !showStrip);

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL fixtures</h1>

      <div className="mt-4 flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={
              f === filter
                ? "rounded-full bg-lime-deep px-4 py-1.5 text-sm font-semibold text-black"
                : "glass rounded-full px-4 py-1.5 text-sm font-semibold text-muted"
            }
          >
            {f}
          </button>
        ))}
      </div>

      {showStrip ? (
        <section className="mt-6">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-live">
            <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-live align-middle" />
            Live now
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {live.map(({ round, match }) => (
              <SportMatchCard key={`${round}-${match.match_no}`} match={match}
                eyebrow={`Round ${round ?? "TBC"} · LIVE`} season={fixtures.season} round={round} />
            ))}
          </div>
        </section>
      ) : null}

      {filter !== "Live" &&
        groups.map((g) => (
          <section key={String(g.round)} className="mt-8">
            <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
              Round {g.round ?? "TBC"}
            </h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {g.matches.map((m) => (
                <SportMatchCard key={m.match_no} match={m}
                  eyebrow={`Round ${g.round ?? "TBC"}`} season={fixtures.season} round={g.round} />
              ))}
            </div>
          </section>
        ))}

      {empty ? <p className="mt-8 text-sm text-muted">{EMPTY[filter]}</p> : null}
    </div>
  );
}
```

Adaptation rules: if `text-live`/`bg-live` tokens don't exist in the Tailwind config, use the live-badge classes `SportMatchCard` or the WC26 island already uses (search for the LIVE badge) — never invent new color tokens.

- [ ] **Step 4: Replace `frontend/app/nrl/matches/page.tsx` body**

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlMatchesServer } from "@/lib/api";
import { MatchesClient } from "./MatchesClient";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "NRL fixtures — FinalWhistle",
  description:
    "Every NRL fixture with the model's frozen win probabilities, filterable by upcoming, live, or finished.",
};

export default async function NrlMatchesPage() {
  const fixtures = await getNrlMatchesServer().catch(() => null);
  if (!fixtures) notFound();
  return <MatchesClient initial={fixtures} />;
}
```

- [ ] **Step 5: Run tests, then the full gates**

Run: `cd frontend && npx jest app/nrl/matches lib/__tests__/nrlLive --verbose` → all PASS
Then: `npm run typecheck && npm run lint && npm test` → all green (existing NRL page tests must still pass; if the old matches-page snapshot/test asserted the flat round list, update it to the new wrapper behavior — do not weaken unrelated tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/app/nrl/matches/ frontend/lib/api.ts
git commit -m "feat(nrl): WC26-style Upcoming/Live/Finished tabs on the fixtures page"
```

---

### Task 3: PR + verification (stop-gated merge)

- [ ] **Step 1:** Push branch, open PR titled "feat(nrl): Upcoming/Live/Finished tabs on /nrl/matches (WC26 parity)" with a body summarizing the spec, the live-window derivation, and the 60s-while-live refresh. Include gate outputs. End the body with the standard Claude Code attribution.
- [ ] **Step 2:** Confirm CI green. Do NOT merge — the human's "go" gates the merge, then Vercel deploys and `/nrl/matches` gets verified on prod (tabs render, Finished shows Round 19 results first, Upcoming leads with Round 20; if a game is in its window, the live strip appears).
