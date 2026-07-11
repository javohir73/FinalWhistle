# Market Intel Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "Today's Movers" dashboard panel with a Market Intel panel fed by hourly Polymarket/Kalshi odds snapshots, with automatic fallback to the untouched MoversPanel.

**Architecture:** A new GitHub Actions cron runs `pipeline/market_intel.py` hourly: it fetches *active* markets from Polymarket (Gamma API) and Kalshi (public API), maps them onto our matches/teams by normalized team name, removes vig, and writes rows to a new `market_odds_snapshots` table. A new DB-only `GET /api/intel` endpoint serves model-vs-market comparisons and 24h movement storylines. A new client component `IntelPanel` renders them and falls back to `MoversPanel` when `has_data` is false or the fetch fails.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), `requests` (pipeline, already pinned), Next.js App Router + Jest/Testing Library (frontend), GitHub Actions (ops).

**Spec:** `docs/superpowers/specs/2026-07-10-market-intel-panel-design.md` (approved 2026-07-10). Note: the spec commit currently sits on branch `fix/ui-review-batch`.

## Global Constraints

- Data sources: Polymarket Gamma API + Kalshi public market API only — free, read-only, **no auth keys, no secrets beyond the existing `DATABASE_URL`**.
- Ingest **active (unresolved) markets only**; resolved/eliminated outcomes must never be written.
- Engineering constants (single source of truth is where each is defined below): disagreement highlight ≥ `0.05`; max `5` matches; max `3` storylines; movement window `24`h; storyline "live" = latest snapshot ≤ `3`h; fallback when no snapshot < `24`h; retention `14` days.
- Ingest is best-effort/never-raises per source; the run raises only when **all** sources yield zero rows.
- Table name `market_odds_snapshots` (plural per repo convention; the spec calls the entity `market_odds_snapshot`). `match_id`/`team_id` are plain `Integer`s, **not** FKs — sport-scoped like `ProbabilitySnapshot` (football → `matches`/`teams`, NRL → `sport_matches`/`sport_teams`).
- Disclaimer string everywhere: `"For analytics and entertainment only. Not betting advice."`
- Work on a feature branch (e.g. `feat/market-intel-panel`) off `main`. Test gate before PR: `.venv/bin/python -m pytest` and `cd frontend && npm run typecheck && npm run lint && npm test` (or `make test`).
- Deployment sequencing (stop gate, run by the human-approved release step, NOT by task agents): merge PR → dispatch `refresh.yml` (applies `alembic upgrade head`) → verify → only then is `/api/intel` safe. The frontend fallback makes the brief race benign (a 500 from `/api/intel` renders MoversPanel), but the sequencing rule still applies.
- External API notes: adapter constants (`WC_TAG_SLUG`, `NRL_TAG_SLUG`, series tickers) are best-effort guesses verified in Task 5's manual step (read-only GETs — allowed without stop gate). Committed test fixtures are the parsing contract; if live payloads differ, update fixture + parser together.

---

### Task 1: `MarketOddsSnapshot` model + Alembic migration

**Files:**
- Modify: `backend/app/models/__init__.py` (add `Index` import, model class after `ProbabilitySnapshot` at ~line 792, and `__all__` entry)
- Create: `backend/alembic/versions/c7d8e9f0a1b2_market_odds_snapshots.py`
- Test: `backend/tests/test_market_odds_model.py`

**Interfaces:**
- Consumes: `app.db.Base`, existing SQLAlchemy imports in the models module.
- Produces: `app.models.MarketOddsSnapshot` with columns `id, sport (str), source (str), market_type (str), match_id (int|None), team_id (int|None), outcome (str), implied_prob (float), external_id (str), fetched_at (datetime), created_at`. Unique on `(source, external_id, outcome, fetched_at)` named `uq_market_odds_key`. Later tasks import it as `from app.models import MarketOddsSnapshot`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_market_odds_model.py`:

```python
"""market_odds_snapshots: hourly exchange odds rows for the intel panel."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import MarketOddsSnapshot


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _row(**overrides):
    base = dict(
        sport="football", source="polymarket", market_type="match_winner",
        match_id=7, team_id=None, outcome="home", implied_prob=0.62,
        external_id="will-france-win", fetched_at=datetime(2026, 7, 10, 14, 0),
    )
    base.update(overrides)
    return MarketOddsSnapshot(**base)


def test_roundtrip():
    db = _session()
    db.add(_row())
    db.commit()
    row = db.query(MarketOddsSnapshot).one()
    assert (row.sport, row.source, row.outcome) == ("football", "polymarket", "home")
    assert row.implied_prob == 0.62
    assert row.match_id == 7 and row.team_id is None


def test_unique_key_rejects_duplicate_snapshot():
    db = _session()
    db.add(_row())
    db.commit()
    db.add(_row(implied_prob=0.63))  # same (source, external_id, outcome, fetched_at)
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_market_odds_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'MarketOddsSnapshot'`

- [ ] **Step 3: Add the model**

In `backend/app/models/__init__.py`: add `Index` to the existing `from sqlalchemy import (...)` list (it currently imports `JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, false, func, true`). Then append after the `ProbabilitySnapshot` class (before `__all__`):

```python
class MarketOddsSnapshot(Base):
    """Hourly prediction-market odds (Polymarket / Kalshi) for the intel panel.

    Sport-scoped like ProbabilitySnapshot: match_id is matches.id for football
    and sport_matches.id for NRL; team_id likewise teams.id / sport_teams.id.
    Plain Integers (no FKs) because the referenced table depends on `sport`.
    Only ACTIVE (unresolved) exchange markets are ingested, so resolved or
    eliminated outcomes never appear here (spec 2026-07-10).
    """

    __tablename__ = "market_odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", "outcome", "fetched_at",
            name="uq_market_odds_key",
        ),
        Index("ix_market_odds_sport_fetched", "sport", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))  # polymarket / kalshi
    market_type: Mapped[str] = mapped_column(String(20))  # match_winner / title_winner
    match_id: Mapped[int | None] = mapped_column(Integer, index=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    outcome: Mapped[str] = mapped_column(String(10))  # home / draw / away / win
    implied_prob: Mapped[float] = mapped_column(Float)  # vig-normalized mid-price
    external_id: Mapped[str] = mapped_column(String(120))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Add `"MarketOddsSnapshot",` to `__all__` (alphabetical-ish, next to `"ProbabilitySnapshot"`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_market_odds_model.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Write the migration**

`backend/alembic/versions/c7d8e9f0a1b2_market_odds_snapshots.py` (current head is `b3c4d5e6f7a9` — verify with `cd backend && alembic heads` and adjust `down_revision` if a newer head landed):

```python
"""market odds snapshots (intel panel, spec 2026-07-10)

Revision ID: c7d8e9f0a1b2
Revises: b3c4d5e6f7a9
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b3c4d5e6f7a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_odds_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("implied_prob", sa.Float(), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "external_id", "outcome", "fetched_at",
                            name="uq_market_odds_key"),
    )
    op.create_index("ix_market_odds_snapshots_match_id",
                    "market_odds_snapshots", ["match_id"])
    op.create_index("ix_market_odds_snapshots_team_id",
                    "market_odds_snapshots", ["team_id"])
    op.create_index("ix_market_odds_sport_fetched",
                    "market_odds_snapshots", ["sport", "fetched_at"])


def downgrade() -> None:
    op.drop_table("market_odds_snapshots")
```

- [ ] **Step 6: Verify the migration chain**

Run: `cd backend && alembic heads`
Expected: exactly one head, `c7d8e9f0a1b2`. (Do NOT run `alembic upgrade` against any real DB here — prod migration happens at release via `refresh.yml`.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/__init__.py backend/alembic/versions/c7d8e9f0a1b2_market_odds_snapshots.py backend/tests/test_market_odds_model.py
git commit -m "feat: market_odds_snapshots table for the intel panel"
```

---

### Task 2: Team-name normalization for market mapping

**Files:**
- Create: `pipeline/ingest/market_names.py`
- Test: `pipeline/ingest/market_names_test.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces: `normalize(name: str) -> str` (lowercased, accent/punctuation-stripped, alias-folded) and `build_team_index(teams: list[tuple[int, str]]) -> dict[str, int]` mapping normalized name → team id. Tasks 3–5 use these to match exchange display names to our teams.

- [ ] **Step 1: Write the failing test**

`pipeline/ingest/market_names_test.py`:

```python
"""Exchange display names must fold onto our FIFA-style team names."""
from pipeline.ingest.market_names import build_team_index, normalize


def test_normalize_case_accents_punctuation():
    assert normalize("  Côte d'Ivoire ") == "cote divoire"
    assert normalize("USA") == "united states"
    assert normalize("South Korea") == "korea republic"
    assert normalize("Morocco") == "morocco"


def test_unknown_name_passes_through_normalized():
    assert normalize("Atlantis FC") == "atlantis fc"


def test_build_team_index():
    idx = build_team_index([(1, "United States"), (2, "Côte d'Ivoire")])
    assert idx[normalize("USA")] == 1
    assert idx[normalize("Ivory Coast")] == 2
    assert normalize("Narnia") not in idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/market_names_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.ingest.market_names'`

- [ ] **Step 3: Implement**

`pipeline/ingest/market_names.py`:

```python
"""Team-name normalization for mapping exchange markets onto our teams.

Exchanges write display names ("USA", "South Korea", "Ivory Coast"); our
teams table uses FIFA-style names ("United States", "Korea Republic",
"Côte d'Ivoire"). normalize() lowercases, strips accents and punctuation,
then folds known exchange spellings onto the normalized FIFA name via
_ALIASES. Unknown names simply won't match — callers skip those markets
(never guess a mapping).
"""
from __future__ import annotations

import re
import unicodedata

#: normalized exchange spelling -> normalized FIFA-style name (as stored in
#: teams.name / sport_teams.name). Extend as unmapped names show up in the
#: market-intel run logs.
_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "america": "united states",
    "south korea": "korea republic",
    "korea": "korea republic",
    "iran": "ir iran",
    "ivory coast": "cote divoire",
    "bosnia": "bosnia and herzegovina",
    "uae": "united arab emirates",
    "dr congo": "congo dr",
    "czech republic": "czechia",
}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    return _ALIASES.get(s, s)


def build_team_index(teams: list[tuple[int, str]]) -> dict[str, int]:
    """{normalized team name -> team id} for one sport's teams."""
    return {normalize(name): team_id for team_id, name in teams}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/market_names_test.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/market_names.py pipeline/ingest/market_names_test.py
git commit -m "feat: team-name normalization for market mapping"
```

---

### Task 3: Polymarket adapter (fetch + parse)

**Files:**
- Create: `pipeline/ingest/polymarket.py`
- Create: `pipeline/ingest/testdata/polymarket_events.json`
- Test: `pipeline/ingest/polymarket_test.py`

**Interfaces:**
- Consumes: `requests` (pinned in `backend/requirements.txt`), `pipeline.ingest.market_names.normalize`.
- Produces:
  - `fetch_events(tag_slug: str, timeout: float = 15.0) -> list[dict]` — raw Gamma events (network; never called in tests).
  - `parse_events(events: list[dict]) -> list[dict]` — pure. Each output row:
    `{"source": "polymarket", "external_id": str, "group": str, "kind": "match"|"title", "home_name": str|None, "away_name": str|None, "outcome": "home"|"draw"|"away"|"win", "team_name": str|None, "price": float}`
  - Constants `WC_TAG_SLUG = "fifa-world-cup"`, `NRL_TAG_SLUG = "nrl"` (verified live in Task 5).

- [ ] **Step 1: Create the recorded fixture**

`pipeline/ingest/testdata/polymarket_events.json` (representative Gamma shapes; `outcomes`/`outcomePrices` are JSON-encoded strings in real responses):

```json
[
  {
    "slug": "fra-mar-2026-07-11",
    "title": "France vs. Morocco",
    "closed": false,
    "markets": [
      {
        "slug": "will-france-win-fra-mar",
        "question": "Will France win?",
        "active": true,
        "closed": false,
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.63\", \"0.37\"]"
      },
      {
        "slug": "will-morocco-win-fra-mar",
        "question": "Will Morocco win?",
        "active": true,
        "closed": false,
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.15\", \"0.85\"]"
      },
      {
        "slug": "fra-mar-draw",
        "question": "Will the match end in a draw?",
        "active": true,
        "closed": false,
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.27\", \"0.73\"]"
      }
    ]
  },
  {
    "slug": "2026-fifa-world-cup-winner",
    "title": "2026 FIFA World Cup Winner",
    "closed": false,
    "markets": [
      {
        "slug": "will-france-win-the-2026-fifa-world-cup",
        "question": "Will France win the 2026 FIFA World Cup?",
        "active": true,
        "closed": false,
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.31\", \"0.69\"]"
      },
      {
        "slug": "will-argentina-win-the-2026-fifa-world-cup",
        "question": "Will Argentina win the 2026 FIFA World Cup?",
        "active": true,
        "closed": false,
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.24\", \"0.76\"]"
      },
      {
        "slug": "will-mexico-win-the-2026-fifa-world-cup",
        "question": "Will Mexico win the 2026 FIFA World Cup?",
        "active": false,
        "closed": true,
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.001\", \"0.999\"]"
      }
    ]
  }
]
```

- [ ] **Step 2: Write the failing test**

`pipeline/ingest/polymarket_test.py`:

```python
"""Gamma parsing: binary Yes markets -> neutral rows; closed markets dropped."""
import json
from pathlib import Path

from pipeline.ingest.polymarket import parse_events

FIXTURE = Path(__file__).parent / "testdata" / "polymarket_events.json"


def _rows():
    return parse_events(json.loads(FIXTURE.read_text()))


def test_match_event_maps_three_outcomes():
    rows = [r for r in _rows() if r["kind"] == "match"]
    assert {r["outcome"] for r in rows} == {"home", "draw", "away"}
    by = {r["outcome"]: r for r in rows}
    assert by["home"]["team_name"] == "France" and by["home"]["price"] == 0.63
    assert by["away"]["team_name"] == "Morocco" and by["away"]["price"] == 0.15
    assert by["draw"]["team_name"] is None and by["draw"]["price"] == 0.27
    assert by["home"]["home_name"] == "France" and by["home"]["away_name"] == "Morocco"
    assert by["home"]["group"] == "fra-mar-2026-07-11"
    assert by["home"]["source"] == "polymarket"


def test_title_event_one_win_row_per_active_team():
    rows = [r for r in _rows() if r["kind"] == "title"]
    assert [(r["team_name"], r["price"]) for r in rows] == [
        ("France", 0.31), ("Argentina", 0.24),
    ]
    assert all(r["outcome"] == "win" for r in rows)


def test_closed_or_inactive_markets_are_dropped():
    assert not [r for r in _rows() if r["team_name"] == "Mexico"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/polymarket_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.ingest.polymarket'`

- [ ] **Step 4: Implement**

`pipeline/ingest/polymarket.py`:

```python
"""Polymarket Gamma adapter for the intel panel (spec 2026-07-10).

fetch_events() pulls ACTIVE events for one tag from the public Gamma API
(read-only, no auth). parse_events() is pure and fixture-tested: it turns
Gamma's binary Yes/No markets into neutral rows the orchestrator can map.

Event shapes handled:
- Match events: title "A vs B" / "A vs. B"; one binary market per outcome,
  identified by the team name (or the word "draw") in the market question.
- Title events: title containing "winner"; one binary market per team,
  question "Will <team> win the ...?".

Anything that doesn't fit is skipped — the intel panel would rather show
nothing than a wrong mapping.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from pipeline.ingest.market_names import normalize

log = logging.getLogger(__name__)

BASE_URL = "https://gamma-api.polymarket.com"
#: Gamma tag slugs (verified live at rollout — Task 5 manual step).
WC_TAG_SLUG = "fifa-world-cup"
NRL_TAG_SLUG = "nrl"

_VS = re.compile(r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)$", re.IGNORECASE)


def fetch_events(tag_slug: str, timeout: float = 15.0) -> list[dict]:
    """Raw ACTIVE events for one tag. Callers own error handling."""
    resp = requests.get(
        f"{BASE_URL}/events",
        params={"tag_slug": tag_slug, "closed": "false", "limit": 200},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _yes_price(market: dict) -> float | None:
    """Yes-outcome price, or None when malformed/out of range."""
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices = json.loads(market.get("outcomePrices") or "[]")
        yes = outcomes.index("Yes")
        price = float(prices[yes])
    except (ValueError, IndexError, TypeError):
        return None
    return price if 0.0 < price < 1.0 else None


def _is_active(market: dict) -> bool:
    return bool(market.get("active")) and not market.get("closed")


def parse_events(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        if event.get("closed"):
            continue
        title = event.get("title") or ""
        vs = _VS.match(title.strip())
        if vs:
            rows.extend(_parse_match_event(event, vs["home"].strip(), vs["away"].strip()))
        elif "winner" in title.lower():
            rows.extend(_parse_title_event(event))
        else:
            log.info("polymarket: skipping unrecognized event %r", title)
    return rows


def _parse_match_event(event: dict, home: str, away: str) -> list[dict]:
    rows = []
    for market in event.get("markets") or []:
        if not _is_active(market):
            continue
        price = _yes_price(market)
        if price is None:
            continue
        question = normalize(market.get("question") or "")
        if "draw" in question or "tie" in question:
            outcome, team = "draw", None
        elif normalize(home) and normalize(home) in question:
            outcome, team = "home", home
        elif normalize(away) and normalize(away) in question:
            outcome, team = "away", away
        else:
            log.info("polymarket: unmapped match market %r", market.get("question"))
            continue
        rows.append({
            "source": "polymarket", "external_id": market["slug"],
            "group": event["slug"], "kind": "match",
            "home_name": home, "away_name": away,
            "outcome": outcome, "team_name": team, "price": price,
        })
    return rows


_TITLE_Q = re.compile(r"^will\s+(?P<team>.+?)\s+win\b", re.IGNORECASE)


def _parse_title_event(event: dict) -> list[dict]:
    rows = []
    for market in event.get("markets") or []:
        if not _is_active(market):
            continue
        price = _yes_price(market)
        if price is None:
            continue
        m = _TITLE_Q.match((market.get("question") or "").strip())
        if not m:
            log.info("polymarket: unmapped title market %r", market.get("question"))
            continue
        rows.append({
            "source": "polymarket", "external_id": market["slug"],
            "group": event["slug"], "kind": "title",
            "home_name": None, "away_name": None,
            "outcome": "win", "team_name": m["team"].strip(), "price": price,
        })
    return rows
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/polymarket_test.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/polymarket.py pipeline/ingest/polymarket_test.py pipeline/ingest/testdata/polymarket_events.json
git commit -m "feat: polymarket gamma adapter (fetch + fixture-tested parse)"
```

---

### Task 4: Kalshi adapter (fetch + parse)

**Files:**
- Create: `pipeline/ingest/kalshi.py`
- Create: `pipeline/ingest/testdata/kalshi_markets.json`
- Test: `pipeline/ingest/kalshi_test.py`

**Interfaces:**
- Consumes: `requests`.
- Produces:
  - `fetch_markets(series_ticker: str, timeout: float = 15.0) -> list[dict]` — raw open markets (network).
  - `parse_markets(markets: list[dict], kind: "match"|"title") -> list[dict]` — pure; **same output row shape as `polymarket.parse_events`** but with `"source": "kalshi"` and `external_id` = Kalshi ticker.
  - Constants `WC_MATCH_SERIES = "KXWCGAME"`, `WC_TITLE_SERIES = "KXWC"` (verified live in Task 5).

- [ ] **Step 1: Create the recorded fixture**

`pipeline/ingest/testdata/kalshi_markets.json` (prices are integer cents; mid = (yes_bid+yes_ask)/2):

```json
{
  "markets": [
    {
      "ticker": "KXWCGAME-26JUL11FRAMAR-FRA",
      "event_ticker": "KXWCGAME-26JUL11FRAMAR",
      "title": "France vs Morocco: Winner?",
      "yes_sub_title": "France",
      "status": "active",
      "yes_bid": 61, "yes_ask": 65, "last_price": 63
    },
    {
      "ticker": "KXWCGAME-26JUL11FRAMAR-MAR",
      "event_ticker": "KXWCGAME-26JUL11FRAMAR",
      "title": "France vs Morocco: Winner?",
      "yes_sub_title": "Morocco",
      "status": "active",
      "yes_bid": 13, "yes_ask": 17, "last_price": 15
    },
    {
      "ticker": "KXWCGAME-26JUL11FRAMAR-TIE",
      "event_ticker": "KXWCGAME-26JUL11FRAMAR",
      "title": "France vs Morocco: Winner?",
      "yes_sub_title": "Tie",
      "status": "active",
      "yes_bid": 24, "yes_ask": 28, "last_price": 26
    },
    {
      "ticker": "KXWC-26-FRA",
      "event_ticker": "KXWC-26",
      "title": "2026 Men's World Cup Winner?",
      "yes_sub_title": "France",
      "status": "active",
      "yes_bid": 29, "yes_ask": 33, "last_price": 31
    },
    {
      "ticker": "KXWC-26-ZERO",
      "event_ticker": "KXWC-26",
      "title": "2026 Men's World Cup Winner?",
      "yes_sub_title": "Ghostland",
      "status": "active",
      "yes_bid": 0, "yes_ask": 0, "last_price": 0
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`pipeline/ingest/kalshi_test.py`:

```python
"""Kalshi parsing: cent mid-prices -> neutral rows; zero-quote rows dropped."""
import json
from pathlib import Path

from pipeline.ingest.kalshi import parse_markets

FIXTURE = Path(__file__).parent / "testdata" / "kalshi_markets.json"


def _markets():
    return json.loads(FIXTURE.read_text())["markets"]


def test_match_markets_mid_price_and_outcomes():
    rows = parse_markets([m for m in _markets() if m["ticker"].startswith("KXWCGAME")],
                         kind="match")
    by = {r["outcome"]: r for r in rows}
    assert by["home"]["team_name"] == "France" and by["home"]["price"] == 0.63
    assert by["away"]["team_name"] == "Morocco" and by["away"]["price"] == 0.15
    assert by["draw"]["price"] == 0.26 and by["draw"]["team_name"] is None
    assert by["home"]["home_name"] == "France" and by["home"]["away_name"] == "Morocco"
    assert by["home"]["group"] == "KXWCGAME-26JUL11FRAMAR"
    assert by["home"]["source"] == "kalshi"


def test_title_markets_and_zero_quotes_dropped():
    rows = parse_markets([m for m in _markets() if m["ticker"].startswith("KXWC-")],
                         kind="title")
    assert [(r["team_name"], r["price"], r["outcome"]) for r in rows] == [
        ("France", 0.31, "win"),
    ]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/ingest/kalshi_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.ingest.kalshi'`

- [ ] **Step 4: Implement**

`pipeline/ingest/kalshi.py`:

```python
"""Kalshi public-API adapter for the intel panel (spec 2026-07-10).

Market data GETs need no auth. parse_markets() is pure and fixture-tested;
output rows share the polymarket adapter's shape so the orchestrator treats
both sources identically. Prices are integer cents: the implied price is the
bid/ask mid when both sides are quoted, else last_price; zero/unquoted
markets are dropped rather than guessed.
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
#: Series tickers (verified live at rollout — Task 5 manual step).
WC_MATCH_SERIES = "KXWCGAME"
WC_TITLE_SERIES = "KXWC"

_VS = re.compile(r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)(?::.*)?$", re.IGNORECASE)


def fetch_markets(series_ticker: str, timeout: float = 15.0) -> list[dict]:
    """Raw OPEN markets for one series. Callers own error handling."""
    resp = requests.get(
        f"{BASE_URL}/markets",
        params={"series_ticker": series_ticker, "status": "open", "limit": 500},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("markets", [])


def _mid_price(market: dict) -> float | None:
    bid, ask = market.get("yes_bid") or 0, market.get("yes_ask") or 0
    cents = (bid + ask) / 2 if bid and ask else (market.get("last_price") or 0)
    return cents / 100 if 0 < cents < 100 else None


def parse_markets(markets: list[dict], kind: str) -> list[dict]:
    rows: list[dict] = []
    for market in markets:
        if market.get("status") not in ("active", "open"):
            continue
        price = _mid_price(market)
        team = (market.get("yes_sub_title") or "").strip()
        if price is None or not team:
            continue
        if kind == "match":
            vs = _VS.match((market.get("title") or "").strip())
            if not vs:
                log.info("kalshi: unmapped match market %r", market.get("title"))
                continue
            home, away = vs["home"].strip(), vs["away"].strip()
            if team.lower() in ("tie", "draw"):
                outcome, team_name = "draw", None
            elif team == home:
                outcome, team_name = "home", home
            elif team == away:
                outcome, team_name = "away", away
            else:
                log.info("kalshi: outcome %r not in title %r", team, market.get("title"))
                continue
            rows.append({
                "source": "kalshi", "external_id": market["ticker"],
                "group": market["event_ticker"], "kind": "match",
                "home_name": home, "away_name": away,
                "outcome": outcome, "team_name": team_name, "price": price,
            })
        else:  # title
            rows.append({
                "source": "kalshi", "external_id": market["ticker"],
                "group": market["event_ticker"], "kind": "title",
                "home_name": None, "away_name": None,
                "outcome": "win", "team_name": team, "price": price,
            })
    return rows
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/ingest/kalshi_test.py -v`
Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add pipeline/ingest/kalshi.py pipeline/ingest/kalshi_test.py pipeline/ingest/testdata/kalshi_markets.json
git commit -m "feat: kalshi public-api adapter (fetch + fixture-tested parse)"
```

---

### Task 5: `market_intel` orchestrator + hourly workflow

**Files:**
- Create: `pipeline/market_intel.py`
- Create: `.github/workflows/market-intel.yml`
- Test: `pipeline/market_intel_test.py`

**Interfaces:**
- Consumes: `MarketOddsSnapshot` (Task 1), `market_names.build_team_index/normalize` (Task 2), adapter `fetch_*`/`parse_*` + constants (Tasks 3–4), `app.models` `Match/Team/SportMatch/SportTeam`, `app.db.SessionLocal` (in `__main__` only).
- Produces: `run(db: Session, now: datetime) -> int` (rows written; raises `RuntimeError` only when ALL sources yield zero rows), plus internal helpers `_to_rows`, `_replace_hour`, `_prune`. The workflow runs `python -m pipeline.market_intel`.

- [ ] **Step 1: Write the failing tests**

`pipeline/market_intel_test.py`:

```python
"""Orchestrator: mapping, de-vig, idempotent hourly writes, never-raises sources."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import MarketOddsSnapshot, Match, Team, Tournament

from pipeline import market_intel


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


NOW = datetime(2026, 7, 10, 14, 40)


def _seed_football(db):
    t = Tournament(name="WC26", year=2026)
    fra, mar = Team(name="France"), Team(name="Morocco")
    db.add_all([t, fra, mar]); db.flush()
    match = Match(tournament_id=t.id, stage="QF", team_home_id=fra.id,
                  team_away_id=mar.id, status="scheduled",
                  kickoff_utc=NOW + timedelta(hours=16))
    db.add(match); db.commit()
    return fra, mar, match


def _match_rows(price_home=0.63, price_draw=0.27, price_away=0.15,
                home="France", away="Morocco"):
    def row(outcome, team, price, ext):
        return {"source": "polymarket", "external_id": ext, "group": "g1",
                "kind": "match", "home_name": home, "away_name": away,
                "outcome": outcome, "team_name": team, "price": price}
    return [row("home", home, price_home, "m-home"),
            row("draw", None, price_draw, "m-draw"),
            row("away", away, price_away, "m-away")]


def test_match_group_mapped_and_devigged():
    db = _session()
    _fra, _mar, match = _seed_football(db)
    n = market_intel._to_rows(db, "football", _match_rows(), NOW)
    assert len(n) == 3
    by = {r.outcome: r for r in n}
    assert by["home"].match_id == match.id and by["home"].market_type == "match_winner"
    # de-vig: 0.63 / (0.63+0.27+0.15) = 0.6
    assert by["home"].implied_prob == pytest.approx(0.6)
    assert by["draw"].implied_prob == pytest.approx(0.2571, abs=1e-3)


def test_reversed_orientation_swaps_outcomes():
    db = _session()
    fra, _mar, match = _seed_football(db)
    rows = _match_rows(home="Morocco", away="France",
                       price_home=0.15, price_draw=0.27, price_away=0.63)
    by = {r.outcome: r for r in market_intel._to_rows(db, "football", rows, NOW)}
    # Exchange's "home" (Morocco) is OUR away side.
    assert by["home"].match_id == match.id
    assert by["home"].implied_prob == pytest.approx(0.6)  # France = our home


def test_incomplete_football_group_skipped():
    db = _session()
    _seed_football(db)
    rows = [r for r in _match_rows() if r["outcome"] != "draw"]
    assert market_intel._to_rows(db, "football", rows, NOW) == []


def test_title_rows_map_by_team_and_skip_unknown():
    db = _session()
    fra, _mar, _match = _seed_football(db)
    rows = [
        {"source": "kalshi", "external_id": "t-fra", "group": "t", "kind": "title",
         "home_name": None, "away_name": None, "outcome": "win",
         "team_name": "France", "price": 0.31},
        {"source": "kalshi", "external_id": "t-zzz", "group": "t", "kind": "title",
         "home_name": None, "away_name": None, "outcome": "win",
         "team_name": "Narnia", "price": 0.02},
    ]
    out = market_intel._to_rows(db, "football", rows, NOW)
    assert [(r.team_id, r.market_type) for r in out] == [(fra.id, "title_winner")]
    # lone mapped title outcome sums to 0.31 < 0.9 -> raw price kept (no inflation)
    assert out[0].implied_prob == pytest.approx(0.31)


def test_run_idempotent_per_hour_and_prunes(monkeypatch):
    db = _session()
    _seed_football(db)
    monkeypatch.setattr(market_intel, "CONFIGS", [
        market_intel.SourceConfig("football", "polymarket", lambda: _match_rows()),
    ])
    db.add(MarketOddsSnapshot(  # 15 days old -> pruned
        sport="football", source="polymarket", market_type="title_winner",
        team_id=1, outcome="win", implied_prob=0.5, external_id="old",
        fetched_at=NOW - timedelta(days=15)))
    db.commit()
    assert market_intel.run(db, NOW) == 3
    assert market_intel.run(db, NOW) == 3  # same hour re-run: replaced, not duped
    assert db.query(MarketOddsSnapshot).count() == 3  # old row pruned


def test_run_raises_only_when_all_sources_empty(monkeypatch):
    db = _session()
    _seed_football(db)

    def boom():
        raise RuntimeError("api down")

    monkeypatch.setattr(market_intel, "CONFIGS", [
        market_intel.SourceConfig("football", "polymarket", boom),
        market_intel.SourceConfig("football", "kalshi", lambda: _match_rows()),
    ])
    assert market_intel.run(db, NOW) == 3  # one source down: no raise

    monkeypatch.setattr(market_intel, "CONFIGS", [
        market_intel.SourceConfig("football", "polymarket", boom),
    ])
    with pytest.raises(RuntimeError):
        market_intel.run(db, NOW)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/market_intel_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.market_intel'`

- [ ] **Step 3: Implement**

`pipeline/market_intel.py`:

```python
"""Hourly prediction-market odds snapshot (spec 2026-07-10): the intel panel's data.

Fetch+parse ACTIVE markets per SourceConfig, map them onto our matches/teams
by normalized name, de-vig within each market group, then delete-then-insert
per (sport, source, hour) so re-runs stay idempotent (same pattern as
prob_snapshots._replace_day). BEST-EFFORT BY CONTRACT: a malformed market
skips that market, a dead source skips that source; run() raises only when
ALL sources yield zero rows — the workflow should go red then, and only then.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.models import MarketOddsSnapshot, Match, SportMatch, SportTeam, Team
from pipeline.ingest import kalshi, polymarket
from pipeline.ingest.market_names import build_team_index, normalize

log = logging.getLogger(__name__)

RETENTION_DAYS = 14
#: Title groups whose mapped outcomes sum below this keep raw prices —
#: rescaling an incomplete outcome set would inflate every probability.
_DEVIG_FLOOR = 0.9


@dataclass(frozen=True)
class SourceConfig:
    sport: str
    source: str
    #: () -> parsed neutral rows (adapter fetch+parse composed; see CONFIGS).
    load: Callable[[], list[dict]]


def _load_polymarket(tag_slug: str) -> list[dict]:
    return polymarket.parse_events(polymarket.fetch_events(tag_slug))


def _load_kalshi_wc() -> list[dict]:
    return (kalshi.parse_markets(kalshi.fetch_markets(kalshi.WC_MATCH_SERIES), "match")
            + kalshi.parse_markets(kalshi.fetch_markets(kalshi.WC_TITLE_SERIES), "title"))


CONFIGS: list[SourceConfig] = [
    SourceConfig("football", "polymarket",
                 lambda: _load_polymarket(polymarket.WC_TAG_SLUG)),
    SourceConfig("nrl", "polymarket",
                 lambda: _load_polymarket(polymarket.NRL_TAG_SLUG)),
    SourceConfig("football", "kalshi", _load_kalshi_wc),
]


def _fixtures(db: Session, sport: str) -> dict[tuple[str, str], tuple[int, bool]]:
    """{(norm_home, norm_away) -> (match_id, reversed)} for scheduled fixtures."""
    index: dict[tuple[str, str], tuple[int, bool]] = {}
    if sport == "football":
        names = dict(db.query(Team.id, Team.name).all())
        matches = (db.query(Match)
                   .filter(Match.status == "scheduled",
                           Match.team_home_id.isnot(None),
                           Match.team_away_id.isnot(None)).all())
        pairs = [(m.id, names.get(m.team_home_id), names.get(m.team_away_id))
                 for m in matches]
    else:
        names = dict(db.query(SportTeam.id, SportTeam.name)
                     .filter(SportTeam.sport == sport).all())
        matches = (db.query(SportMatch)
                   .filter(SportMatch.sport == sport,
                           SportMatch.status == "scheduled",
                           SportMatch.home_team_id.isnot(None),
                           SportMatch.away_team_id.isnot(None)).all())
        pairs = [(m.id, names.get(m.home_team_id), names.get(m.away_team_id))
                 for m in matches]
    for match_id, home, away in pairs:
        if not home or not away:
            continue
        h, a = normalize(home), normalize(away)
        index[(h, a)] = (match_id, False)
        index[(a, h)] = (match_id, True)
    return index


def _team_index(db: Session, sport: str) -> dict[str, int]:
    if sport == "football":
        return build_team_index(db.query(Team.id, Team.name).all())
    return build_team_index(
        db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == sport).all())


def _to_rows(db: Session, sport: str, parsed: list[dict],
             fetched_at: datetime) -> list[MarketOddsSnapshot]:
    fixtures = _fixtures(db, sport)
    teams = _team_index(db, sport)
    out: list[MarketOddsSnapshot] = []

    groups: dict[str, list[dict]] = {}
    for r in parsed:
        groups.setdefault(f"{r['kind']}:{r['group']}", []).append(r)

    for key, rows in groups.items():
        kind = rows[0]["kind"]
        if kind == "match":
            outcomes = {r["outcome"] for r in rows}
            required = {"home", "draw", "away"} if sport == "football" else {"home", "away"}
            if not required <= outcomes:
                log.info("market intel: incomplete group %s (%s) skipped", key, outcomes)
                continue
            hit = fixtures.get((normalize(rows[0]["home_name"]),
                                normalize(rows[0]["away_name"])))
            if hit is None:
                log.info("market intel: no fixture for group %s", key)
                continue
            match_id, reversed_ = hit
            total = sum(r["price"] for r in rows)
            if total <= 0:
                continue
            flip = {"home": "away", "away": "home", "draw": "draw"}
            for r in rows:
                outcome = flip[r["outcome"]] if reversed_ else r["outcome"]
                out.append(MarketOddsSnapshot(
                    sport=sport, source=r["source"], market_type="match_winner",
                    match_id=match_id, team_id=None, outcome=outcome,
                    implied_prob=r["price"] / total,
                    external_id=r["external_id"], fetched_at=fetched_at))
        else:  # title
            mapped = [(r, teams.get(normalize(r["team_name"] or ""))) for r in rows]
            for r, team_id in mapped:
                if team_id is None:
                    log.info("market intel: unmapped title team %r", r["team_name"])
            mapped = [(r, tid) for r, tid in mapped if tid is not None]
            total = sum(r["price"] for r, _ in mapped)
            scale = total if total >= _DEVIG_FLOOR else 1.0
            for r, team_id in mapped:
                out.append(MarketOddsSnapshot(
                    sport=sport, source=r["source"], market_type="title_winner",
                    match_id=None, team_id=team_id, outcome="win",
                    implied_prob=r["price"] / scale,
                    external_id=r["external_id"], fetched_at=fetched_at))
    return out


def _replace_hour(db: Session, sport: str, source: str, hour: datetime,
                  rows: list[MarketOddsSnapshot]) -> int:
    db.query(MarketOddsSnapshot).filter(
        MarketOddsSnapshot.sport == sport,
        MarketOddsSnapshot.source == source,
        MarketOddsSnapshot.fetched_at == hour,
    ).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def _prune(db: Session, now: datetime) -> None:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    db.query(MarketOddsSnapshot).filter(
        MarketOddsSnapshot.fetched_at < cutoff).delete(synchronize_session=False)
    db.commit()


def run(db: Session, now: datetime) -> int:
    hour = now.replace(minute=0, second=0, microsecond=0)
    total = 0
    for cfg in CONFIGS:
        try:
            rows = _to_rows(db, cfg.sport, cfg.load(), hour)
            total += _replace_hour(db, cfg.sport, cfg.source, hour, rows)
            log.info("market intel: %s/%s wrote %d rows", cfg.source, cfg.sport, len(rows))
        except Exception:
            db.rollback()
            log.exception("market intel: %s/%s failed", cfg.source, cfg.sport)
    _prune(db, now)
    if total == 0:
        raise RuntimeError("market intel: no rows ingested from any source")
    return total


if __name__ == "__main__":
    from datetime import timezone

    from app.db import SessionLocal

    logging.basicConfig(level=logging.INFO)
    session = SessionLocal()
    try:
        run(session, datetime.now(timezone.utc))
    finally:
        session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/market_intel_test.py pipeline/ingest -v`
Expected: all PASSED

- [ ] **Step 5: Add the workflow**

`.github/workflows/market-intel.yml`:

```yaml
# Hourly prediction-market odds snapshot (Polymarket + Kalshi) for the intel
# panel. Read-only public APIs — no keys. Migrations are refresh.yml's job;
# this workflow assumes the schema is already at head. Reduce the cadence to
# every 2-3 hours after the WC final (2026-07-19) when only thin NRL
# coverage remains.
name: market-intel

on:
  schedule:
    - cron: "23 * * * *"
  workflow_dispatch: {}

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r backend/requirements.txt
      - name: Snapshot market odds
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PYTHONPATH: backend:.
        run: python -m pipeline.market_intel
```

- [ ] **Step 6: Manual live verification of adapter constants (read-only)**

Run (no DB writes — pure GETs):

```bash
.venv/bin/python - <<'EOF'
from pipeline.ingest import polymarket, kalshi
ev = polymarket.fetch_events(polymarket.WC_TAG_SLUG)
print("polymarket WC events:", len(ev), [e.get("title") for e in ev[:5]])
mk = kalshi.fetch_markets(kalshi.WC_MATCH_SERIES)
print("kalshi WC match markets:", len(mk), [m.get("title") for m in mk[:5]])
EOF
```

Expected: non-empty lists with recognizable WC26 titles. If empty, discover the real tag/series (Gamma: `GET /events?closed=false` + text search; Kalshi: `GET /series` endpoints), update the constants AND, if payload shapes differ from the fixtures, update fixtures + parsers together, re-running Task 3/4 tests. Record what was verified in the commit message.

- [ ] **Step 7: Commit**

```bash
git add pipeline/market_intel.py pipeline/market_intel_test.py .github/workflows/market-intel.yml
git commit -m "feat: hourly market-intel ingest (polymarket+kalshi) + workflow"
```

---

### Task 6: `GET /api/intel` endpoint

**Files:**
- Create: `backend/app/api/intel.py`
- Modify: `backend/app/main.py` (add `intel` to the `from app.api import (...)` list at ~line 20; add `app.include_router(intel.router)` next to the movers router at ~line 264)
- Test: `backend/tests/test_intel_api.py`

**Interfaces:**
- Consumes: `MarketOddsSnapshot` (Task 1), `serializers.latest_prediction(db, match_id) -> Prediction | None` (existing, shadow-filtered), models `Match/Team/SportMatch/SportPrediction/SportTeam`.
- Produces: `GET /api/intel?sport=football|nrl` returning exactly:

```jsonc
{
  "sport": "football",
  "has_data": true,            // false -> frontend renders MoversPanel
  "updated_at": "2026-07-10T14:00:00+00:00",  // null when has_data false
  "matches": [{
    "match_id": 1, "kickoff_utc": "…",
    "home": {"id": 1, "name": "France"}, "away": {"id": 2, "name": "Morocco"},
    "model": {"home": 0.55, "draw": 0.27, "away": 0.19},   // null if no prediction
    "market": [{"source": "polymarket", "home": 0.6, "draw": 0.257,
                "away": 0.143, "fetched_at": "…"}],
    "disagreement": 0.05       // mean market home - model home; null if either side missing
  }],
  "storylines": [{
    "market_type": "title_winner", "source": "polymarket",
    "outcome": "win", "match_id": null,
    "team": {"id": 3, "name": "Argentina"},
    "prob_from": 0.24, "prob_to": 0.31, "window_hours": 24
  }],
  "disclaimer": "For analytics and entertainment only. Not betting advice."
}
```

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_intel_api.py`:

```python
"""Intel = model-vs-market for upcoming fixtures + biggest 24h market moves."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    MarketOddsSnapshot, Match, Prediction, SportMatch, SportPrediction,
    SportTeam, Team, Tournament,
)

# Naive UTC timestamps: SQLite returns naive datetimes for tz-aware columns;
# the endpoint's _aware() shim normalizes them back to UTC.
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), TestingSession()


def _snap(**overrides):
    base = dict(sport="football", source="polymarket", market_type="match_winner",
                match_id=None, team_id=None, outcome="home", implied_prob=0.6,
                external_id="x", fetched_at=NOW)
    base.update(overrides)
    return MarketOddsSnapshot(**base)


def _seed_match(db, hours_ahead=12):
    t = Tournament(name="WC26", year=2026)
    fra, mar = Team(name="France"), Team(name="Morocco")
    db.add_all([t, fra, mar]); db.flush()
    m = Match(tournament_id=t.id, stage="QF", team_home_id=fra.id,
              team_away_id=mar.id, status="scheduled",
              kickoff_utc=NOW + timedelta(hours=hours_ahead))
    db.add(m); db.flush()
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.55, prob_draw=0.27, prob_away_win=0.18))
    db.commit()
    return fra, mar, m


def test_empty_db_has_no_data():
    client, _db = _client()
    body = client.get("/api/intel?sport=football").json()
    assert body["has_data"] is False
    assert body["matches"] == [] and body["storylines"] == []
    assert body["updated_at"] is None
    app.dependency_overrides.clear()


def test_stale_snapshots_have_no_data():
    client, db = _client()
    db.add(_snap(fetched_at=NOW - timedelta(hours=30))); db.commit()
    assert client.get("/api/intel?sport=football").json()["has_data"] is False
    app.dependency_overrides.clear()


def test_match_comparison_and_disagreement():
    client, db = _client()
    fra, mar, m = _seed_match(db)
    db.add_all([
        _snap(match_id=m.id, outcome="home", implied_prob=0.60, external_id="h"),
        _snap(match_id=m.id, outcome="draw", implied_prob=0.257, external_id="d"),
        _snap(match_id=m.id, outcome="away", implied_prob=0.143, external_id="a"),
    ])
    db.commit()
    body = client.get("/api/intel?sport=football").json()
    assert body["has_data"] is True
    entry = body["matches"][0]
    assert entry["home"]["name"] == "France" and entry["away"]["name"] == "Morocco"
    assert entry["model"] == {"home": 0.55, "draw": 0.27, "away": 0.18}
    assert entry["market"] == [{"source": "polymarket", "home": 0.6, "draw": 0.257,
                                "away": 0.143,
                                "fetched_at": entry["market"][0]["fetched_at"]}]
    assert entry["disagreement"] == 0.05
    assert "Not betting advice" in body["disclaimer"]
    app.dependency_overrides.clear()


def test_kicked_off_matches_excluded():
    client, db = _client()
    _fra, _mar, m = _seed_match(db, hours_ahead=-2)
    db.add(_snap(match_id=m.id, external_id="h")); db.commit()
    body = client.get("/api/intel?sport=football").json()
    assert body["has_data"] is True and body["matches"] == []
    app.dependency_overrides.clear()


def test_storylines_top_moves_exclude_draw_and_stale():
    client, db = _client()
    fra, mar, m = _seed_match(db)
    old = NOW - timedelta(hours=24)
    db.add_all([
        # title: France 0.24 -> 0.31 (|0.07| = biggest move)
        _snap(market_type="title_winner", team_id=fra.id, outcome="win",
              implied_prob=0.24, external_id="t-fra", fetched_at=old),
        _snap(market_type="title_winner", team_id=fra.id, outcome="win",
              implied_prob=0.31, external_id="t-fra"),
        # match home: 0.60 -> 0.63
        _snap(match_id=m.id, outcome="home", implied_prob=0.60,
              external_id="h", fetched_at=old),
        _snap(match_id=m.id, outcome="home", implied_prob=0.63, external_id="h"),
        # draw moved too but draw storylines are excluded
        _snap(match_id=m.id, outcome="draw", implied_prob=0.20,
              external_id="d", fetched_at=old),
        _snap(match_id=m.id, outcome="draw", implied_prob=0.30, external_id="d"),
        # stale market (latest snapshot 6h old > LIVE_HOURS): excluded
        _snap(market_type="title_winner", team_id=mar.id, outcome="win",
              implied_prob=0.02, external_id="t-mar", fetched_at=old),
        _snap(market_type="title_winner", team_id=mar.id, outcome="win",
              implied_prob=0.09, external_id="t-mar",
              fetched_at=NOW - timedelta(hours=6)),
    ])
    db.commit()
    body = client.get("/api/intel?sport=football").json()
    lines = body["storylines"]
    assert [(s["market_type"], s["prob_from"], s["prob_to"]) for s in lines] == [
        ("title_winner", 0.24, 0.31),
        ("match_winner", 0.6, 0.63),
    ]
    assert lines[0]["team"]["name"] == "France"
    assert lines[1]["team"]["name"] == "France" and lines[1]["match_id"] == m.id
    assert lines[0]["window_hours"] == 24
    app.dependency_overrides.clear()


def test_nrl_scoped_to_sport_tables():
    client, db = _client()
    storm = SportTeam(sport="nrl", name="Melbourne Storm")
    roosters = SportTeam(sport="nrl", name="Sydney Roosters")
    db.add_all([storm, roosters]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=19, match_no=1,
                   home_team_id=storm.id, away_team_id=roosters.id,
                   status="scheduled", kickoff_utc=NOW + timedelta(hours=20))
    db.add(m); db.flush()
    db.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                           p_home=0.61, p_draw=0.04, p_away=0.35))
    db.add_all([
        _snap(sport="nrl", match_id=m.id, outcome="home", implied_prob=0.66,
              external_id="n-h"),
        _snap(sport="nrl", match_id=m.id, outcome="away", implied_prob=0.34,
              external_id="n-a"),
    ])
    db.commit()
    body = client.get("/api/intel?sport=nrl").json()
    entry = body["matches"][0]
    assert entry["home"]["name"] == "Melbourne Storm"
    assert entry["model"]["home"] == 0.61
    assert entry["market"][0]["draw"] is None
    # football endpoint unaffected by nrl rows
    assert client.get("/api/intel?sport=football").json()["has_data"] is False
    app.dependency_overrides.clear()


def test_bad_sport_422():
    client, _db = _client()
    assert client.get("/api/intel?sport=cricket").status_code == 422
    app.dependency_overrides.clear()
```

Note: `SportPrediction` requires only the fields used above — check its definition around `backend/app/models/__init__.py:730` while implementing and add any non-nullable columns (e.g. `created_at` has a server default; `p_home/p_draw/p_away/model_version/match_id` are the required ones).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_intel_api.py -v`
Expected: FAIL — 404s (`/api/intel` not mounted) / import errors.

- [ ] **Step 3: Implement the endpoint**

`backend/app/api/intel.py`:

```python
"""Market intel: prediction-market odds vs the model + movement storylines.

Serves entirely from market_odds_snapshots (written hourly by
pipeline/market_intel.py) — the request path never touches an exchange API.
has_data=False (the frontend then falls back to the movers panel) when the
sport has no snapshot fresher than FRESH_HOURS. Only active exchange markets
are ever ingested, so resolved/eliminated outcomes cannot appear here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import serializers
from app.db import get_db
from app.models import (
    MarketOddsSnapshot, Match, SportMatch, SportPrediction, SportTeam, Team,
)

router = APIRouter(prefix="/api/intel", tags=["intel"])

FRESH_HOURS = 24    # no snapshot this recent -> has_data False (movers fallback)
LIVE_HOURS = 3      # storyline markets need a snapshot this recent (~2 cycles)
WINDOW_HOURS = 24   # movement comparison window
MIN_AGE_HOURS = 18  # a "from" snapshot must be at least this old
MAX_MATCHES = 5
MAX_STORYLINES = 3
_DISCLAIMER = "For analytics and entertainment only. Not betting advice."


def _aware(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes for tz-aware columns; pin to UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("")
def intel(sport: str = Query(...), db: Session = Depends(get_db)):
    if sport not in ("football", "nrl"):
        raise HTTPException(status_code=422, detail={"code": "bad_sport",
                                                     "message": "sport must be football or nrl"})
    now = datetime.now(timezone.utc)
    horizon = (now - timedelta(hours=WINDOW_HOURS + 6)).replace(tzinfo=None)
    rows = (
        db.query(MarketOddsSnapshot)
        .filter(MarketOddsSnapshot.sport == sport,
                MarketOddsSnapshot.fetched_at >= horizon)
        .all()
    )
    latest_at = max((_aware(r.fetched_at) for r in rows), default=None)
    if latest_at is None or latest_at < now - timedelta(hours=FRESH_HOURS):
        return {"sport": sport, "has_data": False, "updated_at": None,
                "matches": [], "storylines": [], "disclaimer": _DISCLAIMER}

    # Newest row per (source, external_id, outcome) + full history per key.
    current: dict[tuple, MarketOddsSnapshot] = {}
    history: dict[tuple, list[MarketOddsSnapshot]] = defaultdict(list)
    for r in rows:
        key = (r.source, r.external_id, r.outcome)
        history[key].append(r)
        if key not in current or _aware(r.fetched_at) > _aware(current[key].fetched_at):
            current[key] = r

    fixtures, teams, models = _sport_context(db, sport, current, now)
    matches_out = _build_matches(sport, current, fixtures, teams, models)
    storylines = _build_storylines(current, history, fixtures, teams, now)
    return {"sport": sport, "has_data": True,
            "updated_at": latest_at.isoformat(),
            "matches": matches_out, "storylines": storylines,
            "disclaimer": _DISCLAIMER}


def _sport_context(db: Session, sport: str, current: dict, now: datetime):
    """(future fixtures by id, team names by id, model probs by match id)."""
    match_ids = {r.match_id for r in current.values()
                 if r.market_type == "match_winner" and r.match_id is not None}
    fixtures: dict[int, dict] = {}
    models: dict[int, dict] = {}
    if sport == "football":
        teams = dict(db.query(Team.id, Team.name).all())
        for m in (db.query(Match).filter(Match.id.in_(match_ids),
                                         Match.status == "scheduled").all()
                  if match_ids else []):
            if m.kickoff_utc is None or _aware(m.kickoff_utc) <= now:
                continue
            fixtures[m.id] = {"kickoff": _aware(m.kickoff_utc),
                              "home_id": m.team_home_id, "away_id": m.team_away_id}
            pred = serializers.latest_prediction(db, m.id)
            if pred is not None:
                models[m.id] = {"home": round(pred.prob_home_win, 3),
                                "draw": round(pred.prob_draw, 3),
                                "away": round(pred.prob_away_win, 3)}
    else:
        teams = dict(db.query(SportTeam.id, SportTeam.name)
                     .filter(SportTeam.sport == sport).all())
        for m in (db.query(SportMatch).filter(SportMatch.id.in_(match_ids),
                                              SportMatch.status == "scheduled").all()
                  if match_ids else []):
            if m.kickoff_utc is None or _aware(m.kickoff_utc) <= now:
                continue
            fixtures[m.id] = {"kickoff": _aware(m.kickoff_utc),
                              "home_id": m.home_team_id, "away_id": m.away_team_id}
            pred = (db.query(SportPrediction)
                    .filter(SportPrediction.match_id == m.id)
                    .order_by(SportPrediction.created_at.desc(),
                              SportPrediction.id.desc())
                    .first())
            if pred is not None:
                models[m.id] = {"home": round(pred.p_home, 3),
                                "draw": round(pred.p_draw, 3),
                                "away": round(pred.p_away, 3)}
    return fixtures, teams, models


def _build_matches(sport, current, fixtures, teams, models):
    by_match: dict[int, dict[str, dict[str, MarketOddsSnapshot]]] = \
        defaultdict(lambda: defaultdict(dict))
    for r in current.values():
        if r.market_type == "match_winner" and r.match_id in fixtures:
            by_match[r.match_id][r.source][r.outcome] = r

    out = []
    for match_id in sorted(by_match, key=lambda i: fixtures[i]["kickoff"])[:MAX_MATCHES]:
        fx = fixtures[match_id]
        markets = []
        for source in sorted(by_match[match_id]):
            oc = by_match[match_id][source]
            if "home" not in oc or "away" not in oc:
                continue
            markets.append({
                "source": source,
                "home": round(oc["home"].implied_prob, 3),
                "draw": round(oc["draw"].implied_prob, 3) if "draw" in oc else None,
                "away": round(oc["away"].implied_prob, 3),
                "fetched_at": _aware(oc["home"].fetched_at).isoformat(),
            })
        if not markets:
            continue
        model = models.get(match_id)
        disagreement = None
        if model is not None:
            market_home = sum(mk["home"] for mk in markets) / len(markets)
            disagreement = round(market_home - model["home"], 3)
        out.append({
            "match_id": match_id,
            "kickoff_utc": fx["kickoff"].isoformat(),
            "home": _team_ref(teams, fx["home_id"]),
            "away": _team_ref(teams, fx["away_id"]),
            "model": model, "market": markets, "disagreement": disagreement,
        })
    return out


def _team_ref(teams: dict, team_id: int | None):
    if team_id is None:
        return None
    return {"id": team_id, "name": teams.get(team_id, "Unknown")}


def _build_storylines(current, history, fixtures, teams, now):
    live_cut = now - timedelta(hours=LIVE_HOURS)
    old_cut = now - timedelta(hours=MIN_AGE_HOURS)
    target = now - timedelta(hours=WINDOW_HOURS)
    candidates = []
    for key, cur in current.items():
        if _aware(cur.fetched_at) < live_cut:
            continue
        if cur.market_type == "match_winner":
            if cur.outcome == "draw" or cur.match_id not in fixtures:
                continue
        elif cur.team_id is None:
            continue
        olds = [r for r in history[key] if _aware(r.fetched_at) <= old_cut]
        if not olds:
            continue
        past = min(olds, key=lambda r: abs((_aware(r.fetched_at) - target).total_seconds()))
        if past.implied_prob == cur.implied_prob:
            continue
        candidates.append((abs(cur.implied_prob - past.implied_prob), cur, past))

    candidates.sort(key=lambda c: c[0], reverse=True)
    out, seen = [], set()
    for _delta, cur, past in candidates:
        dedupe = (cur.market_type, cur.match_id, cur.team_id, cur.outcome)
        if dedupe in seen:
            continue  # same move reported by another source: keep the bigger one
        seen.add(dedupe)
        if cur.market_type == "match_winner":
            fx = fixtures[cur.match_id]
            team = _team_ref(teams, fx["home_id" if cur.outcome == "home" else "away_id"])
        else:
            team = _team_ref(teams, cur.team_id)
        window = (_aware(cur.fetched_at) - _aware(past.fetched_at)).total_seconds() / 3600
        out.append({
            "market_type": cur.market_type, "source": cur.source,
            "outcome": cur.outcome, "match_id": cur.match_id, "team": team,
            "prob_from": round(past.implied_prob, 3),
            "prob_to": round(cur.implied_prob, 3),
            "window_hours": round(window),
        })
        if len(out) == MAX_STORYLINES:
            break
    return out
```

In `backend/app/main.py`: add `intel` to the existing `from app.api import (...)` import list (line ~20) and `app.include_router(intel.router)` directly after `app.include_router(movers.router)` (line ~264).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_intel_api.py backend/tests/test_movers_api.py -v`
Expected: all PASSED (movers untouched and still green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/intel.py backend/app/main.py backend/tests/test_intel_api.py
git commit -m "feat: /api/intel endpoint (model-vs-market + storylines)"
```

---

### Task 7: Frontend — types, fetcher, IntelPanel with fallback, page wiring

**Files:**
- Modify: `frontend/lib/types.ts` (append Intel types near `MoversResponse` at ~line 398)
- Modify: `frontend/lib/api.ts` (add `IntelResponse` to the type import; add `getIntel` next to `getMovers` at ~line 84)
- Create: `frontend/components/IntelPanel.tsx`
- Modify: `frontend/app/HomeExperience.tsx` (import at line ~11, usage at line ~210)
- Modify: `frontend/app/nrl/page.tsx` (import at line ~6, usage at line ~36)
- Test: `frontend/components/IntelPanel.test.tsx`

**Interfaces:**
- Consumes: `GET /api/intel` response (Task 6 shape, verbatim), existing `MoversPanel`, `getJson` client fetch helper.
- Produces: `IntelPanel({ sport: "football" | "nrl" })` — self-contained: fetches intel, renders the panel when `has_data`, renders `<MoversPanel sport={sport} />` on `has_data: false` OR fetch error. Exported helpers `storylineLabel(s, sport)` and `minutesAgo(iso, now?)` for tests.

- [ ] **Step 1: Add types**

Append to `frontend/lib/types.ts` (after `MoversResponse`):

```typescript
/** One source's implied probabilities for a match, from GET /api/intel. */
export interface IntelMarket {
  source: string;
  home: number;
  draw: number | null;
  away: number;
  fetched_at: string;
}

export interface IntelTeamRef {
  id: number;
  name: string;
}

export interface IntelMatch {
  match_id: number;
  kickoff_utc: string;
  home: IntelTeamRef | null;
  away: IntelTeamRef | null;
  model: { home: number; draw: number | null; away: number } | null;
  market: IntelMarket[];
  disagreement: number | null;
}

export interface IntelStoryline {
  market_type: "match_winner" | "title_winner";
  source: string;
  outcome: string;
  match_id: number | null;
  team: IntelTeamRef | null;
  prob_from: number;
  prob_to: number;
  window_hours: number;
}

export interface IntelResponse {
  sport: "football" | "nrl";
  has_data: boolean;
  updated_at: string | null;
  matches: IntelMatch[];
  storylines: IntelStoryline[];
  disclaimer: string;
}
```

Add to `frontend/lib/api.ts`: `IntelResponse` in the type import block, and after `getMovers`:

```typescript
/** Market intel (Polymarket/Kalshi vs the model). has_data=false means the
 *  caller should render the movers fallback instead. */
export const getIntel = (sport: "football" | "nrl") =>
  getJson<IntelResponse>(`/api/intel?sport=${sport}`);
```

- [ ] **Step 2: Write the failing test**

`frontend/components/IntelPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { IntelPanel, minutesAgo, storylineLabel } from "@/components/IntelPanel";
import type { IntelResponse } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  getIntel: jest.fn(),
  getMovers: jest.fn(),
}));
const { getIntel, getMovers } = jest.requireMock("@/lib/api");

const INTEL: IntelResponse = {
  sport: "football",
  has_data: true,
  updated_at: new Date(Date.now() - 23 * 60 * 1000).toISOString(),
  matches: [
    {
      match_id: 1,
      kickoff_utc: new Date(Date.now() + 12 * 3600 * 1000).toISOString(),
      home: { id: 1, name: "France" },
      away: { id: 2, name: "Morocco" },
      model: { home: 0.55, draw: 0.27, away: 0.18 },
      market: [
        { source: "polymarket", home: 0.62, draw: 0.24, away: 0.14,
          fetched_at: new Date().toISOString() },
      ],
      disagreement: 0.07,
    },
  ],
  storylines: [
    { market_type: "title_winner", source: "polymarket", outcome: "win",
      match_id: null, team: { id: 3, name: "Argentina" },
      prob_from: 0.24, prob_to: 0.31, window_hours: 24 },
  ],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

describe("IntelPanel", () => {
  beforeEach(() => jest.resetAllMocks());

  it("renders model vs market and storylines when has_data", async () => {
    getIntel.mockResolvedValue(INTEL);
    render(<IntelPanel sport="football" />);
    expect(await screen.findByText("Market intel")).toBeInTheDocument();
    expect(screen.getByText(/France vs Morocco/)).toBeInTheDocument();
    expect(screen.getByText(/Market 62%/)).toBeInTheDocument();
    expect(screen.getByText(/Model 55%/)).toBeInTheDocument();
    expect(screen.getByText(/Argentina to win the Cup/)).toBeInTheDocument();
    expect(screen.getByText(/24% → 31%/)).toBeInTheDocument();
    expect(getMovers).not.toHaveBeenCalled();
  });

  it("falls back to MoversPanel when has_data is false", async () => {
    getIntel.mockResolvedValue({ ...INTEL, has_data: false, matches: [], storylines: [] });
    getMovers.mockResolvedValue({ sport: "football", as_of: null, movers: [
      { entity_id: 1, name: "France", market: "win_title", prob: 0.31,
        delta: 0.05, series: [0.26, 0.31] },
    ], disclaimer: "" });
    render(<IntelPanel sport="football" />);
    expect(await screen.findByText("Today's movers")).toBeInTheDocument();
  });

  it("falls back to MoversPanel when the intel fetch fails", async () => {
    getIntel.mockRejectedValue(new Error("boom"));
    getMovers.mockResolvedValue({ sport: "football", as_of: null, movers: [
      { entity_id: 1, name: "France", market: "win_title", prob: 0.31,
        delta: null, series: [0.31] },
    ], disclaimer: "" });
    render(<IntelPanel sport="football" />);
    expect(await screen.findByText("Today's movers")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("storylineLabel wording per market and sport", () => {
    expect(storylineLabel(INTEL.storylines[0], "football"))
      .toBe("Argentina to win the Cup");
    expect(storylineLabel({ ...INTEL.storylines[0], market_type: "match_winner",
                            team: { id: 1, name: "France" } }, "football"))
      .toBe("France to win the match");
    expect(storylineLabel(INTEL.storylines[0], "nrl"))
      .toBe("Argentina to win the Premiership");
  });

  it("minutesAgo formats", () => {
    const now = new Date("2026-07-10T15:00:00Z");
    expect(minutesAgo("2026-07-10T14:37:00Z", now)).toBe("23m ago");
    expect(minutesAgo("2026-07-10T12:00:00Z", now)).toBe("3h ago");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx jest components/IntelPanel.test.tsx`
Expected: FAIL — `Cannot find module '@/components/IntelPanel'`

- [ ] **Step 4: Implement the component**

`frontend/components/IntelPanel.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getIntel } from "@/lib/api";
import type { IntelMatch, IntelResponse, IntelStoryline } from "@/lib/types";
import { MoversPanel } from "@/components/MoversPanel";

const pct = (p: number) => `${Math.round(p * 100)}%`;

/** Disagreement worth calling out: market and model ≥5 points apart. */
const DISAGREE_PTS = 0.05;

/** "Argentina to win the Cup" / "France to win the match". */
export function storylineLabel(
  s: IntelStoryline,
  sport: "football" | "nrl",
): string {
  const name = s.team?.name ?? "—";
  if (s.market_type === "title_winner") {
    return `${name} to win the ${sport === "football" ? "Cup" : "Premiership"}`;
  }
  return `${name} to win the match`;
}

/** "23m ago" / "3h ago" for the provenance footer. */
export function minutesAgo(iso: string, now: Date = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  return mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`;
}

function MatchRow({ m, sport }: { m: IntelMatch; sport: "football" | "nrl" }) {
  const market = m.market[0];
  const disagree =
    m.disagreement !== null && Math.abs(m.disagreement) >= DISAGREE_PTS;
  // NRL match pages are keyed by (season, round, match_no) — not by the
  // sport_matches id this payload carries — so only football rows link out.
  const Body = sport === "football" ? Link : "div";
  return (
    <li className="border-t border-white/10 py-2.5 first:border-t-0">
      <Body href={`/matches/${m.match_id}`} className="block">
        <span className="font-display text-[15px] font-semibold text-white">
          {m.home?.name ?? "TBD"} vs {m.away?.name ?? "TBD"}
        </span>
        <span className="mt-0.5 block text-[12px] font-medium text-white/60">
          Market {pct(market.home)}
          {market.draw !== null ? ` · draw ${pct(market.draw)}` : ""} ·{" "}
          {pct(market.away)}
        </span>
        {m.model ? (
          <span className="block text-[12px] font-medium text-white/45">
            Model {pct(m.model.home)}
            {m.model.draw !== null ? ` · draw ${pct(m.model.draw)}` : ""} ·{" "}
            {pct(m.model.away)}
            {disagree ? (
              <span className="ml-2 font-semibold text-win">
                market {m.disagreement! > 0 ? "higher" : "lower"} on{" "}
                {m.home?.name ?? "home"}
              </span>
            ) : null}
          </span>
        ) : null}
      </Body>
    </li>
  );
}

/** Dashboard hero (spec 2026-07-10): prediction-market odds vs our model for
 *  the next fixtures + the biggest 24h market moves. Falls back to the movers
 *  panel whenever the sport has no fresh market data or the fetch fails. */
export function IntelPanel({ sport }: { sport: "football" | "nrl" }) {
  const [intel, setIntel] = useState<IntelResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setIntel(null);
    setFailed(false);
    getIntel(sport)
      .then((res) => {
        if (active) setIntel(res);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [sport]);

  if (failed || (intel !== null && !intel.has_data)) {
    return <MoversPanel sport={sport} />;
  }

  return (
    <section className="panel-pitch mt-6 rounded-2xl p-5">
      <p className="font-display text-[11px] font-semibold uppercase tracking-[0.2em] text-white/60">
        Market intel
      </p>
      {intel === null ? (
        <div className="skeleton mt-4 h-32 rounded-xl" aria-hidden="true" />
      ) : (
        <>
          <ul className="mt-2">
            {intel.matches.map((m) => (
              <MatchRow key={m.match_id} m={m} sport={sport} />
            ))}
          </ul>
          {intel.storylines.length > 0 ? (
            <ul className="mt-3 border-t border-white/10 pt-2">
              {intel.storylines.map((s) => (
                <li
                  key={`${s.market_type}-${s.match_id ?? s.team?.id}-${s.outcome}`}
                  className="py-1 text-[12px] font-medium text-white/60"
                >
                  {storylineLabel(s, sport)}{" "}
                  <span className={s.prob_to >= s.prob_from ? "text-win" : "text-loss"}>
                    {pct(s.prob_from)} → {pct(s.prob_to)}
                  </span>{" "}
                  <span className="text-white/35">
                    in {s.window_hours}h · {s.source}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {intel.updated_at ? (
            <p className="mt-2 text-[11px] font-medium text-white/35">
              via Polymarket · Kalshi · updated {minutesAgo(intel.updated_at)}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
```

Note: check `text-loss` exists in the Tailwind palette (`grep -rn "text-loss\|text-win" frontend/components | head`); if the codebase uses a different down-tone class, match it.

- [ ] **Step 5: Wire into both home pages**

`frontend/app/HomeExperience.tsx` line ~11: replace
`import { MoversPanel } from "@/components/MoversPanel";` with
`import { IntelPanel } from "@/components/IntelPanel";`
and line ~210: replace `<MoversPanel sport="football" />` with `<IntelPanel sport="football" />`.

`frontend/app/nrl/page.tsx` line ~6: replace
`import { MoversPanel } from "@/components/MoversPanel";` with
`import { IntelPanel } from "@/components/IntelPanel";`
and line ~36: replace `<MoversPanel sport="nrl" />` with `<IntelPanel sport="nrl" />`.

(If another file still imports `MoversPanel` — `MatchScoreboard.tsx` references it only in a comment — leave it alone. MoversPanel itself stays untouched: it IS the fallback.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx jest components/IntelPanel.test.tsx && npm run typecheck`
Expected: all PASSED, typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/IntelPanel.tsx frontend/components/IntelPanel.test.tsx frontend/app/HomeExperience.tsx frontend/app/nrl/page.tsx
git commit -m "feat: IntelPanel replaces movers on both dashboards (movers = fallback)"
```

---

### Task 8: Full test gate + PR

**Files:** none new — verification and PR only.

**Interfaces:**
- Consumes: everything above.
- Produces: a green branch and an open PR. Merge/deploy stays behind the stop gate.

- [ ] **Step 1: Run the full Python suite**

Run: `.venv/bin/python -m pytest`
Expected: all PASSED (testpaths: backend, ml, pipeline). Paste the tail of the output into the PR description.

- [ ] **Step 2: Run the full frontend gate**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: all clean/PASSED.

- [ ] **Step 3: Open the PR**

```bash
git push -u origin feat/market-intel-panel
gh pr create --title "feat: Market Intel panel (Polymarket/Kalshi) replaces Today's Movers" --body "$(cat <<'EOF'
Replaces the stale Today's Movers dashboard panel with a Market Intel panel:
model-vs-market probabilities (Polymarket + Kalshi) for upcoming fixtures plus
the biggest 24h market moves. MoversPanel is untouched and renders as the
automatic fallback whenever a sport has no fresh market data (NRL most days,
football after the final) or the fetch fails.

Spec: docs/superpowers/specs/2026-07-10-market-intel-panel-design.md

- New market_odds_snapshots table (migration c7d8e9f0a1b2)
- Hourly .github/workflows/market-intel.yml (read-only public APIs, no new secrets)
- New GET /api/intel (DB-only; exchanges never in the request path)
- New IntelPanel component wired into both sport dashboards

RELEASE SEQUENCING (stop gate): merge -> dispatch refresh.yml (applies the
migration) -> verify GET /api/health and GET /api/intel?sport=football on prod.
The frontend falls back to movers if /api/intel errors, so the merge->migration
window is user-invisible.

(replace this line with the actual pytest + npm test output tails from Steps 1-2 before submitting)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Stop.** Report the PR link and the test output to the human. Merging to `main`, dispatching `refresh.yml`, and the first `market-intel.yml` run against prod are stop-gated — wait for the explicit "go".
