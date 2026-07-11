# Market Intel Panel — Design

**Date:** 2026-07-10
**Status:** Approved by user (brainstorming session)
**Replaces:** "Today's Movers" panel on the dashboard

## Problem

The "Today's Movers" panel on the home dashboard surfaces stale, resolved markets.
On 2026-07-10 (knockout stage) it showed Mexico, South Africa, and Canada at
"100% to reach the knockouts" — a market that resolved weeks ago, for teams
already eliminated.

Root cause (from code scout):

- `backend/app/api/movers.py` ranks `ProbabilitySnapshot` rows purely by
  `abs(delta)` with zero awareness of tournament stage or elimination.
- `pipeline/generate_predictions.py` writes `TournamentOdds` for all teams
  unconditionally from `simulate_tournament()`; nothing zeroes eliminated teams.
- No `is_eliminated` flag exists anywhere in the serving tables.

## Decision (user-approved scope)

Replace the movers panel with a **Market Intel** panel fed by live prediction-market
data (Polymarket + Kalshi, free public read-only APIs). No news API. Applies to
**both sports**, with an automatic **fallback to the existing MoversPanel** whenever
a sport has no fresh market data (NRL most days; football after the tournament ends).

The movers backend/pipeline bug is explicitly **out of scope** — the movers code
path survives only as the fallback, unchanged. Ingesting only *active* (unresolved)
exchange markets makes stale/eliminated content structurally impossible in the new
panel: the exchanges close markets on elimination, doing that tracking for us.

## Architecture (approach A — chosen over live-fetch and hybrid)

Hourly snapshots via GitHub Actions; the backend serves from the DB only. The
request path never touches an external API. Odds are up to ~1h old, acceptable
behind the existing 60s public cache.

```
Polymarket Gamma API ─┐
                      ├─ pipeline/market_intel.py ── market_odds_snapshot (DB)
Kalshi public API ────┘        (hourly GH Actions)          │
                                                            ▼
                                             GET /api/intel?sport=…
                                                            │
                                                            ▼
                                    IntelPanel (has_data) / MoversPanel (fallback)
```

## Panel content (UX)

Same dashboard slot and visual language as MoversPanel (green glass card). Two parts:

1. **Model vs. market, per upcoming match** — up to 5 not-yet-kicked-off
   fixtures with market coverage, soonest first: model win/draw/win
   probabilities beside market implied probabilities, with disagreement
   highlighted when ≥ 5 percentage points ("Market: France 62% · Model: 55%").
2. **Movement storylines** — up to 3 lines, biggest absolute 24h moves first:
   "Morocco to win the title drifted 6% → 3% overnight (Polymarket)". Market
   movement stands in for news (injuries/lineups price in within minutes).

Footer: "via Polymarket · Kalshi · updated Nm ago" (provenance + freshness).
Each match row links to the existing match detail page. The "See all movement"
link exists only on the fallback MoversPanel.

**Fallback rule:** if a sport has no snapshot fresher than 24h — or the intel
fetch fails — render the existing MoversPanel instead. MoversPanel is untouched.

## Data model

New table `market_odds_snapshot` (one Alembic migration):

| Column | Notes |
|---|---|
| `id` | PK |
| `sport` | "football" / "nrl" |
| `source` | "polymarket" / "kalshi" |
| `market_type` | "match_winner" (→ match) / "title_winner" (→ team) |
| `match_id` | nullable FK → matches |
| `team_id` | nullable FK → teams |
| `outcome` | "home" / "draw" / "away", or the team for title markets |
| `implied_prob` | float; vig-normalized mid-price |
| `external_id` | Polymarket slug / Kalshi ticker |
| `fetched_at` | UTC |

Index `(sport, fetched_at)`. Unique `(source, external_id, outcome, fetched_at)`
so re-runs are idempotent.

## Ingest

`pipeline/market_intel.py`, run hourly by `.github/workflows/market-intel.yml`
(same secrets pattern as `refresh.yml`):

1. Fetch **active** World Cup markets from Polymarket Gamma and Kalshi's public
   market API (both free, no auth for read).
2. Map markets to our matches/teams by team-name matching against upcoming
   fixtures, with a small alias table ("USA"/"United States",
   "Korea Republic"/"South Korea"). Unmappable markets are logged and skipped,
   never guessed.
3. Normalize prices across a market's outcomes (rescale to sum to 1) to remove
   vig; skip malformed/out-of-range prices rather than clamping.
4. Write snapshot rows with per-source and per-market error boundaries
   (never-raises pattern from the NRL ingest). The workflow fails only when
   **both** sources return nothing.
5. Prune snapshots older than 14 days.

**Ops:** hourly ≈ 700–800 GH Actions minutes/month — within the private-repo
free tier (2,000) but a meaningful share alongside CI. Drop the cron to every
2–3 hours after the World Cup final (2026-07-19), when only thin NRL coverage
remains.

## Backend API

New router `backend/app/api/intel.py`, mounted alongside `movers.py`:

`GET /api/intel?sport=football` →

```jsonc
{
  "has_data": true,          // false when no snapshot < 24h old for the sport
  "updated_at": "…",         // latest fetched_at, for the footer
  "matches": [
    {
      "match_id": 123, "kickoff_utc": "…", "home": {…}, "away": {…},
      "model":  { "home": 0.55, "draw": 0.27, "away": 0.19 },  // existing predictions tables
      "market": [ { "source": "polymarket", "home": 0.62, "draw": 0.24, "away": 0.14, "fetched_at": "…" } ],
      "disagreement": 0.07   // market − model, home-win basis; omitted if no model prediction
    }
  ],
  "storylines": [
    { "market_type": "title_winner", "team": {…}, "prob_from": 0.06,
      "prob_to": 0.03, "window_hours": 24, "source": "polymarket" }
  ]
}
```

- `matches[]` includes only matches with a future `kickoff_utc` (not yet kicked
  off), capped at 5, soonest first.
- Storylines: top 3 absolute moves, latest snapshot vs. the snapshot closest to
  24h prior. "Live" is defined concretely: the market's latest snapshot must be
  ≤ 3h old (≈ 2 ingest cycles) — closed markets stop getting snapshots and drop
  out on their own; match-winner storylines additionally require a future
  kickoff. Structured facts only — the frontend renders the sentence (same
  division of labor as `marketLabel()` today).
- A match with market rows but no model prediction still returns its market side,
  omitting `disagreement`.
- Inherits the default 60s public cache + stale-while-revalidate.

## Frontend

- New `frontend/components/IntelPanel.tsx` — same visual language as MoversPanel.
- New `getIntel(sport)` in `frontend/lib/api.ts`.
- Both home pages (football `HomeExperience`, NRL home) render a small wrapper:
  fetch intel → `has_data ? <IntelPanel/> : <MoversPanel/>`; fetch error also
  falls back. The panel can never be a blank hole.

## Error handling summary

| Failure | Behavior |
|---|---|
| One market malformed | Skip that market, continue |
| One source down | Skip that source, keep the other |
| Both sources empty | Workflow fails loudly (visible in Actions) |
| No fresh snapshots | `has_data: false` → MoversPanel fallback |
| Intel fetch fails in frontend | MoversPanel fallback |
| Market rows without model prediction | Show market side only |

## Testing (repo test gate)

- `pipeline/market_intel_test.py` — parsing against **recorded** Polymarket/Kalshi
  JSON fixtures (no live API calls in tests), alias mapping, unmappable-market
  skip, vig normalization, idempotent re-run, pruning.
- Backend — `has_data` freshness logic, 24h storyline window selection,
  disagreement math, sport scoping, empty-DB behavior.
- Frontend — IntelPanel render test, fallback-wrapper test,
  `npm run typecheck && npm run lint && npm test`.

## Deployment sequencing

Standard rule (CLAUDE.md): the migration merges and is applied via `refresh.yml`
**before** the intel code path goes live, or the API 500s. Merging to `main`,
dispatching `refresh.yml`, and enabling the hourly cron all sit behind the stop
gate.
