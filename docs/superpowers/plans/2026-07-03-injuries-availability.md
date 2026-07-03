# Injuries → Day-Ahead Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed api-sports `/injuries` (already in the Pro plan) into the existing shadow-first availability adjustment, so the forecast reflects who's out/doubtful **days ahead**, not just from the ~1h announced XI.

**Architecture:** One unified resolver picks the best "who's available" signal per team — the announced XI when present (v1, unchanged; XI supersedes), else the reference XI with injury multipliers (out → 0.0, doubtful → 0.5). The same clamped attack offset, shadow twin, note, and benchmark are reused. Injuries are ingested per-fixture (mirroring `refresh_odds`) into a new JSON `Match.injuries` column.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Alembic / pytest; Next.js / TypeScript / jest.

## Global Constraints

- **Best-available resolver:** both announced XIs present → XI path (v1, unchanged); else `Match.injuries` non-empty → injury path for BOTH sides; else no twin/note. A lone XI (only one side) is ignored in favour of injuries.
- **Weights:** `DOUBTFUL_WEIGHT = 0.5`; "out" → 0.0; fit → 1.0. Clamp unchanged: `[ATTACK_OFFSET_LO=-0.25, ATTACK_OFFSET_HI=0.10]`, attack-side only.
- **Injury type mapping:** api-sports `player.type == "Missing Fixture"` → `"out"`; anything else → `"doubtful"`.
- **`Match.injuries`** JSON column: `null` = not ingested, `[]` = checked/clear, else `[{provider_player_id, name, type, reason, side}]` (mirrors `goal_events`/`card_events`).
- **Champion untouched:** no change to the published prediction/probabilities, the sims, `write_availability_prediction`, or the `is_shadow=False` path. One `+avail` twin version (no new version string).
- **Ingestion is best-effort:** `refresh_injuries` NEVER raises (mirror `refresh_odds`).
- **Alembic head is `c4d5e6f7a8b0`** — the new migration's `down_revision`.
- **Migration is exercised in prod via `refresh.yml` branch-dispatch pre-merge** (finishing step); tests use `create_all` (model-driven), consistent with the repo — no migration unit test.
- **Test conventions:** ml/pipeline tests are `<module>_test.py` beside the module; backend tests are `backend/tests/test_*.py`; all share the root `./conftest.py` `db_session`. Run: `.venv/bin/python -m pytest <path> -v`. Frontend gate: `cd frontend && npm run typecheck && npm run lint && npm test`.
- **Every commit** ends with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. **Do not merge** — prepare the branch/PR; a human merges.

---

## File Structure

- **Create** `backend/alembic/versions/d1e2f3a4b5c6_add_match_injuries.py` — additive nullable JSON column.
- **Modify** `backend/app/models/__init__.py` — `Match.injuries` column.
- **Create** `backend/tests/test_match_injuries_model.py` — column round-trip.
- **Modify** `pipeline/ingest/api_football.py` — `fetch_injuries` + `parse_injuries`.
- **Create** `pipeline/ingest/injuries.py` — `refresh_injuries` (mirrors `refresh_odds`).
- **Create** `pipeline/ingest/injuries_test.py` — parse + refresh tests.
- **Modify** `pipeline/run_pipeline.py` — wire the `injuries` step after `odds`.
- **Modify** `ml/models/availability.py` — `_clamped_offset` refactor + `injury_availability_offset` + `DOUBTFUL_WEIGHT`.
- **Modify** `ml/models/availability_test.py` — injury-offset tests.
- **Modify** `backend/app/availability.py` — injury branch in `availability_for_match`.
- **Modify** `backend/app/serializers.py` — `_availability_note` handles status/reason.
- **Modify** `backend/app/schemas/__init__.py` — optional `status`/`reason` on `AvailabilityPlayerOut`.
- **Modify** `frontend/lib/types.ts` — optional `status`/`reason` on `AvailabilityPlayer`.
- **Modify** `backend/tests/test_availability.py` + `backend/tests/test_availability_serving.py` — injury-path tests.

---

### Task 1: Migration + `Match.injuries` column

**Files:**
- Create: `backend/alembic/versions/d1e2f3a4b5c6_add_match_injuries.py`
- Modify: `backend/app/models/__init__.py` (add `injuries` to `Match`, next to `card_events` ~line 138)
- Test: `backend/tests/test_match_injuries_model.py`

**Interfaces:**
- Produces: `Match.injuries: list | None` (JSON).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_match_injuries_model.py
"""Match.injuries JSON column round-trips (model-driven; create_all in conftest)."""
from app.models import Match, Team


def test_match_injuries_column_roundtrips(db_session):
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db_session.add_all([h, a]); db_session.commit()
    m = Match(tournament_id=1, stage="group", team_home_id=h.id, team_away_id=a.id,
              injuries=[{"provider_player_id": 1, "name": "Neymar", "type": "out",
                         "reason": "Calf Injury", "side": "home"}])
    db_session.add(m); db_session.commit()
    got = db_session.get(Match, m.id)
    assert got.injuries[0]["name"] == "Neymar"
    assert got.injuries[0]["type"] == "out"
    assert got.injuries[0]["side"] == "home"


def test_match_injuries_defaults_none(db_session):
    h, a = Team(name="France"), Team(name="Spain")
    db_session.add_all([h, a]); db_session.commit()
    m = Match(tournament_id=1, stage="group", team_home_id=h.id, team_away_id=a.id)
    db_session.add(m); db_session.commit()
    assert db_session.get(Match, m.id).injuries is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_match_injuries_model.py -v`
Expected: FAIL — `TypeError: 'injuries' is an invalid keyword argument for Match`.

- [ ] **Step 3: Add the model column**

In `backend/app/models/__init__.py`, inside `class Match`, immediately after the `card_events` column (~line 138), add:

```python
    # Per-fixture availability snapshot (day-ahead), same JSON pattern as
    # card_events: [{provider_player_id, name, type: "out"|"doubtful", reason, side}].
    # null = not yet ingested, [] = checked/clear.
    injuries: Mapped[list | None] = mapped_column(JSON)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_match_injuries_model.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Create the Alembic migration**

```python
# backend/alembic/versions/d1e2f3a4b5c6_add_match_injuries.py
"""add injuries column to matches

Additive, nullable JSON — safe, no data change. Holds the per-fixture
availability list feeding the day-ahead availability adjustment.

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b0
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c4d5e6f7a8b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("injuries", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "injuries")
```

- [ ] **Step 6: Verify the migration is head-consistent and single-headed**

Run: `cd backend && PYTHONPATH=..:. .venv/bin/alembic heads 2>&1 | head`
Expected: a single head, `d1e2f3a4b5c6 (head)`.
If the alembic CLI can't load its env here, instead verify by grep — `grep -rl "down_revision.*d1e2f3a4b5c6" backend/alembic/versions` returns nothing (no child), and `grep -c "revision: str = \"d1e2f3a4b5c6\"" backend/alembic/versions/*.py` shows exactly one file. State which check you used.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/d1e2f3a4b5c6_add_match_injuries.py backend/tests/test_match_injuries_model.py
git commit -m "feat(db): add nullable injuries JSON column to matches"
```

---

### Task 2: `fetch_injuries` + `parse_injuries`

**Files:**
- Modify: `pipeline/ingest/api_football.py` (add both functions; `requests`, `BASE_URL`, `log` already present)
- Test: `pipeline/ingest/injuries_test.py`

**Interfaces:**
- Produces:
  - `fetch_injuries(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]`
  - `parse_injuries(response: list[dict]) -> list[dict]` → `[{provider_player_id, name, type, reason, team_name}]`, `type ∈ {"out","doubtful"}`.

- [ ] **Step 1: Write the failing tests**

```python
# pipeline/ingest/injuries_test.py
"""Tests for the injuries ingest (parse now; refresh added in the next task)."""
from pipeline.ingest.api_football import parse_injuries


def _rec(name, itype, reason, team):
    return {"player": {"id": 10, "name": name, "type": itype, "reason": reason},
            "team": {"id": 1, "name": team}}


def test_parse_maps_missing_fixture_to_out():
    out = parse_injuries([_rec("Neymar", "Missing Fixture", "Calf Injury", "Brazil")])
    assert out == [{"provider_player_id": 10, "name": "Neymar", "type": "out",
                    "reason": "Calf Injury", "team_name": "Brazil"}]


def test_parse_maps_everything_else_to_doubtful():
    out = parse_injuries([_rec("Vini", "Questionable", "Knock", "Brazil")])
    assert out[0]["type"] == "doubtful"


def test_parse_skips_nameless_and_malformed_rows():
    out = parse_injuries([
        {"player": {"id": 1, "name": None, "type": "Missing Fixture"}, "team": {"name": "X"}},
        "not-a-dict",
        _rec("Real", "Missing Fixture", "ACL", "Brazil"),
    ])
    assert [r["name"] for r in out] == ["Real"]


def test_parse_empty_response():
    assert parse_injuries([]) == []
    assert parse_injuries(None) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/ingest/injuries_test.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_injuries'`.

- [ ] **Step 3: Add the functions**

Append to `pipeline/ingest/api_football.py`:

```python
def fetch_injuries(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw injury list for one fixture from api-sports.io (/injuries)."""
    resp = requests.get(
        f"{BASE_URL}/injuries",
        headers={"x-apisports-key": api_key},
        params={"fixture": fixture_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football injuries errors: %s", data["errors"])
    return data.get("response") or []


def parse_injuries(response: list[dict]) -> list[dict]:
    """PURE mapping: api-sports /injuries response -> our injury dicts. Each row is
    ``{provider_player_id, name, type, reason, team_name}`` where ``type`` is "out"
    for "Missing Fixture" else "doubtful". Nameless / malformed rows are skipped
    rather than fabricated (same posture as parse_lineups)."""
    out: list[dict] = []
    for rec in response or []:
        if not isinstance(rec, dict):
            continue
        player = rec.get("player") or {}
        name = player.get("name")
        if not name:
            continue
        team = rec.get("team") or {}
        out.append({
            "provider_player_id": player.get("id"),
            "name": name,
            "type": "out" if player.get("type") == "Missing Fixture" else "doubtful",
            "reason": player.get("reason"),
            "team_name": team.get("name"),
        })
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/ingest/injuries_test.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/api_football.py pipeline/ingest/injuries_test.py
git commit -m "feat(ingest): fetch_injuries + parse_injuries for api-sports /injuries"
```

---

### Task 3: `refresh_injuries` + pipeline wiring

**Files:**
- Create: `pipeline/ingest/injuries.py`
- Modify: `pipeline/run_pipeline.py` (add the `injuries` step in the api-key-gated block ~lines 71-76)
- Test: `pipeline/ingest/injuries_test.py` (append)

**Interfaces:**
- Consumes: `fetch_injuries`, `parse_injuries` (Task 2); `pipeline.team_mapping.normalize_team_name`; `app.lineups._resolve_fixture_id`.
- Produces: `refresh_injuries(db, api_key, window_hours=48.0) -> dict`; sets `Match.injuries`.

- [ ] **Step 1: Write the failing tests**

```python
# append to pipeline/ingest/injuries_test.py
from datetime import datetime, timedelta, timezone

from app.models import Match, Team
from pipeline.ingest import injuries as injuries_mod
from pipeline.ingest.injuries import refresh_injuries


def _scheduled_match(db, kickoff_in_hours=24):
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", status="scheduled",
              team_home_id=h.id, team_away_id=a.id, provider_fixture_id=555,
              kickoff_utc=datetime.now(timezone.utc) + timedelta(hours=kickoff_in_hours))
    db.add(m); db.commit()
    return m, h, a


def test_refresh_sets_injuries_with_sides(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    # Raw api-sports records: one Brazil (home), one Serbia (away).
    monkeypatch.setattr(injuries_mod, "fetch_injuries", lambda key, fid: [
        {"player": {"id": 10, "name": "Neymar", "type": "Missing Fixture", "reason": "Calf"},
         "team": {"name": "Brazil"}},
        {"player": {"id": 20, "name": "Mitrovic", "type": "Questionable", "reason": "Knock"},
         "team": {"name": "Serbia"}},
    ])
    out = refresh_injuries(db_session, "key")
    got = db_session.get(Match, m.id).injuries
    assert {(i["name"], i["side"], i["type"]) for i in got} == {
        ("Neymar", "home", "out"), ("Mitrovic", "away", "doubtful")}
    assert out["matches_injuries"] == 1


def test_refresh_sets_empty_list_when_no_injuries(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    monkeypatch.setattr(injuries_mod, "fetch_injuries", lambda key, fid: [])
    refresh_injuries(db_session, "key")
    assert db_session.get(Match, m.id).injuries == []


def test_refresh_never_raises_on_fetch_error(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    def boom(key, fid):
        raise RuntimeError("feed down")
    monkeypatch.setattr(injuries_mod, "fetch_injuries", boom)
    out = refresh_injuries(db_session, "key")  # must not raise
    assert out["matches_skipped"] == 1
    assert db_session.get(Match, m.id).injuries is None  # untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/ingest/injuries_test.py -k refresh -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.ingest.injuries'`.

- [ ] **Step 3: Write `refresh_injuries`**

```python
# pipeline/ingest/injuries.py
"""Pre-match injury/availability snapshot from API-Football, per fixture.

Mirrors pipeline.ingest.odds.refresh_odds: for every scheduled match with both
teams kicking off inside the window, resolve the provider fixture id, fetch its
injuries, and store a normalized per-side list on Match.injuries (feeding the
day-ahead availability adjustment). BEST-EFFORT BY CONTRACT — any fetch failure
or malformed answer leaves that match unchanged and refresh_injuries NEVER raises
to callers, so prediction generation is unblockable by the feed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Match, Team
from pipeline.ingest.api_football import fetch_injuries, parse_injuries
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)

WINDOW_HOURS = 48.0


def _fixture_id(db: Session, match: Match, api_key: str) -> int | None:
    """Provider fixture id: the stored one, else the lineups path's resolver
    (team pair + kickoff date). Mirrors pipeline.ingest.odds._fixture_id."""
    if match.provider_fixture_id is not None:
        return match.provider_fixture_id
    from app.lineups import _resolve_fixture_id

    return _resolve_fixture_id(db, match, api_key)


def refresh_injuries(db: Session, api_key: str, window_hours: float = WINDOW_HOURS) -> dict:
    """One best-effort injuries pass over upcoming matches. NEVER raises.

    For each scheduled match kicking off inside ``window_hours`` it fetches the
    fixture's injuries and sets ``Match.injuries`` to a per-side list (``[]`` when
    the fixture is checked but clear). A match whose fixture can't be resolved or
    whose feed errors is skipped silently, leaving its ``injuries`` untouched.
    """
    now = datetime.now(timezone.utc)
    summary = {"matches_injuries": 0, "matches_skipped": 0}
    try:
        matches = (
            db.query(Match)
            .filter(
                Match.status == "scheduled",
                Match.team_home_id.isnot(None),
                Match.team_away_id.isnot(None),
                Match.kickoff_utc.isnot(None),
                Match.kickoff_utc >= now,
                Match.kickoff_utc <= now + timedelta(hours=window_hours),
            )
            .order_by(Match.kickoff_utc.asc(), Match.id.asc())
            .all()
        )
        for m in matches:
            try:
                fid = _fixture_id(db, m, api_key)
                if fid is None:
                    summary["matches_skipped"] += 1
                    continue
                records = parse_injuries(fetch_injuries(api_key, fid))
            except Exception as exc:  # noqa: BLE001 - best-effort per match
                log.warning("injuries fetch failed for match %s: %s", m.id, exc)
                summary["matches_skipped"] += 1
                continue
            home = db.get(Team, m.team_home_id)
            away = db.get(Team, m.team_away_id)
            hn = normalize_team_name(home.name) if home else None
            an = normalize_team_name(away.name) if away else None
            injuries: list[dict] = []
            for r in records:
                tn = normalize_team_name(r["team_name"]) if r.get("team_name") else None
                side = "home" if tn == hn else "away" if tn == an else None
                if side is None:
                    continue
                injuries.append({
                    "provider_player_id": r["provider_player_id"], "name": r["name"],
                    "type": r["type"], "reason": r["reason"], "side": side,
                })
            m.injuries = injuries
            summary["matches_injuries"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the pass itself must never raise
        db.rollback()
        log.warning("injuries refresh aborted: %s", exc)
        return {"matches_injuries": 0, "matches_skipped": summary["matches_skipped"],
                "error": str(exc)}
    return summary
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/ingest/injuries_test.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Wire the step into the pipeline**

In `pipeline/run_pipeline.py`, replace the api-key-gated odds block (~lines 71-76):

```python
    if settings.api_football_api_key:
        from pipeline.ingest.odds import refresh_odds

        step("odds", lambda: refresh_odds(db, settings.api_football_api_key))
    else:
        log.info("step skipped: odds (no API_FOOTBALL_API_KEY)")
```

with:

```python
    if settings.api_football_api_key:
        from pipeline.ingest.injuries import refresh_injuries
        from pipeline.ingest.odds import refresh_odds

        step("odds", lambda: refresh_odds(db, settings.api_football_api_key))
        # Day-ahead availability snapshot, BEFORE predictions so the twin can use it.
        step("injuries", lambda: refresh_injuries(db, settings.api_football_api_key))
    else:
        log.info("step skipped: odds + injuries (no API_FOOTBALL_API_KEY)")
```

- [ ] **Step 6: Run the full suite (regression + wiring imports resolve)**

Run: `.venv/bin/python -m pytest`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add pipeline/ingest/injuries.py pipeline/ingest/injuries_test.py pipeline/run_pipeline.py
git commit -m "feat(ingest): refresh_injuries per-fixture pass, wired into the daily pipeline"
```

---

### Task 4: `injury_availability_offset` (pure)

**Files:**
- Modify: `ml/models/availability.py` (add `DOUBTFUL_WEIGHT`, `_clamped_offset`, `injury_availability_offset`; refactor `availability_offset` to use `_clamped_offset`)
- Test: `ml/models/availability_test.py` (append)

**Interfaces:**
- Consumes: existing `attack_capacity`, `reference_eleven`, `_rate`, clamp constants.
- Produces:
  - `DOUBTFUL_WEIGHT = 0.5`
  - `injury_availability_offset(squad: list[dict], statuses: dict[int, dict]) -> tuple[float, dict] | None`, where `statuses` maps `provider_player_id → {"status": "out"|"doubtful", "reason": str|None}`. Explanation `players_out` entries carry `name, weight, status, reason`.
- Refactor note: `availability_offset` keeps its exact behavior (the v1 tests must stay green) — only the clamp/ratio→(offset, delta) step is extracted into `_clamped_offset`.

- [ ] **Step 1: Write the failing tests**

```python
# append to ml/models/availability_test.py
from ml.models.availability import DOUBTFUL_WEIGHT, injury_availability_offset


def _sq():
    # Elite striker (pid 1) + 10 ordinary regulars, all full-season minutes.
    return [_p(1, "F", 25, 2700, name="Star")] + [_p(i, "M", 2, 2700) for i in range(2, 12)]


def test_injury_out_removes_full_weight():
    squad = _sq()
    off, expl = injury_availability_offset(squad, {1: {"status": "out", "reason": "Calf"}})
    assert off < 0.0
    assert {"name": "Star", "weight": expl["players_out"][0]["weight"],
            "status": "out", "reason": "Calf"} == expl["players_out"][0]
    assert expl["attack_delta_pct"] == round(math.exp(off) - 1.0, 4)


def test_injury_doubtful_is_half_of_out():
    squad = _sq()
    # Injure a mid-tier regular (pid 2), NOT the dominant striker — otherwise both
    # offsets saturate the -0.25 clamp and the inequality can't be observed.
    off_out, _ = injury_availability_offset(squad, {2: {"status": "out", "reason": None}})
    off_dbt, _ = injury_availability_offset(squad, {2: {"status": "doubtful", "reason": None}})
    assert off_out < off_dbt < 0.0  # doubtful cuts less than out, neither clamped


def test_injury_no_injuries_is_zero_offset():
    off, expl = injury_availability_offset(_sq(), {})
    assert off == 0.0
    assert expl["players_out"] == []


def test_injury_offset_clamped_low():
    squad = _sq()
    statuses = {i: {"status": "out", "reason": None} for i in range(1, 12)}  # whole XI out
    off, _ = injury_availability_offset(squad, statuses)
    assert off == ATTACK_OFFSET_LO


def test_injury_player_not_in_reference_has_no_effect():
    squad = _sq()
    off, expl = injury_availability_offset(squad, {999: {"status": "out", "reason": "x"}})
    assert off == 0.0 and expl["players_out"] == []


def test_injury_none_when_empty_squad():
    assert injury_availability_offset([], {1: {"status": "out", "reason": None}}) is None


def test_doubtful_weight_default():
    assert DOUBTFUL_WEIGHT == 0.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/models/availability_test.py -k injury -v`
Expected: FAIL — `ImportError: cannot import name 'injury_availability_offset'`.

- [ ] **Step 3: Refactor `_clamped_offset` and add the injury path**

In `ml/models/availability.py`, add `DOUBTFUL_WEIGHT = 0.5` under the clamp constants (~line 21). Add the shared helper and the new function, and rewrite `availability_offset`'s clamp step to use it:

```python
DOUBTFUL_WEIGHT = 0.5


def _clamped_offset(effective: float, reference: float) -> tuple[float, float] | None:
    """(offset, attack_delta_pct) from an effective/reference capacity ratio, or
    None when the reference capacity is ~0. Shared by the XI and injury paths so
    the clamp lives in exactly one place. attack_delta_pct = exp(offset) - 1."""
    if reference <= 0.0:
        return None
    ratio = effective / reference
    if ratio <= 0.0:
        offset = ATTACK_OFFSET_LO
    else:
        offset = max(ATTACK_OFFSET_LO, min(ATTACK_OFFSET_HI, math.log(ratio)))
    return offset, round(math.exp(offset) - 1.0, 4)
```

Rewrite `availability_offset` (same behavior, now via the helper):

```python
def availability_offset(
    announced_starters: list[dict], squad: list[dict]
) -> tuple[float, dict] | None:
    """Bounded attack offset (log-lambda units) for one team plus an explanation,
    or None when it can't be computed (no XI, or reference capacity ~ 0). ratio =
    attack_capacity(announced XI) / attack_capacity(reference XI), clamped."""
    if not announced_starters:
        return None
    reference = reference_eleven(squad)
    clamped = _clamped_offset(attack_capacity(announced_starters), attack_capacity(reference))
    if clamped is None:
        return None
    offset, delta_pct = clamped
    starting_ids = {p.get("provider_player_id") for p in announced_starters}
    missing = [p for p in reference if p.get("provider_player_id") not in starting_ids]
    missing.sort(key=_rate, reverse=True)
    explanation = {
        "attack_delta_pct": delta_pct,
        "players_out": [
            {"name": p.get("name"), "weight": round(_rate(p), 4)} for p in missing
        ],
    }
    return offset, explanation


def injury_availability_offset(
    squad: list[dict], statuses: dict[int, dict]
) -> tuple[float, dict] | None:
    """Bounded attack offset for one team from injury statuses, or None when the
    reference capacity is ~0. ``statuses`` maps provider_player_id -> {"status":
    "out"|"doubtful", "reason": str|None}; a player absent from ``statuses`` is
    fully fit. Out contributes 0.0 of its attacking weight, doubtful
    DOUBTFUL_WEIGHT, fit 1.0. The explanation lists the affected reference
    starters (by attacking weight desc) with their status + reason."""
    reference = reference_eleven(squad)

    def _mult(pid) -> float:
        s = (statuses.get(pid) or {}).get("status")
        return 0.0 if s == "out" else DOUBTFUL_WEIGHT if s == "doubtful" else 1.0

    effective = sum(_rate(p) * _mult(p.get("provider_player_id")) for p in reference)
    clamped = _clamped_offset(effective, attack_capacity(reference))
    if clamped is None:
        return None
    offset, delta_pct = clamped
    affected = [
        p for p in reference
        if (statuses.get(p.get("provider_player_id")) or {}).get("status") in ("out", "doubtful")
    ]
    affected.sort(key=_rate, reverse=True)
    explanation = {
        "attack_delta_pct": delta_pct,
        "players_out": [
            {"name": p.get("name"), "weight": round(_rate(p), 4),
             "status": (statuses.get(p.get("provider_player_id")) or {}).get("status"),
             "reason": (statuses.get(p.get("provider_player_id")) or {}).get("reason")}
            for p in affected
        ],
    }
    return offset, explanation
```

- [ ] **Step 4: Run the injury tests AND the existing v1 tests (refactor must not regress)**

Run: `.venv/bin/python -m pytest ml/models/availability_test.py -v`
Expected: PASS (all — the pre-existing `availability_offset` tests plus the new injury ones).

- [ ] **Step 5: Commit**

```bash
git add ml/models/availability.py ml/models/availability_test.py
git commit -m "feat(ml): injury_availability_offset (out=0, doubtful=0.5) via shared clamp"
```

---

### Task 5: Wire the injury path + serve the note

**Files:**
- Modify: `backend/app/availability.py` (injury branch in `availability_for_match`)
- Modify: `backend/app/serializers.py` (`_availability_note` handles status/reason)
- Modify: `backend/app/schemas/__init__.py` (`AvailabilityPlayerOut` optional `status`/`reason`)
- Modify: `frontend/lib/types.ts` (`AvailabilityPlayer` optional `status`/`reason`)
- Test: `backend/tests/test_availability.py` + `backend/tests/test_availability_serving.py` (append)

**Interfaces:**
- Consumes: `injury_availability_offset` (Task 4); `Match.injuries` (Task 1).
- Produces: `availability_for_match` returns its existing `(off_home, off_away, expl_home, expl_away) | None` from either path.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_availability.py
def _match_inj(db, injuries):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id, injuries=injuries)
    db.add(m); db.commit()
    return m, h, a


def test_injury_path_when_no_xi(db_session):
    m, h, a = _match_inj(db_session, [
        {"provider_player_id": 1, "name": "Star", "type": "out", "reason": "Calf", "side": "home"}])
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)   # helper from this file
    result = availability_for_match(db_session, m)
    assert result is not None
    off_home, off_away, expl_home, expl_away = result
    assert off_home < 0.0                       # home lost its striker to injury
    assert off_away == 0.0                       # away clear
    assert expl_home["players_out"][0]["status"] == "out"
    assert expl_home["players_out"][0]["reason"] == "Calf"


def test_xi_supersedes_injuries(db_session):
    # Both XIs present AND injuries present -> XI path is used (injuries ignored).
    m, h, a = _match_inj(db_session, [
        {"provider_player_id": 1, "name": "Star", "type": "out", "reason": "Calf", "side": "home"}])
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    _lineup(db_session, m.id, "home", [1] + [100 + i for i in range(10)])  # Star (1) IS in the XI
    _lineup(db_session, m.id, "away", [2] + [200 + i for i in range(10)])
    off_home, _off_away, expl_home, _expl_away = availability_for_match(db_session, m)
    assert off_home == 0.0                       # XI path: Star present -> full strength
    assert all("status" not in p for p in expl_home["players_out"])  # XI-path shape, no injury tags


def test_no_adjustment_without_xi_or_injuries(db_session):
    m, h, a = _match_inj(db_session, None)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    assert availability_for_match(db_session, m) is None
```

```python
# append to backend/tests/test_availability_serving.py
def test_injury_note_names_player_and_reason(db_session):
    m, h, a, pred = _match_pred(db_session)   # helper from this file
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    m.injuries = [{"provider_player_id": 1, "name": "Star", "type": "out",
                   "reason": "Calf Injury", "side": "home"}]
    db_session.commit()
    out = prediction_to_out(db_session, m, pred)
    assert out.availability is not None
    home = next(t for t in out.availability.per_team if t.side == "home")
    assert "Star" in home.note and "Calf Injury" in home.note
    assert home.attack_delta_pct < 0.0
    assert out.probabilities.home_win == 0.55   # published number unchanged
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_availability.py -k "injury or supersed or without_xi_or" backend/tests/test_availability_serving.py -k injury -v`
Expected: FAIL — the injury branch doesn't exist yet (`availability_for_match` returns None on the injury-only match).

- [ ] **Step 3: Add the injury branch to `availability_for_match`**

In `backend/app/availability.py`, replace `availability_for_match` with:

```python
def _squad_dicts(db: Session, team_id: int) -> list[dict]:
    from app.goalscorers import _player_dict  # lazy: avoids import cycle

    return [_player_dict(p, None) for p in db.query(Player).filter_by(team_id=team_id).all()]


def _injury_statuses(match: Match, side: str, squad_ids: set) -> dict[int, dict]:
    """{provider_player_id: {status, reason}} for one side, restricted to players
    in our squad (an injured player we don't track can't affect the reference XI)."""
    out: dict[int, dict] = {}
    for inj in match.injuries or []:
        if inj.get("side") != side:
            continue
        pid = inj.get("provider_player_id")
        if pid in squad_ids:
            out[pid] = {"status": inj.get("type"), "reason": inj.get("reason")}
    return out


def availability_for_match(
    db: Session, match: Match
) -> tuple[float, float, dict, dict] | None:
    """(off_home, off_away, expl_home, expl_away) from the best available signal:
    both announced XIs -> the v1 XI path; else, if injuries are ingested, the
    day-ahead injury path for both sides; else None."""
    home = availability_inputs(db, match, "home")
    away = availability_inputs(db, match, "away")
    if home is not None and away is not None:
        h = availability_offset(home[0], home[1])
        a = availability_offset(away[0], away[1])
        if h is None or a is None:
            return None
        return h[0], a[0], h[1], a[1]
    if match.injuries:
        from ml.models.availability import injury_availability_offset

        results = []
        for side in ("home", "away"):
            team_id = match.team_home_id if side == "home" else match.team_away_id
            squad = _squad_dicts(db, team_id)
            statuses = _injury_statuses(match, side, {p.get("provider_player_id") for p in squad})
            res = injury_availability_offset(squad, statuses)
            if res is None:
                return None
            results.append(res)
        return results[0][0], results[1][0], results[0][1], results[1][1]
    return None
```

Add `injury_availability_offset` is imported lazily above; `availability_offset` stays the top-level import.

- [ ] **Step 4: Extend the serializer note + schema + frontend type**

In `backend/app/serializers.py`, replace `_availability_note` with:

```python
def _availability_note(team_name: str, expl: dict) -> str:
    """One human line: who's unavailable and the attack impact. Handles the
    announced-XI path (players_out = {name, weight}) and the injury path (entries
    also carry status/reason)."""
    players = expl["players_out"]
    if not players:
        return f"{team_name}: at full attacking strength."
    pct_txt = f"{expl['attack_delta_pct'] * 100.0:+.0f}%"
    if any(p.get("status") for p in players):
        def _label(p: dict) -> str:
            det = ", ".join(x for x in (p.get("reason"), p.get("status")) if x)
            return f"{p['name']} ({det})" if det else p["name"]
        body = ", ".join(_label(p) for p in players[:3])
    else:
        body = "usual XI missing " + ", ".join(p["name"] for p in players[:3])
    return f"{team_name}: {body} → attack {pct_txt}."
```

In `backend/app/schemas/__init__.py`, extend `AvailabilityPlayerOut`:

```python
class AvailabilityPlayerOut(BaseModel):
    name: str
    weight: float
    status: str | None = None
    reason: str | None = None
```

In `frontend/lib/types.ts`, extend `AvailabilityPlayer`:

```typescript
export interface AvailabilityPlayer {
  name: string;
  weight: number;
  status?: string | null;
  reason?: string | null;
}
```

- [ ] **Step 5: Run the backend tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_availability.py backend/tests/test_availability_serving.py -v`
Expected: PASS (all — new injury tests plus the pre-existing XI-path ones).

- [ ] **Step 6: Run the frontend gate (type change)**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: PASS (the optional fields are additive; the existing availabilityNote test is unaffected).

- [ ] **Step 7: Commit**

```bash
git add backend/app/availability.py backend/app/serializers.py backend/app/schemas/__init__.py frontend/lib/types.ts backend/tests/test_availability.py backend/tests/test_availability_serving.py
git commit -m "feat(api): day-ahead injury path in the availability resolver + note"
```

---

### Task 6: Full suite + PR

**Files:** none (verification + PR prep)

- [ ] **Step 1: Full Python suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS (all).

- [ ] **Step 2: Full frontend gate**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: PASS.

- [ ] **Step 3: Push and open the PR (do NOT merge; the migration is applied pre-merge — see below)**

```bash
git push -u origin feat/injuries-availability
gh pr create --base main --title "feat: injuries -> day-ahead availability" --body "$(cat <<'EOF'
Feeds api-sports /injuries (already in the Pro plan) into the shadow-first availability adjustment, so the forecast reflects who's out/doubtful DAYS ahead — not just from the ~1h announced XI.

- **One resolver:** announced XI when present (v1, unchanged; XI supersedes), else the reference XI with injury multipliers (out=0.0, doubtful=0.5).
- **Ingestion:** `refresh_injuries` per-fixture (mirrors `refresh_odds`), best-effort, into a new nullable JSON `Match.injuries` column.
- **Same** shadow twin, note, gate, benchmark; champion untouched.

## Deploy sequencing (migration)
`Match.injuries` is a new column. Per the card-aware pattern, apply it to prod BEFORE merge to avoid a 500 window:
1. Dispatch `refresh.yml` on THIS branch → `alembic upgrade head` adds the nullable column (backward-compatible with running code).
2. Verify the column exists, then merge → Render deploys the reading code safely.

Spec: `docs/superpowers/specs/2026-07-03-injuries-availability-design.md`
Plan: `docs/superpowers/plans/2026-07-03-injuries-availability.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4:** Stop. Hand off to the human for the migration dispatch + merge (guarded pipeline + stop-gate).

---

## Notes for the executor

- **Champion / v1 untouched:** don't change `write_availability_prediction`, `latest_prediction`, the sims, or the `is_shadow=False` path. The `availability_offset` refactor (Task 4) must keep the v1 tests green — the extracted `_clamped_offset` is behavior-preserving.
- **Best-effort ingestion:** `refresh_injuries` must never raise (a feed hiccup can't block predictions) — mirror `refresh_odds` exactly.
- **Migration is prod-only:** tests use `create_all` (the model column is enough); the Alembic file is exercised via the `refresh.yml` branch-dispatch in finishing, consistent with the repo (no migration unit test).
- **Both-sides discipline:** the injury path adjusts both sides (a clear side → offset 0); a lone announced XI without the other is ignored in favour of injuries.
