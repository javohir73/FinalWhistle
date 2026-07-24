"""Tests for the EPL 2026-27 structure loader (league pivot D1/D2)."""
from app.cache import cache
from app.models import Group, GroupTeam, Match, Team, Tournament
from pipeline.ingest import league_structure as ls_mod
from pipeline.ingest.league_structure import load_league_structure
from pipeline.ingest.wc26_structure import load_structure as load_wc26_structure


def _fixture(fid, home, away, *, status="NS", gh=None, ga=None,
             kickoff="2026-08-21T19:00:00+00:00", round_=None):
    fx = {
        "fixture": {"id": fid, "date": kickoff, "status": {"short": status}},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": gh, "away": ga},
    }
    if round_ is not None:
        fx["league"] = {"round": round_}
    return fx


def test_seeds_teams_group_and_tournament_mode(db_session, monkeypatch):
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [])
    load_league_structure(db_session, api_key="x")

    assert db_session.query(Team).count() == 20
    tournament = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()
    assert tournament.year == 2026
    assert tournament.home_advantage_mode == "home"

    group = db_session.query(Group).filter_by(tournament_id=tournament.id).one()
    assert group.name == "Premier League"
    assert db_session.query(GroupTeam).filter_by(group_id=group.id).count() == 20


def test_upserts_fixtures_idempotently(db_session, monkeypatch):
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(1001, "Arsenal", "Chelsea", status="NS")],
    )
    summary = load_league_structure(db_session, api_key="x")
    assert summary["fixtures_created"] == 1
    assert summary["fixtures_updated"] == 0

    match = db_session.query(Match).filter_by(provider_fixture_id=1001).one()
    assert match.status == "scheduled"
    assert match.stage == "group"
    assert match.is_neutral is False
    arsenal = db_session.query(Team).filter_by(name="Arsenal").one()
    assert match.team_home_id == arsenal.id

    # Re-run with an updated status/score for the same fixture id: update, not duplicate.
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(1001, "Arsenal", "Chelsea", status="FT", gh=2, ga=1)],
    )
    second = load_league_structure(db_session, api_key="x")
    assert second["fixtures_created"] == 0
    assert second["fixtures_updated"] == 1
    assert db_session.query(Match).filter_by(provider_fixture_id=1001).count() == 1

    match = db_session.query(Match).filter_by(provider_fixture_id=1001).one()
    assert match.status == "finished"
    assert match.score_home == 2
    assert match.score_away == 1


def test_normalizes_football_data_style_aliases(db_session, monkeypatch):
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(2002, "Man United", "Nott'm Forest")],
    )
    load_league_structure(db_session, api_key="x")
    match = db_session.query(Match).filter_by(provider_fixture_id=2002).one()
    home = db_session.get(Team, match.team_home_id)
    away = db_session.get(Team, match.team_away_id)
    assert home.name == "Manchester United"
    assert away.name == "Nottingham Forest"


def test_never_touches_wc26_rows(db_session, monkeypatch):
    load_wc26_structure(db_session)
    wc26_matches = db_session.query(Match).count()
    wc26_tournament = db_session.query(Tournament).filter_by(
        name="FIFA World Cup 2026"
    ).one()

    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(3003, "Everton", "Fulham")],
    )
    load_league_structure(db_session, api_key="x")

    assert db_session.query(Match).filter_by(tournament_id=wc26_tournament.id).count() == wc26_matches
    epl_tournament = db_session.query(Tournament).filter_by(
        name="Premier League 2026-27"
    ).one()
    assert epl_tournament.id != wc26_tournament.id
    assert db_session.query(Match).filter_by(tournament_id=epl_tournament.id).count() == 1


def test_load_invalidates_the_tournaments_active_cache(db_session, monkeypatch):
    """Opus review of PR #171, item 2: a stale "tournaments:active" cached
    answer (e.g. WC26/knockout, from before this load ran) must not survive
    a structure load in the SAME process. (In the real deployed topology the
    daily pipeline runs in a separate process from the web server, where this
    is a no-op — GET /api/tournaments/active's short ttl_seconds is what
    bounds staleness there; this test covers the in-process case directly.)"""
    cache.set("tournaments:active", {"name": "FIFA World Cup 2026", "format": "knockout"})
    assert cache.get("tournaments:active") is not None

    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [])
    load_league_structure(db_session, api_key="x")

    assert cache.get("tournaments:active") is None
    cache.clear()


def test_skips_fixture_with_unknown_team(db_session, monkeypatch):
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(4004, "Arsenal", "Some Nonexistent FC")],
    )
    summary = load_league_structure(db_session, api_key="x")
    assert summary["fixtures_skipped"] == 1
    assert db_session.query(Match).filter_by(provider_fixture_id=4004).count() == 0


# ---------------------------------------------------------------------------
# matchweek write-side (League Score Predictions design doc, matches.
# matchweek migration c8d9e0f1a2b3): parsing API-Football's fixture.league.
# round into Match.matchweek.
# ---------------------------------------------------------------------------

def test_stores_matchweek_parsed_from_league_round(db_session, monkeypatch):
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(5005, "Arsenal", "Chelsea", round_="Regular Season - 5")],
    )
    load_league_structure(db_session, api_key="x")
    match = db_session.query(Match).filter_by(provider_fixture_id=5005).one()
    assert match.matchweek == 5


def test_matchweek_stays_null_when_round_missing_or_unparseable(db_session, monkeypatch):
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [
            _fixture(6006, "Arsenal", "Chelsea"),  # no round key at all
            _fixture(6007, "Man United", "Nott'm Forest", round_="Quarter-finals"),  # no trailing number
        ],
    )
    load_league_structure(db_session, api_key="x")
    assert db_session.query(Match).filter_by(provider_fixture_id=6006).one().matchweek is None
    assert db_session.query(Match).filter_by(provider_fixture_id=6007).one().matchweek is None


def test_matchweek_updates_on_re_ingestion_after_reschedule(db_session, monkeypatch):
    """Set unconditionally on every upsert, like kickoff_utc/status/score_* --
    a fixture moved to a different matchweek (broadcaster reshuffle) must
    correct on the next ingestion, not just the first time the row is
    created."""
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(7007, "Arsenal", "Chelsea", round_="Regular Season - 5")],
    )
    load_league_structure(db_session, api_key="x")
    assert db_session.query(Match).filter_by(provider_fixture_id=7007).one().matchweek == 5

    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [_fixture(7007, "Arsenal", "Chelsea", round_="Regular Season - 6")],
    )
    load_league_structure(db_session, api_key="x")
    assert db_session.query(Match).filter_by(provider_fixture_id=7007).one().matchweek == 6
