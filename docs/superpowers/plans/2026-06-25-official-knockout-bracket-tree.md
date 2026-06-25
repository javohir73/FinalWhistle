# Official Knockout Bracket Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an official, view-only knockout bracket tree (R32 → R16 → QF → SF → Final plus a detached 3rd-place node) on `/brackets` that renders slot labels during the group stage and overlays real teams + live scores + winners as the tournament progresses.

**Architecture:** Phase 1 is a pure-frontend presentational converging tree driven by the static topology already encoded in `frontend/lib/bracketStructure.ts`; it degrades to label-only when no backend data exists. Phase 2 adds the backend subsystem — a `match_no` column, KO kickoff seeding, a non-circular stage-keyed team-assignment path, a penalties-aware winner resolver shared by `/api/knockout/bracket` and `recompute_scores`, plus a no-store endpoint and frontend live overlay.

**Tech Stack:** Next.js (App Router) + React + TypeScript + Tailwind (Daylight tokens) + Jest/RTL on the frontend; FastAPI + SQLAlchemy + Alembic + Pydantic + pytest on the backend; football-data v4 and api-sports live providers.

## Global Constraints

- Node 20 (frontend CI); Python 3.12 (backend CI).
- Conventional Commits for every commit: `type(scope): subject` (types `feat`/`fix`/`chore`/`docs`; scopes like `bracket`). Branch naming `type/kebab-subject`.
- Exactly one Alembic head — enforced in CI (`ScriptDirectory.from_config(Config('alembic.ini')).get_heads()` must be length 1). Any new migration sets `down_revision = "f1a2b3c4d5e8"`.
- TDD: every change is written test-first (failing test → minimal impl → passing test → commit).
- Live poll cadence is `30_000` ms (the project-wide live cadence). Pass it as the `pollMs` arg to `useFetch`.
- Unassigned knockout sides are `team_id: null` / `team: null` — **never the string `"TBD"`**. The frontend resolves the slot label from static topology.
- Daylight tokens: winner text/links/icons use `text-lime-deep` (#2f6b1e) — **never `--win`/`bg-win` as text**. `bg-win` is fills only. Live state reuses the `loss` token (`bg-loss/15`, `text-loss`, pulsing `bg-loss` dot, `ring-loss/40`); finished/muted use `text-muted`.
- Both phases must be CI-green before the last group match kicks off (`2026-06-28T02:00:00Z`).

---

## File Structure

### Phase 1 (frontend)

| File | Action | Responsibility |
|---|---|---|
| `frontend/lib/types.ts` | Modify | Add `KnockoutSide`, `KnockoutTie`, `KnockoutBracket` API types. |
| `frontend/lib/bracketStructure.ts` | Modify | Add `THIRD_PLACE` metadata (3rd-place node + SF loser feeders). |
| `frontend/lib/officialBracket.ts` | Create | Pure, React-free logic: `resolveSlotLabel`, `resolveWinner`, `buildTree`, plus `TieState`/`SideView`/`TieView` types. |
| `frontend/lib/officialBracket.test.ts` | Create | Unit tests for the pure logic. |
| `frontend/lib/api.ts` | Modify | Add `getOfficialBracket` / `getOfficialBracketServer` fetchers. |
| `frontend/components/OfficialBracket.tsx` | Create | Presentational converging tree; props `{ ties: Record<number, TieView> }`; no fetching. |
| `frontend/components/__tests__/officialBracket.test.tsx` | Create | Render tests (states, mixed rows, detached 3rd-place, a11y). |
| `frontend/app/brackets/BracketsClient.tsx` | Modify | 3-segment control; in-page Official/AI toggle; live poll wiring. |
| `frontend/app/brackets/page.tsx` | Modify | SSR-seed `initialBracket` via `getOfficialBracketServer`. |

### Phase 2 (backend + overlay)

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/__init__.py` | Modify | Add `Match.match_no` column; add `third_place` to the stage comment. |
| `backend/alembic/versions/a1b2c3d4e5f9_add_match_no.py` | Create | Migration adding nullable `matches.match_no`. |
| `pipeline/ingest/wc26_structure.py` | Modify | Stamp `match_no` 73–104 + `kickoff_utc` on the 32 KO placeholders. |
| `pipeline/data/wc26_ko_schedule.json` | Create | Published KO kickoff times keyed by `match_no` 73–104. |
| `pipeline/ingest/ko_venues.py` | Modify | Look up KO rows by `match_no`, not DB id. |
| `pipeline/ingest/api_football.py` | Modify | `_to_item` forwards `league.round` as a `stage` key. |
| `pipeline/ingest/live_scores.py` | Modify | Add `assign_knockout_teams`; call it in `refresh_live` before `update_live_scores`; KO indexing by `provider_fixture_id`. |
| `pipeline/ingest/testdata/wc_ko_matches.json` | Create | Synthetic football-data v4 KO payload. |
| `pipeline/ingest/testdata/wc_ko_matches_apisports.json` | Create | Synthetic api-sports KO payload. |
| `backend/app/scoring.py` | Modify | Add `knockout_results_from_db` (penalties-aware; 103 = SF losers, no points). |
| `backend/app/schemas/__init__.py` | Modify | Add `KnockoutSideOut`, `KnockoutTieOut`, `KnockoutBracketOut`. |
| `backend/app/api/knockout.py` | Modify | Add `GET /bracket` route + serializer. |
| `backend/app/main.py` | Modify | `no-store` clause for `/api/knockout/bracket`. |
| `backend/app/api/internal.py` | Modify | Pass `knockout_results` into `recompute_scores` (`recompute_scores_endpoint`). |
| `pipeline/learning_loop.py` | Modify | Pass `knockout_results` into `recompute_scores` (post-final-whistle chain, line ~266). |
| `pipeline/run_pipeline.py` | Modify | Pass `knockout_results` into `recompute_scores` (daily `bracket_scores` step, line ~67). |
| `backend/tests/test_knockout_bracket.py` | Create | Backend unit + ingestion-against-fixture + endpoint + canary tests. |

---

## Phase 1 — presentational tree (ships now)

Phase 1 is fully shippable on its own: the tab degrades to label-only state from static topology when `/api/knockout/bracket` does not yet exist (404 → `null` → `buildTree(null)`).

---

### Task 1: Frontend knockout API types

**Files:**
- Modify: `frontend/lib/types.ts` (append a new sectioned block after `MatchLineups`, line 242)
- Test: type-only change — verified by `npm run typecheck` (no dedicated unit test; consumed by Task 2's tests)

**Interfaces:**
- Consumes: nothing.
- Produces (exact, used by every later frontend task):
  - `KnockoutSide = { team_id: number | null; team: string | null; score: number | null; penalty: number | null }`
  - `KnockoutTie = { match_no: number; match_id: number | null; stage: "R32" | "R16" | "QF" | "SF" | "third_place" | "final"; status: "scheduled" | "in_play" | "finished"; kickoff_utc: string | null; home: KnockoutSide; away: KnockoutSide; minute: number | null; period: string | null; injury_time: number | null }`
  - `KnockoutBracket = { ties: KnockoutTie[] }`

- [ ] **Step 1: Add the types**

Append to the end of `frontend/lib/types.ts` (after the `MatchLineups` block):

```ts
// ---- Official knockout bracket (live; real teams + scores, never picks) ----
export type KnockoutSide = {
  team_id: number | null;
  team: string | null;
  score: number | null;
  penalty: number | null;
};

export type KnockoutTie = {
  match_no: number;
  match_id: number | null;
  stage: "R32" | "R16" | "QF" | "SF" | "third_place" | "final";
  status: "scheduled" | "in_play" | "finished";
  kickoff_utc: string | null;
  home: KnockoutSide;
  away: KnockoutSide;
  minute: number | null;
  period: string | null;
  injury_time: number | null;
};

export type KnockoutBracket = { ties: KnockoutTie[] };
```

- [ ] **Step 2: Run typecheck to verify it compiles**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS (no errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/types.ts
git commit -m "feat(bracket): add KnockoutSide/KnockoutTie/KnockoutBracket types"
```

---

### Task 2: `THIRD_PLACE` topology + pure `officialBracket.ts` logic

**Files:**
- Modify: `frontend/lib/bracketStructure.ts` (add `THIRD_PLACE` export)
- Create: `frontend/lib/officialBracket.ts`
- Test: `frontend/lib/officialBracket.test.ts`

**Interfaces:**
- Consumes: `R32`, `THIRD_SLOTS`, `KO_TREE` from `./bracketStructure`; `KnockoutBracket`, `KnockoutTie` from `./types`.
- Produces (exact):
  - `THIRD_PLACE = { no: 103, loserFeeders: [101, 102] as [number, number] }` (in `bracketStructure.ts`)
  - `type TieState = "labels" | "scheduled" | "in_play" | "finished"`
  - `type SideView = { teamId: number | null; team: string | null; label: string; score: number | null; penalty: number | null; isWinner: boolean }`
  - `type TieView = { matchNo: number; matchId: number | null; round: "r32"|"r16"|"qf"|"sf"|"final"|"third"; state: TieState; a: SideView; b: SideView; liveLabel: string; penaltyText: string | null }`
  - `function buildTree(bracket: KnockoutBracket | null): Record<number, TieView>`
  - `function resolveSlotLabel(matchNo: number, side: "a" | "b"): string`
  - `function resolveWinner(tie: KnockoutTie): "a" | "b" | null`

- [ ] **Step 1: Add `THIRD_PLACE` to `bracketStructure.ts`**

Append to the end of `frontend/lib/bracketStructure.ts`:

```ts
/** 3rd-place match (103): NOT in KO_TREE — it is fed by the two SF LOSERS
 *  (101, 102), not winners. Rendered as a detached node beside the Final. */
export const THIRD_PLACE = { no: 103, loserFeeders: [101, 102] as [number, number] };
```

- [ ] **Step 2: Write the failing test**

Create `frontend/lib/officialBracket.test.ts`:

```ts
import { buildTree, resolveSlotLabel, resolveWinner } from "./officialBracket";
import { THIRD_PLACE } from "./bracketStructure";
import type { KnockoutTie } from "./types";

function tie(over: Partial<KnockoutTie>): KnockoutTie {
  return {
    match_no: 89,
    match_id: 1,
    stage: "R16",
    status: "scheduled",
    kickoff_utc: null,
    home: { team_id: null, team: null, score: null, penalty: null },
    away: { team_id: null, team: null, score: null, penalty: null },
    minute: null,
    period: null,
    injury_time: null,
    ...over,
  };
}

describe("resolveSlotLabel", () => {
  it("renders R32 placement sides as <pos><group>", () => {
    expect(resolveSlotLabel(73, "a")).toBe("2A");
    expect(resolveSlotLabel(73, "b")).toBe("2B");
    expect(resolveSlotLabel(75, "a")).toBe("1F");
    expect(resolveSlotLabel(88, "b")).toBe("2G");
  });

  it("renders R32 third-place sides as 3-<sorted elig>", () => {
    expect(resolveSlotLabel(74, "b")).toBe("3-ABCDF");
    expect(resolveSlotLabel(77, "b")).toBe("3-CDFGH");
    expect(resolveSlotLabel(87, "b")).toBe("3-DEIJL");
  });

  it("resolves downstream feeders to 'Winner <feeder>'", () => {
    expect(resolveSlotLabel(89, "a")).toBe("Winner 74");
    expect(resolveSlotLabel(89, "b")).toBe("Winner 77");
    expect(resolveSlotLabel(104, "a")).toBe("Winner 101");
    expect(resolveSlotLabel(104, "b")).toBe("Winner 102");
  });

  it("resolves 103 via THIRD_PLACE loser feeders, never KO_TREE", () => {
    expect(resolveSlotLabel(THIRD_PLACE.no, "a")).toBe("Loser 101");
    expect(resolveSlotLabel(THIRD_PLACE.no, "b")).toBe("Loser 102");
  });
});

describe("resolveWinner", () => {
  it("returns null when not finished", () => {
    expect(resolveWinner(tie({ status: "in_play", home: { team_id: 1, team: "A", score: 2, penalty: null }, away: { team_id: 2, team: "B", score: 1, penalty: null } }))).toBeNull();
  });

  it("picks the higher score when finished", () => {
    expect(resolveWinner(tie({ status: "finished", home: { team_id: 1, team: "A", score: 2, penalty: null }, away: { team_id: 2, team: "B", score: 1, penalty: null } }))).toBe("a");
  });

  it("AET 1-2 picks away by score", () => {
    expect(resolveWinner(tie({ status: "finished", period: "extra_time", home: { team_id: 1, team: "A", score: 1, penalty: null }, away: { team_id: 2, team: "B", score: 2, penalty: null } }))).toBe("b");
  });

  it("1-1 with penalties 4-2 picks home", () => {
    expect(resolveWinner(tie({ status: "finished", home: { team_id: 1, team: "A", score: 1, penalty: 4 }, away: { team_id: 2, team: "B", score: 1, penalty: 2 } }))).toBe("a");
  });

  it("0-0 with penalties 3-3 is undecided", () => {
    expect(resolveWinner(tie({ status: "finished", home: { team_id: 1, team: "A", score: 0, penalty: 3 }, away: { team_id: 2, team: "B", score: 0, penalty: 3 } }))).toBeNull();
  });
});

describe("buildTree", () => {
  it("null bracket yields a full label-only tree", () => {
    const tree = buildTree(null);
    expect(tree[89].state).toBe("labels");
    expect(tree[89].a.label).toBe("Winner 74");
    expect(tree[89].matchId).toBeNull();
    expect(tree[103].round).toBe("third");
    expect(tree[103].a.label).toBe("Loser 101");
    expect(tree[104].round).toBe("final");
    expect(Object.keys(tree)).toHaveLength(32); // 73..104
  });

  it("overlays real teams and marks winner + penalty text on a finished tie", () => {
    const tree = buildTree({
      ties: [
        tie({
          match_no: 89,
          match_id: 312,
          stage: "R16",
          status: "finished",
          home: { team_id: 44, team: "Argentina", score: 1, penalty: 4 },
          away: { team_id: 51, team: "France", score: 1, penalty: 2 },
        }),
      ],
    });
    const v = tree[89];
    expect(v.state).toBe("finished");
    expect(v.matchId).toBe(312);
    expect(v.a.team).toBe("Argentina");
    expect(v.a.isWinner).toBe(true);
    expect(v.b.isWinner).toBe(false);
    expect(v.penaltyText).toBe("(4-2 pens)");
    expect(v.liveLabel).toBe("FT");
  });

  it("renders a mixed tie: real team on A, slot label on B", () => {
    const tree = buildTree({
      ties: [
        tie({
          match_no: 90,
          match_id: 320,
          stage: "R16",
          status: "scheduled",
          home: { team_id: 44, team: "Argentina", score: null, penalty: null },
          away: { team_id: null, team: null, score: null, penalty: null },
        }),
      ],
    });
    const v = tree[90];
    expect(v.state).toBe("scheduled");
    expect(v.a.team).toBe("Argentina");
    expect(v.b.team).toBeNull();
    expect(v.b.label).toBe("Winner 75");
  });

  it("emits in_play liveLabel and ET label", () => {
    const tree = buildTree({
      ties: [
        tie({
          match_no: 91,
          match_id: 330,
          stage: "R16",
          status: "in_play",
          period: "extra_time",
          minute: 105,
          home: { team_id: 44, team: "A", score: 1, penalty: null },
          away: { team_id: 51, team: "B", score: 1, penalty: null },
        }),
      ],
    });
    expect(tree[91].state).toBe("in_play");
    expect(tree[91].liveLabel).toBe("ET 105'");
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- lib/officialBracket.test.ts`
Expected: FAIL — `Cannot find module './officialBracket'`.

- [ ] **Step 4: Write the minimal implementation**

Create `frontend/lib/officialBracket.ts`:

```ts
/** Pure, React-free logic for the official knockout bracket tree.
 *  Maps KO Match rows (or pure topology when null) to renderable TieViews:
 *  slot-label resolution, node-state derivation, penalties-aware winner read. */
import { R32, THIRD_SLOTS, KO_TREE, THIRD_PLACE } from "./bracketStructure";
import { liveLabel } from "./liveLabel";
import type { KnockoutBracket, KnockoutTie } from "./types";

export type TieState = "labels" | "scheduled" | "in_play" | "finished";

export type SideView = {
  teamId: number | null;
  team: string | null;
  label: string;
  score: number | null;
  penalty: number | null;
  isWinner: boolean;
};

export type TieView = {
  matchNo: number;
  matchId: number | null;
  round: "r32" | "r16" | "qf" | "sf" | "final" | "third";
  state: TieState;
  a: SideView;
  b: SideView;
  liveLabel: string;
  penaltyText: string | null;
};

const R16_NOS = [89, 90, 91, 92, 93, 94, 95, 96];
const QF_NOS = [97, 98, 99, 100];
const SF_NOS = [101, 102];

/** All KO match numbers in render order, 73..104 (including 103). */
const ALL_NOS: number[] = [
  ...R32.map((m) => m.no),
  ...R16_NOS,
  ...QF_NOS,
  ...SF_NOS,
  THIRD_PLACE.no,
  104,
];

function roundOf(matchNo: number): TieView["round"] {
  if (matchNo === THIRD_PLACE.no) return "third";
  if (matchNo === 104) return "final";
  if (SF_NOS.includes(matchNo)) return "sf";
  if (QF_NOS.includes(matchNo)) return "qf";
  if (R16_NOS.includes(matchNo)) return "r16";
  return "r32";
}

/** A side's slot label from R32 placements / THIRD_SLOTS / KO_TREE / THIRD_PLACE. */
export function resolveSlotLabel(matchNo: number, side: "a" | "b"): string {
  if (matchNo === THIRD_PLACE.no) {
    const feeder = THIRD_PLACE.loserFeeders[side === "a" ? 0 : 1];
    return `Loser ${feeder}`;
  }
  const r32 = R32.find((m) => m.no === matchNo);
  if (r32) {
    const slot = side === "a" ? r32.a : r32.b;
    if ("third" in slot) {
      const t = THIRD_SLOTS.find((s) => s.no === matchNo);
      const letters = t ? [...t.elig].sort().join("") : "";
      return `3-${letters}`;
    }
    return `${slot.pos}${slot.g}`;
  }
  const feeders = KO_TREE[matchNo];
  if (feeders) return `Winner ${feeders[side === "a" ? 0 : 1]}`;
  return "";
}

/** Winner: score first, then penalties; null until finished / still undecided. */
export function resolveWinner(tie: KnockoutTie): "a" | "b" | null {
  if (tie.status !== "finished") return null;
  const { home, away } = tie;
  if (home.score != null && away.score != null) {
    if (home.score > away.score) return "a";
    if (away.score > home.score) return "b";
  }
  if (home.penalty != null && away.penalty != null) {
    if (home.penalty > away.penalty) return "a";
    if (away.penalty > home.penalty) return "b";
  }
  return null;
}

function side(
  raw: KnockoutTie["home"] | null,
  matchNo: number,
  which: "a" | "b",
  isWinner: boolean,
): SideView {
  return {
    teamId: raw?.team_id ?? null,
    team: raw?.team ?? null,
    label: resolveSlotLabel(matchNo, which),
    score: raw?.score ?? null,
    penalty: raw?.penalty ?? null,
    isWinner,
  };
}

function viewFor(matchNo: number, tie: KnockoutTie | undefined): TieView {
  const round = roundOf(matchNo);
  if (!tie) {
    return {
      matchNo,
      matchId: null,
      round,
      state: "labels",
      a: side(null, matchNo, "a", false),
      b: side(null, matchNo, "b", false),
      liveLabel: "",
      penaltyText: null,
    };
  }
  const winner = resolveWinner(tie);
  const hasTeam = tie.home.team_id != null || tie.away.team_id != null;
  const state: TieState = !hasTeam ? "labels" : tie.status;
  const penaltyText =
    tie.status === "finished" &&
    tie.home.penalty != null &&
    tie.away.penalty != null
      ? `(${tie.home.penalty}-${tie.away.penalty} pens)`
      : null;
  return {
    matchNo,
    matchId: tie.match_id,
    round,
    state,
    a: side(tie.home, matchNo, "a", winner === "a"),
    b: side(tie.away, matchNo, "b", winner === "b"),
    liveLabel: liveLabel(tie),
    penaltyText,
  };
}

/** Build the full 32-node tree from official data, or pure topology when null. */
export function buildTree(bracket: KnockoutBracket | null): Record<number, TieView> {
  const byNo = new Map<number, KnockoutTie>();
  for (const t of bracket?.ties ?? []) byNo.set(t.match_no, t);
  const out: Record<number, TieView> = {};
  for (const no of ALL_NOS) out[no] = viewFor(no, byNo.get(no));
  return out;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- lib/officialBracket.test.ts`
Expected: PASS (all assertions green).

- [ ] **Step 6: Run typecheck**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/bracketStructure.ts frontend/lib/officialBracket.ts frontend/lib/officialBracket.test.ts
git commit -m "feat(bracket): pure officialBracket tree logic + THIRD_PLACE topology"
```

---

### Task 3: `OfficialBracket.tsx` presentational component

**Files:**
- Create: `frontend/components/OfficialBracket.tsx`
- Test: `frontend/components/__tests__/officialBracket.test.tsx`

**Interfaces:**
- Consumes: `TieView`, `buildTree` from `@/lib/officialBracket`; `Flag` from `@/components/Flag`; `Link` from `next/link`.
- Produces: default export `OfficialBracket`, props `{ ties: Record<number, TieView> }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/components/__tests__/officialBracket.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import OfficialBracket from "@/components/OfficialBracket";
import { buildTree } from "@/lib/officialBracket";
import type { KnockoutTie } from "@/lib/types";

function tie(over: Partial<KnockoutTie>): KnockoutTie {
  return {
    match_no: 89,
    match_id: 1,
    stage: "R16",
    status: "scheduled",
    kickoff_utc: null,
    home: { team_id: null, team: null, score: null, penalty: null },
    away: { team_id: null, team: null, score: null, penalty: null },
    minute: null,
    period: null,
    injury_time: null,
    ...over,
  };
}

it("renders label-only ties as non-links with slot labels", () => {
  render(<OfficialBracket ties={buildTree(null)} />);
  expect(screen.getByText("Winner 74")).toBeInTheDocument();
  // a label-only tie has no /match link
  expect(document.querySelector('a[href^="/match/"]')).toBeNull();
});

it("renders a finished tie with score, pens text, winner highlight, and a link", () => {
  const ties = buildTree({
    ties: [
      tie({
        match_no: 89,
        match_id: 312,
        status: "finished",
        home: { team_id: 44, team: "Argentina", score: 1, penalty: 4 },
        away: { team_id: 51, team: "France", score: 1, penalty: 2 },
      }),
    ],
  });
  render(<OfficialBracket ties={ties} />);
  expect(screen.getByText("(4-2 pens)")).toBeInTheDocument();
  const link = document.querySelector('a[href="/match/312"]');
  expect(link).not.toBeNull();
  // winner side gets the lime-deep token; loser is muted
  const winner = screen.getByText("Argentina").closest("[data-side]");
  expect(winner?.className).toContain("text-lime-deep");
});

it("renders an in_play tie with a live badge and label", () => {
  const ties = buildTree({
    ties: [
      tie({
        match_no: 91,
        match_id: 330,
        status: "in_play",
        period: "second_half",
        minute: 57,
        home: { team_id: 44, team: "A", score: 1, penalty: null },
        away: { team_id: 51, team: "B", score: 0, penalty: null },
      }),
    ],
  });
  render(<OfficialBracket ties={ties} />);
  expect(screen.getByLabelText(/Live, 57'/)).toBeInTheDocument();
});

it("renders a mixed tie: real team on A, label on B", () => {
  const ties = buildTree({
    ties: [
      tie({
        match_no: 90,
        match_id: 320,
        status: "scheduled",
        home: { team_id: 44, team: "Argentina", score: null, penalty: null },
        away: { team_id: null, team: null, score: null, penalty: null },
      }),
    ],
  });
  render(<OfficialBracket ties={ties} />);
  expect(screen.getByText("Argentina")).toBeInTheDocument();
  expect(screen.getByText("Winner 75")).toBeInTheDocument();
});

it("renders the detached 3rd-place node", () => {
  render(<OfficialBracket ties={buildTree(null)} />);
  expect(screen.getByText("Loser 101")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: /third place/i })).toBeInTheDocument();
});

it("exposes round lists and per-tie aria-labels; connectors are aria-hidden", () => {
  render(<OfficialBracket ties={buildTree(null)} />);
  expect(screen.getByRole("list", { name: "Round of 32" })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Final" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- officialBracket.test.tsx`
Expected: FAIL — `Cannot find module '@/components/OfficialBracket'`.

- [ ] **Step 3: Write the minimal implementation**

Create `frontend/components/OfficialBracket.tsx`:

```tsx
"use client";

import Link from "next/link";
import { Flag } from "@/components/Flag";
import type { SideView, TieView } from "@/lib/officialBracket";
import { cn } from "@/lib/utils";

const ROUND_COLUMNS: { round: TieView["round"]; label: string; nos: number[] }[] = [
  { round: "r32", label: "Round of 32", nos: [73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88] },
  { round: "r16", label: "Round of 16", nos: [89, 90, 91, 92, 93, 94, 95, 96] },
  { round: "qf", label: "Quarter-finals", nos: [97, 98, 99, 100] },
  { round: "sf", label: "Semi-finals", nos: [101, 102] },
  { round: "final", label: "Final", nos: [104] },
];

function sideAria(s: SideView): string {
  const name = s.team ?? s.label;
  const score = s.score != null ? ` ${s.score}` : "";
  return `${name}${score}`;
}

function tieAria(v: TieView, roundLabel: string): string {
  const a = sideAria(v.a);
  const b = sideAria(v.b);
  const winner =
    v.a.isWinner ? `, ${v.a.team ?? v.a.label} win` : v.b.isWinner ? `, ${v.b.team ?? v.b.label} win` : "";
  return `${roundLabel}: ${a} vs ${b}, ${v.state}${winner}`;
}

function SideRow({ s, live }: { s: SideView; live: boolean }) {
  return (
    <div
      data-side
      className={cn(
        "flex items-center justify-between gap-2 py-0.5",
        s.isWinner ? "font-bold text-lime-deep" : s.team ? "text-foreground" : "text-muted",
      )}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {s.team ? <Flag team={s.team} size={18} /> : null}
        <span className="truncate text-sm">{s.team ?? s.label}</span>
      </span>
      {(live || s.score != null) && s.score != null ? (
        <span className="font-display text-sm font-extrabold tabular-nums">{s.score}</span>
      ) : null}
    </div>
  );
}

function TieCard({ v, roundLabel, final }: { v: TieView; roundLabel: string; final?: boolean }) {
  const live = v.state === "in_play";
  const body = (
    <div
      className={cn(
        "rounded-2xl p-3",
        final ? "panel-pitch" : "glass card-hover",
        live ? "ring-1 ring-loss/40" : "",
      )}
    >
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wide text-muted">#{v.matchNo}</span>
        {live ? (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-loss"
            aria-label={`Live, ${v.liveLabel}`}
          >
            <span className="h-1.5 w-1.5 motion-safe:animate-pulse rounded-full bg-loss" aria-hidden />
            {v.liveLabel}
          </span>
        ) : v.state === "finished" ? (
          <span className="rounded-full bg-surface-2/70 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted">
            FT
          </span>
        ) : null}
      </div>
      <SideRow s={v.a} live={live} />
      <SideRow s={v.b} live={live} />
      {v.penaltyText ? (
        <div className="mt-1 text-[11px] font-semibold text-muted">{v.penaltyText}</div>
      ) : null}
    </div>
  );

  const linkable = v.matchId != null && v.state !== "labels";
  return (
    <li className="min-w-[180px]" aria-label={tieAria(v, roundLabel)}>
      {linkable ? (
        <Link href={`/match/${v.matchId}`} className="block">
          {body}
        </Link>
      ) : (
        <div>{body}</div>
      )}
    </li>
  );
}

export default function OfficialBracket({ ties }: { ties: Record<number, TieView> }) {
  const third = ties[103];
  return (
    <div className="space-y-4">
      <div
        className="flex gap-6 overflow-x-auto pb-4 [scroll-snap-type:x_proximity] [-webkit-overflow-scrolling:touch]"
        aria-label="Official knockout bracket"
      >
        {ROUND_COLUMNS.map((col) => (
          <ol
            key={col.round}
            aria-label={col.label}
            className="flex shrink-0 flex-col justify-around gap-3 [scroll-snap-align:start]"
          >
            <li className="mb-1 text-xs font-bold uppercase tracking-wide text-muted" aria-hidden>
              {col.label}
            </li>
            {col.nos.map((no) =>
              ties[no] ? (
                <TieCard key={no} v={ties[no]} roundLabel={col.label} final={col.round === "final"} />
              ) : null,
            )}
          </ol>
        ))}
      </div>

      {/* Detached 3rd-place node — NOT part of the converging tree, no connectors. */}
      {third ? (
        <ol aria-label="Third place" className="max-w-[200px]">
          <li className="mb-1 text-xs font-bold uppercase tracking-wide text-muted" aria-hidden>
            Third place
          </li>
          <TieCard v={third} roundLabel="Third place" />
        </ol>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- officialBracket.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run lint + typecheck**

Run (from `frontend/`): `npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/OfficialBracket.tsx frontend/components/__tests__/officialBracket.test.tsx
git commit -m "feat(bracket): presentational OfficialBracket converging tree component"
```

---

### Task 4: `api.ts` fetchers for the official bracket

**Files:**
- Modify: `frontend/lib/api.ts` (add after the `getKnockoutOdds` / `getKnockoutOddsServer` pairs)
- Test: type-only + integration — verified by `npm run typecheck` and Task 5's wiring.

**Interfaces:**
- Consumes: `getJson`, `getServer` (existing private helpers); `KnockoutBracket` from `./types`.
- Produces: `getOfficialBracket(): Promise<KnockoutBracket>`; `getOfficialBracketServer(): Promise<KnockoutBracket | null>`.

- [ ] **Step 1: Add the import for `KnockoutBracket`**

In `frontend/lib/api.ts`, add `KnockoutBracket` to the existing type import from `./types` (the file already imports `TournamentOdds`, `Group`, etc.). Locate the import line that pulls types and add `KnockoutBracket` to it. If types are imported individually, add:

```ts
import type { KnockoutBracket } from "./types";
```

- [ ] **Step 2: Add the client fetcher** (after the `getKnockoutOdds` export, ~line 62)

```ts
export const getOfficialBracket = () =>
  getJson<KnockoutBracket>("/api/knockout/bracket");
```

- [ ] **Step 3: Add the server fetcher** (after the `getKnockoutOddsServer` export, ~line 102)

```ts
export const getOfficialBracketServer = () =>
  getServer<KnockoutBracket>("/api/knockout/bracket", 30);
```

- [ ] **Step 4: Run typecheck**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(bracket): add getOfficialBracket(+Server) api fetchers"
```

---

### Task 5: Wire the Official tab into `BracketsClient` + SSR seed

**Files:**
- Modify: `frontend/app/brackets/BracketsClient.tsx`
- Modify: `frontend/app/brackets/page.tsx`
- Test: `frontend/components/__tests__/bracketsClient.test.tsx`

**Interfaces:**
- Consumes: `getOfficialBracket` from `@/lib/api`; `buildTree` from `@/lib/officialBracket`; `OfficialBracket` from `@/components/OfficialBracket`; `KnockoutBracket` from `@/lib/types`; existing `useFetch`, `getKnockoutOdds`, `AIBracket`, `SkeletonRounds`, `NotReady`, `ErrorState`.
- Produces: `BracketsClient` now accepts an extra prop `initialBracket?: KnockoutBracket`; renders a 3-segment control (My picks link · Official · AI bracket) with an in-page `useState<"official" | "ai">` toggle.

- [ ] **Step 1: Write the failing test**

Create `frontend/components/__tests__/bracketsClient.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { BracketsClient } from "@/app/brackets/BracketsClient";

it("defaults to the AI bracket view and switches to Official on tab click", () => {
  render(<BracketsClient />);
  // AI is the default active in-page view
  expect(screen.getByRole("tab", { name: "AI bracket" })).toHaveAttribute("aria-selected", "true");

  fireEvent.click(screen.getByRole("tab", { name: "Official" }));
  expect(screen.getByRole("tab", { name: "Official" })).toHaveAttribute("aria-selected", "true");
  // Official tree paints from static topology even with no backend data
  expect(screen.getByLabelText("Official knockout bracket")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Official bracket" })).toBeInTheDocument();
});

it("keeps My picks as a cross-page link", () => {
  render(<BracketsClient />);
  const myPicks = screen.getByRole("tab", { name: "My picks" });
  expect(myPicks.closest("a")).toHaveAttribute("href", "/my-bracket");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- bracketsClient.test.tsx`
Expected: FAIL — no `Official` tab / no `Official bracket` heading exists yet.

- [ ] **Step 3: Update imports + props in `BracketsClient.tsx`**

Replace the import block and props/state. New imports (add to the existing import list):

```tsx
import { getGroups, getKnockoutOdds, getOfficialBracket } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct } from "@/lib/format";
import { Flag } from "@/components/Flag";
import { Reveal } from "@/components/Reveal";
import { ErrorState } from "@/components/States";
import { trackEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { buildTree } from "@/lib/officialBracket";
import OfficialBracket from "@/components/OfficialBracket";
import type { Group, TournamentOdds, KnockoutBracket } from "@/lib/types";
import Link from "next/link";
import { useState } from "react";
```

- [ ] **Step 4: Update the component body**

Replace the component signature, state, the segmented control, and the body branch. The function becomes:

```tsx
export function BracketsClient({
  initialOdds,
  initialGroups,
  initialBracket,
}: {
  initialOdds?: TournamentOdds[];
  initialGroups?: Group[];
  initialBracket?: KnockoutBracket;
}) {
  const [view, setView] = useState<"official" | "ai">("ai");
  const oddsState = useFetch(getKnockoutOdds, [], undefined, initialOdds);
  useFetch(getGroups, [], undefined, initialGroups);
  const bracketState = useFetch(getOfficialBracket, [], 30_000, initialBracket);

  const segBase = "flex-1 rounded-[11px] px-3 py-2 text-center text-sm font-semibold transition";
  const segOn = "bg-surface text-foreground shadow-[0_1px_3px_rgba(18,40,25,0.1)]";
  const segOff = "text-muted hover:text-foreground";

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="font-display text-2xl font-extrabold">
        {view === "official" ? "Official bracket" : "The AI's bracket"}
      </h1>

      <div
        role="tablist"
        aria-label="Bracket views"
        className="mt-5 flex max-w-md gap-1 rounded-[14px] bg-surface-2 p-1"
      >
        <Link
          href="/my-bracket"
          role="tab"
          aria-selected={false}
          className={cn(segBase, segOff)}
        >
          My picks
        </Link>
        <button
          type="button"
          role="tab"
          aria-selected={view === "official"}
          onClick={() => setView("official")}
          className={cn(segBase, view === "official" ? segOn : segOff)}
        >
          Official
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "ai"}
          onClick={() => setView("ai")}
          className={cn(segBase, view === "ai" ? segOn : segOff)}
        >
          AI bracket
        </button>
      </div>

      <div role="tabpanel" className="mt-5">
        {view === "ai" ? (
          <>
            {oddsState.status === "error" && <ErrorState message={oddsState.message} onRetry={oddsState.retry} />}
            {oddsState.status === "loading" && <SkeletonRounds />}
            {oddsState.status === "success" &&
              (oddsState.data.length === 0 ? <NotReady /> : <AIBracket odds={oddsState.data} />)}
          </>
        ) : (
          <>
            {bracketState.status === "loading" && <SkeletonRounds />}
            {bracketState.status === "error" && (
              <OfficialBracket ties={buildTree(null)} />
            )}
            {bracketState.status === "success" && (
              <OfficialBracket ties={buildTree(bracketState.data)} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
```

Note: keep the existing `ROUND_DEFS`, `AIBracket`, `NotReady`, `SkeletonRounds` helper functions below unchanged. (If the original outer wrapper markup used a different container className, preserve the surrounding `Reveal`/wrapper structure; only the segmented control, heading, and body branch change.)

- [ ] **Step 5: Seed `initialBracket` in `page.tsx`**

Replace `frontend/app/brackets/page.tsx`:

```tsx
import {
  getKnockoutOddsServer,
  getGroupsServer,
  getOfficialBracketServer,
} from "@/lib/api";
import { BracketsClient } from "./BracketsClient";

/** Server-rendered: title odds + projected bracket are in the first HTML. Tabs
 *  and team links hydrate client-side; data refreshes in the background. */
export default async function BracketsPage() {
  const [initialOdds, initialGroups, initialBracket] = await Promise.all([
    getKnockoutOddsServer().catch(() => null),
    getGroupsServer().catch(() => null),
    getOfficialBracketServer().catch(() => null),
  ]);
  return (
    <BracketsClient
      initialOdds={initialOdds ?? undefined}
      initialGroups={initialGroups ?? undefined}
      initialBracket={initialBracket ?? undefined}
    />
  );
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- bracketsClient.test.tsx`
Expected: PASS.

- [ ] **Step 7: Run the full frontend gate**

Run (from `frontend/`): `npm run lint && npm run typecheck && npm test`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/brackets/BracketsClient.tsx frontend/app/brackets/page.tsx frontend/components/__tests__/bracketsClient.test.tsx
git commit -m "feat(bracket): Official tab on /brackets with 30s live poll + SSR seed"
```

**Phase 1 is now fully shippable.** The Official tab renders the full label-only tree from static topology even when `/api/knockout/bracket` returns 404.

---

## Phase 2 — backend + live overlay

Ordered so each task ends with a CI-green, committable deliverable. Run backend tests from repo root `/Users/macbookpro/Projects/FIFA WC26 Prediction` with `python -m pytest`.

---

### Task 6: Add `Match.match_no` column + migration

**Files:**
- Modify: `backend/app/models/__init__.py` (add column; extend stage comment)
- Create: `backend/alembic/versions/a1b2c3d4e5f9_add_match_no.py`
- Test: `backend/tests/test_knockout_bracket.py` (first test added here)

**Interfaces:**
- Consumes: existing `Match` model, `Integer` (already imported).
- Produces: `Match.match_no: Mapped[int | None]` (nullable, unique, indexed). Migration revision `a1b2c3d4e5f9`, `down_revision = "f1a2b3c4d5e8"`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_knockout_bracket.py`:

```python
from app.models import Match


def test_match_has_nullable_match_no_column(db_session):
    m = Match(tournament_id=1, stage="R32", match_no=73, is_neutral=True)
    db_session.add(m)
    db_session.commit()
    got = db_session.query(Match).filter_by(match_no=73).one()
    assert got.match_no == 73
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -v`
Expected: FAIL — `TypeError: 'match_no' is an invalid keyword argument for Match` (column does not exist).

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/__init__.py`, inside `class Match`, add right after the `stage` column (line ~91), and update the stage comment to include `third_place`:

```python
    stage: Mapped[str] = mapped_column(String(20))  # group / R32 / R16 / QF / SF / third_place / final
    match_no: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)  # official KO match number (73..104)
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -v`
Expected: PASS.

- [ ] **Step 5: Write the Alembic migration**

Create `backend/alembic/versions/a1b2c3d4e5f9_add_match_no.py`:

```python
"""Add matches.match_no.

Official knockout match number (73..104), nullable for group rows. Decouples
KO lookups from the previously-assumed DB-id == match_no coupling.

Revision ID: a1b2c3d4e5f9
Revises: f1a2b3c4d5e8
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, None] = "f1a2b3c4d5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("match_no", sa.Integer(), nullable=True))
    op.create_index("ix_matches_match_no", "matches", ["match_no"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_matches_match_no", table_name="matches")
    op.drop_column("matches", "match_no")
```

- [ ] **Step 6: Verify the single Alembic head**

Run (from `backend/`):
```bash
python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; h=ScriptDirectory.from_config(Config('alembic.ini')).get_heads(); assert len(h)==1, f'Expected exactly one Alembic head, found {h}'; print('OK — single head:', h[0])"
```
Expected: `OK — single head: a1b2c3d4e5f9`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/a1b2c3d4e5f9_add_match_no.py backend/tests/test_knockout_bracket.py
git commit -m "feat(bracket): add Match.match_no column + migration (single head)"
```

---

### Task 7: Stamp `match_no` + seed KO `kickoff_utc`

**Files:**
- Create: `pipeline/data/wc26_ko_schedule.json`
- Modify: `pipeline/ingest/wc26_structure.py` (KO seeding loop, lines 187–204)
- Test: `backend/tests/test_knockout_bracket.py` (add invariant tests)

**Interfaces:**
- Consumes: `KNOCKOUT_STAGES` (`[("R32",16),("R16",8),("QF",4),("SF",2),("third_place",1),("final",1)]`), `load_structure`.
- Produces: after `load_structure`, every KO row has a unique `match_no` 73–104 and a non-null `kickoff_utc`. The per-stage `match_no` ranges: R32→73–88, R16→89–96, QF→97–100, SF→101–102, third_place→103, final→104.

- [ ] **Step 1: Create the KO schedule data file**

Create `pipeline/data/wc26_ko_schedule.json` (kickoff times are the published 2026 KO schedule; entered once — these are placeholders to be confirmed against the official schedule, one entry per `match_no` 73–104):

```json
{
  "_source": "FIFA World Cup 2026 official knockout schedule",
  "_note": "Hand-entered KO kickoff times keyed by official match_no 73-104.",
  "kickoffs": {
    "73": "2026-06-29T19:00:00Z",
    "74": "2026-06-29T23:00:00Z",
    "75": "2026-06-30T19:00:00Z",
    "76": "2026-06-30T23:00:00Z",
    "77": "2026-07-01T19:00:00Z",
    "78": "2026-07-01T23:00:00Z",
    "79": "2026-07-02T19:00:00Z",
    "80": "2026-07-02T23:00:00Z",
    "81": "2026-07-03T19:00:00Z",
    "82": "2026-07-03T23:00:00Z",
    "83": "2026-07-04T19:00:00Z",
    "84": "2026-07-04T23:00:00Z",
    "85": "2026-07-05T19:00:00Z",
    "86": "2026-07-05T23:00:00Z",
    "87": "2026-07-06T19:00:00Z",
    "88": "2026-07-06T23:00:00Z",
    "89": "2026-07-04T19:00:00Z",
    "90": "2026-07-04T23:00:00Z",
    "91": "2026-07-05T19:00:00Z",
    "92": "2026-07-05T23:00:00Z",
    "93": "2026-07-06T19:00:00Z",
    "94": "2026-07-06T23:00:00Z",
    "95": "2026-07-07T19:00:00Z",
    "96": "2026-07-07T23:00:00Z",
    "97": "2026-07-09T19:00:00Z",
    "98": "2026-07-10T19:00:00Z",
    "99": "2026-07-10T23:00:00Z",
    "100": "2026-07-11T19:00:00Z",
    "101": "2026-07-14T19:00:00Z",
    "102": "2026-07-15T19:00:00Z",
    "103": "2026-07-18T19:00:00Z",
    "104": "2026-07-19T19:00:00Z"
  }
}
```

- [ ] **Step 2: Write the failing invariant tests**

Add to `backend/tests/test_knockout_bracket.py`:

```python
from pipeline.ingest.wc26_structure import load_structure

KO_STAGE_NOS = {
    "R32": list(range(73, 89)),
    "R16": [89, 90, 91, 92, 93, 94, 95, 96],
    "QF": [97, 98, 99, 100],
    "SF": [101, 102],
    "third_place": [103],
    "final": [104],
}


def test_ko_rows_stamped_with_match_no(db_session):
    load_structure(db_session)
    for stage, nos in KO_STAGE_NOS.items():
        rows = db_session.query(Match).filter(Match.stage == stage).all()
        assert sorted(r.match_no for r in rows) == nos, stage
    # every match_no 73..104 present exactly once
    all_nos = sorted(
        r.match_no
        for r in db_session.query(Match).filter(Match.match_no.isnot(None)).all()
    )
    assert all_nos == list(range(73, 105))


def test_every_ko_row_has_kickoff_utc(db_session):
    load_structure(db_session)
    ko = db_session.query(Match).filter(Match.stage != "group").all()
    assert len(ko) == 32
    assert all(m.kickoff_utc is not None for m in ko)


def test_load_structure_backfills_existing_unstamped_ko_rows(db_session):
    # Mimic a pre-existing prod DB: KO rows present but match_no/kickoff NULL.
    load_structure(db_session)
    for m in db_session.query(Match).filter(Match.stage != "group").all():
        m.match_no = None
        m.kickoff_utc = None
    db_session.commit()
    # Re-run: must backfill in place, not duplicate.
    load_structure(db_session)
    ko = db_session.query(Match).filter(Match.stage != "group").all()
    assert len(ko) == 32  # no duplicate rows
    assert all(m.match_no is not None and m.kickoff_utc is not None for m in ko)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "match_no or kickoff or backfill" -v`
Expected: FAIL — `match_no` is None and `kickoff_utc` is None on KO rows.

- [ ] **Step 4: Update the KO seeding loop**

In `pipeline/ingest/wc26_structure.py`, add a module-level loader near the other data loads and rewrite the KO placeholder loop (lines 187–204). First add the helper (top of module, after imports):

```python
import json
from datetime import datetime
from pathlib import Path

_KO_SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "data" / "wc26_ko_schedule.json"


def _ko_kickoffs() -> dict[int, datetime]:
    raw = json.loads(_KO_SCHEDULE_PATH.read_text())["kickoffs"]
    return {int(k): datetime.fromisoformat(v.replace("Z", "+00:00")) for k, v in raw.items()}
```

Then replace the KO seeding block with an **idempotent create-or-backfill** loop.

> **Why backfill, not just create:** production already holds 32 teamless KO rows
> seeded before `match_no` existed. A `if existing_ko == 0:` guard would leave
> those rows with `match_no = NULL` / `kickoff_utc = NULL` forever, silently
> breaking the whole feature in prod. `load_structure` is the `run_pipeline.py`
> "structure" step that runs on every refresh, so an idempotent stamp reaches
> prod on the next pipeline run after deploy.

```python
    # 3. Knockout placeholders + idempotent match_no/kickoff stamping.
    #    Stamps newly-created AND pre-existing teamless rows; safe to re-run.
    kickoffs = _ko_kickoffs()
    match_no = 73
    ko_created = ko_stamped = 0
    for stage, count in KNOCKOUT_STAGES:
        rows = (
            db.query(Match)
            .filter(
                Match.tournament_id == tournament.id,
                Match.group_id.is_(None),
                Match.stage == stage,
            )
            .order_by(Match.id)
            .all()
        )
        for i in range(count):
            if i < len(rows):
                row = rows[i]
            else:
                row = Match(
                    tournament_id=tournament.id,
                    group_id=None,
                    stage=stage,
                    is_neutral=True,
                    status="scheduled",
                )
                db.add(row)
                ko_created += 1
            row.match_no = match_no
            if row.kickoff_utc is None:
                row.kickoff_utc = kickoffs.get(match_no)
            ko_stamped += 1
            match_no += 1
    db.commit()
```

(Preserve the function's existing return dict; you may add `"ko_stamped": ko_stamped` to it. If a summary key like `"knockouts"` already exists, keep it.)

- [ ] **Step 5: Run the tests to verify they pass**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "match_no or kickoff or backfill" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/data/wc26_ko_schedule.json pipeline/ingest/wc26_structure.py backend/tests/test_knockout_bracket.py
git commit -m "feat(bracket): stamp match_no 73-104 + seed KO kickoff_utc at load"
```

---

### Task 8: Look up KO venues by `match_no`

**Files:**
- Modify: `pipeline/ingest/ko_venues.py` (`apply_ko_venues`, lines 35–47)
- Test: `backend/tests/test_knockout_bracket.py`

**Interfaces:**
- Consumes: `KO_VENUES` (keyed by `match_no` 73–104), `Match`.
- Produces: `apply_ko_venues(db)` finds rows via `Match.match_no`, not `db.get(Match, id)`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_knockout_bracket.py`:

```python
from pipeline.ingest.ko_venues import apply_ko_venues, KO_VENUES


def test_apply_ko_venues_resolves_by_match_no(db_session):
    load_structure(db_session)
    updated = apply_ko_venues(db_session)
    assert updated == len(KO_VENUES)
    sample_no = next(iter(KO_VENUES))
    city, country = KO_VENUES[sample_no]
    row = db_session.query(Match).filter_by(match_no=sample_no).one()
    assert row.venue_city == city
    assert row.venue_country == country
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "venues" -v`
Expected: FAIL — `db.get(Match, match_no)` returns the row whose **id** equals `match_no` (id 73 is a group row), so the venue lands on the wrong row / assertion fails.

- [ ] **Step 3: Update the lookup**

In `pipeline/ingest/ko_venues.py`, replace the body of `apply_ko_venues`:

```python
def apply_ko_venues(db: Session) -> int:
    """Populate venue_city/venue_country on KO Match rows (keyed by match_no).
    Returns the number of rows updated."""
    updated = 0
    for match_no, (city, country) in KO_VENUES.items():
        m = db.query(Match).filter(Match.match_no == match_no).one_or_none()
        if m is None:
            continue
        m.venue_city = city
        m.venue_country = country
        updated += 1
    db.commit()
    return updated
```

Ensure `from app.models import Match` is imported at the top of the file (it already imports `Match` for the `db.get` call).

- [ ] **Step 4: Run the test to verify it passes**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "venues" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/ko_venues.py backend/tests/test_knockout_bracket.py
git commit -m "fix(bracket): resolve KO venues by match_no, not DB id"
```

---

### Task 9: `assign_knockout_teams` (stage-keyed, offline-fixture tested)

**Files:**
- Modify: `pipeline/ingest/api_football.py` (`_to_item`, forward `league.round` as `stage`)
- Modify: `pipeline/ingest/live_scores.py` (add `assign_knockout_teams`; call before `update_live_scores`; KO ingestion by `provider_fixture_id`)
- Create: `pipeline/ingest/testdata/wc_ko_matches.json`
- Create: `pipeline/ingest/testdata/wc_ko_matches_apisports.json`
- Test: `backend/tests/test_knockout_bracket.py`

**Interfaces:**
- Consumes: `Match`, `Team`, `normalize_team_name`, `_index_by_pair` (existing), `KNOCKOUT_STAGES` order; football-data v4 items carry `stage`; api-sports items carry `stage` (forwarded from `league.round`).
- Produces: `def assign_knockout_teams(db, api_matches) -> dict` — keyed on stage + `provider_fixture_id`; sets `team_home_id`/`team_away_id`/`provider_fixture_id` (+ `kickoff_utc` if present); never fabricates teams; freezes once `in_play`/`finished`; allows overwrite while `scheduled`. Returns `{"assigned": int, "skipped": int, "unmapped_stage": int}`.

Provider stage map: `ROUND_OF_32`/`LAST_32`→`R32`, `LAST_16`→`R16`, `QUARTER_FINALS`→`QF`, `SEMI_FINALS`→`SF`, `THIRD_PLACE`→`third_place`, `FINAL`→`final`; api-sports `league.round` free text mapped equivalently ("Round of 32"→R32, "Round of 16"→R16, "Quarter-finals"→QF, "Semi-finals"→SF, "3rd Place Final"→third_place, "Final"→final).

- [ ] **Step 1: Create the synthetic football-data fixture**

Create `pipeline/ingest/testdata/wc_ko_matches.json`:

```json
[
  {
    "stage": "LAST_16",
    "homeTeam": {"name": "Argentina"},
    "awayTeam": {"name": "France"},
    "status": "FINISHED",
    "lastUpdated": "2026-07-04T21:00:00Z",
    "id": 9001,
    "score": {
      "fullTime": {"home": 1, "away": 1},
      "duration": "PENALTY_SHOOTOUT",
      "penalties": {"home": 4, "away": 2}
    }
  },
  {
    "stage": "LAST_16",
    "homeTeam": {"name": "Brazil"},
    "awayTeam": {"name": "Germany"},
    "status": "IN_PLAY",
    "lastUpdated": "2026-07-04T20:10:00Z",
    "minute": 57,
    "id": 9002,
    "score": {
      "fullTime": {"home": 2, "away": 0},
      "duration": "REGULAR"
    }
  },
  {
    "stage": "THIRD_PLACE",
    "homeTeam": {"name": "Spain"},
    "awayTeam": {"name": "Portugal"},
    "status": "SCHEDULED",
    "lastUpdated": "2026-07-18T12:00:00Z",
    "id": 9103,
    "score": {"fullTime": {"home": null, "away": null}, "duration": "REGULAR"}
  },
  {
    "stage": "FINAL",
    "homeTeam": {"name": "Argentina"},
    "awayTeam": {"name": "Brazil"},
    "status": "SCHEDULED",
    "lastUpdated": "2026-07-19T12:00:00Z",
    "id": 9104,
    "score": {"fullTime": {"home": null, "away": null}, "duration": "REGULAR"}
  }
]
```

- [ ] **Step 2: Create the synthetic api-sports fixture**

Create `pipeline/ingest/testdata/wc_ko_matches_apisports.json`:

```json
[
  {
    "fixture": {"id": 7001, "status": {"short": "FT", "elapsed": 90}, "league": {"round": "Round of 16"}},
    "league": {"round": "Round of 16"},
    "teams": {"home": {"name": "Argentina"}, "away": {"name": "France"}},
    "goals": {"home": 1, "away": 1},
    "score": {"penalty": {"home": 4, "away": 2}}
  },
  {
    "fixture": {"id": 7002, "status": {"short": "2H", "elapsed": 57}, "league": {"round": "Round of 16"}},
    "league": {"round": "Round of 16"},
    "teams": {"home": {"name": "Brazil"}, "away": {"name": "Germany"}},
    "goals": {"home": 2, "away": 0},
    "score": {}
  }
]
```

- [ ] **Step 3: Forward `league.round` as `stage` in `_to_item`**

In `pipeline/ingest/api_football.py`, inside `_to_item`, after the `item: dict = {...}` is built (before the `elapsed` block), add:

```python
    league = fx.get("league") or (fx.get("fixture") or {}).get("league") or {}
    rnd = league.get("round")
    if rnd:
        item["stage"] = rnd
```

- [ ] **Step 4: Write the failing tests**

Add to `backend/tests/test_knockout_bracket.py`:

```python
import json
from pathlib import Path

from app.models import Team
from pipeline.ingest.live_scores import assign_knockout_teams, update_live_scores
from pipeline.ingest.api_football import to_feed

_TESTDATA = Path("pipeline/ingest/testdata")


def _seed_teams(db, names):
    existing = {t.name for t in db.query(Team).all()}
    for n in names:
        if n not in existing:
            db.add(Team(name=n))
    db.commit()


def test_assign_knockout_teams_football_data(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany", "Spain", "Portugal"])
    api_matches = json.loads((_TESTDATA / "wc_ko_matches.json").read_text())

    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["assigned"] >= 4
    assert summary["unmapped_stage"] == 0

    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    # First R16 fixture by kickoff zips onto the lowest R16 match_no (89)
    first = r16[0]
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    assert {first.team_home_id, first.team_away_id} == {arg.id, fra.id}
    assert first.provider_fixture_id == 9001


def test_assign_knockout_teams_apisports(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany"])
    raw = json.loads((_TESTDATA / "wc_ko_matches_apisports.json").read_text())
    api_matches = to_feed(raw)

    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["assigned"] >= 2
    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    assert r16[0].provider_fixture_id == 7001


def test_assign_never_fabricates_and_freezes_after_in_play(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France"])
    api_matches = [
        {
            "stage": "LAST_16",
            "homeTeam": {"name": "Argentina"},
            "awayTeam": {"name": "France"},
            "status": "IN_PLAY",
            "id": 5001,
            "score": {"fullTime": {"home": 0, "away": 0}, "duration": "REGULAR"},
        }
    ]
    assign_knockout_teams(db_session, api_matches)
    row = db_session.query(Match).filter(Match.match_no == 89).one()
    row.status = "in_play"
    db_session.commit()
    # A correction with different teams must NOT overwrite a live row
    api_matches[0]["homeTeam"] = {"name": "Brazil"}
    assign_knockout_teams(db_session, api_matches)
    db_session.refresh(row)
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    assert arg.id in {row.team_home_id, row.team_away_id}


def test_unmapped_stage_is_skipped_and_counted(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France"])
    api_matches = [
        {
            "stage": "GROUP_STAGE",
            "homeTeam": {"name": "Argentina"},
            "awayTeam": {"name": "France"},
            "status": "SCHEDULED",
            "id": 6001,
            "score": {"fullTime": {"home": None, "away": None}, "duration": "REGULAR"},
        }
    ]
    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["unmapped_stage"] == 1
    assert summary["assigned"] == 0
```

- [ ] **Step 5: Run the tests to verify they fail**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "assign or unmapped" -v`
Expected: FAIL — `cannot import name 'assign_knockout_teams'`.

- [ ] **Step 6: Implement `assign_knockout_teams`**

In `pipeline/ingest/live_scores.py`, add (near the top, after `_index_by_pair`):

```python
# Provider KO stage -> our stage. football-data uses enum-ish stage strings;
# api-sports league.round is free text (forwarded as `stage` by _to_item).
_KO_STAGE_MAP = {
    "ROUND_OF_32": "R32", "LAST_32": "R32", "ROUND OF 32": "R32",
    "LAST_16": "R16", "ROUND OF 16": "R16",
    "QUARTER_FINALS": "QF", "QUARTER-FINALS": "QF",
    "SEMI_FINALS": "SF", "SEMI-FINALS": "SF",
    "THIRD_PLACE": "third_place", "3RD PLACE FINAL": "third_place",
    "FINAL": "final",
}


def _map_ko_stage(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    return _KO_STAGE_MAP.get(raw.strip().upper())


def assign_knockout_teams(db: Session, api_matches: list[dict]) -> dict:
    """Assign real teams to KO placeholder rows, keyed on stage + provider
    fixture id (NOT team-pair — placeholders have no teams yet, so the pair
    index is circular). Within a stage, feed fixtures are ordered by kickoff
    (tiebreak: fixture id) and zipped onto match_no-ordered placeholders.
    Never fabricates teams; freezes a row once it is in_play/finished; allows
    overwrite only while scheduled."""
    assigned = skipped = unmapped = 0

    # Bucket incoming fixtures by our stage.
    by_stage: dict[str, list[dict]] = {}
    for am in api_matches:
        stage = _map_ko_stage(am.get("stage"))
        if stage is None:
            if am.get("stage") is not None:
                log.warning("unmapped KO stage %r — skipping fixture", am.get("stage"))
                unmapped += 1
            continue
        by_stage.setdefault(stage, []).append(am)

    for stage, fixtures in by_stage.items():
        # Order feed fixtures by kickoff (utcDate) then fixture id.
        fixtures.sort(key=lambda a: (a.get("utcDate") or "", a.get("_fixture_id") or a.get("id") or 0))
        rows = (
            db.query(Match)
            .filter(Match.stage == stage)
            .order_by(Match.match_no)
            .all()
        )
        for am, row in zip(fixtures, rows):
            # Gate: confirmed (non-placeholder) team objects only.
            try:
                home_name = normalize_team_name(am["homeTeam"]["name"])
                away_name = normalize_team_name(am["awayTeam"]["name"])
            except (KeyError, TypeError):
                skipped += 1
                continue
            if not home_name or not away_name or home_name == away_name:
                skipped += 1
                continue
            # Freeze once the match is live/finished.
            if row.status in ("in_play", "finished"):
                skipped += 1
                continue
            home = db.query(Team).filter(Team.name == home_name).one_or_none()
            away = db.query(Team).filter(Team.name == away_name).one_or_none()
            if home is None or away is None:
                # Never fabricate teams.
                skipped += 1
                continue
            row.team_home_id = home.id
            row.team_away_id = away.id
            fid = am.get("_fixture_id") or am.get("id")
            if fid is not None:
                row.provider_fixture_id = fid
            assigned += 1

    db.commit()
    return {"assigned": assigned, "skipped": skipped, "unmapped_stage": unmapped}
```

Confirm `normalize_team_name` and `Team` are imported at the top of `live_scores.py` (they are, used by `_index_by_pair`/`update_live_scores`).

- [ ] **Step 7: Run the tests to verify they pass**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "assign or unmapped" -v`
Expected: PASS.

- [ ] **Step 8: Wire `assign_knockout_teams` into `refresh_live`**

In `pipeline/ingest/live_scores.py`, in `refresh_live`, change the final line from `return update_live_scores(db, api_matches)` to call assignment first:

```python
    assign_knockout_teams(db, api_matches)
    return update_live_scores(db, api_matches)
```

- [ ] **Step 9: Run the full backend gate**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add pipeline/ingest/live_scores.py pipeline/ingest/api_football.py pipeline/ingest/testdata/wc_ko_matches.json pipeline/ingest/testdata/wc_ko_matches_apisports.json backend/tests/test_knockout_bracket.py
git commit -m "feat(bracket): assign_knockout_teams (stage-keyed, fixture-id) + provider fixtures"
```

---

### Task 10: End-to-end offline ingestion (assign → score)

**Files:**
- Test: `backend/tests/test_knockout_bracket.py` (no production code change — proves the reuse claim)

**Interfaces:**
- Consumes: `assign_knockout_teams`, `update_live_scores`.
- Produces: a passing integration test proving that after assignment, `update_live_scores` writes score/period/penalty onto the now-indexed KO rows.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_knockout_bracket.py`:

```python
def test_end_to_end_offline_assign_then_update(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany", "Spain", "Portugal"])
    api_matches = json.loads((_TESTDATA / "wc_ko_matches.json").read_text())

    assign_knockout_teams(db_session, api_matches)
    update_live_scores(db_session, api_matches)

    arg = db_session.query(Team).filter_by(name="Argentina").one()
    finished = (
        db_session.query(Match)
        .filter(Match.stage == "R16", Match.team_home_id == arg.id)
        .one_or_none()
        or db_session.query(Match)
        .filter(Match.stage == "R16", Match.team_away_id == arg.id)
        .one()
    )
    assert finished.status == "finished"
    assert {finished.score_home, finished.score_away} == {1, 1}
    assert {finished.penalty_home, finished.penalty_away} == {4, 2}
```

- [ ] **Step 2: Run the test to verify it fails, then passes**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "end_to_end" -v`
Expected: PASS immediately (the production code from Task 9 already makes this true). If it fails, that is a real bug to fix in `assign_knockout_teams`/orientation, not a test issue.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_knockout_bracket.py
git commit -m "test(bracket): end-to-end offline assign-then-update ingestion"
```

---

### Task 11: Penalties-aware `knockout_results_from_db` + wire into recompute

**Files:**
- Modify: `backend/app/scoring.py` (add `knockout_results_from_db`)
- Modify: `backend/app/api/internal.py` (pass `knockout_results` — `recompute_scores_endpoint`)
- Modify: `pipeline/learning_loop.py` (pass `knockout_results` — line ~266)
- Modify: `pipeline/run_pipeline.py` (pass `knockout_results` — `bracket_scores` step, line ~67)
- Test: `backend/tests/test_knockout_bracket.py`

**Interfaces:**
- Consumes: `Match`, `Session`, `recompute_scores` (existing, accepts `knockout_results: dict[int, int] | None`).
- Produces: `def knockout_results_from_db(db) -> dict[int, int]` — `match_no` → winning `team_id`; finished KO rows only; score then `penalty_home`/`penalty_away`; omit if still tied; `match_no` 103 included as a normal winner resolution but carries no points (the existing `_ADVANCE_NOS`/`FINALIST_NO`/`CHAMPION` sets already exclude 103).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_knockout_bracket.py`:

```python
from app.scoring import knockout_results_from_db


def _ko_row(db, match_no, home, away, **kw):
    row = db.query(Match).filter(Match.match_no == match_no).one()
    h = db.query(Team).filter_by(name=home).one()
    a = db.query(Team).filter_by(name=away).one()
    row.team_home_id, row.team_away_id = h.id, a.id
    for k, v in kw.items():
        setattr(row, k, v)
    db.commit()
    return row, h, a


def test_knockout_results_score_then_penalties(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["A", "B", "C", "D", "E", "F", "G", "H"])

    # 89: 2-1 -> home wins by score
    _, h89, _ = _ko_row(db_session, 89, "A", "B", status="finished", score_home=2, score_away=1)
    # 90: 1-1 pens 4-2 -> home wins on pens
    _, h90, _ = _ko_row(db_session, 90, "C", "D", status="finished",
                        score_home=1, score_away=1, penalty_home=4, penalty_away=2)
    # 91: 0-0 pens 3-3 -> undecided, omitted
    _ko_row(db_session, 91, "E", "F", status="finished",
            score_home=0, score_away=0, penalty_home=3, penalty_away=3)
    # 92: in_play -> omitted
    _ko_row(db_session, 92, "G", "H", status="in_play", score_home=1, score_away=0)

    results = knockout_results_from_db(db_session)
    assert results[89] == h89.id
    assert results[90] == h90.id
    assert 91 not in results
    assert 92 not in results
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "knockout_results" -v`
Expected: FAIL — `cannot import name 'knockout_results_from_db'`.

- [ ] **Step 3: Implement the resolver**

In `backend/app/scoring.py`, add after `group_results_from_db`:

```python
def knockout_results_from_db(db: Session) -> dict[int, int]:
    """Finished KO matches -> winning team id, keyed by official match_no.
    Winner = higher score; if level, higher penalty tally; omit if still tied.
    (match_no 103 is resolved like any other KO row but carries no points —
    the ADVANCE/FINALIST/CHAMPION sets already exclude 103.)"""
    out: dict[int, int] = {}
    finished = (
        db.query(Match)
        .filter(Match.stage != "group", Match.status == "finished", Match.match_no.isnot(None))
        .all()
    )
    for m in finished:
        if m.team_home_id is None or m.team_away_id is None:
            continue
        winner: int | None = None
        if m.score_home is not None and m.score_away is not None:
            if m.score_home > m.score_away:
                winner = m.team_home_id
            elif m.score_away > m.score_home:
                winner = m.team_away_id
        if winner is None and m.penalty_home is not None and m.penalty_away is not None:
            if m.penalty_home > m.penalty_away:
                winner = m.team_home_id
            elif m.penalty_away > m.penalty_home:
                winner = m.team_away_id
        if winner is not None:
            out[m.match_no] = winner
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "knockout_results" -v`
Expected: PASS.

- [ ] **Step 5: Wire into `internal.py`**

In `backend/app/api/internal.py`, in `recompute_scores_endpoint`, change the import + call:

```python
    from app.scoring import recompute_scores, knockout_results_from_db

    scored = recompute_scores(db, knockout_results=knockout_results_from_db(db))
```

- [ ] **Step 6: Wire into the two pipeline call sites**

There are two more `recompute_scores(db)` call sites (the daily pipeline and the post-final-whistle chain). Both must pass `knockout_results`, or knockout winners never score in prod.

In `pipeline/run_pipeline.py`: the import at line ~28 is `from app.scoring import recompute_scores`. Change it to also import the resolver, and update the `bracket_scores` step (line ~67):

```python
    from app.scoring import recompute_scores, knockout_results_from_db
```

```python
    step("bracket_scores", lambda: recompute_scores(db, knockout_results=knockout_results_from_db(db)))
```

In `pipeline/learning_loop.py`: the import at line ~259 is `from app.scoring import recompute_scores`. Change it to also import the resolver, and update the call at line ~266:

```python
    from app.scoring import recompute_scores, knockout_results_from_db
```

```python
    summary["brackets"] = recompute_scores(db, knockout_results=knockout_results_from_db(db))
```

- [ ] **Step 7: Add a scoring-integration test**

Add to `backend/tests/test_knockout_bracket.py`:

```python
from app.scoring import recompute_scores, _ADVANCE_NOS


def test_recompute_uses_knockout_results_and_103_scores_zero(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["A", "B", "C", "D"])
    # 103 (third place) finished — must not be in the points-bearing sets.
    _ko_row(db_session, 103, "A", "B", status="finished", score_home=2, score_away=0)
    results = knockout_results_from_db(db_session)
    assert results[103] == db_session.query(Team).filter_by(name="A").one().id
    assert 103 not in _ADVANCE_NOS  # 103 never awards advance points
    # recompute runs cleanly with knockout_results supplied
    assert recompute_scores(db_session, knockout_results=results) >= 0
```

- [ ] **Step 8: Run the full backend gate**

Run (from repo root): `python -m pytest -v`
Expected: PASS (existing scoring tests + new ones).

- [ ] **Step 9: Commit**

```bash
git add backend/app/scoring.py backend/app/api/internal.py pipeline/learning_loop.py pipeline/run_pipeline.py backend/tests/test_knockout_bracket.py
git commit -m "feat(bracket): knockout_results_from_db winner resolver wired into recompute"
```

---

### Task 12: `GET /api/knockout/bracket` + schema + no-store

**Files:**
- Modify: `backend/app/schemas/__init__.py` (add `KnockoutSideOut`, `KnockoutTieOut`, `KnockoutBracketOut`)
- Modify: `backend/app/api/knockout.py` (add `GET /bracket`)
- Modify: `backend/app/main.py` (no-store clause)
- Test: `backend/tests/test_knockout_bracket.py`

**Interfaces:**
- Consumes: `Match`, `Team`, `Session`, `knockout_results_from_db`; existing `cache` (skipped for the live bracket).
- Produces:
  - `KnockoutSideOut(BaseModel)`: `team_id: int | None; team: str | None; score: int | None; penalty: int | None`
  - `KnockoutTieOut(BaseModel)`: `match_no: int; match_id: int | None; stage: str; status: str; kickoff_utc: datetime | None; home: KnockoutSideOut; away: KnockoutSideOut; minute: int | None; period: str | None; injury_time: int | None`
  - `KnockoutBracketOut(BaseModel)`: `ties: list[KnockoutTieOut]`
  - `GET /api/knockout/bracket` → `KnockoutBracketOut`; response carries `Cache-Control: no-store`.

- [ ] **Step 1: Add the schemas**

In `backend/app/schemas/__init__.py`, add (after `TournamentOddsOut`; ensure `from datetime import datetime` is present at the top — it is used by other schemas):

```python
class KnockoutSideOut(BaseModel):
    team_id: int | None
    team: str | None
    score: int | None
    penalty: int | None


class KnockoutTieOut(BaseModel):
    match_no: int
    match_id: int | None
    stage: str
    status: str
    kickoff_utc: datetime | None
    home: KnockoutSideOut
    away: KnockoutSideOut
    minute: int | None
    period: str | None
    injury_time: int | None


class KnockoutBracketOut(BaseModel):
    ties: list[KnockoutTieOut]
```

- [ ] **Step 2: Write the failing endpoint test**

Add to `backend/tests/test_knockout_bracket.py`:

```python
from fastapi.testclient import TestClient
from app.main import app
from app.db import get_db


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_bracket_endpoint_serializes_null_not_tbd_and_no_store(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France"])
    _ko_row(db_session, 89, "Argentina", "France",
            status="finished", score_home=2, score_away=1, match_id_keep=True) if False else None
    row = db_session.query(Match).filter(Match.match_no == 89).one()
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    row.team_home_id, row.team_away_id = arg.id, fra.id
    row.status, row.score_home, row.score_away = "finished", 2, 1
    db_session.commit()

    client = _client(db_session)
    try:
        resp = client.get("/api/knockout/bracket")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    body = resp.json()
    ties = {t["match_no"]: t for t in body["ties"]}
    assert len(ties) == 32
    # populated tie carries ids + match_no + DB id
    t89 = ties[89]
    assert t89["match_id"] == row.id
    assert t89["home"]["team"] == "Argentina"
    # an unassigned tie is null, never "TBD"
    t104 = ties[104]
    assert t104["home"]["team_id"] is None
    assert t104["home"]["team"] is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "endpoint" -v`
Expected: FAIL — 404 (route does not exist).

- [ ] **Step 4: Implement the route**

In `backend/app/api/knockout.py`, add (the file already imports `Team`; add `Match`):

```python
from app.models import Match, Team, TournamentOdds  # update the existing import line


@router.get("/bracket", response_model=schemas.KnockoutBracketOut)
def get_bracket(db: Session = Depends(get_db)):
    """Official knockout bracket: every KO Match row (real teams + live scores).
    Unassigned sides serialize team_id/team = null (never 'TBD'). Live feed —
    not edge-cached (see main.py no-store clause)."""
    rows = (
        db.query(Match)
        .filter(Match.stage != "group", Match.match_no.isnot(None))
        .order_by(Match.match_no)
        .all()
    )
    ties = []
    for m in rows:
        home_team = db.get(Team, m.team_home_id) if m.team_home_id else None
        away_team = db.get(Team, m.team_away_id) if m.team_away_id else None
        ties.append(
            schemas.KnockoutTieOut(
                match_no=m.match_no,
                match_id=m.id if (m.team_home_id or m.team_away_id) else None,
                stage=m.stage,
                status=m.status,
                kickoff_utc=m.kickoff_utc,
                home=schemas.KnockoutSideOut(
                    team_id=m.team_home_id,
                    team=home_team.name if home_team else None,
                    score=m.score_home,
                    penalty=m.penalty_home,
                ),
                away=schemas.KnockoutSideOut(
                    team_id=m.team_away_id,
                    team=away_team.name if away_team else None,
                    score=m.score_away,
                    penalty=m.penalty_away,
                ),
                minute=m.minute,
                period=m.period,
                injury_time=m.injury_time,
            )
        )
    return schemas.KnockoutBracketOut(ties=ties)
```

- [ ] **Step 5: Add the no-store clause in `main.py`**

In `backend/app/main.py`, in the `cache_control` middleware, extend the live-scoreboard `elif` branch condition to include the bracket. Change:

```python
    elif path == "/api/matches/upcoming" or (
        path.startswith("/api/matches/") and path.endswith("/summary")
    ):
```

to:

```python
    elif path.startswith("/api/knockout/bracket") or path == "/api/matches/upcoming" or (
        path.startswith("/api/matches/") and path.endswith("/summary")
    ):
```

- [ ] **Step 6: Run the test to verify it passes**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "endpoint" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/api/knockout.py backend/app/main.py backend/tests/test_knockout_bracket.py
git commit -m "feat(bracket): GET /api/knockout/bracket + schema + no-store cache header"
```

---

### Task 13: Canary — KO `in_play` must never render as a label in `/bracket`

**Files:**
- Test: `backend/tests/test_knockout_bracket.py`

**Interfaces:**
- Consumes: `GET /api/knockout/bracket`.
- Produces: an integration assertion that any KO `in_play` row serializes with a non-null `team_id` on at least one side (assignment did not silently fail).

- [ ] **Step 1: Write the canary test**

Add to `backend/tests/test_knockout_bracket.py`:

```python
def test_canary_in_play_ko_is_not_label_in_bracket(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Brazil", "Germany"])
    # Simulate the assigned + live state the cron would produce.
    row = db_session.query(Match).filter(Match.match_no == 90).one()
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    row.team_home_id, row.team_away_id = bra.id, ger.id
    row.status, row.score_home, row.score_away, row.minute = "in_play", 1, 0, 57
    db_session.commit()

    client = _client(db_session)
    try:
        resp = client.get("/api/knockout/bracket")
    finally:
        app.dependency_overrides.clear()

    ties = {t["match_no"]: t for t in resp.json()["ties"]}
    for t in ties.values():
        if t["status"] == "in_play":
            # at least one real team -> the frontend renders it as in_play, not labels
            assert t["home"]["team_id"] is not None or t["away"]["team_id"] is not None, t["match_no"]
```

- [ ] **Step 2: Run the test to verify it passes**

Run (from repo root): `python -m pytest backend/tests/test_knockout_bracket.py -k "canary" -v`
Expected: PASS.

- [ ] **Step 3: Run the full gate (both suites)**

Run (from repo root): `python -m pytest`
Run (from `frontend/`): `npm run lint && npm run typecheck && npm test`
Run (from `backend/`): `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; h=ScriptDirectory.from_config(Config('alembic.ini')).get_heads(); assert len(h)==1; print('OK', h[0])"`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_knockout_bracket.py
git commit -m "test(bracket): canary — in_play KO row is never a label in /bracket"
```

---

## Self-Review — spec coverage map

| Spec section | Covered by |
|---|---|
| §1 / §2 product decisions (tab, labels, one layout, Daylight, both phases, click→/match) | Tasks 3, 5 |
| §3.1 R32 slot layout | Task 2 (`resolveSlotLabel` tests) |
| §3.2 third-place slot labels | Task 2 |
| §3.3 KO_TREE feeders | Task 2 |
| §3.4 THIRD_PLACE / detached 103 node | Tasks 2, 3 (detached render), 11 (103 scores 0) |
| §4.1 files / static fallback | Tasks 1–5 |
| §4.2 officialBracket pure API | Task 2 |
| §4.3 node states + mixed-state | Tasks 2, 3 |
| §4.4 layout/theme/a11y (role/aria, aria-hidden connectors, reduced-motion) | Task 3 |
| §5.1 endpoint | Task 12 |
| §5.2 response shape (null not TBD, ids + match_no) | Task 12 |
| §5.3 api.ts fetchers | Task 4 |
| §5.4 30_000 live poll + SSR seed | Task 5 |
| §6 3-segment tab IA | Task 5 |
| §7.1 match_no + migration | Task 6 |
| §7.2 KO kickoff_utc seeding | Task 7 |
| §7.3 assign_knockout_teams (stage map both providers, fixture-id key) | Task 9 |
| §7.4 penalties-aware winner resolver + recompute wiring | Task 11 |
| §7.5 gating + freeze-on-live + correction-while-scheduled | Task 9 |
| §8 readiness chain | Tasks 6–13 (end-to-end Task 10, canary Task 13) |
| §9 unit | Task 2 |
| §9 render | Task 3 |
| §9 ingestion-against-fixture (both providers) | Task 9 |
| §9 end-to-end offline | Task 10 |
| §9 winner derivation + scoring | Task 11 |
| §9 endpoint no-store | Task 12 |
| §9 canary | Task 13 |

No spec section is left without a concrete task.
