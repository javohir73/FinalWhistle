"""Tests for _host_adv's tournament-scoped home_advantage_mode (league pivot D4).

WC26's "host_bonus" behavior must stay byte-identical (generate_predictions_test.py
already covers that end to end); this file covers the new "home" branch a club
league switches on, plus the value/fallback wiring.
"""
from app.models import Match, Team, Tournament
from pipeline.generate_predictions import _host_adv
from pipeline.ingest import league_structure as ls_mod
from pipeline.ingest.league_structure import load_league_structure
from pipeline.ingest.wc26_structure import load_structure as load_wc26_structure


def test_wc26_tournament_defaults_to_host_bonus_mode(db_session):
    load_wc26_structure(db_session)
    tournament = db_session.query(Tournament).filter_by(name="FIFA World Cup 2026").one()
    assert tournament.home_advantage_mode == "host_bonus"
    assert tournament.home_advantage_value is None


def test_host_bonus_mode_unchanged_non_host_match_is_zero(db_session):
    load_wc26_structure(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.host_team_id.is_(None))
        .first()
    )
    home = db_session.get(Team, match.team_home_id)
    assert _host_adv(match, home, home_advantage=60.0) == 0.0


def test_host_bonus_mode_signed_for_host_match(db_session):
    load_wc26_structure(db_session)
    match = db_session.query(Match).filter(Match.host_team_id.isnot(None)).first()
    home = db_session.get(Team, match.team_home_id)
    away = db_session.get(Team, match.team_away_id)
    expected_home = 60.0 if match.host_team_id == home.id else -60.0
    expected_away = 60.0 if match.host_team_id == away.id else -60.0
    assert _host_adv(match, home, home_advantage=60.0) == expected_home
    assert _host_adv(match, away, home_advantage=60.0) == expected_away


def test_home_mode_applies_unconditionally_to_team_home(db_session, monkeypatch):
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        {
            "fixture": {"id": 1, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "NS"}},
            "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
            "goals": {"home": None, "away": None},
        }
    ])
    load_league_structure(db_session, api_key="x")
    tournament = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()
    assert tournament.home_advantage_mode == "home"

    match = db_session.query(Match).filter_by(provider_fixture_id=1).one()
    home = db_session.get(Team, match.team_home_id)
    away = db_session.get(Team, match.team_away_id)

    # No tuned value yet -> falls back to the passed-in engine home_advantage,
    # applied to team_home regardless of any host_team_id (leagues never set one).
    assert _host_adv(match, home, home_advantage=60.0) == 60.0
    # NOTE: _host_adv is only ever called with the HOME team in production
    # (build_payload/_simulate_standings/_simulate_tournament all resolve
    # `home` before calling it) — there is no "away" signed case in "home"
    # mode, unlike host_bonus's host-can-be-either-side symmetry.


def test_home_mode_uses_tournament_tuned_value_when_set(db_session, monkeypatch):
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        {
            "fixture": {"id": 2, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "NS"}},
            "teams": {"home": {"name": "Liverpool"}, "away": {"name": "Everton"}},
            "goals": {"home": None, "away": None},
        }
    ])
    load_league_structure(db_session, api_key="x")
    tournament = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()
    tournament.home_advantage_value = 60.0  # the fit winner (pipeline/compute_club_elo.py)
    db_session.commit()

    match = db_session.query(Match).filter_by(provider_fixture_id=2).one()
    home = db_session.get(Team, match.team_home_id)
    # Tuned value wins over the passed-in engine default (80.0).
    assert _host_adv(match, home, home_advantage=80.0) == 60.0
