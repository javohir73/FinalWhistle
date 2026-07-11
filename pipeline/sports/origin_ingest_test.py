"""Origin ingest: both sources flow through nrl_ingest.upsert_season with
sport="origin" and canonical team names. Uses the repo-root conftest
db_session fixture (in-memory SQLite)."""
from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_ingest import upsert_season
from pipeline.sports.origin_ingest import SPORT, seed_rows_by_season
from pipeline.sports.origin_names import CANONICAL

# Verified live shape from fixturedownload.com/feed/json/state-of-origin-2026
LIVE_ROW = {"MatchNumber": 1, "RoundNumber": 1, "DateUtc": "2026-05-27 10:05:00Z",
            "Location": "Accor Stadium", "HomeTeam": "Blues", "AwayTeam": "Maroons",
            "Group": None, "HomeTeamScore": 22, "AwayTeamScore": 20, "Winner": "Blues"}


def test_live_row_canonicalized_and_scoped_to_origin(db_session):
    counts = upsert_season(db_session, 2026, [LIVE_ROW],
                           sport=SPORT, team_name_map=CANONICAL)
    assert counts == {"created": 1, "updated": 0}
    m = db_session.query(SportMatch).one()
    assert m.sport == "origin" and m.season == 2026 and m.round == 1
    names = {t.name for t in db_session.query(SportTeam).filter_by(sport="origin")}
    assert names == {"NSW Blues", "QLD Maroons"}


def test_unknown_team_name_is_skipped(db_session):
    bad = dict(LIVE_ROW, HomeTeam="Fiji Bati")
    counts = upsert_season(db_session, 2026, [bad], sport=SPORT, team_name_map=CANONICAL)
    assert counts == {"created": 0, "updated": 0}
    assert db_session.query(SportMatch).count() == 0


def test_same_name_in_two_sports_is_two_teams(db_session):
    upsert_season(db_session, 2026, [dict(LIVE_ROW, HomeTeam="Broncos", AwayTeam="Storm")])
    upsert_season(db_session, 2026, [LIVE_ROW], sport=SPORT, team_name_map=CANONICAL)
    assert db_session.query(SportTeam).filter_by(sport="nrl").count() == 2
    assert db_session.query(SportTeam).filter_by(sport="origin").count() == 2


def test_seed_rows_round_trip_through_upsert(tmp_path, db_session):
    import json
    seed = {"source": "test", "fetched": "2026-07-11", "matches": [
        {"season": 1982, "round": 1, "match_no": 1,
         "kickoff_utc": "1982-06-08 09:30:00Z", "venue": None,
         "home_team": "NSW Blues", "away_team": "QLD Maroons",
         "score_home": 20, "score_away": 16},
        {"season": 1982, "round": 2, "match_no": 2,
         "kickoff_utc": "1982-06-22 09:30:00Z", "venue": "Lang Park",
         "home_team": "QLD Maroons", "away_team": "NSW Blues",
         "score_home": 11, "score_away": 7},
    ]}
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(seed))

    by_season = seed_rows_by_season(p)
    assert set(by_season) == {1982}
    for season, rows in by_season.items():
        upsert_season(db_session, season, rows, sport=SPORT, team_name_map=CANONICAL)
    ms = db_session.query(SportMatch).filter_by(sport="origin", season=1982).all()
    assert {(m.round, m.status, m.score_home) for m in ms} == {(1, "finished", 20), (2, "finished", 11)}


def test_seed_ingest_is_idempotent(tmp_path, db_session):
    import json
    seed = {"source": "t", "fetched": "d", "matches": [
        {"season": 1983, "round": 1, "match_no": 1,
         "kickoff_utc": "1983-06-07 09:30:00Z", "venue": None,
         "home_team": "NSW Blues", "away_team": "QLD Maroons",
         "score_home": 10, "score_away": 24}]}
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(seed))
    for _ in range(2):
        for season, rows in seed_rows_by_season(p).items():
            upsert_season(db_session, season, rows, sport=SPORT, team_name_map=CANONICAL)
    assert db_session.query(SportMatch).filter_by(sport="origin").count() == 1
