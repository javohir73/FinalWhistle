"""Tests for the StatsBomb xG backfill (pipeline/backfill_xg.py).

Phase 2: pure shot-xG parser + cached fetch scaffolding. All offline — hand-built
event/match fixtures, no network, no DB. Only `type.name=="Shot"` events with a
non-null `shot.statsbomb_xg` count, keyed by `team.name`; the penalty shootout
(period == 5) is excluded because `historical_matches.score_a/score_b` is the
after-extra-time score and would otherwise be compared against xG that roughly
doubles a knockout team's true attacking output (see plan's grounding on the
WC2022 final, Argentina 3-3 France: 5.89/5.41 all-periods vs 2.76/2.27 periods 1-4).

Phase 3: the swapped-orientation fixture matcher (`match_statsbomb_to_rows`,
mirroring `ml/evaluation/market_benchmark.py::join_odds_to_rows`'s
swap-and-flip precedent for neutral-venue matches) and the idempotent
`backfill_xg(db, ...)` orchestrator. All matcher tests are pure over dict
fixtures; the idempotency test uses an in-memory SQLite DB and a pre-seeded
fake cache dir so it stays fully offline.
"""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import HistoricalMatch, Team
from pipeline.backfill_xg import (
    SIX_EDITIONS,
    backfill_xg,
    enumerate_editions,
    match_statsbomb_to_rows,
    match_xg,
    sum_shot_xg_by_team,
)
from pipeline.team_mapping import normalize_team_name


def _shot(team, xg, period=1):
    return {"type": {"name": "Shot"}, "team": {"name": team}, "period": period,
            "shot": {"statsbomb_xg": xg}}


def _other(team, period=1):
    return {"type": {"name": "Pass"}, "team": {"name": team}, "period": period}


def test_sum_shot_xg_by_team_sums_only_shots():
    events = [
        _shot("France", 0.10),
        _other("France"),
        _shot("France", 0.35),
        _shot("Argentina", 0.05),
        _other("Argentina"),
    ]
    out = sum_shot_xg_by_team(events)
    assert out == pytest.approx({"France": 0.45, "Argentina": 0.05})


def test_sum_shot_xg_skips_missing_xg():
    events = [
        _shot("France", 0.20),
        {"type": {"name": "Shot"}, "team": {"name": "France"}, "period": 1,
         "shot": {}},  # statsbomb_xg absent -> skipped, not counted as 0
        _shot("Argentina", 0.15),
    ]
    out = sum_shot_xg_by_team(events)
    assert out == {"France": 0.20, "Argentina": 0.15}


def test_match_xg_maps_home_away():
    match = {"home_team": {"home_team_name": "Canada"},
             "away_team": {"away_team_name": "Morocco"}}
    events = [_shot("Canada", 1.096), _shot("Morocco", 0.426)]
    home_xg, away_xg = match_xg(match, events)
    assert home_xg == 1.096
    assert away_xg == 0.426


def test_match_xg_absent_side_is_none():
    match = {"home_team": {"home_team_name": "Canada"},
             "away_team": {"away_team_name": "Morocco"}}
    events = [_shot("Canada", 1.096)]  # Morocco has zero shot-xG entries
    home_xg, away_xg = match_xg(match, events)
    assert home_xg == 1.096
    assert away_xg is None

    # malformed events -> (None, None), no raise
    home_xg2, away_xg2 = match_xg(match, [{"garbage": True}, None])
    assert (home_xg2, away_xg2) == (None, None)


def test_sum_shot_xg_excludes_shootout():
    # WC2022 final grounding: periods 1-4 sum to 2.76/2.27; adding period-5
    # (shootout) inflates to 5.89/5.41. Only periods <= 4 should count.
    events = [
        _shot("Argentina", 1.50, period=1),
        _shot("Argentina", 1.26, period=4),
        _shot("France", 1.20, period=2),
        _shot("France", 1.07, period=4),
        # Shootout (period 5) -- must be excluded.
        _shot("Argentina", 3.13, period=5),
        _shot("France", 3.14, period=5),
    ]
    out = sum_shot_xg_by_team(events)
    assert out["Argentina"] == pytest.approx(2.76)
    assert out["France"] == pytest.approx(2.27)


# ---------------------------------------------------------------------------
# Phase 3: swapped-orientation fixture matcher (match_statsbomb_to_rows)
# ---------------------------------------------------------------------------

def _sb_record(home, away, match_date, home_xg, away_xg, home_score=1, away_score=0):
    return {
        "match_date": match_date,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "home_xg": home_xg,
        "away_xg": away_xg,
    }


def _row(row_id, team_a_id, team_b_id, d, score_a=1, score_b=0, xg_a=None):
    return {
        "id": row_id,
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "date": d,
        "score_a": score_a,
        "score_b": score_b,
        "xg_a": xg_a,
    }


_ID_TO_NAME = {1: "France", 2: "Argentina"}


def test_direct_key_writes_a_b():
    # Row stored team_a=France, team_b=Argentina; StatsBomb home=France, away=Argentina.
    rows = [_row(1, 1, 2, date(2022, 12, 18), score_a=3, score_b=3)]
    sb = [_sb_record("France", "Argentina", "2022-12-18", 2.27, 2.76, 3, 3)]

    writes, unmatched = match_statsbomb_to_rows(sb, rows, _ID_TO_NAME, normalize_team_name)

    assert unmatched == []
    assert len(writes) == 1
    assert writes[0] == {"id": 1, "xg_a": 2.27, "xg_b": 2.76}


def test_swapped_key_flips_xg():
    # Row stored team_a=Argentina, team_b=France (opposite of StatsBomb's home/away).
    rows = [_row(1, 2, 1, date(2022, 12, 18), score_a=3, score_b=3)]
    sb = [_sb_record("France", "Argentina", "2022-12-18", 2.27, 2.76, 3, 3)]

    writes, unmatched = match_statsbomb_to_rows(sb, rows, _ID_TO_NAME, normalize_team_name)

    assert unmatched == []
    assert len(writes) == 1
    # team_a is Argentina (StatsBomb away) -> xg_a is the away_xg; flipped.
    assert writes[0] == {"id": 1, "xg_a": 2.76, "xg_b": 2.27}


def test_unmatched_is_logged_left_null():
    rows = [_row(1, 1, 2, date(2022, 12, 18))]
    # Different date -> no key hit at all.
    sb = [_sb_record("France", "Argentina", "2022-12-19", 2.27, 2.76)]

    writes, unmatched = match_statsbomb_to_rows(sb, rows, _ID_TO_NAME, normalize_team_name)

    assert writes == []
    assert len(unmatched) == 1


def test_normalize_bridges_iran_and_czechia():
    id_to_name = {1: "IR Iran", 2: "Czech Republic"}
    rows = [_row(1, 1, 2, date(2022, 11, 25))]
    sb = [_sb_record("Iran", "Czechia", "2022-11-25", 0.5, 0.6)]

    writes, unmatched = match_statsbomb_to_rows(sb, rows, id_to_name, normalize_team_name)

    assert unmatched == []
    assert len(writes) == 1
    assert writes[0] == {"id": 1, "xg_a": 0.5, "xg_b": 0.6}

    # empty-string names (normalize_team_name(None) == "") are never keyed / skipped.
    id_to_name_missing = {1: None, 2: "Czechia"}
    writes2, unmatched2 = match_statsbomb_to_rows(sb, rows, id_to_name_missing, normalize_team_name)
    assert writes2 == []
    assert len(unmatched2) == 1


def test_score_crosscheck_flags_mismatch():
    # Key hits (direct orientation) but StatsBomb's score disagrees with the row's.
    rows = [_row(1, 1, 2, date(2022, 12, 18), score_a=3, score_b=3)]
    sb = [_sb_record("France", "Argentina", "2022-12-18", 2.27, 2.76,
                      home_score=2, away_score=1)]  # disagrees with row's 3-3

    writes, unmatched = match_statsbomb_to_rows(sb, rows, _ID_TO_NAME, normalize_team_name)

    # Not silently written: flagged as suspicious via the unmatched/log path.
    assert writes == []
    assert len(unmatched) == 1


def test_ambiguous_key_collision_dropped():
    # Two StatsBomb records collide on the same (date, home, away) key.
    rows = [_row(1, 1, 2, date(2022, 12, 18))]
    sb = [
        _sb_record("France", "Argentina", "2022-12-18", 2.27, 2.76, 3, 3),
        _sb_record("France", "Argentina", "2022-12-18", 1.0, 1.0, 3, 3),
    ]

    writes, unmatched = match_statsbomb_to_rows(sb, rows, _ID_TO_NAME, normalize_team_name)

    assert writes == []
    assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# Phase 3: idempotent backfill_xg(db, ...) orchestrator
# ---------------------------------------------------------------------------

def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_backfill_skips_populated_rows(tmp_path, monkeypatch):
    db = _session()
    france = Team(name="France")
    argentina = Team(name="Argentina")
    db.add_all([france, argentina])
    db.flush()

    # Row already has xg_a populated -> must be skipped; its events file must
    # never be fetched (no cache entry exists for it, and network is blocked).
    populated = HistoricalMatch(
        date=datetime(2022, 12, 18, tzinfo=timezone.utc),
        team_a_id=france.id, team_b_id=argentina.id,
        score_a=3, score_b=3, xg_a=2.27, xg_b=2.76,
    )
    db.add(populated)
    db.commit()

    cache_dir = tmp_path / "statsbomb_cache"
    (cache_dir / "events").mkdir(parents=True)

    competitions = [{"competition_id": cid, "season_id": sid} for cid, sid in SIX_EDITIONS]
    matches_by_edition = {
        SIX_EDITIONS[1]: [
            {
                "match_id": 3857300,
                "match_date": "2022-12-18",
                "home_team": {"home_team_name": "France"},
                "away_team": {"away_team_name": "Argentina"},
                "home_score": 3,
                "away_score": 3,
            }
        ]
    }

    def fake_get_json(url):
        if url.endswith("/competitions.json"):
            return competitions
        for (cid, sid), matches in matches_by_edition.items():
            if url.endswith(f"/matches/{cid}/{sid}.json"):
                return matches
        return []

    def fail_fetch_events(match_id, cache_dir):
        raise AssertionError("events must not be fetched for an already-populated row")

    monkeypatch.setattr("pipeline.backfill_xg._get_json", fake_get_json)
    monkeypatch.setattr("pipeline.backfill_xg._fetch_events", fail_fetch_events)

    summary = backfill_xg(db, cache_dir=str(cache_dir), editions=SIX_EDITIONS)

    assert summary["skipped_populated"] == 1
    assert summary["rows_written"] == 0
    db.refresh(populated)
    assert populated.xg_a == 2.27 and populated.xg_b == 2.76


def test_backfill_survives_malformed_match_date(tmp_path, monkeypatch):
    # A malformed StatsBomb match_date must NOT abort the run (never-raises
    # contract): the bad record is skipped, the valid match is still written.
    db = _session()
    france, argentina = Team(name="France"), Team(name="Argentina")
    db.add_all([france, argentina])
    db.flush()
    row = HistoricalMatch(
        date=datetime(2022, 12, 18, tzinfo=timezone.utc),
        team_a_id=france.id, team_b_id=argentina.id,
        score_a=3, score_b=3, xg_a=None, xg_b=None,
    )
    db.add(row)
    db.commit()

    cache_dir = tmp_path / "statsbomb_cache"
    (cache_dir / "events").mkdir(parents=True)

    competitions = [{"competition_id": cid, "season_id": sid} for cid, sid in SIX_EDITIONS]
    valid = {
        "match_id": 3869685, "match_date": "2022-12-18",
        "home_team": {"home_team_name": "France"},
        "away_team": {"away_team_name": "Argentina"},
        "home_score": 3, "away_score": 3,
    }
    malformed = {
        "match_id": 999, "match_date": "2022-13-99",  # fromisoformat would raise
        "home_team": {"home_team_name": "Brazil"},
        "away_team": {"away_team_name": "Croatia"},
        "home_score": 1, "away_score": 1,
    }
    matches = {SIX_EDITIONS[1]: [valid, malformed]}

    def fake_get_json(url):
        if url.endswith("/competitions.json"):
            return competitions
        for (cid, sid), ms in matches.items():
            if url.endswith(f"/matches/{cid}/{sid}.json"):
                return ms
        return []

    def fake_fetch_events(match_id, cache_dir):
        if match_id == 3869685:
            return [_shot("France", 2.27), _shot("Argentina", 2.76)]
        return []

    monkeypatch.setattr("pipeline.backfill_xg._get_json", fake_get_json)
    monkeypatch.setattr("pipeline.backfill_xg._fetch_events", fake_fetch_events)

    summary = backfill_xg(db, cache_dir=str(cache_dir), editions=SIX_EDITIONS)  # must not raise

    assert summary["rows_written"] == 1
    db.refresh(row)
    assert row.xg_a == 2.27 and row.xg_b == 2.76


def test_enumerate_editions_keeps_282_collision():
    # Copa America 2024 (223,282) and UEFA Euro 2024 (55,282) share season_id
    # 282; enumerate_editions must keep BOTH (keyed on the PAIR, never season_id
    # alone) — the collision the SIX_EDITIONS comment warns about.
    competitions = [
        {"competition_id": 55, "season_id": 282},
        {"competition_id": 223, "season_id": 282},
        {"competition_id": 43, "season_id": 3},
    ]
    editions = enumerate_editions(competitions)
    assert (55, 282) in editions
    assert (223, 282) in editions
