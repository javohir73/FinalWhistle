# Official Knockout Bracket Tree — Design Spec

**Feature:** An official, view-only knockout bracket tree for FinalWhistle / FIFA WC26 Prediction.
**Status:** Implementation-ready. Phase 1 ships now; Phase 2 lands before R32 kickoff (~late June 2026).
**Date:** 2026-06-25
**Author:** spec authored from approved design + five code-grounded findings.

---

## 1. Summary

A new **"Official bracket"** tab on `/brackets` renders the real FIFA World Cup 2026 knockout tree:
Round of 32 (R32) → Round of 16 (R16) → Quarter-finals (QF) → Semi-finals (SF) → Final, plus a detached
3rd-place match. It shows **real teams and live scores/winners** as the tournament progresses — not user
picks, not the AI projection.

Two phases:

- **Phase 1 (frontend-only, ships now, zero backend change):** a presentational converging-tree component
  driven by the topology already encoded in `frontend/lib/bracketStructure.ts`. During the group stage it
  renders **slot labels only** (`1A`, `2B`, `3-CDFGH`). No standings-derived guesses.
- **Phase 2 (backend, before R32 kickoff):** assign real teams to the 32 knockout placeholder `Match` rows,
  derive winners (penalties-aware), advance them, and expose `GET /api/knockout/bracket`. The frontend
  overlays real teams + live score badges, highlights winners, and polls every 30s. Phase 2 is a **new
  subsystem**, not a one-line ingestion tweak — the adversarial critique surfaced four blockers, all resolved
  explicitly in §7.

The single hard product rule: **a slot shows its label until a team is OFFICIALLY assigned to that
`Match` row** (and assignment is gated on official confirmation, not mere presence in a provider feed — see
§7.5).

---

## 2. Confirmed product decisions

- Shows the **official** bracket (real teams + live scores/winners), not predictions, not AI projection.
- Lives as a **tab on `/brackets`**.
- Empty knockout slots show **slot labels only** (`1A`, `2B`, `3-CDFGH`) until a team officially qualifies.
- **One layout everywhere:** the full converging tree; horizontally scrollable/pannable on narrow screens
  (Capacitor iOS).
- Uses the app's existing **"Daylight"** theme tokens (green/lime), not the screenshot's purple.
- Build **both phases now** so it auto-catches knockout data once knockouts start.
- Clicking a knockout tie that has real teams opens that match's detail page (`/match/{id}`).

---

## 3. Canonical topology (source of truth)

All numbers below are verified identical between `frontend/lib/bracketStructure.ts` and
`backend/app/scoring.py`. **The renderer and the backend share this numbering exactly.**

| Stage | `match_no`(s) | count |
|---|---|---|
| R32 | 73–88 (`range(73,89)`) | 16 |
| R16 | 89, 90, 91, 92, 93, 94, 95, 96 | 8 |
| QF | 97, 98, 99, 100 | 4 |
| SF | 101, 102 | 2 |
| **3rd place** | **103** (by convention only — see §3.3) | 1 |
| Final | 104 | 1 |

Total = 32 knockout rows (72 group + 32 KO = 104).

### 3.1 Exact R32 slot layout (`bracketStructure.ts` `R32`, lines 8–25)

Each R32 match has two sides. A `Placement {g,pos}` renders `<pos><group>` (e.g. `{g:"A",pos:2}` → `2A`).
A `{third:true}` side renders the third-place slot label from `THIRD_SLOTS`.

| `match_no` | side A | side B | label |
|---|---|---|---|
| 73 | 2A | 2B | 2A vs 2B |
| 74 | 1E | 3rd | 1E vs 3-ABCDF |
| 75 | 1F | 2C | 1F vs 2C |
| 76 | 1C | 2F | 1C vs 2F |
| 77 | 1I | 3rd | 1I vs 3-CDFGH |
| 78 | 2E | 2I | 2E vs 2I |
| 79 | 1A | 3rd | 1A vs 3-CEFHI |
| 80 | 1L | 3rd | 1L vs 3-EHIJK |
| 81 | 1D | 3rd | 1D vs 3-BEFIJ |
| 82 | 1G | 3rd | 1G vs 3-AEHIJ |
| 83 | 2K | 2L | 2K vs 2L |
| 84 | 1H | 2J | 1H vs 2J |
| 85 | 1B | 3rd | 1B vs 3-EFGIJ |
| 86 | 1J | 2H | 1J vs 2H |
| 87 | 1K | 3rd | 1K vs 3-DEIJL |
| 88 | 2D | 2G | 2D vs 2G |

### 3.2 Third-place slot labels (`THIRD_SLOTS`, lines 28–37)

Keyed by the **same R32 `match_no`**. The label is `"3-"` + sorted `elig` letters:

| `match_no` | elig | label |
|---|---|---|
| 74 | A,B,C,D,F | 3-ABCDF |
| 77 | C,D,F,G,H | 3-CDFGH |
| 79 | C,E,F,H,I | 3-CEFHI |
| 80 | E,H,I,J,K | 3-EHIJK |
| 81 | B,E,F,I,J | 3-BEFIJ |
| 82 | A,E,H,I,J | 3-AEHIJ |
| 85 | E,F,G,I,J | 3-EFGIJ |
| 87 | D,E,I,J,L | 3-DEIJL |

### 3.3 Winner-feeder map (`KO_TREE`, lines 40–50)

`KO_TREE: Record<number,[number,number]>` — each downstream match's two feeder matches whose **winners**
meet. R32 (73–88) are **not** keys (they're group-seeded). **103 is absent.**

| match | feeders | | match | feeders |
|---|---|---|---|---|
| 89 | [74,77] | | 97 | [89,90] |
| 90 | [73,75] | | 98 | [93,94] |
| 91 | [76,78] | | 99 | [91,92] |
| 92 | [79,80] | | 100 | [95,96] |
| 93 | [83,84] | | 101 | [97,98] |
| 94 | [81,82] | | 102 | [99,100] |
| 95 | [86,88] | | 104 | [101,102] |
| 96 | [85,87] | | | |

### 3.4 The 3rd-place match (103) — explicit handling (resolves BLOCKER #3)

**Finding:** a `third_place` `Match` row IS seeded (`wc26_structure.py` `KNOCKOUT_STAGES`) and has a venue
(`ko_venues.py`), but `KO_TREE` has no key 103 and encodes only winner-feeders — so 103 **cannot** be
populated by the converging-tree "advance the winner" mechanism. The 3rd-place match is fed by the two SF
**losers** (101, 102), and 104 by the two SF winners.

**Resolution:**

1. Add new metadata to `bracketStructure.ts`:
   ```ts
   export const THIRD_PLACE = { no: 103, loserFeeders: [101, 102] as [number, number] };
   ```
2. `officialBracket.ts` resolves 103's sides via `loserFeeders` (the **losers** of 101/102), not `KO_TREE`.
3. Render 103 as a **detached node** beside/below the Final — it is explicitly NOT part of the converging
   tree and has no connector lines into 104.
4. Phase 2 team-assignment assigns SF **losers** to 103 (see §7.4); the winner resolver applies to 103 like
   any other KO match but it carries **no points** (`scoring.py`: ADVANCE/FINALIST/CHAMPION points never
   include 103).
5. The renderer must **never assume 103 exists in `KO_TREE`, `ROUNDS`, or `R32`** — it lives only in
   `THIRD_PLACE`.

### 3.5 What is reusable vs pick-specific

**Reuse verbatim (pure topology):** `R32`, `THIRD_SLOTS`, `KO_TREE`, `ROUNDS`, `FINAL_MATCH`, the new
`THIRD_PLACE`, and `matchSides`'s geometry (seeding-first, else feeders). Backend `R32_NOS`/`R16_NOS`/
`QF_NOS`/`SF_NOS`/`FINAL_NO`.

**Do NOT reuse for official data:** `GroupPicks`/`KnockoutPicks` types; `groupTable` /`seedKnockouts`
tie-breaks by model **strength** (a prediction heuristic, invalid for official seeding); `encodeBracket`/
`decodeBracket` (URL pick compression); `pruneKnockoutPicks`; `champion(ko)` (reads a user pick).
Official seeding and the official `Seeding` shape must come from real assignment, not `seedKnockouts`.

**Key divergence flagged:** FE `KnockoutPicks` is keyed by team **name** (string); BE picks are keyed by
team **id** (int). The official bracket endpoint returns **both** ids and resolved names plus `match_no`
and the DB `id`, so the frontend never re-derives any of them (resolves MINOR #9, #10).

---

## 4. Phase 1 — presentational tree (ships now)

### 4.1 Files

| File | Action |
|---|---|
| `frontend/components/OfficialBracket.tsx` | **ADD** — pure presentational converging tree; props only, no fetching. |
| `frontend/lib/officialBracket.ts` | **ADD** — pure logic: KO matches → tree nodes, slot-label resolution, advancement via `KO_TREE` + `THIRD_PLACE`; node state derivation; penalties-aware winner read. React-free, unit-testable. |
| `frontend/lib/bracketStructure.ts` | **EDIT** — add `THIRD_PLACE` (§3.4). No other changes. |
| `frontend/app/brackets/BracketsClient.tsx` | **EDIT** — add the tab toggle + render the new tab (§6). |
| `frontend/lib/types.ts` | **EDIT** — add `KnockoutBracket` / `KnockoutTie` types (§5.2). |
| `frontend/lib/api.ts` | **EDIT** — add `getOfficialBracket` / `getOfficialBracketServer` (§5.1). |

In Phase 1 the endpoint may not exist yet; the tab degrades gracefully to **slot-label-only** state driven
entirely by the static `bracketStructure.ts` topology (resolves MAJOR #7's "useful even if backend cold").

### 4.2 `officialBracket.ts` API (pure)

```ts
type TieState = "labels" | "scheduled" | "in_play" | "finished";

type SideView = {
  teamId: number | null;     // null => unassigned => show slot label
  team: string | null;       // resolved display name (for <Flag/>)
  label: string;             // slot label, e.g. "2A" / "3-CDFGH" — always present
  score: number | null;
  penalty: number | null;
  isWinner: boolean;
};

type TieView = {
  matchNo: number;
  matchId: number | null;    // DB id for /match/{id}; null when no row/teams
  round: "r32"|"r16"|"qf"|"sf"|"final"|"third";
  state: TieState;
  a: SideView; b: SideView;
  liveLabel: string;         // "" | "57'" | "HT" | "ET 105'" | "PENS" | "FT"
  penaltyText: string | null;// e.g. "(4-2 pens)" when finished on shootout
};

// builds the full node set from official data (or pure topology when bracket is null)
buildTree(bracket: KnockoutBracket | null): Record<number, TieView>;
// resolves a side's slot label from R32 / THIRD_SLOTS / KO_TREE / THIRD_PLACE
resolveSlotLabel(matchNo: number, side: "a"|"b"): string;
// winner: score first, then penalties; null until finished
resolveWinner(tie: RawTie): "a" | "b" | null;
```

**Winner rule (single source of truth, mirrors backend §7.4):** if `status !== "finished"` → no winner. Else
compare `score_home` vs `score_away`; **if equal, compare `penalty_home` vs `penalty_away`**; if penalties
also equal (still undecided) → no winner. The frontend uses this only for **display highlight**; the backend
resolver is authoritative for scoring (§7.4).

### 4.3 `OfficialBracket.tsx` (presentational)

- Props: `{ ties: Record<number, TieView> }`. No fetching, no `match_no`/id derivation.
- Renders five columns (R32 → Final) in `ROUNDS` order + the detached **3rd-place** node beside the Final.
- **Node states** (resolves MINOR #10):
  - `labels` — both sides show slot labels; non-interactive; muted styling.
  - `scheduled` — real team(s) + flags, no score; links to `/match/{matchId}`.
  - `in_play` — live badge (`bg-loss/15`, pulsing dot) + `liveLabel` (incl. `ET`/`PENS`); `ring-1 ring-loss/40`.
  - `finished` — final score, optional `(x-y pens)`, **winner side highlighted** (`text-lime-deep` + bold;
    loser muted); links to `/match/{matchId}`.
- **Mixed-state rendering** (resolves MAJOR #6): one tie may have a real team on side A and a `2B` label on
  side B; one round may be fully known while the next is all labels. Each `SideView` always carries `label`,
  so the component renders the team when `teamId != null` else the label — no `"TBD"` sentinel is ever used.
- A populated tie links via `<Link href={`/match/${tie.matchId}`}>` (resolves MINOR #9). Label-only ties
  render as a non-link `<div>`.
- Flags: `<Flag team={side.team} size={22} />` (resolves display name to a self-hosted PNG, initials chip
  fallback).

### 4.4 Layout, theme, accessibility

**One layout, horizontally pannable** (resolves MINOR #11):

- Semantic structure: each round is an `<ol aria-label="Round of 16">`; each tie is an `<li>` with an
  `aria-label` naming both sides and state (e.g. `"Round of 16: Argentina 2 vs France 1, finished, Argentina
  win"`). Connector lines are decorative SVG with `aria-hidden`.
- Horizontal scroll container with `overflow-x-auto`, `scroll-snap-type: x proximity`, momentum scrolling,
  and a visible scroll affordance (fade edge). Tap targets ≥ 44px.
- Honor `prefers-reduced-motion` consistent with the existing `Reveal` system; the live pulse dot respects it.
- VoiceOver-on-device check is part of the test plan (§9).

**Theme tokens (Daylight) — exact usage:**

| Element | token / class |
|---|---|
| Round cards | `.glass` + `.card-hover` |
| Final card | `.panel-pitch` (deep-green hero) |
| Tab rail track | `bg-surface-2`, rounded `[14px]`, `p-1` |
| Active tab | `bg-surface` + `shadow-[0_1px_3px_rgba(18,40,25,0.1)]` |
| Winner text/links/icons on white | `text-lime-deep` (#2f6b1e) — **never `--win` as text** |
| Fills (progress/toggles) | `bg-win` (lime, fills only) |
| Live badge | `bg-loss/15` + `text-loss` + pulsing `bg-loss` dot; live tie ring `ring-loss/40` |
| Muted / labels | `text-muted` |
| Hairlines | `border-border` |

Live-state helpers reused verbatim from `frontend/lib/liveLabel.ts`: `isLiveNow(m)` (self-heals a stale
feed by bounding `in_play` to kickoff) and `liveLabel(s)` (`57'`/`HT`/`ET 105'`/`PENS`/`FT`). The tree does
**not** re-derive these.

---

## 5. The endpoint and frontend data layer

### 5.1 `GET /api/knockout/bracket`

Lives in `backend/app/api/knockout.py` (existing `router = APIRouter(prefix="/api/knockout")`, registered in
`main.py`). Add alongside `/odds`:

```py
@router.get("/bracket", response_model=KnockoutBracket)
def get_bracket(db: Session = Depends(get_db)) -> KnockoutBracket: ...
```

Data source: `Match` rows where `stage != "group"`. The model already carries everything: `id`, `match_no`
(added in Phase 2, §7.1), `stage`, `team_home_id`/`team_away_id`, `home_team`/`away_team`, `status`,
`score_home`/`score_away`, `minute`, `period`, `injury_time`, `penalty_home`/`penalty_away`, `kickoff_utc`,
`is_neutral`.

**Caching — `no-store` (resolves data-finding §4 + MAJOR #8):** the bracket is a **live feed**. The generic
GET branch in `main.py` would otherwise apply `public, max-age=60, stale-while-revalidate=300` via
`setdefault`, letting Vercel/CDN PoPs serve minutes-stale boards after a KO result lands and starving the
30s poll. **Add an explicit clause** to the `cache_control` middleware:

```py
if path.startswith("/api/knockout/bracket"):
    response.headers["Cache-Control"] = "no-store"
```

(Note: `/api/knockout/odds` stays on the 60s SWR default — it is pre-tournament Monte-Carlo, not live state.)
Do **not** rely on the in-process `cache` for the bracket while any KO match is `in_play`; either skip the
in-memory cache for `/bracket` or give it a ≤15s TTL AND ensure `live_refresh.cache.clear()` evicts it.
Document the Render free-tier cold-start latency; Phase 1's static fallback keeps the tab useful when the
backend is cold.

### 5.2 Response shape

```jsonc
{
  "ties": [
    {
      "match_no": 89,
      "match_id": 312,            // DB id; null only if the row is absent
      "stage": "R16",
      "status": "finished",       // scheduled | in_play | finished
      "kickoff_utc": "2026-07-04T19:00:00Z",
      "home": { "team_id": 44, "team": "Argentina", "score": 2, "penalty": null },
      "away": { "team_id": 51, "team": "France",    "score": 1, "penalty": null },
      "minute": null, "period": null, "injury_time": null
    }
    // ... every knockout row, including match_no 103
  ]
}
```

Rules (resolve MAJOR #6, MINOR #9):

- Unassigned sides return `team_id: null` and `team: null` — **never the string `"TBD"`**. The frontend
  resolves the slot label from static topology.
- Always include `match_no` and the DB `id` so the client links to `/match/{id}` without assuming
  `id == match_no`.
- Penalty fields are non-null only when a shootout occurred; the frontend renders `(4-2 pens)` and picks the
  winner from the tally.

### 5.3 `frontend/lib/api.ts` additions

Mirror the existing `getKnockoutOdds`/`getKnockoutOddsServer` pair. Client call goes through the same-origin
rewrite `/backend-api/...` (cookie-bearing); `getJson` is already `cache: "no-store"`.

```ts
export const getOfficialBracket = () => getJson<KnockoutBracket>("/api/knockout/bracket");
export const getOfficialBracketServer = () =>
  getServer<KnockoutBracket>("/api/knockout/bracket", 30); // short revalidate just to seed SSR
```

`KnockoutBracket`/`KnockoutTie` added to `frontend/lib/types.ts`. Backend Pydantic schema in
`backend/app/schemas/`.

### 5.4 Live poll reuse

Reuse `useFetch` exactly as `MatchScoreboard` does:

```tsx
const state = useFetch(getOfficialBracket, [], 30_000, initialBracket);
```

`30_000` is the project's live cadence. `pollMs` triggers a **silent** refresh (keeps last-good data, no
skeleton flash). Pass the SSR-seeded `initialBracket` (4th arg) so the tree paints instantly.

---

## 6. Tab integration (resolves MAJOR #8 IA mismatch)

**Reality check from the finding:** `BracketsClient.tsx` today renders a two-segment control that is *not*
real tabs — **"My picks"** is a `<Link href="/my-bracket">` and **"AI bracket"** is a static
`<span aria-selected>`. The heading is hardcoded `"The AI's bracket"`. There is no `"AI projection"` tab and
no generic `Tabs` primitive in `frontend/components/` (the closest, `MatchTabs.tsx`, is hardcoded to
overview/lineups).

**Resolution — a 3-segment control, IA reconciled:**

- Segments: **My picks** (keeps its cross-page `<Link href="/my-bracket">`) · **Official** (new) · **AI
  bracket** (existing AI view, untouched).
- Introduce local `useState<"official" | "ai">("ai")` in `BracketsClient` to toggle between the two
  *in-page* views (Official, AI). "My picks" stays a link, as today.
- The existing AI-view body (`oddsState = useFetch(getKnockoutOdds, …)` → `<AIBracket/>` / `<SkeletonRounds/>`
  / `<NotReady/>`) becomes the `"ai"` branch, **unchanged**.
- The `"official"` branch renders `useFetch(getOfficialBracket, [], 30_000, initialBracket)` → `<OfficialBracket
  ties={…}/>`, with `<SkeletonRounds/>` while loading and a label-only static fallback on error.
- Make the heading dynamic: `"Official bracket"` vs `"The AI's bracket"` based on the active in-page view.
- Reuse the existing a11y pattern (`role="tablist"`, `role="tab"`, `aria-selected`) and `.seg` styling
  (`rounded-[14px] bg-surface-2 p-1`; active `bg-surface … shadow-[0_1px_3px_rgba(18,40,25,0.1)]`). Replicate
  inline (button-based, copying `MatchTabs` lines 18–40) — **do not** build a divergent shared component.
- `brackets/page.tsx` (server) additionally fetches `getOfficialBracketServer().catch(() => null)` and passes
  `initialBracket` to `BracketsClient`, alongside the existing `initialOdds`/`initialGroups`.

---

## 7. Phase 2 — backend (before R32 kickoff)

Phase 2 is a **new subsystem**. The four blockers from the adversarial critique are each resolved below.

### 7.1 Add `Match.match_no` and stamp 73–104 (resolves MAJOR #5)

**Finding:** `Match` has no `match_no` column; `match_no` lives only on `BracketKnockoutPick` and in
`scoring.py` constants. `ko_venues.apply_ko_venues` does `db.get(Match, match_no)` — i.e. it relies on the
undocumented, unenforced coupling `DB id == match_no`, which holds only on a pristine seed and breaks
silently on any reseed/partial-seed/reorder.

**Resolution:**

- `backend/app/models/__init__.py` — add `match_no: Mapped[int | None]` to `Match` (nullable for group rows;
  73–104 for KO).
- New Alembic migration `backend/alembic/versions/` — add `matches.match_no` (nullable), single head (CI
  already enforces single Alembic head).
- `pipeline/ingest/wc26_structure.py` (lines 37–44, 187–204) — stamp `match_no` deterministically in the
  existing `KNOCKOUT_STAGES` loop: R32→73–88, R16→89–96, QF→97–100, SF→101–102, third_place→103, final→104.
  Add `third_place` to the model stage comment (currently omits it).
- `pipeline/ingest/ko_venues.py` — change `db.get(Match, match_no)` to lookup **by `match_no`**, not by id.
- CI/startup invariant test: every KO stage's rows map to exactly the expected `match_no` set; every
  `match_no` 73–104 is present exactly once.
- The endpoint returns `match_no` explicitly and never leaks/assumes `id == match_no`.

### 7.2 Seed `kickoff_utc` on the 32 KO rows (resolves BLOCKER #1)

**Finding:** KO rows are seeded with **no `kickoff_utc`** (`wc26_structure.py`; `ko_venues.py` sets venue
only). `live_refresh.in_live_window()` opens the cron window only for matches `in_play` OR (`scheduled` AND
`kickoff_utc IS NOT NULL` within ±window). **With NULL kickoff the live window never opens for KO games**, so
`refresh_live()` is never called and no live scores ingest — the "attaches automatically" claim is false
as-is. (Data finding confirms: the schedule JSON contains only the 72 group games; no KO kickoff dates exist
anywhere in the repo. The only "post-group" anchor we hold is the last group kickoff `2026-06-28T02:00:00Z`.)

**Resolution:**

- Extend `pipeline/data/wc26_schedule.json` (or a new `pipeline/data/wc26_ko_schedule.json`) to carry the
  published KO kickoff times for `match_no` 73–104. These dates are publicly available; they are entered once.
- Stamp `kickoff_utc` (and `venue_city`/`venue_country` from `ko_venues.py`) onto the 32 placeholders at seed
  time, idempotently.
- Test: assert **every** `match_no` 73–104 has a non-null `kickoff_utc`; add an `in_live_window` coverage case
  proving the window opens for a KO row.

### 7.3 Assign real teams to placeholders by `(stage, match_no)` (resolves BLOCKER #4)

**Finding:** `live_scores._index_by_pair` (lines 65–74) indexes **only** rows with `team_home_id IS NOT NULL`
and keys them by the unordered normalized team-name pair `frozenset({home, away})`. KO placeholders have NULL
teams → never indexed → silently skipped (`index.get(...)` returns `None`). You **cannot** assign teams via
the pair index because the placeholder has no teams yet — it's circular. The provider feed *does* carry stage
(football-data v4 `stage`; api-sports `league.round`) and real teams once the draw resolves, but the code
**never reads `stage`** and `_to_item` drops `league.round`.

**Resolution — a separate assignment path, keyed on stage + provider fixture id, NOT team-pair:**

- New `assign_knockout_teams(db, api_matches)` in `pipeline/ingest/live_scores.py`, called from
  `refresh_live` (lines 274–305) **before** `update_live_scores`.
- Read `am.get("stage")` and map provider stage → our stage:

  | football-data | api-sports `league.round` | our stage |
  |---|---|---|
  | `ROUND_OF_32` / `LAST_32` | "Round of 32" | R32 |
  | `LAST_16` | "Round of 16" | R16 |
  | `QUARTER_FINALS` | "Quarter-finals" | QF |
  | `SEMI_FINALS` | "Semi-finals" | SF |
  | `THIRD_PLACE` | "3rd Place Final" | third_place |
  | `FINAL` | "Final" | final |

  **Log unmapped stage strings loudly** (mirror the `log.warning` for unknown status) so silent drops are
  caught (resolves the stage-drift risk).
- Within each stage, order feed fixtures by `utcDate`/kickoff (tiebreak: provider fixture id) and zip onto our
  `match_no`-ordered placeholders for that stage. FIFA schedules KO games in match-number order
  chronologically, so kickoff order ≈ `match_no` order. (A hardcoded bracket-progression map is the robust
  long-term option; chronological ordering is the minimal correct mapping to *display* live scores.)
- **Persist `provider_fixture_id`** (existing column, `models` line 118) on each KO row at assignment. **Switch
  KO live ingestion to key on `provider_fixture_id`** rather than the team-pair, eliminating the cross-stage
  pair-collision hazard (the docstring's "pairs are unique" guarantee holds only for groups). Group ingestion
  keeps the pair index unchanged.
- Resolve both names via `normalize_team_name` → `Team` rows; set `team_home_id`/`team_away_id` (+
  `kickoff_utc`/venue if present). **Never fabricate teams** (mirror the `_player_row` "never fabricate"
  pattern): no-op when a side is a placeholder/null or doesn't resolve to a known `Team`.
- `pipeline/ingest/api_football.py` `_to_item` (lines 179–216) — forward `league.round` as a `stage` key in
  the v4-shaped item so api-sports KO fixtures carry stage too.
- `pipeline/team_mapping.py` — add KO-team spellings as they surface (existing pattern).
- Once teams are set, `_index_by_pair`/the fixture-id path picks the row up and **all existing live-scoring
  logic (orientation, freshness guard, score/period/penalty writes) runs unchanged** — this is the leverage.

### 7.4 Derive winners (penalties-aware) + 3rd-place losers (resolves BLOCKER #2, #3)

**Finding:** there is **no winner concept anywhere** — no `winner_team_id` column, no code deriving a winner.
`scoring.py`'s `group_results_from_db` derives home/away/draw from `max(score)`, which is **invalid for KO**: a
1-1 game won 4-2 on penalties has equal scores (a "draw") but the winner is the higher penalty tally.
`recompute_scores()` is called **without** `knockout_results` (`internal.py`, `learning_loop.py`), so official
KO winners are never computed today.

**Resolution — one penalties-aware resolver, single source of truth:**

- Add `knockout_results_from_db(db) -> dict[int, int]` in `scoring.py` (`match_no` → winning `team_id`):
  - Only for KO rows with `status == "finished"`.
  - Winner = compare `score_home` vs `score_away`; **if equal, compare `penalty_home` vs `penalty_away`**; if
    penalties also equal → still undecided, omit (no winner).
  - For `match_no` 103, assign the **SF losers** as the two sides (via `THIRD_PLACE.loserFeeders` logic on the
    backend) — but 103 carries no points.
- Feed this into `recompute_scores(db, knockout_results=knockout_results_from_db(db))` at the call sites in
  `internal.py` and `learning_loop.py`, so **the official bracket and the leaderboard agree** on winners.
- The new `/bracket` serializer uses the same resolver to mark the winning side; the frontend's
  `resolveWinner` (§4.2) mirrors the exact rule for display only. No duplicated tie-break logic — both read
  score-then-penalties.
- Penalty/ET data is already wired for any indexed match: `_derive_period` → `match.period`
  (`extra_time`/`penalty_shootout`); `penalty_home`/`penalty_away` from `score.penalties`. Once KO rows are
  assigned, these flow with no further work.

### 7.5 Assignment trigger gating (resolves MAJOR #7)

**Finding:** the product rule is "labels until OFFICIALLY qualified," but the naive trigger is "teams present
in feed." A provider may publish projected/seeded fixtures before group play is mathematically complete or
before the 8-best-third combinatorics finalize; writing teams early flips the label prematurely/wrongly and
also feeds the predictions/odds pipeline real teams. There is no defined un-assign/correction path. (Data
finding confirms we **cannot** derive official qualification ourselves: our ranking is only
`points → GD → GF → qualification_prob`; the full FIFA tiebreaker chain — goals-scored, head-to-head,
fair-play, drawing of lots — and the cross-group best-thirds ranking are **not implemented**. Official
seeding **must** come from the provider draw.)

**Resolution:**

- Gate `assign_knockout_teams` on an **explicit official-confirmation signal**, not mere feed presence: the
  provider fixture has confirmed (non-placeholder) `homeTeam`/`awayTeam` AND a confirmed status, OR the
  feeding round is fully finished. Reject/skip placeholder team objects.
- **Idempotent + correctable:** allow overwrite while the row is `scheduled` (provider corrects a wrong team);
  **freeze** the assignment once the row is `in_play` or `finished`. Only write on NULL→value or
  value→value-while-scheduled transitions; never thrash.
- Slot label stays until the row is officially assigned. This satisfies "no standings-derived guesses."

### 7.6 Phase 2 files summary

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | Add `Match.match_no`. |
| `backend/alembic/versions/<new>.py` | Migration: `matches.match_no` nullable (single head). |
| `pipeline/ingest/wc26_structure.py` | Stamp `match_no` 73–104; add `third_place` to stage comment. |
| `pipeline/data/wc26_schedule.json` (or new KO file) | Seed KO `kickoff_utc` 73–104. |
| `pipeline/ingest/ko_venues.py` | Look up by `match_no`, not DB id; stamp kickoff/venue. |
| `pipeline/ingest/live_scores.py` | `assign_knockout_teams` (read `stage`, map, order, fixture-id key); call before `update_live_scores`; KO indexing by `provider_fixture_id`. |
| `pipeline/ingest/api_football.py` | `_to_item` forwards `league.round` as `stage`. |
| `backend/app/scoring.py` | `knockout_results_from_db` (penalties-aware); 103-loser handling. |
| `backend/app/api/knockout.py` | `GET /bracket` route + serializer using the resolver. |
| `backend/app/schemas/` | `KnockoutBracket` schema. |
| `backend/app/main.py` | `no-store` clause for `/api/knockout/bracket`. |
| `backend/app/api/internal.py`, `learning_loop.py` | Pass `knockout_results` into `recompute_scores`. |
| `pipeline/team_mapping.py` | KO-team spellings as they surface. |

---

## 8. Phasing & readiness — proving auto-catch before R32 kickoff

To "auto-catch knockout data once knockouts start," the full chain
**assign → ingest → resolve-winner → advance → serve** must be in place and tested **before** the last group
match (`2026-06-28T02:00:00Z`). Readiness checklist, each item code-grounded and testable offline:

1. **`Match.match_no` exists and is stamped 73–104** (§7.1) — invariant test green. ✔ unblocks every
   match_no-keyed lookup.
2. **Every KO row has `kickoff_utc`** (§7.2) — without this `in_live_window` never opens and nothing ingests;
   covered by an explicit test. ✔
3. **`assign_knockout_teams` reads `stage`, maps both providers, keys by `provider_fixture_id`** (§7.3) — the
   non-circular assignment path; fixture-tested for football-data and api-sports. ✔
4. **Gating on official confirmation + freeze-on-live** (§7.5) — labels won't flip early/wrong; correctable
   until kickoff. ✔
5. **Penalties-aware winner resolver feeding both `/bracket` and `recompute_scores`** (§7.4) — bracket and
   leaderboard agree; ET/PENS cases tested. ✔
6. **3rd-place (103) modeled via `THIRD_PLACE.loserFeeders`** (§3.4, §7.4) — the one node the converging tree
   can't reach is handled explicitly. ✔
7. **`/api/knockout/bracket` returns ids + `match_no` + null (not "TBD") + live fields, `no-store`** (§5) —
   frontend renders mixed states and links correctly; cache won't serve stale boards. ✔
8. **Phase 1 tree degrades to label-only from static topology** (§4.1) — the tab is useful even if the backend
   is cold/unreachable or assignment hasn't run. ✔
9. **Provider KO fixtures committed NOW** (§9) — synthetic payloads matching both schemas, since no real KO
   payload exists until July. The full chain is integration-tested against them before kickoff.
10. **Canary** (§9) — alert if any KO match reaches `in_play` while `/bracket` still shows that tie as labels
    (assignment silently failed).

If items 1–7 and 9 are green in CI before 2026-06-28, the system will auto-catch R32 data when the draw
publishes.

---

## 9. Testing plan

### Unit (pure, React-free) — `frontend/lib/officialBracket.ts`

- `resolveSlotLabel`: every R32 side → correct `<pos><group>`; every `{third:true}` → correct `3-XXXXX` from
  `THIRD_SLOTS`; R16–Final feeders resolve to the right upstream labels; **103 resolves via `THIRD_PLACE`,
  never `KO_TREE`**.
- `resolveWinner`: 2-1 → home; 1-1 pens 4-2 → home; 0-0 pens 3-3 → no winner; AET 2-1 (no pens) → home; not
  finished → no winner.
- `buildTree(null)` → full label-only tree (Phase-1 fallback). Mixed state: real team on A, label on B.

### Render — `OfficialBracket.tsx`

- States: `labels` (non-link, muted), `scheduled` (flags, link), `in_play` (live badge + `liveLabel` incl.
  `ET`/`PENS`, ring), `finished` (score, `(4-2 pens)`, winner highlighted, link to `/match/{matchId}`).
- Mixed/partial round: some R16 known, QF all labels — renders cleanly.
- Detached 3rd-place node renders beside the Final with no connector into 104.
- a11y: `role`/`aria-label` per tie/round; connectors `aria-hidden`; reduced-motion respected. VoiceOver
  smoke test on device (Capacitor iOS) for horizontal-pan focus order + tap targets.

### Backend unit + ingestion-against-fixture

There are **no recorded JSON fixtures** today — existing tests build inline dicts. **Commit synthetic
fixtures now** matching both provider schemas:

- `pipeline/ingest/testdata/wc_ko_matches.json` — football-data v4 items with `stage` (`LAST_16`,
  `QUARTER_FINALS`, `THIRD_PLACE`, `FINAL`), real `homeTeam`/`awayTeam`, a `score.fullTime` +
  `score.penalties` + `duration: PENALTY_SHOOTOUT` case, `lastUpdated`.
- The api-sports analogue (`league.round`, `score.penalty`) to exercise `to_feed`/`_to_item`.

Tests (seed an in-memory DB via `load_structure`, reuse the `db_session` fixture):

1. **`match_no` invariant:** stages map to expected `match_no` sets; 73–104 each present once.
2. **`kickoff_utc` invariant:** every KO row non-null; `in_live_window` opens for a KO row.
3. **`assign_knockout_teams`:** correct `Team` ids land on the right `match_no` rows (stage map + ordering +
   orientation/normalization); `provider_fixture_id` persisted; both providers.
4. **End-to-end offline:** after assignment, feed the same payload to `update_live_scores`; assert
   score/period/penalty flow into the now-indexed KO rows (proves the reuse claim).
5. **Winner derivation + scoring:** 1-1 pens 4-2 → home (not draw); AET 2-1 → home by score; 0-0 pens 3-3 →
   undecided; `recompute_scores` awards `ADVANCE_PTS`/`FINALIST_PTS`/`CHAMPION_PTS` correctly; 103 awards 0.
6. **Negative:** placeholder/null teams → no rows mutated; unmapped stage → logged + skipped; freeze after
   `in_play` (no overwrite); correction allowed while `scheduled`.
7. **Endpoint:** unassigned sides serialize `team_id: null` (never `"TBD"`); `match_no` + DB `id` present;
   response carries `Cache-Control: no-store`.
8. **Canary:** integration assertion that any KO `in_play` row is non-label in `/bracket`.

---

## 10. Open questions / risks (genuinely uncertain)

1. **KO kickoff data entry (§7.2).** We must hand-enter published KO kickoff times into the seed file; there is
   no source for them in the repo. If a kickoff time changes (FIFA reschedules), the window/ordering can drift.
   *Mitigation:* re-seed is idempotent; the canary catches an `in_play`-but-label state. **Open:** do we also
   pull kickoff from the provider feed to self-correct, or treat the seed file as authoritative?
2. **Chronological ↔ `match_no` ordering (§7.3).** Zipping same-stage feed fixtures by kickoff assumes FIFA's
   chronological order matches match-number order. If two same-stage games share a slot, the zip can transpose
   two ties. *Mitigation:* fixture-id tiebreak now; encode a hardcoded bracket-progression map later. **Open:**
   is the published 2026 KO schedule strictly match-number-ordered by kickoff? Verify against the official
   schedule once finalized.
3. **Provider stage strings (§7.3).** football-data has used both `LAST_16` and round names across versions;
   api-sports `league.round` is free text. A missing mapping silently drops a stage. *Mitigation:* loud
   logging + canary. **Open:** exact stage strings the 2026 competition emits won't be 100% confirmable until
   the provider populates them.
4. **Real KO payload shape unverifiable until July.** All Phase-2 ingestion tests run against *synthetic*
   payloads. There's residual risk the live shape differs (e.g. how a placeholder team is represented before
   the draw). *Mitigation:* land synthetic fixtures + canary now; capture and re-test against the first real KO
   payload immediately when it appears.
5. **`live_mode_enabled = False` by default.** Nothing flows until ops flips it — a deployment gotcha, not a
   bug. **Open:** confirm the ops runbook flips it before R32 kickoff.
6. **In-memory cache is per-process on Render.** Even with `no-store` at the edge, multi-instance/restart means
   the app-level `cache` isn't shared. *Mitigation:* skip the in-memory cache for `/bracket` while any KO row
   is `in_play`. **Open:** is a single Render instance guaranteed, or do we need to make `/bracket` fully
   cache-bypassing?
