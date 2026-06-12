"""Tests for live in-game score ingestion (mocked feed, no network)."""
from datetime import datetime, timedelta, timezone

from app.models import Match, Team
from pipeline.ingest.live_scores import estimate_minute, refresh_live, update_live_scores
from pipeline.ingest.wc26_structure import load_structure


def _match_for(db, home: str, away: str) -> Match:
    h = db.query(Team).filter_by(name=home).one()
    a = db.query(Team).filter_by(name=away).one()
    return (
        db.query(Match)
        .filter_by(team_home_id=h.id, team_away_id=a.id)
        .one()
    )


def test_updates_status_score_and_minute(db_session):
    load_structure(db_session)
    api = [{
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "status": "IN_PLAY", "minute": 67,
        "score": {"fullTime": {"home": 2, "away": 1}},
    }]
    summary = update_live_scores(db_session, api)
    assert summary["updated"] == 1 and summary["live"] == 1

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "in_play"
    assert m.score_home == 2 and m.score_away == 1
    assert m.minute == 67


def test_orientation_is_normalized_to_our_home_away(db_session):
    load_structure(db_session)
    # Feed reversed (our fixture is Mexico home, South Africa away).
    api = [{
        "homeTeam": {"name": "South Africa"}, "awayTeam": {"name": "Mexico"},
        "status": "FINISHED",
        "score": {"fullTime": {"home": 3, "away": 0}},
    }]
    update_live_scores(db_session, api)
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "finished"
    assert m.score_home == 0 and m.score_away == 3  # Mexico 0, South Africa 3
    assert m.minute is None  # cleared when not in play


def test_team_name_aliases_are_mapped(db_session):
    load_structure(db_session)
    api = [{
        "homeTeam": {"name": "Korea Republic"}, "awayTeam": {"name": "Czechia"},
        "status": "IN_PLAY", "minute": 12,
        "score": {"fullTime": {"home": 0, "away": 0}},
    }]
    summary = update_live_scores(db_session, api)
    assert summary["updated"] == 1  # "Korea Republic" -> "South Korea"


def test_minute_estimated_from_kickoff_when_feed_omits_it(db_session):
    # football-data.org's free tier sends no `minute` field — the live clock
    # must still tick, estimated from kickoff time.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()

    api = [{
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "status": "IN_PLAY",  # no "minute" key at all
        "score": {"fullTime": {"home": 1, "away": 0}},
    }]
    update_live_scores(db_session, api)
    db_session.refresh(m)
    assert m.status == "in_play"
    assert m.minute == 31  # 30 elapsed minutes → playing the 31st


def test_estimate_minute_maps_match_phases():
    k = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    at = lambda mins: k + timedelta(minutes=mins)  # noqa: E731
    assert estimate_minute(None) is None
    assert estimate_minute(k, at(-2)) == 1     # pre-kickoff race → clamp
    assert estimate_minute(k, at(0.5)) == 1    # opening minute
    assert estimate_minute(k, at(30)) == 31    # first half
    assert estimate_minute(k, at(50)) == 45    # stoppage / half-time holds at 45
    assert estimate_minute(k, at(61)) == 47    # second half resumes (15' break)
    assert estimate_minute(k, at(120)) == 90   # capped
    # Naive datetimes (SQLite) are treated as UTC.
    assert estimate_minute(k.replace(tzinfo=None), at(30)) == 31


def test_no_api_key_is_a_safe_noop(db_session):
    load_structure(db_session)
    summary = refresh_live(db_session, api_key="")
    assert summary["skipped"] == "no_api_key"
    assert summary["updated"] == 0
