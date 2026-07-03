# Availability Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Factor announced-XI player availability into the WC26 forecast as a bounded, explainable attack-side adjustment — logged as a shadow twin and surfaced as a context note, without moving the published number.

**Architecture:** A pure ML function turns "who's in the announced XI vs the usual XI" into a clamped attack offset (log-lambda units), reusing the existing `goalscorers.player_rate` weights. A thin DB-glue module loads XI+squad and produces per-team offsets. The daily pipeline writes an availability-adjusted `is_shadow` twin (for measurement); the read path recomputes the same adjustment to serve a note. A benchmark scores the twin vs production once results accumulate.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / pytest (backend, ml, pipeline); Next.js 15 / React / TypeScript / jest + @testing-library/react (frontend).

## Global Constraints

- **No DB migration.** The twin reuses the existing `Prediction.is_shadow` column, distinguished by `model_version`. No schema change, so no `refresh.yml` sequencing.
- **Champion untouched.** The published prediction (`is_shadow=False`) and its probabilities are never altered. Group/knockout simulations are not touched.
- **Twin model version:** `AVAILABILITY_MODEL_VERSION = "poisson-elo-v0.3+avail"` — mirrors the existing `SHADOW_MODEL_VERSION = "poisson-elo-v0.3-shadow"` versioning.
- **Attack-side only (v1).** Only `atk_home`/`atk_away` move (via a lambda multiply); `def_*` untouched. No defensive/GK availability, no paid injuries feed.
- **Both-XI gate.** The adjustment (twin AND note) is produced only when BOTH sides have a stored announced XI — mirrors the goalscorers "lineup mode" gate. Otherwise: no twin, no note.
- **Clamp:** `ATTACK_OFFSET_LO = -0.25`, `ATTACK_OFFSET_HI = 0.10` (log-lambda units).
- **Test file conventions:** ml/ and pipeline/ tests live beside the module as `<module>_test.py`; backend tests live in `backend/tests/test_*.py`. All share the root `./conftest.py` `db_session` fixture. Run Python tests with `.venv/bin/python -m pytest <path> -v`.
- **Every commit** ends with the trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Do not merge.** Prepare the branch + PR; a human merges (guarded pipeline).

---

## File Structure

- **Create** `ml/models/availability.py` — pure core: attack capacity, reference XI, clamped offset + explanation. No I/O.
- **Create** `ml/models/availability_test.py` — unit tests for the core.
- **Create** `backend/app/availability.py` — DB glue: load XI+squad, produce per-team offsets. No schemas, no `app.serializers`/`app.goalscorers` imports (cycle-free).
- **Create** `backend/tests/test_availability.py` — DB-level tests for the glue.
- **Modify** `pipeline/generate_predictions.py` — add `AVAILABILITY_MODEL_VERSION`, `write_availability_prediction`, wire into the loop; `import math`.
- **Modify** `pipeline/generate_predictions_test.py` — tests for the twin writer.
- **Modify** `backend/app/schemas/__init__.py` — `AvailabilityPlayerOut` / `TeamAvailabilityOut` / `AvailabilityOut`; add `availability` to `PredictionOut`.
- **Modify** `backend/app/serializers.py` — `availability_out` + note composition; populate `PredictionOut.availability`.
- **Create** `backend/tests/test_availability_serving.py` — serializer-level tests.
- **Create** `frontend/components/AvailabilityNote.tsx` — the context note.
- **Create** `frontend/components/__tests__/availabilityNote.test.tsx` — component test.
- **Modify** `frontend/lib/types.ts` — availability types + field on `Prediction`.
- **Modify** `frontend/app/match/[id]/page.tsx` — render the note.
- **Modify** `frontend/app/methodology/page.tsx` — update the limitation line.
- **Create** `ml/evaluation/availability_benchmark.py` — pure production-vs-availability paired benchmark.
- **Create** `ml/evaluation/availability_benchmark_test.py` — benchmark tests.
- **Create** `pipeline/run_availability_benchmark.py` — thin DB runner (best-effort; not unit-tested).

---

### Task 1: Pure availability core (`ml/models/availability.py`)

**Files:**
- Create: `ml/models/availability.py`
- Test: `ml/models/availability_test.py`

**Interfaces:**
- Consumes: `ml.models.goalscorers.player_rate(club_goals, club_minutes, wc_goals, wc_minutes, position) -> float` (existing).
- Produces:
  - `ATTACK_OFFSET_LO = -0.25`, `ATTACK_OFFSET_HI = 0.10`, `REFERENCE_XI_SIZE = 11`
  - `attack_capacity(players: list[dict]) -> float`
  - `reference_eleven(squad: list[dict]) -> list[dict]`
  - `availability_offset(announced_starters: list[dict], squad: list[dict]) -> tuple[float, dict] | None`
    where the dict is `{"attack_delta_pct": float, "players_out": [{"name": str, "weight": float}, ...]}`.
  - Player dicts use keys: `club_goals, club_minutes, wc_goals, wc_minutes, position, name, provider_player_id`.

- [ ] **Step 1: Write the failing tests**

```python
# ml/models/availability_test.py
"""Unit tests for the pure availability core (announced-XI attack adjustment)."""
import math

from ml.models.availability import (
    ATTACK_OFFSET_HI, ATTACK_OFFSET_LO, attack_capacity, availability_offset,
    reference_eleven,
)


def _p(pid, pos, cg, cm, wg=0, wm=0, name=None):
    return {"provider_player_id": pid, "name": name or f"p{pid}", "position": pos,
            "club_goals": cg, "club_minutes": cm, "wc_goals": wg, "wc_minutes": wm}


def _squad_11():
    # 1 elite striker + 10 ordinary regulars, all full-season minutes.
    return [_p(1, "F", 25, 2700, name="Star")] + [
        _p(i, "M" if i < 8 else "D", 2, 2700) for i in range(2, 12)
    ]


def test_full_strength_xi_has_zero_offset():
    squad = _squad_11()
    offset, expl = availability_offset(squad, squad)  # announced == usual XI
    assert offset == 0.0
    assert expl["attack_delta_pct"] == 0.0
    assert expl["players_out"] == []


def test_missing_striker_gives_negative_offset_and_names_him():
    squad = _squad_11() + [_p(99, "F", 0, 300, name="Sub")]  # a weak deputy
    # Announced XI = the ten regulars + the weak deputy (Star benched).
    announced = [p for p in squad if p["provider_player_id"] not in (1,)][:11]
    offset, expl = availability_offset(announced, squad)
    assert offset < 0.0
    assert expl["attack_delta_pct"] == round(math.exp(offset) - 1.0, 4)
    assert "Star" in {p["name"] for p in expl["players_out"]}


def test_offset_is_clamped_low():
    squad = [_p(1, "F", 40, 2700, name="Star")] + [_p(i, "D", 0, 2700) for i in range(2, 12)]
    weak = [_p(500 + i, "G", 0, 200) for i in range(11)]  # a keeper-only XI
    offset, _ = availability_offset(weak, squad)
    assert offset == ATTACK_OFFSET_LO


def test_offset_capped_when_xi_stronger_than_usual():
    squad = [_p(i, "D", 0, 2700) for i in range(1, 12)] + [_p(50, "F", 30, 400, name="WonderKid")]
    strong = [_p(50, "F", 30, 400, name="WonderKid")] + [_p(i, "D", 0, 2700) for i in range(1, 11)]
    offset, _ = availability_offset(strong, squad)
    assert offset <= ATTACK_OFFSET_HI


def test_reference_eleven_picks_top_by_minutes():
    squad = [_p(i, "M", 1, i * 100) for i in range(1, 15)]  # 14 players, ascending minutes
    ref = reference_eleven(squad)
    assert len(ref) == 11
    assert {p["provider_player_id"] for p in ref} == set(range(4, 15))  # top 11 by minutes


def test_none_when_no_announced_xi():
    assert availability_offset([], _squad_11()) is None


def test_none_when_squad_empty():
    assert availability_offset(_squad_11(), []) is None


def test_attack_capacity_is_positive_for_nonempty():
    assert attack_capacity([_p(1, "F", 10, 900)]) > 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/models/availability_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.models.availability'`.

- [ ] **Step 3: Write the implementation**

```python
# ml/models/availability.py
"""Player-availability adjustment for the match forecast (announced-XI only, v1).

Turns "who is actually in the announced XI" into a bounded, explainable offset to
a team's expected goals, reusing the goalscorers attacking weights. Pure functions
— no I/O, no DB. Shadow-first: the caller logs the adjusted forecast as a twin and
surfaces the explanation as context; it does not move the published number.
See docs/superpowers/specs/2026-07-03-availability-signal-design.md.
"""
from __future__ import annotations

import math

from ml.models.goalscorers import player_rate

# Attack offset clamp (log-lambda units). Deliberately asymmetric and tight: a
# missing player almost always subtracts, and the clamp guarantees a garbled or
# empty XI can never wreck a forecast. -0.25 ~= -22% attack, +0.10 ~= +10%.
ATTACK_OFFSET_LO = -0.25
ATTACK_OFFSET_HI = 0.10
REFERENCE_XI_SIZE = 11


def _rate(p: dict) -> float:
    """A player's shrunk goals-per-90 (attacking weight) via goalscorers.player_rate."""
    return player_rate(
        p.get("club_goals"), p.get("club_minutes"),
        p.get("wc_goals"), p.get("wc_minutes"), p.get("position"),
    )


def attack_capacity(players: list[dict]) -> float:
    """Sum of shrunk goals-per-90 over the given players — a rough 'how much
    scoring these individuals bring'. Reuses goalscorers.player_rate."""
    return sum(_rate(p) for p in players)


def reference_eleven(squad: list[dict]) -> list[dict]:
    """The squad's top eleven by total (club+WC) minutes — the usual starters."""
    return sorted(
        squad,
        key=lambda p: (p.get("club_minutes") or 0) + (p.get("wc_minutes") or 0),
        reverse=True,
    )[:REFERENCE_XI_SIZE]


def availability_offset(
    announced_starters: list[dict], squad: list[dict]
) -> tuple[float, dict] | None:
    """Bounded attack offset (log-lambda units) for one team plus an explanation,
    or None when it can't be computed (no XI, or reference capacity ~ 0).

    ratio = attack_capacity(announced XI) / attack_capacity(reference XI); the
    offset is ln(ratio) clamped to [ATTACK_OFFSET_LO, ATTACK_OFFSET_HI]. The
    explanation names the reference starters absent from the announced XI (by
    attacking weight desc) and attack_delta_pct = exp(offset) - 1.
    """
    if not announced_starters:
        return None
    reference = reference_eleven(squad)
    ref_cap = attack_capacity(reference)
    if ref_cap <= 0.0:
        return None
    ratio = attack_capacity(announced_starters) / ref_cap
    if ratio <= 0.0:
        offset = ATTACK_OFFSET_LO
    else:
        offset = max(ATTACK_OFFSET_LO, min(ATTACK_OFFSET_HI, math.log(ratio)))
    starting_ids = {p.get("provider_player_id") for p in announced_starters}
    missing = [p for p in reference if p.get("provider_player_id") not in starting_ids]
    missing.sort(key=_rate, reverse=True)
    explanation = {
        "attack_delta_pct": round(math.exp(offset) - 1.0, 4),
        "players_out": [
            {"name": p.get("name"), "weight": round(_rate(p), 4)} for p in missing
        ],
    }
    return offset, explanation
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ml/models/availability_test.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add ml/models/availability.py ml/models/availability_test.py
git commit -m "feat(ml): pure availability core — bounded attack offset from announced XI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: DB glue (`backend/app/availability.py`)

**Files:**
- Create: `backend/app/availability.py`
- Test: `backend/tests/test_availability.py`

**Interfaces:**
- Consumes: `ml.models.availability.availability_offset` (Task 1); `app.models.{Match, MatchLineup, Player}`.
- Produces:
  - `availability_inputs(db, match, side) -> tuple[list[dict], list[dict]] | None` — `(announced_starter_dicts, full_squad_dicts)`, or None if no stored XI for that side.
  - `availability_for_match(db, match) -> tuple[float, float, dict, dict] | None` — `(off_home, off_away, expl_home, expl_away)`, or None unless BOTH sides have an XI and both offsets compute.
- **Cycle note:** this module re-implements the tiny `_lineup_rows`/`_player_dict` helpers (mirrors `app/goalscorers.py`) instead of importing them, so it does NOT import `app.goalscorers` or `app.serializers`. That keeps `serializers → app.availability` free of the `serializers → goalscorers → serializers` cycle.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_availability.py
"""DB-level tests for the announced-XI availability glue."""
from datetime import datetime, timezone

from app.availability import availability_for_match, availability_inputs
from app.models import LineupPlayer, Match, MatchLineup, Player, Team


def _match(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    return m, h, a


def _squad(db, team_id, star_pid):
    # An elite striker (highest minutes, so it's in the reference XI) + 11 regulars.
    players = [Player(provider_player_id=star_pid, name="Star", team_id=team_id,
                      position="F", club_goals=25, club_minutes=3000, wc_goals=3, wc_minutes=270)]
    for i in range(11):
        players.append(Player(provider_player_id=star_pid * 100 + i, name=f"reg{i}",
                              team_id=team_id, position="M", club_goals=2,
                              club_minutes=2400, wc_goals=0, wc_minutes=270))
    db.add_all(players); db.commit()
    return players


def _lineup(db, match_id, side, starter_pids):
    ml = MatchLineup(match_id=match_id, side=side, provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.add(ml); db.commit()
    db.add_all([LineupPlayer(match_lineup_id=ml.id, name=f"pid{pid}", is_starter=True,
                             order=i, provider_player_id=pid)
                for i, pid in enumerate(starter_pids)])
    db.commit()


def test_none_when_no_lineup(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    assert availability_for_match(db_session, m) is None


def test_none_when_only_one_lineup(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    _lineup(db_session, m.id, "home", [1] + [100 + i for i in range(10)])  # away XI missing
    assert availability_for_match(db_session, m) is None


def test_both_lineups_home_missing_star(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    # Home XI = 11 regulars, Star (pid 1) benched.
    _lineup(db_session, m.id, "home", [100 + i for i in range(11)])
    # Away XI = Star (pid 2) + 10 regulars: full strength.
    _lineup(db_session, m.id, "away", [2] + [200 + i for i in range(10)])
    result = availability_for_match(db_session, m)
    assert result is not None
    off_home, off_away, expl_home, expl_away = result
    assert off_home < 0.0                       # home lost its striker
    assert "Star" in {p["name"] for p in expl_home["players_out"]}
    assert off_away == 0.0 or off_away >= -1e-9  # away roughly full strength


def test_inputs_join_stats(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1)
    _lineup(db_session, m.id, "home", [1])
    starters, squad = availability_inputs(db_session, m, "home")
    assert any(s["provider_player_id"] == 1 and s["club_goals"] == 25 for s in starters)
    assert len(squad) == 12
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_availability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.availability'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/availability.py
"""Announced-XI availability adjustment, wired to the DB (v1).

Loads a match's announced XI + squad and turns them into the per-team attack
offset from ml.models.availability. BOTH the daily writer (the shadow twin) and
the read path (the match-page note) go through here, so they never diverge.
Requires BOTH sides to have an announced XI — mirrors the goalscorers 'lineup
mode' gate; otherwise returns None (no adjustment, no note).

Self-contained on purpose: it re-implements the small lineup/player helpers
(mirroring app.goalscorers) rather than importing app.goalscorers or
app.serializers, so importing this from serializers.py introduces no cycle.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import LineupPlayer, Match, MatchLineup, Player
from ml.models.availability import availability_offset


def _lineup_rows(db: Session, match_id: int, side: str) -> list[LineupPlayer] | None:
    lineup = db.query(MatchLineup).filter_by(match_id=match_id, side=side).one_or_none()
    if lineup is None or not lineup.players:
        return None
    return list(lineup.players)


def _player_dict(p: Player) -> dict:
    return {"provider_player_id": p.provider_player_id, "name": p.name,
            "position": p.position, "club_goals": p.club_goals,
            "club_minutes": p.club_minutes, "wc_goals": p.wc_goals,
            "wc_minutes": p.wc_minutes}


def availability_inputs(
    db: Session, match: Match, side: str
) -> tuple[list[dict], list[dict]] | None:
    """(announced_starter_dicts, full_squad_dicts) for one side, or None when no
    announced XI is stored. Starters join the XI to Player stats by
    provider_player_id; an XI player with no stats row falls back to zeros (the
    position prior carries it, exactly as the goalscorers path does)."""
    team_id = match.team_home_id if side == "home" else match.team_away_id
    rows = _lineup_rows(db, match.id, side)
    if not rows:
        return None
    squad = db.query(Player).filter_by(team_id=team_id).all()
    by_pid = {p.provider_player_id: p for p in squad}
    starters: list[dict] = []
    for lp in rows:
        if not lp.is_starter:
            continue
        stat = by_pid.get(lp.provider_player_id)
        if stat is not None:
            starters.append(_player_dict(stat))
        else:
            starters.append({"provider_player_id": lp.provider_player_id,
                             "name": lp.name, "position": lp.position,
                             "club_goals": 0, "club_minutes": 0,
                             "wc_goals": 0, "wc_minutes": 0})
    return starters, [_player_dict(p) for p in squad]


def availability_for_match(
    db: Session, match: Match
) -> tuple[float, float, dict, dict] | None:
    """(off_home, off_away, expl_home, expl_away) or None unless BOTH sides have an
    announced XI and both offsets are computable."""
    home = availability_inputs(db, match, "home")
    away = availability_inputs(db, match, "away")
    if home is None or away is None:
        return None
    h = availability_offset(home[0], home[1])
    a = availability_offset(away[0], away[1])
    if h is None or a is None:
        return None
    return h[0], a[0], h[1], a[1]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_availability.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/availability.py backend/tests/test_availability.py
git commit -m "feat(api): DB glue for announced-XI availability (both-XI gate)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Pipeline twin writer (`pipeline/generate_predictions.py`)

**Files:**
- Modify: `pipeline/generate_predictions.py` (add `import math`; add `AVAILABILITY_MODEL_VERSION` near `SHADOW_MODEL_VERSION` line 34; add `write_availability_prediction` after `write_shadow_prediction` ~line 315; call it in the loop after `write_shadow_prediction` ~line 505)
- Test: `pipeline/generate_predictions_test.py` (append tests)

**Interfaces:**
- Consumes: `app.availability.availability_for_match` (Task 2); existing `predict_from_lambdas`, `estimate_strength`, `effective_gap`, `_host_adv`, `_write_prediction`; `ml.models.params.ModelParams`.
- Produces: `AVAILABILITY_MODEL_VERSION = "poisson-elo-v0.3+avail"`; `write_availability_prediction(db, match, payload, strengths, params) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# append to pipeline/generate_predictions_test.py
from datetime import datetime, timezone

from app.models import LineupPlayer, MatchLineup, Player
from ml.models.params import DEFAULT_PARAMS
from pipeline.generate_predictions import (
    AVAILABILITY_MODEL_VERSION, write_availability_prediction,
)


def _avail_payload(match_id):
    return {"match_id": match_id, "lambda_home": 2.0, "lambda_away": 1.0, "rho": -0.1,
            "probabilities": {"home_win": 0.55, "draw": 0.27, "away_win": 0.18},
            "predicted_score": {"home": 2, "away": 1, "probability": 0.12},
            "confidence": "Medium", "reasons": ["a", "b", "c"], "top_features": []}


def _scheduled_match_with_squads(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    h.elo_rating = a.elo_rating = 1700.0
    for team in (h, a):
        star = team.id
        db.add(Player(provider_player_id=star, name="Star", team_id=team.id, position="F",
                      club_goals=25, club_minutes=3000, wc_goals=3, wc_minutes=270))
        for i in range(11):
            db.add(Player(provider_player_id=star * 100 + i, name=f"reg{i}", team_id=team.id,
                          position="M", club_goals=2, club_minutes=2400, wc_goals=0, wc_minutes=270))
    db.commit()
    return m, h, a


def _add_lineup(db, match_id, side, starter_pids):
    ml = MatchLineup(match_id=match_id, side=side, provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.add(ml); db.commit()
    db.add_all([LineupPlayer(match_lineup_id=ml.id, name=f"pid{pid}", is_starter=True,
                             order=i, provider_player_id=pid)
                for i, pid in enumerate(starter_pids)])
    db.commit()


def test_availability_twin_written_when_both_xi(db_session):
    m, h, a = _scheduled_match_with_squads(db_session)
    _add_lineup(db_session, m.id, "home", [h.id * 100 + i for i in range(11)])            # 11 regulars, Star benched
    _add_lineup(db_session, m.id, "away", [a.id] + [a.id * 100 + i for i in range(10)])   # Star + 10 regulars
    write_availability_prediction(db_session, m, _avail_payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    twin = (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).one())
    assert twin.is_shadow is True
    assert twin.lambda_home < 2.0   # home attack cut by the availability offset (lambda *= exp(offset<0))


def test_no_availability_twin_without_lineups(db_session):
    m, h, a = _scheduled_match_with_squads(db_session)
    write_availability_prediction(db_session, m, _avail_payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    assert (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).count() == 0)


def test_availability_twin_blocked_after_kickoff(db_session):
    m, h, a = _scheduled_match_with_squads(db_session)
    _add_lineup(db_session, m.id, "home", [h.id] + [h.id * 100 + i for i in range(10)])
    _add_lineup(db_session, m.id, "away", [a.id] + [a.id * 100 + i for i in range(10)])
    m.status = "in_play"; db_session.commit()
    write_availability_prediction(db_session, m, _avail_payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    assert (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).count() == 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py -k availability -v`
Expected: FAIL — `ImportError: cannot import name 'AVAILABILITY_MODEL_VERSION'`.

- [ ] **Step 3: Add the import and constant**

At the top of `pipeline/generate_predictions.py`, add `import math` under `import logging` (line 10). Add the availability import after the existing `from app.models import ...` block:

```python
from app.availability import availability_for_match
```

After `SHADOW_MODEL_VERSION = "poisson-elo-v0.3-shadow"` (line 34), add:

```python
#: Version tag for the announced-XI availability twin. Mirrors SHADOW_MODEL_VERSION:
#: an is_shadow row, never served, logged pre-kickoff for the production-vs-
#: availability comparison (docs/superpowers/specs/2026-07-03-availability-signal-design.md).
AVAILABILITY_MODEL_VERSION = "poisson-elo-v0.3+avail"
```

- [ ] **Step 4: Write `write_availability_prediction`**

Add after `write_shadow_prediction` (after line 315):

```python
def write_availability_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """Write the announced-XI availability twin of a production payload, when BOTH
    sides have a stored XI (availability_for_match gates this). The per-team attack
    offset scales the production lambdas (lambda *= exp(offset)); the grid/triple/
    headline are recomputed through the same calibrated pipeline
    (predict_from_lambdas). No XI on either side -> no row (partial coverage is
    expected). Never served — is_shadow=True, tagged AVAILABILITY_MODEL_VERSION."""
    adj = availability_for_match(db, match)
    if adj is None:
        return
    off_home, off_away, _expl_home, _expl_away = adj
    lam_h = payload["lambda_home"] * math.exp(off_home)
    lam_a = payload["lambda_away"] * math.exp(off_away)
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    pred = predict_from_lambdas(
        lam_h, lam_a, rho=params.rho, temperature=params.temperature,
        calibrator=params.calibrator,
        eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
    )
    twin = {
        **payload,
        "probabilities": {
            "home_win": round(pred.prob_home_win, 4),
            "draw": round(pred.prob_draw, 4),
            "away_win": round(pred.prob_away_win, 4),
        },
        "predicted_score": {
            "home": pred.score_home, "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "lambda_home": round(pred.lambda_home, 4),
        "lambda_away": round(pred.lambda_away, 4),
    }
    _write_prediction(db, match, twin, AVAILABILITY_MODEL_VERSION, is_shadow=True)
```

- [ ] **Step 5: Wire it into the generation loop**

In `generate_predictions`, right after the `write_shadow_prediction(db, match, payload, strengths, params)` call (line 505), add:

```python
        write_availability_prediction(db, match, payload, strengths, params)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py -k availability -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Run the whole predictions test file (regression)**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 8: Commit**

```bash
git add pipeline/generate_predictions.py pipeline/generate_predictions_test.py
git commit -m "feat(pipeline): log availability-adjusted shadow twin from announced XI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Serve the availability note (`schemas` + `serializers`)

**Files:**
- Modify: `backend/app/schemas/__init__.py` (add three classes; add `availability` to `PredictionOut` after `goal_markets`, line 94)
- Modify: `backend/app/serializers.py` (import `availability_for_match`; add `_availability_note` + `availability_out`; set `availability=availability_out(db, match)` in `prediction_to_out`)
- Test: `backend/tests/test_availability_serving.py`

**Interfaces:**
- Consumes: `app.availability.availability_for_match` (Task 2).
- Produces:
  - `schemas.AvailabilityPlayerOut{name: str, weight: float}`
  - `schemas.TeamAvailabilityOut{side: str, attack_delta_pct: float, players_out: list[AvailabilityPlayerOut], note: str}`
  - `schemas.AvailabilityOut{has_lineup: bool, per_team: list[TeamAvailabilityOut]}`
  - `PredictionOut.availability: AvailabilityOut | None = None`
  - `serializers.availability_out(db, match) -> schemas.AvailabilityOut | None`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_availability_serving.py
"""Serializer-level tests: PredictionOut carries the availability note when both
XIs are known, and None otherwise."""
from datetime import datetime, timezone

from app.models import LineupPlayer, Match, MatchLineup, Player, Prediction, Team
from app.serializers import prediction_to_out


def _match_pred(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    pred = Prediction(match_id=m.id, model_version="v", prob_home_win=0.55,
                      prob_draw=0.27, prob_away_win=0.18, lambda_home=2.0,
                      lambda_away=1.0, rho=-0.1, confidence="Medium",
                      predicted_score_home=2, predicted_score_away=1,
                      predicted_score_prob=0.1, reasons=["a", "b", "c"], top_features=[])
    db.add(pred); db.commit()
    return m, h, a, pred


def _squad(db, team_id, star_pid):
    db.add(Player(provider_player_id=star_pid, name="Star", team_id=team_id, position="F",
                  club_goals=25, club_minutes=3000, wc_goals=3, wc_minutes=270))
    for i in range(11):
        db.add(Player(provider_player_id=star_pid * 100 + i, name=f"reg{i}", team_id=team_id,
                      position="M", club_goals=2, club_minutes=2400, wc_goals=0, wc_minutes=270))
    db.commit()


def _lineup(db, match_id, side, pids):
    ml = MatchLineup(match_id=match_id, side=side, provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.add(ml); db.commit()
    db.add_all([LineupPlayer(match_lineup_id=ml.id, name=f"pid{p}", is_starter=True,
                             order=i, provider_player_id=p) for i, p in enumerate(pids)])
    db.commit()


def test_prediction_out_has_availability_when_both_xi(db_session):
    m, h, a, pred = _match_pred(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    _lineup(db_session, m.id, "home", [100 + i for i in range(11)])   # 11 regulars, Star (1) benched
    _lineup(db_session, m.id, "away", [2] + [200 + i for i in range(10)])     # full strength
    out = prediction_to_out(db_session, m, pred)
    assert out.availability is not None
    assert out.availability.has_lineup is True
    home_block = next(t for t in out.availability.per_team if t.side == "home")
    assert home_block.attack_delta_pct < 0.0
    assert "Star" in home_block.note
    # The published triple is unchanged by availability.
    assert out.probabilities.home_win == 0.55


def test_prediction_out_availability_none_without_xi(db_session):
    m, h, a, pred = _match_pred(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    out = prediction_to_out(db_session, m, pred)
    assert out.availability is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_availability_serving.py -v`
Expected: FAIL — `AttributeError: ... object has no attribute 'availability'` (PredictionOut lacks the field).

- [ ] **Step 3: Add the schemas**

In `backend/app/schemas/__init__.py`, add (right before `class PredictionOut` at line 69):

```python
class AvailabilityPlayerOut(BaseModel):
    name: str
    weight: float


class TeamAvailabilityOut(BaseModel):
    side: str  # "home" | "away"
    attack_delta_pct: float
    players_out: list[AvailabilityPlayerOut]
    note: str


class AvailabilityOut(BaseModel):
    """Announced-XI availability context (v1). Explanation only — it does NOT move
    the published `probabilities`; the adjusted forecast is logged as a shadow twin."""
    has_lineup: bool
    per_team: list[TeamAvailabilityOut]
```

Then add the field to `PredictionOut`, immediately after `goal_markets: GoalMarketsOut | None = None` (line 94):

```python
    availability: AvailabilityOut | None = None
```

- [ ] **Step 4: Add `availability_out` to the serializer and wire it in**

In `backend/app/serializers.py`, add the import near the other `from app.*` imports (after line 14):

```python
from app.availability import availability_for_match
```

Add these functions (e.g. just above `prediction_to_out`, line 86):

```python
def _availability_note(team_name: str, expl: dict) -> str:
    """One human line: who's missing from the usual XI and the attack impact."""
    if not expl["players_out"]:
        return f"{team_name}: announced XI at full attacking strength."
    outs = ", ".join(p["name"] for p in expl["players_out"][:3])
    pct_txt = f"{expl['attack_delta_pct'] * 100.0:+.0f}%"
    return f"{team_name}: usual XI missing {outs} → attack {pct_txt}."


def availability_out(db: Session, match: Match) -> schemas.AvailabilityOut | None:
    """Announced-XI availability context for the match page (Task: availability
    signal). None unless BOTH sides have a stored XI. Explanation only — the
    published triple is untouched; the adjusted forecast lives in the shadow log."""
    adj = availability_for_match(db, match)
    if adj is None:
        return None
    off_home, off_away, expl_home, expl_away = adj
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    names = {"home": home.name if home else "Home", "away": away.name if away else "Away"}
    per_team = []
    for side, expl in (("home", expl_home), ("away", expl_away)):
        per_team.append(schemas.TeamAvailabilityOut(
            side=side,
            attack_delta_pct=expl["attack_delta_pct"],
            players_out=[schemas.AvailabilityPlayerOut(**p) for p in expl["players_out"]],
            note=_availability_note(names[side], expl),
        ))
    return schemas.AvailabilityOut(has_lineup=True, per_team=per_team)
```

Finally, in `prediction_to_out`, add the field to the `schemas.PredictionOut(...)` return (after `goal_markets=...`, line 120):

```python
        availability=availability_out(db, match),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_availability_serving.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Regression — serializer + schema suites**

Run: `.venv/bin/python -m pytest backend/tests/test_schema.py backend/tests/test_goalscorers_serving.py backend/tests/test_availability_serving.py -v`
Expected: PASS (existing PredictionOut consumers unaffected — the new field defaults to None).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/serializers.py backend/tests/test_availability_serving.py
git commit -m "feat(api): serve announced-XI availability note on PredictionOut

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Frontend note + methodology copy

**Files:**
- Modify: `frontend/lib/types.ts` (add availability types; add field to `Prediction`, line 91)
- Create: `frontend/components/AvailabilityNote.tsx`
- Create: `frontend/components/__tests__/availabilityNote.test.tsx`
- Modify: `frontend/app/match/[id]/page.tsx` (import + render in the overview)
- Modify: `frontend/app/methodology/page.tsx` (limitation line ~316)

**Interfaces:**
- Consumes: `Prediction.availability` (from Task 4's API shape).
- Produces: `AvailabilityNote({ availability }: { availability: Availability | null | undefined })`.

- [ ] **Step 1: Add the TypeScript types**

In `frontend/lib/types.ts`, add before `export interface Prediction` (line 68):

```typescript
export interface AvailabilityPlayer {
  name: string;
  weight: number;
}

export interface TeamAvailability {
  side: string;
  attack_delta_pct: number;
  players_out: AvailabilityPlayer[];
  note: string;
}

/** Announced-XI availability context (explanation only — does not move the
 *  published probabilities; the adjusted forecast is logged as a shadow twin). */
export interface Availability {
  has_lineup: boolean;
  per_team: TeamAvailability[];
}
```

Add the field to `Prediction`, after `goal_markets: GoalMarkets | null;` (line 91):

```typescript
  availability?: Availability | null;
```

- [ ] **Step 2: Write the failing component test**

```tsx
// frontend/components/__tests__/availabilityNote.test.tsx
import { render, screen } from "@testing-library/react";
import { AvailabilityNote } from "@/components/AvailabilityNote";
import type { Availability } from "@/lib/types";

const availability: Availability = {
  has_lineup: true,
  per_team: [
    { side: "home", attack_delta_pct: -0.08, note: "France: usual XI missing Mbappe → attack -8%.",
      players_out: [{ name: "Mbappe", weight: 0.58 }] },
    { side: "away", attack_delta_pct: 0.0, note: "Senegal: announced XI at full attacking strength.",
      players_out: [] },
  ],
};

test("renders per-team notes and the not-in-the-number caveat", () => {
  render(<AvailabilityNote availability={availability} />);
  expect(screen.getByText(/France: usual XI missing Mbappe/)).toBeInTheDocument();
  expect(screen.getByText(/Senegal: announced XI at full attacking strength/)).toBeInTheDocument();
  expect(screen.getByText(/not reflected in the number above/i)).toBeInTheDocument();
});

test("renders nothing when there is no lineup", () => {
  const { container } = render(<AvailabilityNote availability={null} />);
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx jest availabilityNote`
Expected: FAIL — cannot find module `@/components/AvailabilityNote`.

- [ ] **Step 4: Write the component**

```tsx
// frontend/components/AvailabilityNote.tsx
import type { Availability } from "@/lib/types";

/** Announced-XI availability context. Shows, per team, who is missing from the
 *  usual XI and the directional attack impact — explicitly NOT folded into the
 *  published probabilities (the adjusted forecast is logged for evaluation).
 *  Renders nothing until both announced XIs are known. */
export function AvailabilityNote({
  availability,
}: {
  availability: Availability | null | undefined;
}) {
  if (!availability?.has_lineup) return null;
  return (
    <section className="glass rounded-2xl p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-display text-lg font-bold text-foreground">Availability</h2>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
          Experimental
        </span>
      </div>
      <ul className="space-y-1.5">
        {availability.per_team.map((t) => (
          <li key={t.side} className="text-sm leading-relaxed text-foreground">
            {t.note}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Context from the announced XI — not reflected in the number above; logged for evaluation.
      </p>
    </section>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx jest availabilityNote`
Expected: PASS (2 passed).

- [ ] **Step 6: Render it on the match page**

In `frontend/app/match/[id]/page.tsx`, add the import after the `LikelyScorers` import (line 23):

```tsx
import { AvailabilityNote } from "@/components/AvailabilityNote";
```

In the overview block, add the note right after the `LikelyScorers` section (after line 133):

```tsx
            {/* Availability — announced-XI context (experimental; not in the number). */}
            <AvailabilityNote availability={p.availability} />
```

- [ ] **Step 7: Update the methodology limitation copy**

In `frontend/app/methodology/page.tsx`, replace the limitation line (line ~316):

```tsx
            <li>Team-level model: individual player form and injuries aren&apos;t factored in.</li>
```

with:

```tsx
            <li>
              The published number is team-level. When an announced XI is available we surface
              player availability as context and log an experimental adjusted forecast — it does
              not move the published number yet (it must first clear our accuracy gate).
            </li>
```

- [ ] **Step 8: Typecheck, lint, and run the frontend tests**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: PASS (typecheck clean; jest green, including the new test).

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/types.ts frontend/components/AvailabilityNote.tsx frontend/components/__tests__/availabilityNote.test.tsx frontend/app/match/[id]/page.tsx frontend/app/methodology/page.tsx
git commit -m "feat(web): announced-XI availability note + honest methodology copy

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Measurement harness (`ml/evaluation/availability_benchmark.py`)

**Files:**
- Create: `ml/evaluation/availability_benchmark.py`
- Test: `ml/evaluation/availability_benchmark_test.py`
- Create: `pipeline/run_availability_benchmark.py` (thin DB runner; exercised manually)

**Interfaces:**
- Consumes: `ml.evaluation.backtest.compute_metrics(probs: list[tuple], labels: list[str]) -> dict` (existing, same as `market_benchmark`).
- Produces: `benchmark_availability(prod_probs, avail_probs, labels, n_bootstrap=2000, seed=26) -> dict` with keys `n_matches, production, availability, diff_log_loss, diff_ci95, availability_win_rate`.

- [ ] **Step 1: Write the failing tests**

```python
# ml/evaluation/availability_benchmark_test.py
"""Tests for the paired production-vs-availability benchmark."""
import pytest

from ml.evaluation.availability_benchmark import benchmark_availability


def test_availability_beats_production_when_closer_to_outcomes():
    # Home always wins ("H"); availability puts more mass on H than production.
    labels = ["H"] * 40
    prod = [(0.40, 0.30, 0.30)] * 40
    avail = [(0.70, 0.20, 0.10)] * 40
    res = benchmark_availability(avail_probs=avail, prod_probs=prod, labels=labels)
    assert res["diff_log_loss"] < 0            # availability LL - production LL < 0
    assert res["diff_ci95"][1] < 0             # whole CI below 0 => credible
    assert res["availability_win_rate"] == 1.0
    assert res["n_matches"] == 40


def test_identical_predictors_have_zero_diff():
    labels = ["H", "D", "A"] * 10
    p = [(0.4, 0.3, 0.3)] * 30
    res = benchmark_availability(prod_probs=p, avail_probs=p, labels=labels)
    assert res["diff_log_loss"] == 0.0


def test_raises_on_empty():
    with pytest.raises(ValueError):
        benchmark_availability(prod_probs=[], avail_probs=[], labels=[])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ml/evaluation/availability_benchmark_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.evaluation.availability_benchmark'`.

- [ ] **Step 3: Write the implementation**

```python
# ml/evaluation/availability_benchmark.py
"""Paired production-vs-availability comparison on realized outcomes.

Once finished matches carry BOTH a production prediction AND an availability twin
(pipeline.generate_predictions writes the twin tagged AVAILABILITY_MODEL_VERSION),
this scores whether folding announced-XI availability into the forecast improves
out-of-sample log-loss — the gate for ever promoting the twin to the published
number (docs/superpowers/specs/2026-07-03-availability-signal-design.md).

Pure module — no DB, no network. Orchestration lives in
pipeline/run_availability_benchmark.py. Mirrors market_benchmark.benchmark's shape,
but compares two model predictors against the outcome instead of model vs market.
"""
from __future__ import annotations

import math
import random

from ml.evaluation.backtest import compute_metrics

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15


def _log_loss_one(probs, label: str) -> float:
    p = max(_EPS, min(1.0 - _EPS, probs[_LABEL_INDEX[label]]))
    return -math.log(p)


def benchmark_availability(
    prod_probs: list, avail_probs: list, labels: list[str],
    n_bootstrap: int = 2000, seed: int = 26,
) -> dict:
    """Paired (availability LL - production LL) over the same finished matches.

    diff_log_loss < 0 with diff_ci95 fully below 0 => the availability-adjusted
    forecast beats the published team-level one out of sample (the promotion
    signal). Straddling 0 => no credible difference.
    """
    if not labels:
        raise ValueError("no matches to benchmark")

    diffs = [
        _log_loss_one(av, lb) - _log_loss_one(pr, lb)
        for pr, av, lb in zip(prod_probs, avail_probs, labels)
    ]
    rng = random.Random(seed)
    n = len(diffs)
    boot = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_bootstrap)
    )
    lo, hi = boot[int(0.025 * n_bootstrap)], boot[int(0.975 * n_bootstrap)]
    return {
        "n_matches": n,
        "production": compute_metrics(prod_probs, labels),
        "availability": compute_metrics(avail_probs, labels),
        "diff_log_loss": sum(diffs) / n,
        "diff_ci95": (lo, hi),
        "availability_win_rate": sum(1 for d in diffs if d < 0) / n,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ml/evaluation/availability_benchmark_test.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Write the thin DB runner**

```python
# pipeline/run_availability_benchmark.py
"""Score the availability twin vs the published prediction on finished matches.

Best-effort operational script (not unit-tested): pulls, per finished match, the
latest published prediction (is_shadow=False) and the latest availability twin
(model_version == AVAILABILITY_MODEL_VERSION), labels each by the final score, and
prints the paired benchmark. Prints a friendly notice until enough matches carry
both rows. Run: `.venv/bin/python -m pipeline.run_availability_benchmark`.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Match, Prediction
from ml.evaluation.availability_benchmark import benchmark_availability
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION


def _latest(db, match_id, *, avail: bool) -> Prediction | None:
    q = db.query(Prediction).filter_by(match_id=match_id)
    q = (q.filter(Prediction.model_version == AVAILABILITY_MODEL_VERSION) if avail
         else q.filter(Prediction.is_shadow.is_(False)))
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def main() -> None:
    db = SessionLocal()
    try:
        prod_probs, avail_probs, labels = [], [], []
        finished = (db.query(Match)
                    .filter(Match.status == "finished",
                            Match.score_home.isnot(None), Match.score_away.isnot(None))
                    .all())
        for m in finished:
            prod = _latest(db, m.id, avail=False)
            avail = _latest(db, m.id, avail=True)
            if prod is None or avail is None:
                continue
            label = "H" if m.score_home > m.score_away else ("A" if m.score_home < m.score_away else "D")
            prod_probs.append((prod.prob_home_win, prod.prob_draw, prod.prob_away_win))
            avail_probs.append((avail.prob_home_win, avail.prob_draw, avail.prob_away_win))
            labels.append(label)

        if not labels:
            print("No finished matches yet carry both a published prediction and an "
                  "availability twin. Nothing to benchmark.")
            return
        res = benchmark_availability(prod_probs, avail_probs, labels)
        lo, hi = res["diff_ci95"]
        print(f"=== Availability twin vs published ({res['n_matches']} matches) ===")
        print(f"  production   log-loss: {res['production']['log_loss']:.4f}")
        print(f"  availability log-loss: {res['availability']['log_loss']:.4f}")
        print(f"  paired mean LL diff (avail - prod): {res['diff_log_loss']:+.4f}  "
              f"CI95 [{lo:+.4f}, {hi:+.4f}]")
        print(f"  availability win rate: {res['availability_win_rate']:.1%}")
        print("  verdict:", "AVAILABILITY BEATS PUBLISHED (credible)" if hi < 0
              else "PUBLISHED BEATS AVAILABILITY (credible)" if lo > 0
              else "NO CREDIBLE DIFFERENCE (CI straddles 0)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Import-smoke the runner**

Run: `.venv/bin/python -c "import pipeline.run_availability_benchmark"`
Expected: no output, exit 0 (imports resolve).

- [ ] **Step 7: Commit**

```bash
git add ml/evaluation/availability_benchmark.py ml/evaluation/availability_benchmark_test.py pipeline/run_availability_benchmark.py
git commit -m "feat(ml): paired availability-vs-published benchmark + DB runner

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Full suite + PR

**Files:** none (verification + PR prep)

- [ ] **Step 1: Run the full Python suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS (backend, ml, pipeline all green).

- [ ] **Step 2: Run the full frontend suite**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: PASS.

- [ ] **Step 3: Push and open the PR (do NOT merge)**

```bash
git push -u origin feat/availability-signal
gh pr create --base main --title "feat: announced-XI availability signal (shadow-first, explanation-only)" --body "$(cat <<'EOF'
Factors announced-XI player availability into the WC26 forecast as a bounded, explainable attack-side adjustment.

- **Shadow-first:** logs an availability-adjusted `is_shadow` twin (`poisson-elo-v0.3+avail`); the published number is untouched.
- **Explanation-only:** the match page shows one number plus an availability context note; no competing percentages.
- **Free path:** announced XI + existing player-form data. No paid injuries feed, no DB migration.
- **Both-XI gate:** adjustment only when both sides' XIs are known.
- **Measurement:** `benchmark_availability` + runner, ready to score the twin vs the published number once results accumulate (the promotion gate).

Spec: `docs/superpowers/specs/2026-07-03-availability-signal-design.md`
Plan: `docs/superpowers/plans/2026-07-03-availability-signal.md`

Full Python + frontend suites green. Next step (separate): source a FREE injuries feed to extend the same adjustment to day-ahead availability.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2 note:** Stop here and hand the PR to a human — do not merge (guarded pipeline).

---

## Notes for the executor

- **Coverage is partial by design.** The twin is written only by a `generate_predictions` run that happens after both XIs are stored (~T-60 to kickoff). The *note* is independent: it recomputes at read time whenever both XIs are cached, so it can appear even if no twin was ever written. Neither depends on the other.
- **Do not** add a `UNIQUE(match_id, ...)` constraint or any migration — the append-only log writes multiple rows per match by design.
- **Do not** touch `write_shadow_prediction`, the group/knockout sims, or any `is_shadow=False` path.
- If `math.log` is ever handed a non-positive ratio it's already guarded; keep that guard.
