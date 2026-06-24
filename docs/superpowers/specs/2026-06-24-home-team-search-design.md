# Home dashboard team search — design

**Date:** 2026-06-24
**Status:** Approved (brainstorming)

## Problem

The returning-user home dashboard (greeting → your-team hero → match of the day →
also today) has no way to look up a team other than your own. To reach any other
nation's profile you must go through "Change country" or navigate via Groups. We
want a quick search: type a team name, pick a result, land on that team's
`/team/[id]` profile.

The new-visitor onboarding screen already has a `CountrySearch` grid, but that
*selects your country* to start the AI-forecast flow — it does not navigate. This
feature is navigation-first and lives only on the returning-user dashboard.

## Scope

- **In:** A compact search/autocomplete bar on the returning-user `HomeDashboard`
  that navigates to `/team/[id]` on selection.
- **Out:** The onboarding screen (unchanged). No backend changes. No new API
  calls — uses the `teams` list already loaded by `HomeExperience`.

## Solution

### New component — `frontend/components/TeamSearch.tsx` (client)

A combobox / autocomplete:

- Slim text input with the search-magnifier icon, placeholder **"Search any team…"**.
- While the trimmed query is non-empty, a dropdown listbox shows the top matches
  (capped at **8**, scrollable). Each row: `Flag` + name + a "Host" badge when
  `is_host`.
- **Ranking** (shared helper, see below): prefix matches first, then substring,
  then alphabetical — so "ar" surfaces Argentina early.
- **On select** (click a row, or press Enter on the highlighted row):
  `router.push('/team/${id}')` via `next/navigation`'s `useRouter`.
- The user's own selected team is **included** in results (it simply navigates to
  that same profile) — no filtering.
- **Keyboard & a11y:**
  - Input: `role="combobox"`, `aria-expanded`, `aria-controls` → listbox id,
    `aria-activedescendant` → highlighted option id, `aria-autocomplete="list"`.
  - `ArrowDown` / `ArrowUp` move the highlight (wrapping is not required — clamp at
    ends), `Enter` navigates to the highlighted option, `Escape` closes the
    dropdown and clears the highlight.
  - Listbox `role="listbox"`; each row `role="option"` with `aria-selected` and a
    stable `id` for `aria-activedescendant`.
- **No match:** a single row reads *No team matches "{query}".*
- Closing behaviour: dropdown is hidden when the query is empty or after Escape;
  re-typing reopens it. (Blur-to-close is optional polish, not required for the
  first cut — keep it simple and rely on Escape + navigation.)

### Shared helper — `frontend/lib/teamSearch.ts`

Extract the existing prefix→substring→alphabetical ranking out of `CountrySearch`
into one pure, testable function:

```ts
export function rankTeams(teams: Team[], query: string): Team[]
```

- Empty/whitespace query → all teams sorted alphabetically.
- Non-empty → substring-filtered, then sorted: prefix matches before non-prefix,
  ties broken alphabetically (case-insensitive, via `localeCompare`).

`CountrySearch` is refactored to call `rankTeams` (behaviour-preserving), removing
its inline `useMemo` sort duplication. `TeamSearch` uses the same helper.

### Wiring

- `HomeExperience` already holds the full `teams` array. Pass it into
  `HomeDashboard` as a new `teams: Team[]` prop.
- In `HomeDashboard`, render `<TeamSearch teams={teams} />` **directly under the
  greeting headline** (the "{n} matches today" `<h1>`) and above the your-team
  hero `Link`.

## Data flow

```
HomeExperience (has teams[]) 
  └─ HomeDashboard(team, teams, groups, odds, matches)
       └─ TeamSearch(teams)  --select-->  router.push(`/team/${id}`)
```

No props change for `MatchOfDayCard` / `AlsoTodayRow`. No server component
changes; `page.tsx` already server-fetches `teams` and seeds `HomeExperience`.

## Error / edge handling

- Empty `teams` (data still loading or fetch failed): the input renders but the
  dropdown shows nothing / the no-match row only when a query is typed. The
  dashboard only mounts once a selection exists, by which point `teams` is
  normally populated; an empty list degrades to "no matches" rather than erroring.
- Names with diacritics / "&" rely on plain `toLowerCase().includes`, matching the
  current `CountrySearch` behaviour (no normalization regression introduced).

## Testing

- **`frontend/lib/teamSearch.test.ts`** — `rankTeams`:
  - empty query → full list, alphabetical;
  - prefix beats substring ("ar" → Argentina before Qatar-style substring hits);
  - case-insensitive; no-match → empty array.
- **`frontend/components/__tests__/teamSearch.test.tsx`** (mock `next/navigation`
  `useRouter`):
  - typing filters the visible options;
  - clicking a result calls `push('/team/<id>')`;
  - ArrowDown to highlight + Enter calls `push` for the highlighted team;
  - no-results message renders for a non-matching query;
  - Escape closes the dropdown.
- Existing `CountrySearch` behaviour stays green after the refactor: the
  onboarding flow test `frontend/components/__tests__/countryFlow.test.tsx` (which
  exercises `CountrySearch` via `CountryOnboarding`) must still pass.

## Out of scope / non-goals

- Searching matches, players, or groups (teams only).
- Fuzzy / typo-tolerant matching beyond substring.
- Persisting recent searches.
- Adding the bar to onboarding or any other route.
