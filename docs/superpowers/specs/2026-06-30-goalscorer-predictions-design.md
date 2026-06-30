# Goalscorer predictions (Phase 2)

Status: APPROVED
Date: 2026-06-30
Author: pete@degail.com
Scope: Phase 2 — individual goalscorer predictions ("who will score, and how
many") on the match card. Builds on Phase 1 (goal-total markets), which already
stores per-team expected goals (`lambda_home`/`lambda_away`/`rho`).

## Goal

A **"Likely scorers"** card on the match page: for each team, the top ~5 players
ranked by their chance to score, with anytime-score `P(≥1)` and a "2+" chip when
notable. Shown in two modes:
- **Squad estimate** — before the lineup is announced, from the full squad
  weighted by expected playing time.
- **Confirmed XI** — once the starting XI is announced (~40 min pre-kickoff),
  restricted to (and sharpened on) the players actually starting.
A badge indicates which mode is active.

## Data feasibility (confirmed)

The existing API-Football key is **Pro tier** and reaches current-season player
data (`/api/health/provider` returned `plan=Pro, player_data_reachable=true`,
quota 3/7500/day). No upgrade needed.

## Model

For a team `T` with stored expected goals `λ_T`, and candidate players `p`
(squad in squad mode; XI + bench in lineup mode):

```
weight_p = rate_p × mins_p
share_p  = weight_p / Σ_q weight_q          (over the team's candidates)
xG_p     = λ_T × share_p                    (player expected goals; Σ_p xG_p = λ_T)
P(p scores ≥1) = 1 − e^(−xG_p)
P(p scores ≥2) = 1 − e^(−xG_p)·(1 + xG_p)
```

Allocating all of `λ_T` to players (ignoring own goals, ~2–3% of goals) keeps the
per-player totals consistent with the team's λ and with Phase 1's markets.

**`rate_p` — blended scoring rate (goals per 90), shrunk by sample size:**

```
rate_p = (goals_club + goals_wc + K · pos_rate) / (nineties_club + nineties_wc + K)
```
- `goals_club / nineties_club`: 2025-26 club-season goals and 90s played (rich prior).
- `goals_wc / nineties_wc`: WC-2026 goals and 90s (recency/form; sparse early).
- `pos_rate`: position base rate (e.g. ST ≈ 0.50, W/AM ≈ 0.32, CM ≈ 0.12,
  FB ≈ 0.05, CB ≈ 0.04, GK ≈ 0.005 goals/90 — defaults, tunable).
- `K`: position pseudo-90s shrinkage strength (default 10). Low-minute players
  pull toward the position prior; high-minute players toward their actual rate.

Total goals (including penalties) feed `goals_*`, so penalty-taking is captured
by the rate. Optional refinement: a small bump for a team's known penalty taker.

**`mins_p` — playing-time weight ∈ [0, 1]:**
- *Squad mode:* a share-of-available-minutes proxy from the player's recent
  minutes (regular starters ≈ 1, fringe players ≈ low), approximating start
  probability without a who-starts classifier. The exact estimator (e.g. minutes
  per available match, normalized within the squad) is finalized in
  implementation; the principle is recent minutes share.
- *Lineup mode:* announced starter = 1.0, named substitute = 0.25, not listed = 0.

## Data / ingestion (new `Player` model)

New `Player` table:
- `id`, `provider_player_id` (API-Football player id, unique), `name`,
  `team_id` (FK to our `teams`), `position`,
- club-season: `club_goals`, `club_minutes`, `club_penalties`,
- WC: `wc_goals`, `wc_minutes`,
- bookkeeping: `season`, `updated_at`.

Ingestion sources (new `pipeline/ingest/players.py`):
- `/players/squads?team={provider_team_id}&season=2026` → rosters + player IDs
  (~32 calls; one per team).
- per-player `/players?id={pid}&season=2025` → **club-season** goals/minutes/
  penalties/position, aggregated over the player's club league(s)
  (~700 calls; one-time + periodic refresh, paced under the plan's rate limit).
- WC form: `/players?league=1&season=2026` (paginated) or per-player season=2026
  → `wc_goals`/`wc_minutes`.
- **Lineup linkage:** extract `player.id` from `/fixtures/lineups` (currently
  ignored in `_player_row`, `pipeline/ingest/api_football.py`) and persist it on
  `LineupPlayer` so the announced XI joins to `Player` by id — no fuzzy matching.

Cadence: a daily pipeline step (`refresh.yml`). Squads + club stats change slowly
(refresh weekly / when stale); WC form refreshes daily.

**Dependency — team id mapping:** squads are keyed by API-Football `team_id`. Add
`provider_team_id` to our `Team` (or a mapping), populated from the fixtures feed
(which already carries team ids). Required before squad ingestion.

## Serving

A `goalscorers` block on the match payload (compute-on-read, like Phase 1's
`goal_markets`, optionally cached), built from: the match's `λ_home`/`λ_away`,
each team's `Player` rows, and the announced lineup when available. Shape:

```
goalscorers: {
  mode: "squad" | "lineup",
  home: [ { name, position, p_score, p_score_2plus, xg } , ... up to ~8 ],
  away: [ ... ],
} | null            # null when player data for both teams is missing
```
Players sorted by `xg` desc; the UI shows the top ~5.

## UI

A **"Likely scorers"** card on the match page (`/match/[id]`), after the Goals
card: two columns (home/away), each listing top ~5 players with name + position +
anytime-score %, a "2+" chip when `p_score_2plus ≥ 0.10`, and a header badge
**"Squad estimate"** or **"Confirmed XI"** per `mode`. Hidden when `goalscorers`
is null.

## Build stages (for the implementation plan)

1. **Data foundation** — `Player` model + migration; `provider_team_id` on `Team`;
   squad + club-season + WC-form ingestion (`pipeline/ingest/players.py`); extract
   and persist `player.id` on lineups; wire into the daily pipeline.
2. **Model + serving** — the allocation model (`ml/` pure functions: `rate_p`,
   `share_p`, `xG_p`, `P(≥1)/P(≥2)`, mode handling); the `goalscorers` serializer
   block + schema; lineup-vs-squad mode selection.
3. **UI** — the "Likely scorers" card (both modes) + types + render on the match
   page, hidden when null.

## Testing

- **Model (ml):** shares sum to 1 and `Σ xG_p = λ_T`; monotonic (`P(≥1) ≥ P(≥2)`);
  shrinkage pulls low-minute players toward position prior; lineup mode zeroes
  non-listed players; a known-input fixture with hand-checkable numbers.
- **Ingestion:** parse squads / per-player stats; `player.id` extracted and
  persisted on lineups; team-id mapping resolves; rate aggregation over multiple
  club leagues.
- **Serving:** `goalscorers` populated in lineup vs squad mode; null when no
  player data.
- **UI:** card renders both modes; "2+" chip gating; hidden when null.

## Out of scope (v1)

- A dedicated who-starts / availability classifier (minutes-weighting stands in).
- Assists, cards, shots, or other player props.
- Predicted-vs-actual scorer review on finished matches (possible fast-follow).
- Own-goal allocation (ignored; ~2–3% of goals).

## Risks / open items

- **Team-id mapping** must exist before squad ingestion (see Dependency above).
- **API pacing:** ~700 one-time per-player calls must respect the Pro plan's
  per-minute limit (throttle/backoff in the ingester).
- **Sparse early WC form** is expected; the club-season prior + shrinkage carry
  the estimate until WC minutes accumulate.
- **Season param:** club-season 2025-26 is `season=2025` in API-Football; WC is
  `season=2026`. The ingester queries both per player.
- **Name/availability gaps:** injured or withdrawn players may linger in squads;
  lineup mode (actual XI) is the source of truth once available.

## Rollout

Stage 1 adds a migration (the `Player` table + `provider_team_id`) and a pipeline
step — deploys via `refresh.yml` (which runs `alembic upgrade head`). Stages 2–3
are additive (serializer + frontend), no migration. The card appears once player
data is ingested for a match's teams.
