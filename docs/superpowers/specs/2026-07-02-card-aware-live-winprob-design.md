# Card-Aware Live Win Probability — Design

**Date:** 2026-07-02
**Status:** Approved (user-reviewed via brainstorming session)

## Problem

The in-play win probability (`backend/app/live_winprob.py`) recomputes W/D/L from the
current score, the clock, and the pre-match expected-goals rates — nothing else. A red
card is one of the strongest in-play signals in football (a sending-off shifts scoring
rates by roughly a third), yet the platform neither ingests card events nor adjusts the
live bar for them. During USA–Bosnia (match 81) a red card left the displayed live
probability visibly overconfident.

## Goals

- Ingest card events (yellow and red) from the live data feed and persist them.
- Adjust the live win probability for red cards (score-state-aware, milder-side
  multipliers) and for yellows via second-yellow risk only.
- Surface cards in the UI so users can see *why* the live bar moved.

## Non-Goals

- No change to the pre-match model (`ml/`) or its features.
- No backfill of card events for already-finished matches.
- No modelling of extra time / shootouts (the live model already falls back to
  pre-match probabilities there).
- No card data from the `football_data` fallback provider (its match list carries
  none) — with that provider the model behaves exactly as today.

## Architecture Overview

Cards flow through the same pipeline goals already use:

```
api-football /fixtures/events  →  cards_from_events()   (pipeline/ingest/api_football.py)
        →  item["cards"]        →  update_live_scores()  (pipeline/ingest/live_scores.py)
        →  Match.card_events    (new JSON column, mirrors goal_events)
        →  serializers.py       (derive per-side red/active-yellow counts)
        →  live_winprob.py      (scale remaining-time goal rates)
        →  MatchSummaryOut      (card_events exposed; frontend renders them)
```

## Components

### 1. Ingestion (`pipeline/ingest/api_football.py`)

- **`cards_from_events(events, home_name, away_name) -> list[dict]`** — parallel to
  `goals_from_events`. Emits `{minute, side, player, type}` with
  `type ∈ {"yellow", "red"}` in OUR home/away orientation. api-sports emits a second
  yellow as a `detail == "Red Card"` event, so red count = count of Red Card events.
  Malformed events and unknown team names are skipped (same posture as goal parsing).
- **`attach_scorers` → renamed `attach_events`** with a second fetch trigger. Today
  events are fetched only when the stored goal count differs from the feed total — a
  red card with no subsequent goal would never be seen. New trigger: an in-play
  fixture also refetches when its last events fetch is older than
  `settings.events_refetch_seconds` (default **180**). Last-fetch times are tracked
  in-process (module dict keyed by fixture id, `time.monotonic()`), consistent with
  the module's other in-process state; a worker restart just refetches once.
  When a fetch happens the item gains BOTH `scorers` and `cards`.
- Quota: with the production Pro api-football key (~7,500 req/day) the staleness
  trigger adds ~20 calls per live match hour — negligible.

### 2. Persistence (`pipeline/ingest/live_scores.py`, `backend/app/models`)

- New nullable JSON column **`Match.card_events`**, exactly mirroring `goal_events`
  (one Alembic migration).
- `update_live_scores`: `if "cards" in am: match.card_events = am["cards"]` —
  same guarded assignment pattern as scorers.

### 3. Live model (`backend/app/live_winprob.py`)

`live_win_probabilities()` gains keyword args (all defaulting to zero so existing
callers are unaffected): `red_home, red_away, yellow_home, yellow_away`.

**Red cards — score-state-dependent multipliers** applied to the remaining-time
rates (`lam_h_rem` / `lam_a_rem`), where the state is the carded team's current
score situation *at recompute time* (the model is per-request, so effects re-derive
as the score changes):

| Carded team is… | Own rate × | Opponent rate × | Rationale                          |
|-----------------|------------|-----------------|------------------------------------|
| Leading         | 0.60       | 1.05            | Bunker: goals dry up, hold prob stays high |
| Level           | 0.75       | 1.10            | Standard mild 10v11 effect         |
| Trailing        | 0.75       | 1.15            | Must chase; opponent counters      |

Multiple reds compound multiplicatively with the same state factors; at most
**3 reds per side** are counted.

**Yellows — second-yellow risk only, no flat discount.** Each *active* yellow
(a booking whose player has no red event — derivable because card events carry
player names; the serializer computes this) contributes
`p = SECOND_YELLOW_HAZARD × (minutes_remaining / 90)` with
`SECOND_YELLOW_HAZARD = 0.04`. Per active booking, BOTH remaining-time rates are
blended toward their red-card values using the same state-dependent factors: the
booked team's rate `λ_own ×= (1 − p) + p × own_factor` and the opponent's rate
`λ_opp ×= (1 − p) + p × opp_factor`.
Two bookings with 45' left ≈ 1% rate shift — negligible by design and decaying
to zero at full time. At most **5 active yellows per side** are counted.

All constants are module-level, named, and commented with their evidence basis
(literature-consistent for reds; deliberately weak for yellows).

**Invariant preserved:** zero cards ⇒ all factors 1.0 ⇒ output bit-identical to the
current implementation (the kickoff "no twitch" property still holds).

### 4. Serving (`backend/app/serializers.py`, `backend/app/schemas`)

- New `CardEventOut {minute, side, player, type}`; `MatchSummaryOut` gains
  `card_events: list[CardEventOut] = []` alongside `goal_events`.
- The serializer derives the four counts from `match.card_events` (active-yellow
  logic lives here) and threads them into `live_probabilities_for_match`, which
  passes them through to `live_win_probabilities`.
- `card_events is None` (fallback provider, old rows) ⇒ zero counts ⇒ unchanged
  behaviour.

### 5. Frontend

- The match summary type gains `card_events`.
- **Red cards** render as events in the match timeline alongside goals (player,
  minute, red marker) — this is the visible explanation for live-bar jumps.
- **Yellows** render as a compact per-team count (not individual timeline entries,
  to avoid clutter).
- Exact component placement follows the existing goal-event rendering patterns
  (located during implementation planning).

## Error Handling

- Malformed / unknown-team card events: skipped at parse time.
- Events fetch failure: never breaks the refresh (existing `refresh_live` posture).
- Provider without card data: `card_events` stays `None`; model unchanged.
- Extra time / shootout: `live_probabilities_for_match` already returns `None`
  (pre-match bar shown); cards inherit that behaviour.

## Testing (TDD throughout)

- **Parser:** yellow/red split, second-yellow-as-red counting, own-orientation
  mapping, unknown team and malformed event skipping.
- **Fetch trigger:** goal-change fires; staleness fires for in-play; fresh and
  unchanged does not fetch; finished fixtures keep the goal-count-only trigger.
- **Persistence:** cards written through `update_live_scores`; partial payloads
  never blank stored cards.
- **Model properties:** a red lowers the carded team's win probability and raises
  the opponent's; triple always sums to 1; zero cards is bit-identical to the
  pre-change implementation (regression pin); leading-team red raises hold/draw
  relative to the level-state factors; compounding and caps respected; yellow
  effect small and decays with the clock.
- **Serializer:** counts derived correctly (including active-yellow exclusion of
  sent-off players); `card_events` exposed on the summary.
