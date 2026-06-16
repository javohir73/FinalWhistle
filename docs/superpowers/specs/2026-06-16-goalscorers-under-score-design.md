# Goalscorers under the score — design

**Date:** 2026-06-16
**Status:** Approved (design)
**Scope:** Show goalscorer names under the score on the match **detail page**, for
**live and finished** matches, updating live via the existing summary poll.

## Goal

Under the live/actual score in `MatchScoreboard`, list who scored — e.g.
`R. Rezaeian 32'`, `M. Mohebi 64'` — with `(pen)` / `(OG)` annotations, updating
in near-real-time as goals happen.

## Constraints / decisions

- **Provider:** api-sports (`api_football`) only. It carries goal events; the
  football-data free tier does not. On `football_data`, the feature is a no-op
  (no scorers shown) — graceful, never an error.
- **Storage:** a nullable JSON column `matches.goal_events` (mirrors the existing
  `scoreline_probs` JSON-column pattern). A normalized table is overkill for the
  ~2–6 rows per match.
- **API budget:** fetch events for a fixture **only when its goal total changes**
  (or the first time it's seen in_play/finished), not every refresh. ⇒ roughly
  one events call per goal + one at finish, well within the Pro daily cap.

## Data model

`goal_events` (JSON, nullable) — ordered list of:

```json
{ "minute": 64, "side": "home", "player": "M. Mohebi", "type": "goal" }
```

- `side`: `"home"` | `"away"` — the side **credited** with the goal (for an own
  goal, the side that benefits).
- `type`: `"goal"` | `"penalty"` | `"own_goal"`.
- `minute`: integer (event elapsed minute).

## Source mapping (api-sports → our shape)

`GET /fixtures/events?fixture={id}` → keep `type == "Goal"` events:

| api-sports `detail` | our `type` | credited `side` |
|---------------------|-----------|-----------------|
| `Normal Goal`       | `goal`    | event team's side |
| `Penalty`           | `penalty` | event team's side |
| `Own Goal`          | `own_goal`| **opponent** of the event team's side |

(`Missed Penalty` and non-`Goal` events are ignored.) Side is resolved by
matching the event team name to the fixture's home/away (via `normalize_team_name`).

## Ingestion flow (api_football branch of `refresh_live`)

1. Bulk `fetch_fixtures()` → `to_feed()` as today (scores/status/minute).
2. For each feed item that is `IN_PLAY` or just-`FINISHED`, decide whether to
   fetch events: yes if its goal total (home+away) differs from the goal count
   currently stored in `matches.goal_events`, or none stored yet.
3. For those, `fetch_events(fixture_id)` → translate → attach to the feed item as
   a `scorers` list (already in home/away orientation).
4. `update_live_scores()` stores `item["scorers"]` onto `match.goal_events` when
   present (provider-agnostic: absent ⇒ left unchanged).

## New / changed units

- `pipeline/ingest/api_football.py`:
  - `fetch_events(api_key, fixture_id, timeout=15.0)` — thin GET, mirrors `fetch_fixtures`.
  - `goals_from_events(events, home_name, away_name)` — pure translator → scorer dicts.
  - hook in the `refresh_live` api_football branch for the on-goal-change fetch.
- Alembic migration: add `goal_events` JSON column to `matches`.
- `backend/app/models`: `Match.goal_events`.
- `pipeline/ingest/live_scores.update_live_scores`: store `scorers` when present.
- `backend/app/schemas`: `GoalEventOut` + `MatchSummaryOut.goal_events: list[GoalEventOut] | None`.
- `backend/app/serializers.match_to_summary`: copy `match.goal_events`.
- `frontend/components/MatchScoreboard.tsx`: render scorers under the score
  (home scorers on the home side, away on the away side; `(pen)`/`(OG)` labels);
  updates live via the existing 30s `getMatchSummary` poll.
- `frontend/lib/types.ts`: `GoalEvent` type + `goal_events` on the summary type.

## Testing (TDD)

- `goals_from_events`: normal goal, penalty, own-goal orientation, reversed feed,
  non-goal events ignored, missing player defensive.
- `update_live_scores`: stores `goal_events` when a feed item carries `scorers`;
  leaves it untouched when absent (football_data path).
- on-goal-change gate: events fetched when goal total rises, skipped otherwise.
- serializer: `goal_events` present in `MatchSummaryOut`.
- frontend: `MatchScoreboard` renders scorer lines with minute + annotations.

## Out of scope (YAGNI)

- Cards, substitutions, assists, lineups.
- Scorers on the compact match-board cards (detail page only).
- Backfilling scorers for already-finished matches (they fill in on the next
  refresh that touches them).
