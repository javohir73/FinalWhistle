"""Tests for pipeline/sports/nrl_team_lists.py — team-list ingest with
late-change flagging (Wave 3 Task 2). No live HTTP anywhere in this file.

The real TeamListEntry (pipeline.sports.nrl_stats) carries no match_id — a
provider can't know our DB ids — so ingest_round resolves each entry to a
match by matching entry.team against the home/away team NAMES of that
round's SportMatch rows. upsert_team_list takes entries already grouped by
DB match id (entries_by_match: dict[int, list[TeamListEntry]]).
"""
from datetime import datetime, timedelta, timezone

from app.models import NrlTeamList, SportMatch, SportTeam
from pipeline.sports.nrl_fixture_provider import RecordedFixtureStatsProvider
from pipeline.sports.nrl_stats import TeamListEntry
from pipeline.sports.nrl_team_lists import (
    ingest_round,
    rounds_needing_team_lists,
    upsert_team_list,
)


def _make_match(db, season=2026, round_no=1, match_no=1, home="Broncos", away="Storm",
                 status="scheduled", kickoff_utc=None):
    home_team = SportTeam(sport="nrl", name=home)
    away_team = SportTeam(sport="nrl", name=away)
    db.add_all([home_team, away_team])
    db.flush()
    m = SportMatch(
        sport="nrl", season=season, round=round_no, match_no=match_no,
        home_team_id=home_team.id, away_team_id=away_team.id,
        status=status, kickoff_utc=kickoff_utc,
    )
    db.add(m)
    db.commit()
    return m


# --- upsert_team_list --------------------------------------------------------

def test_upsert_team_list_first_announcement_is_not_late_change(db_session):
    m = _make_match(db_session)
    entries = [
        TeamListEntry(team="Broncos", jersey=1, player="A. First", position="FB"),
        TeamListEntry(team="Broncos", jersey=2, player="B. Second", position="WG"),
    ]
    summary = upsert_team_list(db_session, {m.id: entries})
    assert summary == {"matches": 1, "players": 2, "late_changes": 0}
    rows = db_session.query(NrlTeamList).filter_by(match_id=m.id).all()
    assert len(rows) == 2
    assert all(not r.is_late_change for r in rows)


def test_upsert_team_list_flags_swapped_player_as_late_change(db_session):
    m = _make_match(db_session)
    first = [TeamListEntry(team="Broncos", jersey=1, player="A. First", position="FB")]
    upsert_team_list(db_session, {m.id: first})

    swapped = [TeamListEntry(team="Broncos", jersey=1, player="C. Replacement", position="FB")]
    summary = upsert_team_list(db_session, {m.id: swapped})
    assert summary == {"matches": 1, "players": 1, "late_changes": 1}
    row = db_session.query(NrlTeamList).filter_by(match_id=m.id, jersey=1).one()
    assert row.player == "C. Replacement"
    assert row.is_late_change is True


def test_upsert_team_list_same_player_reingested_is_not_late_change(db_session):
    m = _make_match(db_session)
    entries = [TeamListEntry(team="Broncos", jersey=1, player="A. First", position="FB")]
    upsert_team_list(db_session, {m.id: entries})
    summary = upsert_team_list(db_session, {m.id: entries})
    assert summary["late_changes"] == 0
    assert summary == {"matches": 1, "players": 1, "late_changes": 0}


# --- ingest_round -------------------------------------------------------------

def test_ingest_round_never_raises_on_fetch_error(db_session):
    class _Boom:
        def fetch_team_list(self, season, round_no):
            raise RuntimeError("feed down")
        def fetch_match_stats(self, *a): return None
        def fetch_live(self, *a): return None

    summary = ingest_round(db_session, 2026, 1, _Boom())
    assert summary == {"matches": 0, "players": 0, "late_changes": 0}


def test_ingest_round_with_recorded_fixture_provider(db_session):
    m = _make_match(db_session, season=2026, round_no=1, home="Broncos", away="Storm")
    provider = RecordedFixtureStatsProvider(team_lists={
        (2026, 1): [TeamListEntry(team="Broncos", jersey=1, player="A. First", position="FB")],
    })
    summary = ingest_round(db_session, 2026, 1, provider)
    assert summary["matches"] == 1
    assert summary["players"] == 1
    assert summary["late_changes"] == 0
    row = db_session.query(NrlTeamList).filter_by(match_id=m.id, jersey=1).one()
    assert row.player == "A. First"
    assert row.team == "Broncos"


def test_ingest_round_ignores_entries_for_unknown_matches(db_session):
    # A match exists in the round, but none of its team names ("Broncos" /
    # "Storm") match the provider's entry team ("Ghosts") -- unresolvable
    # entries are dropped rather than guessed at.
    _make_match(db_session, season=2026, round_no=1, home="Broncos", away="Storm")
    provider = RecordedFixtureStatsProvider(team_lists={
        (2026, 1): [TeamListEntry(team="Ghosts", jersey=1, player="Ghost Player", position="FB")],
    })
    summary = ingest_round(db_session, 2026, 1, provider)
    assert summary == {"matches": 0, "players": 0, "late_changes": 0}
    assert db_session.query(NrlTeamList).count() == 0


# --- rounds_needing_team_lists -------------------------------------------------

def test_rounds_needing_team_lists_only_includes_near_term_scheduled(db_session):
    now = datetime.now(timezone.utc)
    near = SportMatch(sport="nrl", season=2026, round=5, match_no=1, status="scheduled",
                       kickoff_utc=now + timedelta(days=2))
    far = SportMatch(sport="nrl", season=2026, round=9, match_no=1, status="scheduled",
                      kickoff_utc=now + timedelta(days=30))
    finished = SportMatch(sport="nrl", season=2026, round=4, match_no=1, status="finished",
                           kickoff_utc=now - timedelta(days=3), score_home=10, score_away=6)
    db_session.add_all([near, far, finished])
    db_session.commit()

    assert rounds_needing_team_lists(db_session, 2026) == [5]
