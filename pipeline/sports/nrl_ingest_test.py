"""Tests for the NRL fixturedownload ingest adapter (task-2-brief.md).

fetch_season/parse_row/upsert_season mirror pipeline.ingest.injuries's
never-raises, best-effort idiom: fetch never raises (returns [] + logs on any
error), parse is pure (None for malformed rows), and upsert is idempotent and
never overwrites a stored finished match (freshness-guard spirit).
"""
import sys
from datetime import datetime, timezone

import requests

import app.db
import pipeline.sports.nrl_ingest as nrl_ingest
from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_ingest import fetch_season, parse_row, upsert_season

# Verified live shape from https://fixturedownload.com/feed/json/nrl-2026
SAMPLE = {"MatchNumber": 1, "RoundNumber": 1, "DateUtc": "2026-03-01 02:15:00Z",
          "Location": "Allegiant Stadium", "HomeTeam": "Knights",
          "AwayTeam": "Cowboys", "Group": None,
          "HomeTeamScore": 28, "AwayTeamScore": 18, "Winner": "Knights"}

SCHEDULED_SAMPLE = {"MatchNumber": 204, "RoundNumber": 27,
                     "DateUtc": "2026-09-06 06:05:00Z", "Location": "CommBank Stadium",
                     "HomeTeam": "Panthers", "AwayTeam": "Wests Tigers", "Group": None,
                     "HomeTeamScore": None, "AwayTeamScore": None, "Winner": ""}


# ---- parse_row (pure) ----

def test_parse_row_finished_match():
    row = parse_row(SAMPLE)
    assert row == {
        "match_no": 1, "round": 1,
        "kickoff_utc": datetime(2026, 3, 1, 2, 15, tzinfo=timezone.utc),
        "venue": "Allegiant Stadium", "home_team": "Knights", "away_team": "Cowboys",
        "score_home": 28, "score_away": 18, "status": "finished",
    }


def test_parse_row_scheduled_match_null_scores():
    row = parse_row(SCHEDULED_SAMPLE)
    assert row["status"] == "scheduled"
    assert row["score_home"] is None
    assert row["score_away"] is None
    assert row["match_no"] == 204


def test_parse_row_missing_team_name_is_malformed():
    bad = dict(SAMPLE, HomeTeam="")
    assert parse_row(bad) is None
    bad = dict(SAMPLE, AwayTeam=None)
    assert parse_row(bad) is None


def test_parse_row_unparseable_date_is_malformed():
    bad = dict(SAMPLE, DateUtc="not-a-date")
    assert parse_row(bad) is None


def test_parse_row_missing_match_number_is_malformed():
    bad = dict(SAMPLE)
    del bad["MatchNumber"]
    assert parse_row(bad) is None


def test_parse_row_null_match_number_is_malformed():
    bad = dict(SAMPLE, MatchNumber=None)
    assert parse_row(bad) is None


def test_parse_row_one_score_null_is_scheduled():
    # A partially-filled score pair (shouldn't happen live, but the contract
    # says "either null" -> scheduled with scores None, not a half-filled row).
    bad = dict(SAMPLE, AwayTeamScore=None)
    row = parse_row(bad)
    assert row["status"] == "scheduled"
    assert row["score_home"] is None
    assert row["score_away"] is None


# ---- fetch_season (never raises) ----

def test_fetch_season_returns_empty_list_on_http_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(requests, "get", _raise)
    assert fetch_season(2099) == []


def test_fetch_season_returns_empty_list_on_bad_json(monkeypatch):
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    assert fetch_season(2099) == []


def test_fetch_season_returns_empty_list_on_404(monkeypatch):
    class _Resp:
        status_code = 404

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("404")

        def json(self):
            return []

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    assert fetch_season(2016) == []


def test_fetch_season_passes_user_agent_and_timeout(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [SAMPLE]

    def _get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(requests, "get", _get)
    rows = fetch_season(2026)
    assert rows == [SAMPLE]
    assert captured["url"] == "https://fixturedownload.com/feed/json/nrl-2026"
    assert captured["headers"] == {"User-Agent": "Mozilla/5.0"}
    assert captured["timeout"] == 20


# ---- upsert_season (idempotent, freshness-guarded) ----

def test_upsert_season_creates_teams_and_match(db_session):
    counts = upsert_season(db_session, 2026, [SAMPLE])
    assert counts == {"created": 1, "updated": 0}

    teams = {t.name for t in db_session.query(SportTeam).filter_by(sport="nrl").all()}
    assert teams == {"Knights", "Cowboys"}

    match = db_session.query(SportMatch).filter_by(sport="nrl", season=2026, match_no=1).one()
    assert match.status == "finished"
    assert match.score_home == 28
    assert match.score_away == 18


def test_upsert_season_is_idempotent(db_session):
    upsert_season(db_session, 2026, [SAMPLE])
    counts = upsert_season(db_session, 2026, [SAMPLE])
    assert counts == {"created": 0, "updated": 0}
    assert db_session.query(SportMatch).filter_by(sport="nrl", season=2026).count() == 1
    assert db_session.query(SportTeam).filter_by(sport="nrl").count() == 2


def test_upsert_season_reuses_teams_across_matches(db_session):
    other = dict(SAMPLE, MatchNumber=2, HomeTeam="Knights", AwayTeam="Storm")
    upsert_season(db_session, 2026, [SAMPLE, other])
    assert db_session.query(SportTeam).filter_by(sport="nrl").count() == 3  # Knights/Cowboys/Storm


def test_upsert_season_late_score_flips_scheduled_to_finished(db_session):
    upsert_season(db_session, 2026, [SCHEDULED_SAMPLE])
    match = db_session.query(SportMatch).filter_by(sport="nrl", match_no=204).one()
    assert match.status == "scheduled"

    finished_now = dict(SCHEDULED_SAMPLE, HomeTeamScore=20, AwayTeamScore=16, Winner="Panthers")
    counts = upsert_season(db_session, 2026, [finished_now])
    assert counts == {"created": 0, "updated": 1}

    db_session.refresh(match)
    assert match.status == "finished"
    assert match.score_home == 20
    assert match.score_away == 16


def test_upsert_season_never_overwrites_a_finished_match(db_session):
    upsert_season(db_session, 2026, [SAMPLE])  # finished, 28-18

    changed = dict(SAMPLE, HomeTeamScore=99, AwayTeamScore=1)
    counts = upsert_season(db_session, 2026, [changed])
    assert counts == {"created": 0, "updated": 0}

    match = db_session.query(SportMatch).filter_by(sport="nrl", match_no=1).one()
    assert match.score_home == 28
    assert match.score_away == 18


def test_upsert_season_skips_malformed_rows(db_session):
    bad = dict(SAMPLE, HomeTeam="")
    counts = upsert_season(db_session, 2026, [bad])
    assert counts == {"created": 0, "updated": 0}
    assert db_session.query(SportMatch).count() == 0


def test_upsert_season_dedupes_match_no_collisions_within_a_batch(db_session):
    # fixturedownload's 2020 COVID-restart feed reuses MatchNumber across
    # distinct fixtures in the same response (round 1 and round 3 both use
    # MatchNumber=1). The batch must not crash on the unique constraint —
    # first-seen wins, later collisions are dropped.
    first = dict(SAMPLE, MatchNumber=1, RoundNumber=1)
    collides = dict(SAMPLE, MatchNumber=1, RoundNumber=3,
                     HomeTeam="Broncos", AwayTeam="Storm")
    counts = upsert_season(db_session, 2020, [first, collides])
    assert counts == {"created": 1, "updated": 0}
    match = db_session.query(SportMatch).filter_by(sport="nrl", season=2020, match_no=1).one()
    assert match.round == 1  # first-seen kept


def test_upsert_season_scoped_by_season(db_session):
    upsert_season(db_session, 2026, [SAMPLE])
    same_match_no_next_year = dict(SAMPLE)
    counts = upsert_season(db_session, 2027, [same_match_no_next_year])
    assert counts == {"created": 1, "updated": 0}
    assert db_session.query(SportMatch).filter_by(sport="nrl").count() == 2


# ---- main() CLI loop (per-season error boundary) ----

def test_main_one_bad_season_does_not_abort_the_backfill(monkeypatch, db_session):
    # A season whose upsert_season blows up (e.g. an unexpected feed shape, a
    # constraint violation) must not take down the rest of the backfill —
    # main()'s loop rolls back and moves on, mirroring
    # pipeline.ingest.injuries's never-raises-to-the-caller posture.
    db_session.close = lambda: None  # the fixture owns teardown, not main()
    monkeypatch.setattr(app.db, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(nrl_ingest, "fetch_season", lambda year, timeout=20.0: [SAMPLE])

    real_upsert_season = nrl_ingest.upsert_season

    def _flaky_upsert_season(db, year, rows):
        if year == 2020:
            raise RuntimeError("boom: season 2020 is broken")
        return real_upsert_season(db, year, rows)

    monkeypatch.setattr(nrl_ingest, "upsert_season", _flaky_upsert_season)
    monkeypatch.setattr(sys, "argv", ["nrl_ingest.py", "--seasons", "2020", "2021"])

    rc = nrl_ingest.main()

    assert rc == 0
    assert db_session.query(SportMatch).filter_by(sport="nrl", season=2020).count() == 0
    match = db_session.query(SportMatch).filter_by(sport="nrl", season=2021).one()
    assert match.match_no == SAMPLE["MatchNumber"]
