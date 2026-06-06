"""Tests for the WC2026 structure loader (task 2.10)."""
from app.models import Group, Match, Team
from pipeline.ingest.wc26_structure import load_structure


def test_loads_full_structure(db_session):
    summary = load_structure(db_session)
    assert summary["teams"] == 48
    assert summary["groups"] == 12
    assert summary["total_matches"] == 104
    assert summary["group_matches_created"] == 72  # 12 groups x 6
    assert summary["knockout_created"] == 32

    assert db_session.query(Team).count() == 48
    assert db_session.query(Group).count() == 12
    assert db_session.query(Match).count() == 104


def test_host_advantage_set_for_host_group_matches(db_session):
    load_structure(db_session)
    # 3 hosts x 3 group matches each = 9 matches with a host playing at home.
    host_matches = db_session.query(Match).filter(Match.host_team_id.isnot(None)).all()
    assert len(host_matches) == 9
    for m in host_matches:
        assert m.is_neutral is False
        assert m.venue_country in {"Mexico", "Canada", "United States"}


def test_is_idempotent(db_session):
    load_structure(db_session)
    second = load_structure(db_session)
    assert second["group_matches_created"] == 0
    assert second["knockout_created"] == 0
    assert db_session.query(Match).count() == 104


def test_group_a_membership(db_session):
    load_structure(db_session)
    group_a = db_session.query(Group).filter_by(name="Group A").one()
    names = sorted(gt.team.name for gt in group_a.group_teams)
    assert names == ["Czechia", "Mexico", "South Africa", "South Korea"]
