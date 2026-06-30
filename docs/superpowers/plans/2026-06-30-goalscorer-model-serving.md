# Goalscorer Model + Serving (Stage 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the ingested `Player` stats into ranked "likely scorers" per team for a match — a pure allocation model + a lazy `GET /api/matches/{id}/goalscorers` endpoint, in squad or lineup mode.

**Architecture:** A pure `ml/models/goalscorers.py` distributes a team's expected goals λ across its players by a club+WC+position blended scoring rate × a playing-time weight, then `P(score)=1-e^-xG`. A serializer helper loads each team's `Player` rows (squad mode) or the announced XI joined by `provider_player_id` (lineup mode) and computes the block. A lazy endpoint serves it (like `/lineups`), null when no player data. Compute-on-read; no migration.

**Tech Stack:** Python (math, dataclass-free dicts), SQLAlchemy, FastAPI, pytest.

## Global Constraints

- **Same distribution discipline as Phase 1:** the per-player xG must sum to the team's λ over included players (`Σ xG_p = λ_team`). Read λ from the stored `Prediction.lambda_home`/`lambda_away`.
- **Model (verbatim):** `rate_p = (club_goals + wc_goals + K·pos_rate) / ((club_minutes+wc_minutes)/90 + K)`; `weight_p = rate_p · mins_p`; `share_p = weight_p/Σweight`; `xG_p = λ·share_p`; `P(≥1)=1-e^-xG`; `P(≥2)=1-e^-xG·(1+xG)`. Constants: `POS_RATE={"F":0.45,"M":0.12,"D":0.04,"G":0.005}`, `DEFAULT_RATE=0.08` (unknown position), `K_SHRINK=10.0`, `FULL_SEASON_MINUTES=3000.0`. All probabilities rounded 4 dp.
- **Playing-time weight `mins_p`:** lineup mode → starter `1.0`, sub `0.25`, not-listed `0.0`; squad mode → `clamp((club_minutes+wc_minutes)/FULL_SEASON_MINUTES, 0, 1)`.
- **Mode selection:** if the match has a stored announced lineup (≥1 `MatchLineup` with players), mode=`"lineup"` and only lineup players are scored; else mode=`"squad"` over all the team's `Player` rows.
- **Nulls → 0** for any missing stat. A player with no `Player` stats row (lineup mode) still scores via the position prior (zeros + pos_rate).
- **Lazy + null-safe:** the endpoint returns the block or `null`/`{available:false}` when there is no player data for either team — never a 5xx, never fabricated players.
- Reuse Stage 1a/1b: `Player` (team_id, provider_player_id, position, club/wc goals+minutes), `LineupPlayer.provider_player_id`, `Match.home_team_id/away_team_id`, `latest_prediction`.

---

### Task 1: Pure allocation model (`ml/models/goalscorers.py`)

**Files:**
- Create: `ml/models/goalscorers.py`
- Test: `ml/models/goalscorers_test.py`

**Interfaces:**
- Produces: `player_rate(club_goals, club_minutes, wc_goals, wc_minutes, position) -> float`; `squad_minutes_weight(club_minutes, wc_minutes) -> float`; `goalscorers(lambda_team: float, players: list[dict], mode: str) -> list[dict]`. Each input player dict has keys `provider_player_id, name, position, club_goals, club_minutes, wc_goals, wc_minutes, lineup_status` (`lineup_status` ∈ {"starter","sub",None}). Each output dict has `provider_player_id, name, position, xg, p_score, p_score_2plus`, sorted by `xg` desc; players with zero weight are omitted.

- [ ] **Step 1: Write the failing test**

Create `ml/models/goalscorers_test.py`:

```python
import math

from ml.models.goalscorers import goalscorers, player_rate, squad_minutes_weight


def _p(pid, name, pos, cg, cm, wg, wm, status=None):
    return {"provider_player_id": pid, "name": name, "position": pos,
            "club_goals": cg, "club_minutes": cm, "wc_goals": wg, "wc_minutes": wm,
            "lineup_status": status}


def test_player_rate_blends_form_and_position_prior():
    # a striker with 20 club goals in ~2700 min (30 nineties): pulled toward ~0.66/90
    high = player_rate(20, 2700, 0, 0, "F")
    # a striker with no minutes -> pure position prior 0.45
    cold = player_rate(0, 0, 0, 0, "F")
    assert abs(cold - 0.45) < 1e-9
    assert 0.5 < high < 0.7


def test_squad_minutes_weight_clamps():
    assert squad_minutes_weight(3000, 0) == 1.0
    assert squad_minutes_weight(6000, 0) == 1.0
    assert squad_minutes_weight(600, 0) == 0.2
    assert squad_minutes_weight(0, 0) == 0.0


def test_goalscorers_xg_sums_to_lambda_and_is_sorted():
    players = [
        _p(1, "Striker", "F", 18, 2700, 2, 270, "starter"),
        _p(2, "Mid", "M", 6, 2700, 0, 270, "starter"),
        _p(3, "Defender", "D", 1, 2700, 0, 270, "starter"),
    ]
    out = goalscorers(2.0, players, "lineup")
    assert abs(sum(r["xg"] for r in out) - 2.0) < 1e-3      # conserves team lambda
    assert out[0]["name"] == "Striker"                       # sorted by xg desc
    assert out[0]["p_score"] == round(1 - math.exp(-out[0]["xg"]), 4)
    assert all(r["p_score"] >= r["p_score_2plus"] for r in out)


def test_lineup_mode_excludes_not_listed_players():
    players = [
        _p(1, "Starter", "F", 10, 2000, 1, 200, "starter"),
        _p(2, "Benched", "F", 12, 2000, 1, 200, "sub"),
        _p(3, "NotListed", "F", 15, 2000, 1, 200, None),
    ]
    out = goalscorers(2.0, players, "lineup")
    names = {r["name"] for r in out}
    assert "NotListed" not in names          # mins weight 0 -> omitted
    assert {"Starter", "Benched"} <= names


def test_returns_empty_when_total_weight_zero():
    assert goalscorers(2.0, [_p(1, "X", "G", 0, 0, 0, 0, None)], "lineup") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest ml/models/goalscorers_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.models.goalscorers'`.

- [ ] **Step 3: Implement the model**

Create `ml/models/goalscorers.py`:

```python
"""Distribute a team's expected goals (lambda) across its players to rank likely
scorers. xG_p = lambda * share_p, where share_p is proportional to a club+WC+
position blended scoring rate times a playing-time weight. P(score)=1-e^-xG.
Pure functions — same scoreline distribution philosophy as the goal-total markets."""
from __future__ import annotations

import math

# Goals-per-90 base rate by our position code (G/D/M/F); the shrinkage prior.
POS_RATE = {"F": 0.45, "M": 0.12, "D": 0.04, "G": 0.005}
DEFAULT_RATE = 0.08          # unknown/None position
K_SHRINK = 10.0              # position-prior pseudo-90s (shrinkage strength)
FULL_SEASON_MINUTES = 3000.0  # a regular starter's ~season minutes (squad weight)

# Playing-time weight by announced-lineup status.
_LINEUP_WEIGHT = {"starter": 1.0, "sub": 0.25}


def player_rate(club_goals: int, club_minutes: int, wc_goals: int, wc_minutes: int,
                position: str | None) -> float:
    """Shrunk goals-per-90: observed (club+WC) goals over 90s, pulled toward the
    position prior by K_SHRINK pseudo-90s. Low-minute players lean on position."""
    pos = POS_RATE.get(position or "", DEFAULT_RATE)
    nineties = ((club_minutes or 0) + (wc_minutes or 0)) / 90.0
    goals = (club_goals or 0) + (wc_goals or 0)
    return (goals + K_SHRINK * pos) / (nineties + K_SHRINK)


def squad_minutes_weight(club_minutes: int, wc_minutes: int) -> float:
    """Pre-lineup playing-time proxy: share of a full starter season, clamped."""
    total = (club_minutes or 0) + (wc_minutes or 0)
    return max(0.0, min(1.0, total / FULL_SEASON_MINUTES))


def goalscorers(lambda_team: float, players: list[dict], mode: str) -> list[dict]:
    """Ranked likely scorers for one team. `mode` is 'lineup' (weight by announced
    status) or 'squad' (weight by season minutes). Returns dicts with xg / p_score /
    p_score_2plus, sorted by xg desc; zero-weight players are omitted."""
    weighted: list[tuple[dict, float]] = []
    for p in players:
        rate = player_rate(p.get("club_goals"), p.get("club_minutes"),
                           p.get("wc_goals"), p.get("wc_minutes"), p.get("position"))
        if mode == "lineup":
            mins = _LINEUP_WEIGHT.get(p.get("lineup_status"), 0.0)
        else:
            mins = squad_minutes_weight(p.get("club_minutes"), p.get("wc_minutes"))
        weighted.append((p, rate * mins))

    total = sum(w for _, w in weighted)
    if total <= 0.0 or lambda_team is None or lambda_team <= 0.0:
        return []

    out: list[dict] = []
    for p, w in weighted:
        if w <= 0.0:
            continue
        xg = lambda_team * (w / total)
        out.append({
            "provider_player_id": p.get("provider_player_id"),
            "name": p.get("name"),
            "position": p.get("position"),
            "xg": round(xg, 4),
            "p_score": round(1.0 - math.exp(-xg), 4),
            "p_score_2plus": round(1.0 - math.exp(-xg) * (1.0 + xg), 4),
        })
    out.sort(key=lambda r: r["xg"], reverse=True)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest ml/models/goalscorers_test.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ml/models/goalscorers.py ml/models/goalscorers_test.py
git commit -m "feat(ml): goalscorers allocation model (distribute lambda by scoring share)"
```

---

### Task 2: Serializer + schema for the goalscorers block

**Files:**
- Modify: `backend/app/schemas/__init__.py` (add `GoalscorerOut`, `GoalscorersOut`)
- Create: `backend/app/goalscorers.py` (the serving helper)
- Test: `backend/tests/test_goalscorers_serving.py`

**Interfaces:**
- Consumes: `goalscorers()` (Task 1); `Player`, `LineupPlayer`, `MatchLineup`, `Match`, `latest_prediction`.
- Produces: `GoalscorersOut{mode: str, home: list[GoalscorerOut], away: list[GoalscorerOut]}`; `GoalscorerOut{name: str, position: str|None, p_score: float, p_score_2plus: float, xg: float}`; `build_goalscorers(db: Session, match: Match, top_n: int = 8) -> GoalscorersOut | None` — None when there's no player data for either side.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_goalscorers_serving.py`:

```python
from datetime import datetime, timezone

from app.goalscorers import build_goalscorers
from app.models import (LineupPlayer, Match, MatchLineup, Player, Prediction, Team)


def _match_with_pred(db, lam_home=2.0, lam_away=0.8):
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True,
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    db.add(Prediction(match_id=m.id, model_version="v", prob_home_win=0.6,
                      prob_draw=0.2, prob_away_win=0.2, lambda_home=lam_home,
                      lambda_away=lam_away, rho=-0.1))
    db.commit()
    return m, h, a


def test_squad_mode_when_no_lineup(db_session):
    m, h, a = _match_with_pred(db_session)
    db_session.add_all([
        Player(provider_player_id=1, name="HStriker", team_id=h.id, position="F",
               club_goals=18, club_minutes=2700, wc_goals=2, wc_minutes=270),
        Player(provider_player_id=2, name="HDef", team_id=h.id, position="D",
               club_goals=1, club_minutes=2700, wc_goals=0, wc_minutes=270),
        Player(provider_player_id=3, name="AStriker", team_id=a.id, position="F",
               club_goals=10, club_minutes=2000, wc_goals=0, wc_minutes=180),
    ])
    db_session.commit()
    out = build_goalscorers(db_session, m)
    assert out is not None
    assert out.mode == "squad"
    assert out.home[0].name == "HStriker"
    assert abs(sum(g.xg for g in out.home) - 2.0) < 1e-3      # conserves lambda_home


def test_lineup_mode_uses_announced_xi(db_session):
    m, h, a = _match_with_pred(db_session)
    db_session.add_all([
        Player(provider_player_id=1, name="HStriker", team_id=h.id, position="F",
               club_goals=18, club_minutes=2700, wc_goals=2, wc_minutes=270),
        Player(provider_player_id=9, name="HBench", team_id=h.id, position="F",
               club_goals=20, club_minutes=2700, wc_goals=3, wc_minutes=270),
        Player(provider_player_id=3, name="AStriker", team_id=a.id, position="F",
               club_goals=10, club_minutes=2000, wc_goals=0, wc_minutes=180),
    ])
    ml = MatchLineup(match_id=m.id, side="home", provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db_session.add(ml); db_session.commit()
    db_session.add_all([
        LineupPlayer(match_lineup_id=ml.id, name="HStriker", is_starter=True, order=0, provider_player_id=1),
        LineupPlayer(match_lineup_id=ml.id, name="HBench", is_starter=False, order=1, provider_player_id=9),
    ])
    db_session.commit()
    out = build_goalscorers(db_session, m)
    assert out.mode == "lineup"
    names = {g.name for g in out.home}
    assert "HStriker" in names and "HBench" in names          # both in the XI/bench


def test_none_when_no_player_data(db_session):
    m, h, a = _match_with_pred(db_session)
    assert build_goalscorers(db_session, m) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_goalscorers_serving.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.goalscorers'`.

- [ ] **Step 3: Add the schema**

In `backend/app/schemas/__init__.py`, add near the other match-related out-models (e.g. after `MatchLineupsOut`):

```python
class GoalscorerOut(BaseModel):
    name: str
    position: str | None
    p_score: float
    p_score_2plus: float
    xg: float


class GoalscorersOut(BaseModel):
    mode: str                     # "lineup" | "squad"
    home: list[GoalscorerOut]
    away: list[GoalscorerOut]
```

- [ ] **Step 4: Implement the serving helper**

Create `backend/app/goalscorers.py`:

```python
"""Build the per-team 'likely scorers' block for a match from ingested Player
stats and the match's stored lambda. Lineup mode when an XI is stored, else
squad mode. None when no player data exists for either side."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import schemas
from app.models import LineupPlayer, Match, MatchLineup, Player
from app.serializers import latest_prediction
from ml.models.goalscorers import goalscorers


def _player_dict(p: Player, lineup_status: str | None) -> dict:
    return {
        "provider_player_id": p.provider_player_id, "name": p.name,
        "position": p.position, "club_goals": p.club_goals,
        "club_minutes": p.club_minutes, "wc_goals": p.wc_goals,
        "wc_minutes": p.wc_minutes, "lineup_status": lineup_status,
    }


def _lineup_rows(db: Session, match_id: int, side: str) -> list[LineupPlayer] | None:
    lineup = (
        db.query(MatchLineup).filter_by(match_id=match_id, side=side).one_or_none()
    )
    if lineup is None or not lineup.players:
        return None
    return list(lineup.players)


def _side_players(db: Session, match: Match, side: str) -> tuple[list[dict], bool]:
    """Return (player dicts, lineup_mode) for one side. Lineup mode joins the
    announced XI to Player stats by provider_player_id; squad mode lists all the
    team's Player rows."""
    team_id = match.team_home_id if side == "home" else match.team_away_id
    rows = _lineup_rows(db, match.id, side)
    if rows:
        by_pid = {p.provider_player_id: p for p in
                  db.query(Player).filter_by(team_id=team_id).all()}
        players = []
        for lp in rows:
            status = "starter" if lp.is_starter else "sub"
            stat = by_pid.get(lp.provider_player_id)
            if stat is not None:
                players.append(_player_dict(stat, status))
            else:  # in the XI but no stats row yet -> position prior only
                players.append({"provider_player_id": lp.provider_player_id,
                                "name": lp.name, "position": lp.position,
                                "club_goals": 0, "club_minutes": 0, "wc_goals": 0,
                                "wc_minutes": 0, "lineup_status": status})
        return players, True
    squad = db.query(Player).filter_by(team_id=team_id).all()
    return [_player_dict(p, None) for p in squad], False


def build_goalscorers(db: Session, match: Match, top_n: int = 8) -> schemas.GoalscorersOut | None:
    pred = latest_prediction(db, match.id)
    if pred is None:
        return None
    home_players, home_lineup = _side_players(db, match, "home")
    away_players, away_lineup = _side_players(db, match, "away")
    if not home_players and not away_players:
        return None
    mode = "lineup" if (home_lineup or away_lineup) else "squad"
    home = goalscorers(pred.lambda_home, home_players, mode)[:top_n]
    away = goalscorers(pred.lambda_away, away_players, mode)[:top_n]
    return schemas.GoalscorersOut(
        mode=mode,
        home=[schemas.GoalscorerOut(**{k: g[k] for k in
              ("name", "position", "p_score", "p_score_2plus", "xg")}) for g in home],
        away=[schemas.GoalscorerOut(**{k: g[k] for k in
              ("name", "position", "p_score", "p_score_2plus", "xg")}) for g in away],
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_goalscorers_serving.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the backend suite**

Run: `.venv/bin/python -m pytest backend ml -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/goalscorers.py backend/tests/test_goalscorers_serving.py
git commit -m "feat(api): build_goalscorers serving helper + schema"
```

---

### Task 3: Lazy `GET /api/matches/{id}/goalscorers` endpoint

**Files:**
- Modify: `backend/app/api/matches.py` (add the route)
- Test: `backend/tests/test_goalscorers_endpoint.py`

**Interfaces:**
- Consumes: `build_goalscorers` (Task 2); the `Match`/`get_db`/`HTTPException` already imported in `matches.py`.
- Produces: `GET /api/matches/{id}/goalscorers` → `GoalscorersOut | null` (404 only when the match itself doesn't exist; `null` body when there's no player data).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_goalscorers_endpoint.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, get_db
from app.models import Match, Player, Prediction, Team


def _client_with_data():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    db = S()
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    db.add(Prediction(match_id=m.id, model_version="v", prob_home_win=0.6, prob_draw=0.2,
                      prob_away_win=0.2, lambda_home=2.0, lambda_away=0.8, rho=-0.1))
    db.add(Player(provider_player_id=1, name="HStriker", team_id=h.id, position="F",
                  club_goals=18, club_minutes=2700, wc_goals=2, wc_minutes=270))
    db.commit()
    mid = m.id
    db.close()

    def override():
        s = S()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = override
    return TestClient(app), mid


def test_goalscorers_endpoint_returns_block():
    client, mid = _client_with_data()
    try:
        r = client.get(f"/api/matches/{mid}/goalscorers")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "squad"
        assert body["home"][0]["name"] == "HStriker"
    finally:
        app.dependency_overrides.clear()


def test_goalscorers_endpoint_404_for_missing_match():
    client, _ = _client_with_data()
    try:
        assert client.get("/api/matches/99999/goalscorers").status_code == 404
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_goalscorers_endpoint.py -q`
Expected: FAIL — 404 on the existing match (route not defined yet).

- [ ] **Step 3: Add the route**

In `backend/app/api/matches.py`, add (mirror the `/lineups` route; put it near it). Add the import at the top with the others: `from app.goalscorers import build_goalscorers`. Then:

```python
@router.get("/{match_id}/goalscorers", response_model=schemas.GoalscorersOut | None)
def match_goalscorers(match_id: int, db: Session = Depends(get_db)):
    """Likely scorers per team (squad estimate, or the announced XI when stored).
    `null` body when there's no player data yet — never fabricated, never 5xx."""
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    return build_goalscorers(db, match)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_goalscorers_endpoint.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the backend suite**

Run: `.venv/bin/python -m pytest backend -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/matches.py backend/tests/test_goalscorers_endpoint.py
git commit -m "feat(api): lazy GET /api/matches/{id}/goalscorers endpoint"
```

---

## Self-Review

**Spec coverage (Stage 2 slice):** allocation model `xG_p = λ·share_p` with the club+WC+position blended rate + shrinkage (Task 1) ✓; `P(≥1)`/`P(≥2)` ✓; lineup vs squad `mins_p` (Task 1) ✓; mode selection by stored lineup (Task 2) ✓; lineup join by `provider_player_id`, fallback to position prior for stat-less XI players (Task 2) ✓; null when no player data (Tasks 2-3) ✓; lazy serving endpoint (Task 3) ✓; compute-on-read, no migration ✓. The UI card is Stage 3.

**Placeholder scan:** none — complete code + commands in every step.

**Type consistency:** model output keys `provider_player_id/name/position/xg/p_score/p_score_2plus` flow into `GoalscorerOut{name,position,p_score,p_score_2plus,xg}` (the serializer selects the five wire keys); `GoalscorersOut{mode,home,away}` consistent across schema, helper, endpoint, and tests. `build_goalscorers(db, match, top_n=8) -> GoalscorersOut | None` matches between Interfaces, helper, and endpoint. `lineup_status` values "starter"/"sub"/None match `_LINEUP_WEIGHT` keys.
