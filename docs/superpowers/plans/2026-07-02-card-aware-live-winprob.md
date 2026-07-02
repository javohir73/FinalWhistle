# Card-Aware Live Win Probability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest yellow/red card events from the api-football feed, adjust the in-play win probability for them (score-state-aware red multipliers; yellows via second-yellow risk only), and surface cards in the match UI.

**Architecture:** Cards ride the exact pipeline goals already use: api-sports `/fixtures/events` → parser in `pipeline/ingest/api_football.py` → `update_live_scores` → new `Match.card_events` JSON column → serializer derives per-side counts → `live_winprob` scales the remaining-time goal rates → `MatchSummaryOut.card_events` → frontend scoreboard. Spec: `docs/superpowers/specs/2026-07-02-card-aware-live-winprob-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), stdlib-only live model, pytest, Next.js + Jest/RTL (frontend).

## Global Constraints

- The serving read path never imports/executes `ml/` (PRD §7) — the card adjustment is stdlib math inside `backend/app/live_winprob.py`.
- Zero cards ⇒ output bit-identical to the current model (kickoff "no twitch" invariant).
- Red factors `(own×, opp×)` by carded team's score state: leading `(0.60, 1.05)`, level `(0.75, 1.10)`, trailing `(0.75, 1.15)`; max 3 reds counted per side.
- Yellows: `p = 0.04 × (minutes_remaining/90)` per ACTIVE booking, blending both rates toward the red factors; max 5 counted per side.
- Card event dict shape (storage + API): `{minute, side: "home"|"away", player, type: "yellow"|"red"}`.
- A second yellow arrives from the feed as a single `detail == "Red Card"` event.
- The `football_data` provider carries no cards: `card_events` stays `None` and everything must treat that as zero cards.
- Python tests run from repo root: `.venv/bin/python -m pytest <path> -v`. Frontend: `cd frontend && npx jest <path>`.
- Commit after every green test cycle.

---

### Task 1: Card factors in the live model (`live_winprob.py`)

**Files:**
- Modify: `backend/app/live_winprob.py`
- Test: `backend/tests/test_live_winprob.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `live_win_probabilities(..., red_home=0, red_away=0, yellow_home=0, yellow_away=0)`, `live_probabilities_for_match(..., red_home=0, red_away=0, yellow_home=0, yellow_away=0)`, `_card_factors(score_home, score_away, red_home, red_away, yellow_home, yellow_away, frac) -> tuple[float, float]`, module constants `RED_FACTORS`, `MAX_REDS_COUNTED`, `SECOND_YELLOW_HAZARD`, `MAX_YELLOWS_COUNTED`. Task 5's serializer threads counts through `live_probabilities_for_match`.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_live_winprob.py`:

```python
# --- card adjustments ---------------------------------------------------------

from app.live_winprob import _card_factors


def test_zero_cards_is_bit_identical_to_unadjusted():
    base = live_win_probabilities(1, 0, 1.6, 1.0, 30.0, rho=-0.06)
    carded = live_win_probabilities(1, 0, 1.6, 1.0, 30.0, rho=-0.06,
                                    red_home=0, red_away=0,
                                    yellow_home=0, yellow_away=0)
    assert carded == base


def test_red_card_lowers_carded_team_and_lifts_opponent():
    base = live_win_probabilities(0, 0, 1.4, 1.2, 60.0)
    carded = live_win_probabilities(0, 0, 1.4, 1.2, 60.0, red_home=1)
    assert carded[0] < base[0]
    assert carded[2] > base[2]
    assert abs(sum(carded) - 1.0) < 1e-9


def test_away_red_mirrors_home():
    base = live_win_probabilities(0, 0, 1.4, 1.2, 60.0)
    carded = live_win_probabilities(0, 0, 1.4, 1.2, 60.0, red_away=1)
    assert carded[2] < base[2]
    assert carded[0] > base[0]


def test_card_factors_by_score_state():
    # Home leading: bunker — own rate cut hard, opponent boost small.
    assert _card_factors(1, 0, 1, 0, 0, 0, 1.0) == (0.60, 1.05)
    # Home trailing: must chase — opponent counter boost is largest.
    assert _card_factors(0, 1, 1, 0, 0, 0, 1.0) == (0.75, 1.15)
    # Level: standard mild effect.
    assert _card_factors(0, 0, 1, 0, 0, 0, 1.0) == (0.75, 1.10)
    # Away-side red at level mirrors onto the other factor.
    assert _card_factors(0, 0, 0, 1, 0, 0, 1.0) == (1.10, 0.75)


def test_reds_compound_and_cap_at_three():
    fh, fa = _card_factors(0, 0, 2, 0, 0, 0, 1.0)
    assert abs(fh - 0.75 ** 2) < 1e-12 and abs(fa - 1.10 ** 2) < 1e-12
    fh5, _ = _card_factors(0, 0, 5, 0, 0, 0, 1.0)
    fh3, _ = _card_factors(0, 0, 3, 0, 0, 0, 1.0)
    assert fh5 == fh3  # counted reds cap at 3


def test_yellow_effect_small_and_decays_with_clock():
    fh_half, fa_half = _card_factors(0, 0, 0, 0, 2, 0, 0.5)  # 2 bookings, 45' left
    assert 0.98 < fh_half < 1.0     # about a 1% shift — negligible by design
    assert 1.0 < fa_half < 1.01
    assert _card_factors(0, 0, 0, 0, 2, 0, 0.0) == (1.0, 1.0)  # gone at FT


def test_for_match_threads_card_counts():
    without = live_probabilities_for_match(
        status="in_play", score_home=0, score_away=0, minute=30,
        period="first_half", lam_home=1.4, lam_away=1.2, rho=0.0)
    with_red = live_probabilities_for_match(
        status="in_play", score_home=0, score_away=0, minute=30,
        period="first_half", lam_home=1.4, lam_away=1.2, rho=0.0, red_home=1)
    assert with_red[0] < without[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_live_winprob.py -v`
Expected: FAIL — `ImportError: cannot import name '_card_factors'`.

- [ ] **Step 3: Implement.** In `backend/app/live_winprob.py`, insert after the `_dixon_coles_tau` function:

```python
# --- Card adjustments ----------------------------------------------------------
# A sending-off changes both teams' scoring rates for the minutes REMAINING.
# Factors are (own rate ×, opponent rate ×) per red card, chosen by the carded
# team's CURRENT score situation — the model is recomputed per request, so the
# state re-derives itself whenever the score changes. Values sit at the mild end
# of published 10v11 estimates: a leading team bunkers (its goals dry up but it
# concedes barely more, keeping the hold likely), a trailing team must chase
# into counter-attacks. The football_data provider has no card feed — counts
# stay 0 there and this whole block is a no-op.
RED_FACTORS: dict[str, tuple[float, float]] = {
    "leading": (0.60, 1.05),
    "level": (0.75, 1.10),
    "trailing": (0.75, 1.15),
}
#: Reds beyond this aren't counted (7 players = abandonment; 3 is already farce).
MAX_REDS_COUNTED = 3
#: Chance an ACTIVE booking becomes a second yellow over a full 90 remaining.
#: Deliberately small — a yellow only matters as future-red risk (weak evidence,
#: by design; see the 2026-07-02 card-aware spec).
SECOND_YELLOW_HAZARD = 0.04
MAX_YELLOWS_COUNTED = 5


def _score_state(own: int, opp: int) -> str:
    if own > opp:
        return "leading"
    if own < opp:
        return "trailing"
    return "level"


def _card_factors(
    score_home: int,
    score_away: int,
    red_home: int,
    red_away: int,
    yellow_home: int,
    yellow_away: int,
    frac: float,
) -> tuple[float, float]:
    """Multipliers (home, away) on the remaining-time goal rates for the current
    card situation. Reds apply their score-state factors in full and compound;
    each active yellow blends both rates toward those factors with weight
    p = hazard × fraction-of-90-left, so booking risk decays to zero at full
    time. No cards -> (1.0, 1.0) exactly."""
    f_home = f_away = 1.0
    p = SECOND_YELLOW_HAZARD * max(0.0, min(1.0, frac))

    own_f, opp_f = RED_FACTORS[_score_state(score_home, score_away)]
    n_red = min(max(red_home, 0), MAX_REDS_COUNTED)
    n_yel = min(max(yellow_home, 0), MAX_YELLOWS_COUNTED)
    f_home *= own_f ** n_red * ((1.0 - p) + p * own_f) ** n_yel
    f_away *= opp_f ** n_red * ((1.0 - p) + p * opp_f) ** n_yel

    own_f, opp_f = RED_FACTORS[_score_state(score_away, score_home)]
    n_red = min(max(red_away, 0), MAX_REDS_COUNTED)
    n_yel = min(max(yellow_away, 0), MAX_YELLOWS_COUNTED)
    f_away *= own_f ** n_red * ((1.0 - p) + p * own_f) ** n_yel
    f_home *= opp_f ** n_red * ((1.0 - p) + p * opp_f) ** n_yel

    return f_home, f_away
```

Change `live_win_probabilities`'s signature and rate computation:

```python
def live_win_probabilities(
    score_home: int,
    score_away: int,
    lam_home: float,
    lam_away: float,
    minutes_remaining: float,
    rho: float = 0.0,
    regulation: float = REGULATION_MINUTES,
    max_extra_goals: int = 10,
    red_home: int = 0,
    red_away: int = 0,
    yellow_home: int = 0,
    yellow_away: int = 0,
) -> Probs:
```

and immediately after `lam_a_rem = max(0.0, lam_away) * frac` add:

```python
    f_home, f_away = _card_factors(
        score_home, score_away, red_home, red_away, yellow_home, yellow_away, frac
    )
    lam_h_rem *= f_home
    lam_a_rem *= f_away
```

Change `live_probabilities_for_match` to accept and thread the counts:

```python
def live_probabilities_for_match(
    status: str | None,
    score_home: int | None,
    score_away: int | None,
    minute: int | None,
    period: str | None,
    lam_home: float | None,
    lam_away: float | None,
    rho: float | None = 0.0,
    red_home: int = 0,
    red_away: int = 0,
    yellow_home: int = 0,
    yellow_away: int = 0,
) -> Probs | None:
```

and its return becomes:

```python
    return live_win_probabilities(
        score_home, score_away, lam_home, lam_away, remaining, rho=rho or 0.0,
        red_home=red_home, red_away=red_away,
        yellow_home=yellow_home, yellow_away=yellow_away,
    )
```

Also append one line to each docstring noting the card counts (e.g. "Card counts scale the remaining-time rates — see `_card_factors`.").

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_live_winprob.py -v`
Expected: PASS (all — including every pre-existing test in the file, which pins the zero-card regression).

- [ ] **Step 5: Commit**

```bash
git add backend/app/live_winprob.py backend/tests/test_live_winprob.py
git commit -m "feat(live): score-state-aware card adjustment in live win probability"
```

---

### Task 2: Card event parser (`cards_from_events`)

**Files:**
- Modify: `pipeline/ingest/api_football.py`
- Test: `pipeline/ingest/api_football_test.py` (append)

**Interfaces:**
- Consumes: the existing `_event(detail, team, player, minute, etype="Goal")` test helper; api-sports event dicts (`{type, detail, team.name, player.name, time.elapsed}`).
- Produces: `cards_from_events(events, home_name, away_name) -> list[dict]` emitting `{minute, side, player, type: "yellow"|"red"}`; module constant `_CARD_DETAIL`. Task 3 calls it from `attach_events`.

- [ ] **Step 1: Write the failing tests** — append to `pipeline/ingest/api_football_test.py` (also add `cards_from_events` to the existing `from pipeline.ingest.api_football import to_feed` import):

```python
def test_cards_from_events_yellow_red_and_sides():
    events = [
        _event("Yellow Card", "Iran", "S. Moharrami", 28, etype="Card"),
        _event("Red Card", "New Zealand", "J. Bell", 55, etype="Card"),
    ]
    out = cards_from_events(events, "Iran", "New Zealand")
    assert out == [
        {"minute": 28, "side": "home", "player": "S. Moharrami", "type": "yellow"},
        {"minute": 55, "side": "away", "player": "J. Bell", "type": "red"},
    ]


def test_cards_from_events_skips_goals_unknown_details_and_teams():
    events = [
        _event("Normal Goal", "Iran", "R. Rezaeian", 32),               # not a card
        _event("Card upgrade", "Iran", "X", 40, etype="Card"),          # unknown detail
        _event("Yellow Card", "Brazil", "Y", 50, etype="Card"),         # unknown team
        "garbage",                                                       # malformed
    ]
    assert cards_from_events(events, "Iran", "New Zealand") == []


def test_cards_from_events_defaults_missing_player():
    e = _event("Red Card", "Iran", None, 77, etype="Card")
    e["player"] = {}
    assert cards_from_events([e], "Iran", "New Zealand") == [
        {"minute": 77, "side": "home", "player": "Unknown", "type": "red"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/ingest/api_football_test.py -v`
Expected: FAIL — `ImportError: cannot import name 'cards_from_events'`.

- [ ] **Step 3: Implement.** In `pipeline/ingest/api_football.py`, next to `_GOAL_DETAIL` add:

```python
# api-sports card-event detail -> our card type. A second yellow arrives from
# the feed as a single "Red Card" event. Other details are ignored.
_CARD_DETAIL = {"Yellow Card": "yellow", "Red Card": "red"}
```

and after `goals_from_events` add:

```python
def cards_from_events(events: list[dict], home_name: str, away_name: str) -> list[dict]:
    """Translate api-sports /fixtures/events into card dicts in our home/away
    orientation. Non-Card events, unknown details and unknown teams are skipped
    (same posture as goals_from_events)."""
    out: list[dict] = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "Card":
            continue
        ctype = _CARD_DETAIL.get(e.get("detail"))
        if ctype is None:
            continue
        team = (e.get("team") or {}).get("name")
        if team == home_name:
            side = "home"
        elif team == away_name:
            side = "away"
        else:
            continue
        out.append({
            "minute": (e.get("time") or {}).get("elapsed"),
            "side": side,
            "player": (e.get("player") or {}).get("name") or "Unknown",
            "type": ctype,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/ingest/api_football_test.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/api_football_test.py
git commit -m "feat(ingest): parse card events from api-football fixture events"
```

---

### Task 3: Staleness-triggered events fetch (`attach_scorers` → `attach_events`)

**Files:**
- Modify: `pipeline/ingest/api_football.py` (rename + trigger), `pipeline/ingest/live_scores.py:428-430` (call site), `backend/app/config.py` (new setting)
- Test: `pipeline/ingest/api_football_test.py`

**Interfaces:**
- Consumes: `cards_from_events` (Task 2); `settings.events_refetch_seconds` (added here).
- Produces: `attach_events(db, feed, api_key) -> list[dict]` setting BOTH `item["scorers"]` and `item["cards"]`; module state `_last_events_fetch: dict[int, float]`. `attach_scorers` no longer exists — call sites updated in this task. Task 4 persists `item["cards"]`.

- [ ] **Step 1: Write the failing tests** — append to `pipeline/ingest/api_football_test.py`:

```python
def test_attach_events_refetches_when_stale_without_goal_change(db_session, monkeypatch):
    from app.config import settings as app_settings
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    # Neutralize the goal-count trigger: 0 feed goals == 0 stored goal events.
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    m.goal_events = []
    db_session.commit()

    calls = {"n": 0}
    def fake_events(key, fid, timeout=15.0):
        calls["n"] += 1
        return [_event("Red Card", "Mexico", "J. Vasquez", 50, etype="Card")]
    monkeypatch.setattr(af, "fetch_events", fake_events)
    monkeypatch.setattr(app_settings, "events_refetch_seconds", 180)
    af._last_events_fetch.clear()

    feed = to_feed([_fixture("2H", elapsed=55, gh=0, ga=0)])
    feed[0]["_fixture_id"] = 778
    af.attach_events(db_session, feed, "dummy-key")   # never fetched before -> stale
    assert calls["n"] == 1
    assert feed[0]["cards"] == [
        {"minute": 50, "side": "home", "player": "J. Vasquez", "type": "red"}]
    assert feed[0]["scorers"] == []

    feed2 = to_feed([_fixture("2H", elapsed=56, gh=0, ga=0)])
    feed2[0]["_fixture_id"] = 778
    af.attach_events(db_session, feed2, "dummy-key")  # fresh -> no fetch
    assert calls["n"] == 1
    assert "cards" not in feed2[0]

    af._last_events_fetch[778] -= 9999                # age past the cutoff
    af.attach_events(db_session, feed2, "dummy-key")  # stale again -> fetch
    assert calls["n"] == 2


def test_attach_events_finished_fixture_keeps_goal_count_trigger_only(db_session, monkeypatch):
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    m.goal_events = []
    db_session.commit()

    calls = {"n": 0}
    monkeypatch.setattr(af, "fetch_events",
                        lambda *args, **kw: calls.__setitem__("n", calls["n"] + 1) or [])
    af._last_events_fetch.clear()

    feed = to_feed([_fixture("FT", gh=0, ga=0)])
    feed[0]["_fixture_id"] = 779
    af.attach_events(db_session, feed, "dummy-key")
    assert calls["n"] == 0  # finished + goal totals agree: no staleness refetch
```

Also update the two existing tests that call the old name: in
`test_attach_scorers_fetches_only_when_goal_total_changed` change
`af.attach_scorers(db_session, feed, "dummy-key")` to
`af.attach_events(db_session, feed, "dummy-key")`, and add
`af._last_events_fetch.clear()` immediately before that call (its fixture id
777 must start untracked so the assertion `calls["n"] == 1` stays exact).
`test_refresh_live_api_football_stores_scorers` needs no edit (it goes through
`refresh_live`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/ingest/api_football_test.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'attach_events'` (and `_last_events_fetch`).

- [ ] **Step 3: Implement.**

(a) `backend/app/config.py` — after the `live_provider` field add:

```python
    # In-play events refetch cadence (seconds). Cards can arrive without a goal,
    # so live fixtures refetch /fixtures/events when the last fetch is older
    # than this. ~20 calls per live match hour on the default; the goal-count
    # trigger still fires immediately on any goal.
    events_refetch_seconds: int = 180
```

(b) `pipeline/ingest/api_football.py` — add `import time` to the imports; replace `attach_scorers` (keep the `_SCORABLE` constant above it) with:

```python
#: Feed statuses where the match is live and a card could arrive without a goal.
_LIVE_STATUSES = frozenset({"IN_PLAY", "PAUSED"})

#: fixture id -> time.monotonic() of the last /fixtures/events fetch. In-process
#: on purpose (mirrors live_refresh's module state): a worker restart just
#: refetches once per fixture.
_last_events_fetch: dict[int, float] = {}


def attach_events(db, feed: list[dict], api_key: str) -> list[dict]:
    """Enrich feed items with `scorers` and `cards` from /fixtures/events.

    Fetches when (a) the fixture's goal total differs from what's stored —
    ~once per goal, and the only trigger for finished fixtures — or (b) the
    fixture is live and the last fetch is older than
    settings.events_refetch_seconds, so a red card with no goal around it is
    still seen promptly."""
    from app.config import settings
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
        last = _last_events_fetch.get(fid)
        stale = item.get("status") in _LIVE_STATUSES and (
            last is None or time.monotonic() - last >= settings.events_refetch_seconds
        )
        if stored != total or stale:
            events = fetch_events(api_key, fid)
            _last_events_fetch[fid] = time.monotonic()
            item["scorers"] = goals_from_events(events, home, away)
            item["cards"] = cards_from_events(events, home, away)
    return feed
```

(c) `pipeline/ingest/live_scores.py` `refresh_live` (currently lines 428-430) — update the import and call:

```python
            from pipeline.ingest.api_football import fetch_fixtures, to_feed, attach_events
            api_matches = attach_events(db, to_feed(fetch_fixtures(
                key, settings.api_football_league, settings.api_football_season)), key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/ingest/api_football_test.py pipeline/ingest/live_scores_test.py backend/tests/test_live_refresh.py -v`
Expected: PASS (call-site and refresh paths included).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/live_scores.py backend/app/config.py pipeline/ingest/api_football_test.py
git commit -m "feat(ingest): attach card events with staleness-triggered refetch for live fixtures"
```

---

### Task 4: `Match.card_events` column, migration, persistence

**Files:**
- Modify: `backend/app/models/__init__.py` (after `goal_events`, line ~126), `pipeline/ingest/live_scores.py` (after the `scorers` assignment, line ~394)
- Create: `backend/alembic/versions/d5e6f7a8b9c0_add_card_events.py`
- Test: `pipeline/ingest/api_football_test.py` (append)

**Interfaces:**
- Consumes: `item["cards"]` set by `attach_events` (Task 3).
- Produces: `Match.card_events: list | None` (JSON) — Task 5's serializer reads it. Migration head becomes `d5e6f7a8b9c0` (down_revision `c4d5e6f7a8b9`, the learning_chain_status head).

- [ ] **Step 1: Write the failing test** — append to `pipeline/ingest/api_football_test.py`:

```python
def test_refresh_live_api_football_stores_cards(db_session, monkeypatch):
    from app.config import settings as app_settings
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    monkeypatch.setattr(app_settings, "live_provider", "api_football")
    monkeypatch.setattr(app_settings, "api_football_api_key", "dummy-key")
    monkeypatch.setattr(af, "fetch_fixtures",
                        lambda *a, **k: [_fixture("2H", elapsed=55, gh=1, ga=0)])
    monkeypatch.setattr(af, "fetch_events", lambda *a, **k: [
        _event("Normal Goal", "Mexico", "R. Jimenez", 30),
        _event("Red Card", "South Africa", "T. Mokoena", 44, etype="Card"),
    ])
    af._last_events_fetch.clear()

    refresh_live(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    assert m.card_events == [
        {"minute": 44, "side": "away", "player": "T. Mokoena", "type": "red"}]
    assert m.goal_events == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]

    # A later refresh that fetches no events (goal totals agree, tracker fresh)
    # must not blank the stored cards.
    monkeypatch.setattr(af, "fetch_events", lambda *a, **k: [])
    refresh_live(db_session)
    db_session.refresh(m)
    assert m.card_events == [
        {"minute": 44, "side": "away", "player": "T. Mokoena", "type": "red"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/api_football_test.py::test_refresh_live_api_football_stores_cards -v`
Expected: FAIL — `Match` has no attribute `card_events`.

- [ ] **Step 3: Implement.**

(a) `backend/app/models/__init__.py` — directly under the `goal_events` column add:

```python
    # Card events, same pipeline as goal_events: ordered list of
    # {minute, side: "home"|"away", player, type: "yellow"|"red"}. A second
    # yellow arrives from the feed as a single "red" event. Populated by the
    # api_football provider only (football-data has no cards) — None means
    # "no card data", which every consumer treats as zero cards.
    card_events: Mapped[list | None] = mapped_column(JSON)
```

(b) `pipeline/ingest/live_scores.py` — in `update_live_scores`, directly under the `if "scorers" in am:` block add:

```python
        if "cards" in am:
            match.card_events = am["cards"]
```

(c) Create `backend/alembic/versions/d5e6f7a8b9c0_add_card_events.py`:

```python
"""add card_events JSON column to matches

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("card_events", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "card_events")
```

- [ ] **Step 4: Run tests + verify the migration chain has a single head**

Run: `.venv/bin/python -m pytest pipeline/ingest/api_football_test.py -v`
Expected: PASS.

Run: `cd backend && ../.venv/bin/alembic heads && cd ..`
Expected: exactly one head: `d5e6f7a8b9c0 (head)`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/d5e6f7a8b9c0_add_card_events.py pipeline/ingest/live_scores.py pipeline/ingest/api_football_test.py
git commit -m "feat(db): persist card events on matches (migration d5e6f7a8b9c0)"
```

---

### Task 5: Serializer counts + `card_events` on the summary schema

**Files:**
- Modify: `backend/app/schemas/__init__.py` (next to `GoalEventOut`, line ~107), `backend/app/serializers.py` (`match_to_summary`, line ~126)
- Test: `backend/tests/test_card_events_serializer.py` (create)

**Interfaces:**
- Consumes: `Match.card_events` (Task 4); `live_probabilities_for_match(..., red_home, red_away, yellow_home, yellow_away)` (Task 1).
- Produces: `schemas.CardEventOut {minute, side, player, type}`; `MatchSummaryOut.card_events: list[CardEventOut] = []`; `serializers._card_counts(card_events) -> dict` with keys `red_home, red_away, yellow_home, yellow_away`. Task 6's frontend consumes the `card_events` JSON field.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_card_events_serializer.py`:

```python
"""Card events on the match summary: exposure + live-model count threading."""
from app.models import Match, Prediction, Team
from app.serializers import _card_counts, match_to_summary
from pipeline.ingest.wc26_structure import load_structure


def _match(db_session) -> Match:
    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    return db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()


def test_card_counts_reds_and_active_yellows():
    events = [
        {"minute": 20, "side": "home", "player": "A", "type": "yellow"},
        {"minute": 50, "side": "home", "player": "A", "type": "red"},   # second yellow
        {"minute": 60, "side": "home", "player": "B", "type": "yellow"},
        {"minute": 70, "side": "away", "player": "C", "type": "red"},
    ]
    # A's booking is consumed by the sending-off: only B's yellow stays active.
    assert _card_counts(events) == {
        "red_home": 1, "red_away": 1, "yellow_home": 1, "yellow_away": 0}


def test_card_counts_none_and_malformed_are_zero():
    zero = {"red_home": 0, "red_away": 0, "yellow_home": 0, "yellow_away": 0}
    assert _card_counts(None) == zero
    assert _card_counts(["garbage", {"type": "red", "side": "bench"}]) == zero


def test_summary_exposes_card_events_and_red_moves_live_bar(db_session):
    m = _match(db_session)
    m.status = "in_play"
    m.score_home, m.score_away = 0, 0
    m.minute, m.period = 30, "first_half"
    db_session.add(Prediction(
        match_id=m.id, model_version="test",
        prob_home_win=0.5, prob_draw=0.3, prob_away_win=0.2,
        lambda_home=1.4, lambda_away=1.0, rho=-0.06,
    ))
    db_session.commit()
    base = match_to_summary(db_session, m).live_probabilities
    assert base is not None

    m.card_events = [
        {"minute": 25, "side": "home", "player": "J. Vasquez", "type": "red"}]
    db_session.commit()
    out = match_to_summary(db_session, m)
    assert out.card_events[0].player == "J. Vasquez"
    assert out.card_events[0].type == "red"
    assert out.live_probabilities.home_win < base.home_win


def test_summary_card_events_default_empty(db_session):
    out = match_to_summary(db_session, _match(db_session))
    assert out.card_events == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_card_events_serializer.py -v`
Expected: FAIL — `ImportError: cannot import name '_card_counts'`.

- [ ] **Step 3: Implement.**

(a) `backend/app/schemas/__init__.py` — under `GoalEventOut` add:

```python
class CardEventOut(BaseModel):
    minute: int | None
    side: str          # "home" | "away"
    player: str
    type: str          # "yellow" | "red" (a second yellow arrives as one "red")
```

and in `MatchSummaryOut`, directly under `goal_events`:

```python
    card_events: list[CardEventOut] = []
```

(b) `backend/app/serializers.py` — add above `match_to_summary`:

```python
def _card_counts(card_events: list | None) -> dict[str, int]:
    """Per-side red and ACTIVE-yellow counts for the live model. A yellow is
    active only while its player has not been sent off — once the red arrives
    (a second yellow comes through as one red event for the same player) the
    booking no longer carries second-yellow risk. None/malformed -> all zero."""
    counts = {"red_home": 0, "red_away": 0, "yellow_home": 0, "yellow_away": 0}
    events = [e for e in (card_events or [])
              if isinstance(e, dict) and e.get("side") in ("home", "away")]
    sent_off = {"home": set(), "away": set()}
    for e in events:
        if e.get("type") == "red":
            counts[f"red_{e['side']}"] += 1
            sent_off[e["side"]].add(e.get("player"))
    for e in events:
        if e.get("type") == "yellow" and e.get("player") not in sent_off[e["side"]]:
            counts[f"yellow_{e['side']}"] += 1
    return counts
```

In `match_to_summary`, change the `live_probabilities_for_match` call to:

```python
        live = live_probabilities_for_match(
            status=match.status,
            score_home=match.score_home,
            score_away=match.score_away,
            minute=match.minute,
            period=match.period,
            lam_home=pred.lambda_home,
            lam_away=pred.lambda_away,
            rho=pred.rho,
            **_card_counts(match.card_events),
        )
```

and in the `MatchSummaryOut(...)` construction, directly under `goal_events=...` add:

```python
        card_events=[schemas.CardEventOut(**c) for c in (match.card_events or [])],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_card_events_serializer.py backend/tests/test_goal_events_serializer.py backend/tests/test_match_summary_api.py -v`
Expected: PASS (summary API tests confirm the new field defaults cleanly).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/serializers.py backend/tests/test_card_events_serializer.py
git commit -m "feat(api): expose card events on match summary and feed counts to live model"
```

---

### Task 6: Frontend — reds in the timeline, compact yellow counts

**Files:**
- Modify: `frontend/lib/types.ts` (next to `GoalEvent`, line ~104), `frontend/components/MatchScoreboard.tsx` (events block, line ~117; helpers, line ~226)
- Test: `frontend/components/__tests__/cards.test.tsx` (create)

**Interfaces:**
- Consumes: `card_events` on the summary payload (Task 5).
- Produces: `CardEvent` TS interface; `MatchSummary.card_events?: CardEvent[]` (optional so existing fixtures/payloads stay valid); scoreboard helpers `timelineFor`, `formatRedCard`, `yellowCount`.

- [ ] **Step 1: Write the failing test** — create `frontend/components/__tests__/cards.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import * as api from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

// MatchScoreboard polls getMatchSummary on mount — mock it (mirrors scorers.test.tsx).
jest.mock("@/lib/api");
const mockGetMatchSummary = api.getMatchSummary as jest.Mock;

const summary: MatchSummary = {
  match_id: 1, stage: "group", group: "Group A", kickoff_utc: null,
  venue: null, venue_city: null, venue_country: null, is_neutral: true,
  status: "in_play", score_home: 1, score_away: 0, minute: 70, period: "second_half",
  injury_time: null, penalty_home: null, penalty_away: null,
  teams: { home: "Mexico", away: "South Africa" },
  predicted_winner: "Mexico", probabilities: null, predicted_score: null, confidence: null,
  goal_events: [{ minute: 30, side: "home", player: "R. Jimenez", type: "goal" }],
  card_events: [
    { minute: 44, side: "away", player: "T. Mokoena", type: "red" },
    { minute: 20, side: "home", player: "J. Vasquez", type: "yellow" },
    { minute: 55, side: "home", player: "E. Alvarez", type: "yellow" },
  ],
};

beforeEach(() => mockGetMatchSummary.mockResolvedValue(summary));

test("red cards join the timeline; yellows are a compact count", () => {
  render(
    <MatchScoreboard
      matchId={1} home="Mexico" away="South Africa"
      probabilities={{ home_win: 0.6, draw: 0.2, away_win: 0.2 }}
      predicted={{ home: 2, away: 0, probability: 0.2 }}
      initialSummary={summary}
    />,
  );
  expect(screen.getByText(/T\. Mokoena/)).toBeInTheDocument();       // red in timeline
  expect(screen.getByText(/🟨 ×2/)).toBeInTheDocument();             // home yellow count
  expect(screen.queryByText(/J\. Vasquez/)).not.toBeInTheDocument(); // yellows are not timeline entries
  expect(screen.getByText(/R\. Jimenez/)).toBeInTheDocument();       // goals still render
});

test("summary without card_events renders goals as before", () => {
  const legacy: MatchSummary = { ...summary, card_events: undefined };
  mockGetMatchSummary.mockResolvedValue(legacy);
  render(
    <MatchScoreboard
      matchId={1} home="Mexico" away="South Africa"
      probabilities={{ home_win: 0.6, draw: 0.2, away_win: 0.2 }}
      predicted={{ home: 2, away: 0, probability: 0.2 }}
      initialSummary={legacy}
    />,
  );
  expect(screen.getByText(/R\. Jimenez/)).toBeInTheDocument();
  expect(screen.queryByText(/🟨/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/cards.test.tsx`
Expected: FAIL — TS error on `card_events` (not in `MatchSummary`) / `T. Mokoena` not found.

- [ ] **Step 3: Implement.**

(a) `frontend/lib/types.ts` — under `GoalEvent` add:

```ts
export interface CardEvent {
  minute: number | null;
  side: "home" | "away";
  player: string;
  type: "yellow" | "red";
}
```

and in `MatchSummary`, under `goal_events`:

```ts
  /** Bookings and sendings-off; optional so pre-cards payloads stay valid.
   *  A second yellow arrives as a single "red" event. */
  card_events?: CardEvent[];
```

(b) `frontend/components/MatchScoreboard.tsx` — add `CardEvent` to the `@/lib/types` import. Replace the goal-events block (currently `{hasActual && summary!.goal_events.length > 0 && (...)}`) with:

```tsx
      {hasActual &&
        (timelineFor(summary!, "home").length > 0 ||
          timelineFor(summary!, "away").length > 0 ||
          yellowCount(summary!, "home") > 0 ||
          yellowCount(summary!, "away") > 0) && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 text-[11px] text-muted sm:text-xs">
          <ul className="space-y-0.5 text-right">
            {timelineFor(summary!, "home").map((label, i) => (
              <li key={`h-${i}`} className="tabular-nums">{label}</li>
            ))}
            {yellowCount(summary!, "home") > 0 && (
              <li className="tabular-nums" aria-label="home yellow cards">
                🟨 ×{yellowCount(summary!, "home")}
              </li>
            )}
          </ul>
          <ul className="space-y-0.5 text-left">
            {timelineFor(summary!, "away").map((label, i) => (
              <li key={`a-${i}`} className="tabular-nums">{label}</li>
            ))}
            {yellowCount(summary!, "away") > 0 && (
              <li className="tabular-nums" aria-label="away yellow cards">
                🟨 ×{yellowCount(summary!, "away")}
              </li>
            )}
          </ul>
        </div>
      )}
```

and next to `formatScorer` add:

```tsx
/** Goals and red cards for one side, merged into one minute-ordered timeline.
 *  Yellows stay out of the timeline (rendered as a compact count instead). */
function timelineFor(s: MatchSummary, side: "home" | "away"): string[] {
  const goals = s.goal_events
    .filter((g) => g.side === side)
    .map((g) => ({ minute: g.minute, label: formatScorer(g) }));
  const reds = (s.card_events ?? [])
    .filter((c) => c.side === side && c.type === "red")
    .map((c) => ({ minute: c.minute, label: formatRedCard(c) }));
  return [...goals, ...reds]
    .sort((x, y) => (x.minute ?? 0) - (y.minute ?? 0))
    .map((e) => e.label);
}

function formatRedCard(c: CardEvent): string {
  const min = c.minute != null ? ` ${c.minute}'` : "";
  return `🟥 ${c.player}${min}`;
}

function yellowCount(s: MatchSummary, side: "home" | "away"): number {
  return (s.card_events ?? []).filter((c) => c.side === side && c.type === "yellow").length;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx jest components/__tests__/cards.test.tsx components/__tests__/scorers.test.tsx`
Expected: PASS (scorers test proves goal rendering is unchanged).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/types.ts frontend/components/MatchScoreboard.tsx frontend/components/__tests__/cards.test.tsx
git commit -m "feat(ui): show red cards in the match timeline with compact yellow counts"
```

---

### Task 7: Full verification

**Files:** none new — verification only.

- [ ] **Step 1: Full backend/pipeline suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS, no failures anywhere (live_winprob regression pins prove zero-card behaviour is unchanged).

- [ ] **Step 2: Full frontend suite + typecheck**

Run: `cd frontend && npx jest && npx tsc --noEmit`
Expected: PASS / no type errors.

- [ ] **Step 3: Commit anything outstanding and stop**

```bash
git status --short   # should be clean; commit stragglers if any
```

Deployment note (no action in this plan): the migration runs via the existing
GitHub Actions migration workflow after merge — Render's auto-deploy does not
run migrations (free tier). `events_refetch_seconds` needs no env var (default
180 applies).
