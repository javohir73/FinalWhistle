# NRL Match Intelligence — Program Spec (Waves 1–3)

**Date:** 2026-07-10
**Status:** Approved (user: "go ahead with wave 1 … assign them other 2 waves")
**Reference:** Competitive teardown of alphr.com.au NRL match page (live review, 2026-07-10)

## Goal

Bring FinalWhistle's NRL vertical to competitor-level analytical depth — a dedicated match
intelligence page with predicted margins/totals, form & head-to-head, model factor breakdowns,
team statistics, try-scorer projections and a live layer — while keeping FinalWhistle's
differentiators: clean no-bookmaker posture, Midnight theme, user predictions vs the model,
and the transparent graded record.

## Program structure

Three waves executed by three concurrent Claude Code sessions, each using
superpowers:subagent-driven-development in an **isolated git worktree** (the primary checkout
stays untouched; sessions must not work directly in it).

| Wave | Branch | Scope | Data dependency |
|---|---|---|---|
| 1 | `feat/nrl-match-intel-w1` | Match detail page, margin/total model, form/H2H, factors, finals projections, round pages | None — existing DB only |
| 2 | `feat/nrl-match-intel-w2` | Team-stats ingest (StatsProvider), scoring breakdowns, try timelines, attack/defence profiles | New stats source (spike task) |
| 3 | `feat/nrl-match-intel-w3` | Team lists, try-scorer projections, live scores + live win probability | W2 tables (build on fixtures until W2 merges) |

**Merge order: W1 → W2 → W3.** Waves 2 and 3 do backend/pipeline/data tasks first and schedule
their UI-integration tasks last, rebasing onto main after Wave 1's PR merges (Wave 1 owns the
match-page skeleton they plug into).

Worktree pattern (mandatory, same as prior sessions):
`git worktree add /tmp/<branch-suffix> -b <branch> origin/main`, then
`ln -s "<repo>/frontend/node_modules" frontend/node_modules`, create `frontend/.env.local`
with `NEXT_PUBLIC_API_URL=http://localhost:8000`, and `git reset frontend/node_modules`
before every commit. Remove the worktree when the PR is up.

## Shared architecture (all waves code against this)

### Match Intelligence page

- New route subtree: `frontend/app/nrl/match/[id]/` — server component + `MatchIntelClient.tsx`
  island, ISR `revalidate = 300`, same pattern as `frontend/app/nrl/matches/`.
- The page renders an ordered array of **section slots**. Wave 1 ships the config:

```ts
// frontend/app/nrl/match/[id]/sections.ts
export type IntelSection = { id: string; label: string; render: React.ComponentType<IntelSectionProps> };
// Wave 1 ships: overview, form, model
// Wave 2 appends: stats (Scoring Breakdown + Try Timeline), matchup (profiles)
// Wave 3 appends: scorers, live (live pinned first when match is in progress)
```

- Anchored section nav (sticky pill row) reads that array — later waves add sections by
  appending one entry + one self-contained component file each; no edits to Wave 1 components.

### Backend modules

- Wave 1: `backend/app/api/nrl_intel.py` (detail + projections endpoints).
- Wave 2: `backend/app/api/nrl_stats.py` (+ pipeline `pipeline/sports/nrl_stats.py`).
- Wave 3: `backend/app/api/nrl_players.py`, `backend/app/api/nrl_live.py`.
- Alembic: check the current head with `alembic heads` before choosing revision ids; note both
  `revision = "..."` and `revision: str = "..."` styles exist in the repo — grep both.

### API contracts (frozen so waves build in parallel)

```
GET /api/nrl/matches/{id}            (W1)
  → { match, prediction: { home_prob, away_prob, draw_prob, predicted_margin, predicted_total,
      model_version, preview_text }, form: { home: TeamForm, away: TeamForm },
      h2h: Meeting[], factors: Factor[] }
  TeamForm = { last5: [{ round, opponent, result: "W"|"L"|"D", for, against }],
               avg_for, avg_against, avg_margin }
  Factor  = { key, label, weight, favors: "home"|"away" }

GET /api/nrl/projections             (W1)
  → { computed_at, teams: [{ team, top8, top4, minor_premiership }] }

GET /api/nrl/matches/{id}/stats      (W2)
  → { home: TeamMatchStats, away: TeamMatchStats, try_timeline: TryEvent[] }
  TeamMatchStats = { tries, conversions, penalties_conceded, errors, set_restarts,
                     run_metres, line_breaks, tackles, tackle_efficiency }
  TryEvent = { minute, team, player, score_home, score_away }

GET /api/nrl/teams/{slug}/profile    (W2)
  → { attack_rank, defence_rank, venue_splits, position_concessions }

GET /api/nrl/matches/{id}/scorers    (W3)
  → [{ player, jersey, position, unit, tries_season, games_season,
       last10: [{ round, tries }], p_anytime }]

GET /api/nrl/matches/{id}/live       (W3)
  → { status: "pre"|"live"|"final", minute, score_home, score_away,
      live_home_prob, events: [{ minute, type, team, player?, prob_after }] }
```

### DB tables

- W1: `nrl_projections` (team, top8, top4, minor_premiership, computed_at) — replaced each refresh.
  New columns on the existing NRL prediction rows: `predicted_margin`, `predicted_total`,
  `preview_text`.
- W2: `nrl_match_stats` (match_id, team, …TeamMatchStats fields), `nrl_try_events`
  (match_id, team, player, minute, score_home, score_away).
- W3: `nrl_team_lists` (match_id, team, jersey, player, position, is_late_change).

### StatsProvider protocol (W2 owns the implementation; W3 consumes)

```python
# pipeline/sports/nrl_stats.py
class StatsProvider(Protocol):
    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None: ...
    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]: ...
    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None: ...
```

Default implementation targets the NRL.com public match-centre JSON with respectful rate
limiting and a recorded-fixture test suite; Wave 2's first task is a source spike that either
confirms this or swaps in an alternative (community dataset / CSV import) behind the same
protocol. **Everything downstream builds against recorded fixtures, never live HTTP in tests.**

## Wave feature detail

### Wave 1 — model-native intelligence (no new data)

1. **Margin + total model.** Fit on ingested history (2017–2025 results): expected margin as a
   linear function of Elo difference + home advantage (least squares); expected total from a
   recency-weighted league scoring mean (last two seasons weighted 2:1). Params stored in
   `ml/models/nrl_model_params.json` analogous to football's `model_params.json` (loader +
   version field `nrl-elo-v0.2`). Predictions stamped at `nrl_predict` time.
2. **Detail endpoint** per contract above. Factors are the honest decomposition of our model —
   `elo_gap` (weight 0.5), `form_composite` (0.3, last-5 win rate + scoring differential),
   `home_advantage` (0.2) — normalized, each with `favors`.
3. **Finals projections.** 5,000-run Monte Carlo of remaining fixtures using Elo win
   probabilities (margin sampling for points differential tie-breaks), computed as a
   `nrl-refresh` pipeline step, stored in `nrl_projections`, served by the endpoint.
4. **Prose preview.** Deterministic template generator (no LLM at runtime) producing 3 short
   paragraphs from the numbers (favourite + probability, Elo gap, form lines, predicted
   margin/total). Regenerated each refresh, stored as `preview_text`.
5. **Match Intelligence page** (`/nrl/match/[id]`): hero (club monograms, win-prob chance chips
   with daily delta, margin chip "NZL by 9"-style, total chip, venue + kickoff in
   Australia/Sydney with timeZoneName short), sticky section nav, Overview (preview prose +
   forecast-movement line chart from existing `/api/matches/{id}/prob-history` NRL support),
   Form & H2H (last-5 W/L chips labelled by round, averages, last 5 meetings), Model section
   (Elo bar comparison, factor list with weight bars, confidence, model version, link to
   /nrl/record), share/copy-link row. Reuse existing card/chip components where they exist.
6. **Round pages** `/nrl/round/[n]` + prev/next navigation; `SportMatchCard` and NRL movers
   rows link through to the detail page.
7. **Ladder projections columns.** Top 8 % / Top 4 % columns on `/nrl/ladder` (hidden when the
   projections table is empty).

### Wave 2 — team-stats layer

Source spike → StatsProvider default impl → migrations for `nrl_match_stats` + `nrl_try_events`
→ backfill command (2024–2026 seasons minimum) + `nrl-refresh` ingest step → stats + profile
endpoints per contract → UI modules **after W1 merges**: Scoring Breakdown and Try Timeline
sections on finished matches, attack/defence tier ranks in a `matchup` section, venue splits on
team pages. Respect robots/ToS in the spike; provider stays pluggable.

### Wave 3 — player layer + live

Team-lists ingest (weekly, Tuesday announcements; late-change flag) → try-scorer projection
model over `nrl_try_events` history (empirical anytime-try frequency, last-10 games weighted
2×, blended with position priors and opponent position-concession rates; **outputs
probabilities only — no odds, no value badges**) → scorers endpoint per contract → live layer:
scheduled polling during match windows via StatsProvider `fetch_live`, in-play win probability
(pre-game prob updated by score differential + minutes remaining via a logistic fitted on
historical scorelines), live endpoint + client polling (60s) with `live` section pinned when in
progress (live score, updating win-prob line chart, event list with prob deltas). Graceful
`pre`/`final` states. Until W2 merges, all model work runs against recorded fixtures.

## Global constraints (every wave, every task)

- Isolated worktree; branch from `origin/main`; never commit `frontend/node_modules` (symlink —
  `git reset frontend/node_modules` before commit).
- Midnight theme tokens only — use existing CSS variables/Tailwind classes; no new hex values.
- **No bookmaker links, odds CTAs, or value-vs-odds badges.** Market comparison exists only
  where it already exists (football "Model vs market"). Try-scorer output is probabilities.
- Kickoff times: `Australia/Sydney` with `timeZoneName: "short"`.
- Footer disclaimer stays: analytics and entertainment only.
- Server components + Client islands, ISR like existing NRL pages; all `fetch` fall back with
  `.catch(() => null)` so `npm run build` succeeds without a backend.
- Backend/pipeline: pytest; frontend: jest (worker SIGSEGV under parallel load is a known flake
  — rerun once) + `npm run build` must pass.
- Model version strings come from params loaders (`current_model_version()` pattern), never
  hardcoded in consumers.
- PR per wave; merge order W1 → W2 → W3; each wave independently shippable.

## Out of scope (program-wide)

- AFL / Super League / NFL verticals; referee-tendency modelling (no data); "Ref Watch";
  Same-Game-Multi or any bet-slip constructs; horse racing (shelved); paid tiers.

## Reconciliation addendum (2026-07-10, post plan-writing)

Binding resolutions after the three plans were drafted against the live repo:

1. **Route:** the repo already ships `frontend/app/nrl/match/[season]/[round]/[no]/` (tested,
   linked from SportMatchCard and team pages). That URL is retained; a sibling `[id]` folder
   would be a Next.js dynamic-route collision. Wave 1 extends the existing page. API contracts
   remain `{id}`-based (`SportMatch.id`), added additively; the page resolves season/round/no →
   id internally. `sections.ts` therefore lives at
   `frontend/app/nrl/match/[season]/[round]/[no]/sections.ts` (Wave 2/3 plans updated).
2. **Kickoff display:** the existing page's user-selectable `<LocalKickoff>` is retained
   (viewer-local — Warriors fans see NZ time). The Global Constraint's intent (never raw UTC)
   is satisfied; no `sydneyKickoff` helper is added.
3. **`IntelSectionProps` (Wave 1-defined):** `{ detail: NrlMatchDetail; probHistory: NrlProbHistory | null }`.
   Waves 2/3 adapt their section components' prop destructuring at merge time; their sections
   fetch their own data client-side and must not require new props from Wave 1.
4. **Wave 1 additive endpoints:** `GET /api/nrl/matches/{id}/prob-history` (NRL snapshots) and
   a `match_url` field on `GET /api/movers` rows.
5. **Wave 2:** `position_concessions` ships as `[]` (frozen shape) until Wave 3's team-lists
   provide player→position mapping. Team slugs are derived at request time from
   `SportTeam.name` (no migration). Table names follow the spec's `nrl_*` (documented deviation
   from the repo's `sport_*` convention). `venue_splits` row shape:
   `{venue, played, wins, draws, losses, avg_for, avg_against}`.
6. **Wave 3 additive items:** `team: "home"|"away"` field on scorers rows; `nrl_live_state` +
   `nrl_live_events` tables; a Tuesday cron slot on `nrl-refresh.yml` for team lists; a
   `nrl-live-refresh.yml` workflow (15-min cron during match windows). In-play model is fitted
   on synthetic scoring-event timings anchored to real final scores (no minute-level history
   exists) — documented approximation.
7. **Alembic:** three waves each add migrations in parallel worktrees. Every implementer runs
   `alembic heads` at execution time and chains onto the actual head; expect to re-parent at
   merge time in Waves 2/3 (merge order W1 → W2 → W3).
