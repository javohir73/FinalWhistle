# Goalscorers Under the Score — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show goalscorer names (with minute + pen/OG) under the live/actual score on the match detail page, updating live, sourced from API-Football.

**Architecture:** Add a nullable JSON column `matches.goal_events`. In the `api_football` refresh path, fetch `/fixtures/events` only for fixtures whose goal total changed, translate to scorer dicts (home/away resolved), and store via `update_live_scores`. Serialize on `MatchSummaryOut`; render in `MatchScoreboard` (already polls the summary every 30s, so it updates live). The `football_data` path never supplies scorers — graceful no-op.

**Tech Stack:** Python (SQLAlchemy 2.0, Alembic, FastAPI, pytest), TypeScript (Next.js, React, jest/RTL).

**Spec:** `docs/superpowers/specs/2026-06-16-goalscorers-under-score-design.md`

**Run tests from repo root.** Python: `python -m pytest` (config: `pytest.ini`, `pythonpath = backend .`). Frontend: `cd frontend && npm test`.

**Scorer dict shape (the internal contract):**
```python
{"minute": 64, "side": "home", "player": "M. Mohebi", "type": "goal"}  # type: goal|penalty|own_goal
```

---

### Task 1: DB column + model field `goal_events`

**Files:**
- Create: `backend/alembic/versions/c9d2a1b3e4f5_add_goal_events.py`
- Modify: `backend/app/models/__init__.py` (after line 114, `provider_last_updated`)

- [ ] **Step 1: Add the model field**

In `backend/app/models/__init__.py`, in `class Match`, immediately after the `provider_last_updated` column (line 114), add:

```python
    # Goal events for the live/actual scoreline: ordered list of
    # {minute, side: "home"|"away", player, type: "goal"|"penalty"|"own_goal"}.
    # Populated by the api_football provider only (football-data has no scorers).
    goal_events: Mapped[list | None] = mapped_column(JSON)
```

(`JSON` is already imported at line 13.)

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/c9d2a1b3e4f5_add_goal_events.py`:

```python
"""add goal_events JSON column to matches

Revision ID: c9d2a1b3e4f5
Revises: a7c1f0e2d3b4
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d2a1b3e4f5"
down_revision: Union[str, None] = "a7c1f0e2d3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("goal_events", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "goal_events")
```

- [ ] **Step 3: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: runs without error; `matches.goal_events` exists.

- [ ] **Step 4: Verify model imports and column present**

Run: `python -m pytest backend/ -q -k "model or schema" `
Expected: PASS (no collection/import errors).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/c9d2a1b3e4f5_add_goal_events.py
git commit -m "feat(live): add goal_events JSON column to matches"
```

---

### Task 2: `goals_from_events` translator (api-sports → scorer dicts)

**Files:**
- Modify: `pipeline/ingest/api_football.py`
- Test: `pipeline/ingest/api_football_test.py`

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/ingest/api_football_test.py`:

```python
from pipeline.ingest.api_football import goals_from_events


def _event(detail, team, player, minute, etype="Goal"):
    return {"type": etype, "detail": detail, "team": {"name": team},
            "player": {"name": player}, "time": {"elapsed": minute}}


def test_goals_from_events_normal_penalty_and_side():
    events = [
        _event("Normal Goal", "Iran", "R. Rezaeian", 32),
        _event("Penalty", "New Zealand", "C. Wood", 70),
    ]
    out = goals_from_events(events, "Iran", "New Zealand")
    assert out == [
        {"minute": 32, "side": "home", "player": "R. Rezaeian", "type": "goal"},
        {"minute": 70, "side": "away", "player": "C. Wood", "type": "penalty"},
    ]


def test_own_goal_is_credited_to_the_opponent():
    # Player from the home team scores an own goal -> counts for the AWAY side.
    out = goals_from_events([_event("Own Goal", "Iran", "Defender X", 18)],
                            "Iran", "New Zealand")
    assert out == [{"minute": 18, "side": "away", "player": "Defender X", "type": "own_goal"}]


def test_non_goal_and_missed_penalty_events_ignored():
    events = [
        _event("Yellow Card", "Iran", "Y", 10, etype="Card"),
        _event("Missed Penalty", "Iran", "Z", 22),
    ]
    assert goals_from_events(events, "Iran", "New Zealand") == []


def test_unknown_team_event_is_skipped_and_missing_player_defaulted():
    events = [
        _event("Normal Goal", "Some Other Team", "P", 5),
        {"type": "Goal", "detail": "Normal Goal", "team": {"name": "Iran"},
         "player": {}, "time": {"elapsed": 60}},
    ]
    out = goals_from_events(events, "Iran", "New Zealand")
    assert out == [{"minute": 60, "side": "home", "player": "Unknown", "type": "goal"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest pipeline/ingest/api_football_test.py -q -k goals_from_events`
Expected: FAIL with `ImportError: cannot import name 'goals_from_events'`.

- [ ] **Step 3: Implement `goals_from_events`**

In `pipeline/ingest/api_football.py`, after the `_SHOOTOUT` constant block (after line ~39), add:

```python
# api-sports goal-event detail -> our scorer type. Other details (e.g.
# "Missed Penalty") and non-Goal events are ignored.
_GOAL_DETAIL = {"Normal Goal": "goal", "Penalty": "penalty", "Own Goal": "own_goal"}
```

And at the end of the file add:

```python
def goals_from_events(events: list[dict], home_name: str, away_name: str) -> list[dict]:
    """Translate api-sports /fixtures/events into scorer dicts in our home/away
    orientation. Own goals are credited to the opponent of the scoring player's
    team. Non-goal events and unknown teams are skipped."""
    out: list[dict] = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "Goal":
            continue
        gtype = _GOAL_DETAIL.get(e.get("detail"))
        if gtype is None:
            continue
        team = (e.get("team") or {}).get("name")
        if team == home_name:
            side = "home"
        elif team == away_name:
            side = "away"
        else:
            continue
        if gtype == "own_goal":
            side = "away" if side == "home" else "home"
        out.append({
            "minute": (e.get("time") or {}).get("elapsed"),
            "side": side,
            "player": (e.get("player") or {}).get("name") or "Unknown",
            "type": gtype,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest pipeline/ingest/api_football_test.py -q -k goals_from_events`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/api_football_test.py
git commit -m "feat(live): translate api-sports goal events to scorer dicts"
```

---

### Task 3: `fetch_events` + `attach_scorers` (on-goal-change enrichment)

**Files:**
- Modify: `pipeline/ingest/api_football.py`
- Test: `pipeline/ingest/api_football_test.py`

- [ ] **Step 1: Add `_fixture_id` to feed items (needed to fetch events)**

In `pipeline/ingest/api_football.py`, inside `_to_item`, just before `return item`, add:

```python
    item["_fixture_id"] = (fx.get("fixture") or {}).get("id")
```

- [ ] **Step 2: Write the failing test for `attach_scorers`**

Append to `pipeline/ingest/api_football_test.py`:

```python
def test_attach_scorers_fetches_only_when_goal_total_changed(db_session, monkeypatch):
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    # A live fixture, Mexico 1-0 South Africa, fixture id 777.
    feed = to_feed([_fixture("2H", elapsed=55, gh=1, ga=0)])
    feed[0]["_fixture_id"] = 777

    calls = {"n": 0}
    def fake_events(key, fid, timeout=15.0):
        calls["n"] += 1
        return [_event("Normal Goal", "Mexico", "R. Jimenez", 30)]
    monkeypatch.setattr(af, "fetch_events", fake_events)

    af.attach_scorers(db_session, feed, "dummy-key")
    assert calls["n"] == 1
    assert feed[0]["scorers"] == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest pipeline/ingest/api_football_test.py -q -k attach_scorers`
Expected: FAIL with `AttributeError`/`ImportError` (`attach_scorers` / `fetch_events` missing).

- [ ] **Step 4: Implement `fetch_events` and `attach_scorers`**

In `pipeline/ingest/api_football.py`, after `fetch_fixtures`, add:

```python
def fetch_events(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw event list for one fixture from api-sports.io."""
    resp = requests.get(
        f"{BASE_URL}/fixtures/events",
        headers={"x-apisports-key": api_key},
        params={"fixture": fixture_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football events errors: %s", data["errors"])
    return data.get("response") or []
```

At the end of the file, add:

```python
# Statuses where new goals can have happened and scorers are worth fetching.
_SCORABLE = frozenset({"IN_PLAY", "PAUSED", "FINISHED"})


def attach_scorers(db, feed: list[dict], api_key: str) -> list[dict]:
    """Enrich feed items with a `scorers` list, fetching /fixtures/events ONLY
    for in-play/finished fixtures whose goal total differs from what's stored
    (so events are fetched ~once per goal, not every refresh)."""
    from pipeline.ingest.live_scores import _index_by_pair
    from pipeline.team_mapping import normalize_team_name

    index = _index_by_pair(db)
    for item in feed:
        if item.get("status") not in _SCORABLE:
            continue
        fid = item.get("_fixture_id")
        if fid is None:
            continue
        home, away = item["homeTeam"]["name"], item["awayTeam"]["name"]
        match = index.get(frozenset((normalize_team_name(home), normalize_team_name(away))))
        if match is None:
            continue
        ft = item["score"].get("fullTime") or {}
        total = (ft.get("home") or 0) + (ft.get("away") or 0)
        stored = len(match.goal_events) if match.goal_events is not None else -1
        if stored != total:
            item["scorers"] = goals_from_events(fetch_events(api_key, fid), home, away)
    return feed
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest pipeline/ingest/api_football_test.py -q -k attach_scorers`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/api_football_test.py
git commit -m "feat(live): fetch goal events on score change (attach_scorers)"
```

---

### Task 4: `update_live_scores` stores `scorers` into `goal_events`

**Files:**
- Modify: `pipeline/ingest/live_scores.py` (in `update_live_scores`, near line 259)
- Test: `pipeline/ingest/live_scores_test.py`

- [ ] **Step 1: Write the failing test**

Append to `pipeline/ingest/live_scores_test.py`:

```python
def test_scorers_field_is_stored_as_goal_events(db_session):
    load_structure(db_session)
    feed = _feed("IN_PLAY", home=1, away=0, minute=30)
    feed[0]["scorers"] = [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]
    update_live_scores(db_session, feed)
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.goal_events == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]


def test_absent_scorers_leaves_goal_events_untouched(db_session):
    load_structure(db_session)
    update_live_scores(db_session, _feed("IN_PLAY", home=1, away=0, minute=30))
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.goal_events is None  # football_data feed carries no scorers
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest pipeline/ingest/live_scores_test.py -q -k goal_events`
Expected: FAIL — `test_scorers_field_is_stored_as_goal_events` fails (`m.goal_events is None`, not the list).

- [ ] **Step 3: Implement storage in the main update path**

In `pipeline/ingest/live_scores.py`, in `update_live_scores`, find (near line 259):

```python
        if incoming_lu is not None:
            match.provider_last_updated = incoming_lu
        updated += 1
```

Insert directly above that block:

```python
        if "scorers" in am:
            match.goal_events = am["scorers"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest pipeline/ingest/live_scores_test.py -q -k goal_events`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/live_scores.py pipeline/ingest/live_scores_test.py
git commit -m "feat(live): persist scorers feed field into match.goal_events"
```

---

### Task 5: Wire `attach_scorers` into the `api_football` refresh path

**Files:**
- Modify: `pipeline/ingest/live_scores.py` (`refresh_live`, the `api_football` branch)
- Test: `pipeline/ingest/api_football_test.py`

- [ ] **Step 1: Write the failing test**

Append to `pipeline/ingest/api_football_test.py`:

```python
def test_refresh_live_api_football_stores_scorers(db_session, monkeypatch):
    from app.config import settings as app_settings
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    monkeypatch.setattr(app_settings, "live_provider", "api_football")
    monkeypatch.setattr(app_settings, "api_football_api_key", "dummy-key")
    monkeypatch.setattr(af, "fetch_fixtures",
                        lambda *a, **k: [_fixture("2H", elapsed=55, gh=1, ga=0)])
    monkeypatch.setattr(af, "fetch_events",
                        lambda *a, **k: [_event("Normal Goal", "Mexico", "R. Jimenez", 30)])

    refresh_live(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    assert m.goal_events == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest pipeline/ingest/api_football_test.py -q -k api_football_stores_scorers`
Expected: FAIL (`m.goal_events is None` — refresh_live doesn't enrich yet).

- [ ] **Step 3: Implement the wiring**

In `pipeline/ingest/live_scores.py`, in `refresh_live`, replace the `api_football` branch:

```python
        elif provider == "api_football":
            from pipeline.ingest.api_football import fetch_fixtures, to_feed
            api_matches = to_feed(fetch_fixtures(
                key, settings.api_football_league, settings.api_football_season))
```

with:

```python
        elif provider == "api_football":
            from pipeline.ingest.api_football import fetch_fixtures, to_feed, attach_scorers
            api_matches = attach_scorers(db, to_feed(fetch_fixtures(
                key, settings.api_football_league, settings.api_football_season)), key)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest pipeline/ingest/api_football_test.py -q -k api_football_stores_scorers`
Expected: PASS.

- [ ] **Step 5: Run the full ingest suite (no regressions)**

Run: `python -m pytest pipeline/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/live_scores.py pipeline/ingest/api_football_test.py
git commit -m "feat(live): enrich api_football refresh with goal scorers"
```

---

### Task 6: Serialize `goal_events` on `MatchSummaryOut`

**Files:**
- Modify: `backend/app/schemas/__init__.py` (near `MatchSummaryOut`, line 84-106)
- Modify: `backend/app/serializers.py` (`match_to_summary`, after line 153)
- Test: `backend/tests/` (new `backend/tests/test_goal_events_serializer.py`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_goal_events_serializer.py`:

```python
from app.models import Match, Team
from app.serializers import match_to_summary
from pipeline.ingest.wc26_structure import load_structure


def test_match_to_summary_includes_goal_events(db_session):
    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    m.status = "in_play"
    m.score_home, m.score_away = 1, 0
    m.goal_events = [{"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]
    db_session.commit()

    out = match_to_summary(db_session, m)
    assert len(out.goal_events) == 1
    assert out.goal_events[0].player == "R. Jimenez"
    assert out.goal_events[0].side == "home"
    assert out.goal_events[0].minute == 30


def test_match_to_summary_goal_events_defaults_empty(db_session):
    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    out = match_to_summary(db_session, m)
    assert out.goal_events == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest backend/tests/test_goal_events_serializer.py -q`
Expected: FAIL (`MatchSummaryOut` has no `goal_events`).

- [ ] **Step 3: Add the schema**

In `backend/app/schemas/__init__.py`, immediately before `class MatchSummaryOut` (line 84), add:

```python
class GoalEventOut(BaseModel):
    minute: int | None
    side: str          # "home" | "away"
    player: str
    type: str          # "goal" | "penalty" | "own_goal"
```

Then inside `MatchSummaryOut`, after the `penalty_away` line (line 100), add:

```python
    goal_events: list[GoalEventOut] = []
```

- [ ] **Step 4: Populate it in the serializer**

In `backend/app/serializers.py`, in the `match_to_summary` return (after `penalty_away=match.penalty_away,`, line 153), add:

```python
        goal_events=[schemas.GoalEventOut(**g) for g in (match.goal_events or [])],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest backend/tests/test_goal_events_serializer.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/serializers.py backend/tests/test_goal_events_serializer.py
git commit -m "feat(live): expose goal_events on MatchSummaryOut"
```

---

### Task 7: Frontend types + `MatchScoreboard` rendering

**Files:**
- Modify: `frontend/lib/types.ts` (after `LivePeriod`, before `MatchSummary`; and inside `MatchSummary`)
- Modify: `frontend/components/MatchScoreboard.tsx`
- Test: `frontend/components/__tests__/scorers.test.tsx` (new)

- [ ] **Step 1: Add the type**

In `frontend/lib/types.ts`, after the `LivePeriod` type (line 65), add:

```typescript
export interface GoalEvent {
  minute: number | null;
  side: "home" | "away";
  player: string;
  type: "goal" | "penalty" | "own_goal";
}
```

Then inside `interface MatchSummary`, after `penalty_away: number | null;` (line 83), add:

```typescript
  goal_events: GoalEvent[];
```

- [ ] **Step 2: Write the failing test**

Create `frontend/components/__tests__/scorers.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import * as api from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

// MatchScoreboard polls getMatchSummary on mount (useFetch fetches even when
// seeded), so mock the api module — mirrors predictedVsActual.test.tsx.
jest.mock("@/lib/api");
const mockGetMatchSummary = api.getMatchSummary as jest.Mock;

const summary: MatchSummary = {
  match_id: 1, stage: "group", group: "Group A", kickoff_utc: null,
  venue: null, venue_city: null, venue_country: null, is_neutral: true,
  status: "finished", score_home: 2, score_away: 1, minute: null, period: null,
  injury_time: null, penalty_home: null, penalty_away: null,
  teams: { home: "Mexico", away: "South Africa" },
  predicted_winner: "Mexico", probabilities: null, predicted_score: null, confidence: null,
  goal_events: [
    { minute: 30, side: "home", player: "R. Jimenez", type: "goal" },
    { minute: 70, side: "away", player: "P. Kgatlana", type: "penalty" },
  ],
};

beforeEach(() => mockGetMatchSummary.mockResolvedValue(summary));

test("renders goalscorers under the score", () => {
  render(
    <MatchScoreboard
      matchId={1} home="Mexico" away="South Africa"
      probabilities={{ home_win: 0.6, draw: 0.2, away_win: 0.2 }}
      predicted={{ home: 2, away: 0, probability: 0.2 }}
      initialSummary={summary}
    />,
  );
  expect(screen.getByText(/R\. Jimenez/)).toBeInTheDocument();
  expect(screen.getByText(/P\. Kgatlana/)).toBeInTheDocument();
  expect(screen.getByText(/\(pen\)/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test -- scorers`
Expected: FAIL (scorers not rendered).

- [ ] **Step 4: Implement rendering**

In `frontend/components/MatchScoreboard.tsx`, add the import at the top (extend line 9):

```typescript
import type { MatchSummary, PredictedScore, Probabilities, GoalEvent } from "@/lib/types";
```

Add this helper at the bottom of the file (after `TeamHead`):

```tsx
function formatScorer(g: GoalEvent): string {
  const annot = g.type === "penalty" ? " (pen)" : g.type === "own_goal" ? " (OG)" : "";
  const min = g.minute != null ? ` ${g.minute}'` : "";
  return `${g.player}${min}${annot}`;
}
```

Then, inside the returned JSX, directly after the closing `</div>` of the scoreboard grid (after line 90, the `<TeamHead ... />` then `</div>`), insert:

```tsx
      {hasActual && summary!.goal_events.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 text-[11px] text-muted sm:text-xs">
          <ul className="space-y-0.5 text-right">
            {summary!.goal_events.filter((g) => g.side === "home").map((g, i) => (
              <li key={`h-${i}`} className="tabular-nums">{formatScorer(g)}</li>
            ))}
          </ul>
          <ul className="space-y-0.5 text-left">
            {summary!.goal_events.filter((g) => g.side === "away").map((g, i) => (
              <li key={`a-${i}`} className="tabular-nums">{formatScorer(g)}</li>
            ))}
          </ul>
        </div>
      )}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npm test -- scorers`
Expected: PASS.

- [ ] **Step 6: Typecheck + commit**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

```bash
git add frontend/lib/types.ts frontend/components/MatchScoreboard.tsx frontend/components/__tests__/scorers.test.tsx
git commit -m "feat(live): render goalscorers under the score on the match page"
```

---

### Task 8: Full verification + live smoke test

**Files:** none (verification only)

- [ ] **Step 1: Full Python suite**

Run: `python -m pytest -q`
Expected: PASS (all green).

- [ ] **Step 2: Full frontend suite + typecheck**

Run: `cd frontend && npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 2b: Existing MatchSummary fixtures still typecheck**

Other tests/fixtures that build a `MatchSummary` object now need `goal_events`. If `npm run typecheck` reports missing `goal_events` in any fixture, add `goal_events: []` to it. Re-run until clean.

- [ ] **Step 3: Live smoke test against the real api-sports Pro key**

With `LIVE_PROVIDER=api_football` and a valid `API_FOOTBALL_API_KEY` in `.env`, run from repo root:

```bash
PYTHONPATH=backend:. python -c "
from app.db import engine
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Match, Team
from app.serializers import match_to_summary
from pipeline.ingest.live_scores import refresh_live
conn=engine.connect(); tx=conn.begin()
db=Session(bind=conn, join_transaction_mode='create_savepoint')
try:
    refresh_live(db)
    for m in db.query(Match).filter(Match.goal_events.isnot(None)).limit(3):
        print(match_to_summary(db, m).teams, '->',
              [(g.player, g.minute, g.type) for g in match_to_summary(db, m).goal_events])
finally:
    tx.rollback(); conn.close()
"
```

Expected: real fixtures print their scorers (e.g. `('Iran','New Zealand') -> [('R. Rezaeian',32,'goal'), ...]`). Transaction is rolled back — no DB changes.

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch` to merge `feat/goalscorers` and decide on push/deploy.

---

## Notes for the implementer
- **Run all commands from the repo root** unless a step says `cd frontend`/`cd backend`.
- The `football_data` provider must remain a pure no-op for scorers — never raise if events are absent.
- Keep the scorer dict shape identical across translator, storage, serializer, and TS type: `{minute, side, player, type}`.
- API budget: `attach_scorers` calls `/fixtures/events` only when goal totals change — do not "simplify" it into fetching every refresh.
