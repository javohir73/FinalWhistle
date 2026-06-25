import json
from pathlib import Path

from app.models import Match, Team
from pipeline.ingest.wc26_structure import load_structure
from pipeline.ingest.ko_venues import apply_ko_venues, KO_VENUES
from pipeline.ingest.live_scores import assign_knockout_teams, update_live_scores
from pipeline.ingest.api_football import to_feed

_TESTDATA = Path("pipeline/ingest/testdata")


def _seed_teams(db, names):
    existing = {t.name for t in db.query(Team).all()}
    for n in names:
        if n not in existing:
            db.add(Team(name=n))
    db.commit()

KO_STAGE_NOS = {
    "R32": list(range(73, 89)),
    "R16": [89, 90, 91, 92, 93, 94, 95, 96],
    "QF": [97, 98, 99, 100],
    "SF": [101, 102],
    "third_place": [103],
    "final": [104],
}


def test_match_has_nullable_match_no_column(db_session):
    m = Match(tournament_id=1, stage="R32", match_no=73, is_neutral=True)
    db_session.add(m)
    db_session.commit()
    got = db_session.query(Match).filter_by(match_no=73).one()
    assert got.match_no == 73


def test_ko_rows_stamped_with_match_no(db_session):
    load_structure(db_session)
    for stage, nos in KO_STAGE_NOS.items():
        rows = db_session.query(Match).filter(Match.stage == stage).all()
        assert sorted(r.match_no for r in rows) == nos, stage
    # every match_no 73..104 present exactly once
    all_nos = sorted(
        r.match_no
        for r in db_session.query(Match).filter(Match.match_no.isnot(None)).all()
    )
    assert all_nos == list(range(73, 105))


def test_every_ko_row_has_kickoff_utc(db_session):
    load_structure(db_session)
    ko = db_session.query(Match).filter(Match.stage != "group").all()
    assert len(ko) == 32
    assert all(m.kickoff_utc is not None for m in ko)


def test_load_structure_backfills_existing_unstamped_ko_rows(db_session):
    # Mimic a pre-existing prod DB: KO rows present but match_no/kickoff NULL.
    load_structure(db_session)
    for m in db_session.query(Match).filter(Match.stage != "group").all():
        m.match_no = None
        m.kickoff_utc = None
    db_session.commit()
    # Re-run: must backfill in place, not duplicate.
    load_structure(db_session)
    ko = db_session.query(Match).filter(Match.stage != "group").all()
    assert len(ko) == 32  # no duplicate rows
    assert all(m.match_no is not None and m.kickoff_utc is not None for m in ko)


def test_apply_ko_venues_resolves_by_match_no(db_session):
    # Break the id==match_no coincidence so this test actually guards the
    # db.get(Match, match_no) regression: a decoy row shifts auto-increment ids
    # (different tournament_id => load_structure ignores it).
    db_session.add(Match(tournament_id=999, stage="group", is_neutral=True))
    db_session.commit()
    load_structure(db_session)
    updated = apply_ko_venues(db_session)
    assert updated == len(KO_VENUES)
    # Verify all venues are applied to the correct rows (by match_no, not id)
    for match_no, (expected_city, expected_country) in KO_VENUES.items():
        row = db_session.query(Match).filter_by(match_no=match_no).one()
        assert row.venue_city == expected_city, f"match_no={match_no}: expected city {expected_city}, got {row.venue_city}"
        assert row.venue_country == expected_country, f"match_no={match_no}: expected country {expected_country}, got {row.venue_country}"


def test_assign_knockout_teams_football_data(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany", "Spain", "Portugal"])
    api_matches = json.loads((_TESTDATA / "wc_ko_matches.json").read_text())

    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["assigned"] >= 4
    assert summary["unmapped_stage"] == 0

    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    # First R16 fixture by kickoff zips onto the lowest R16 match_no (89)
    first = r16[0]
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    assert {first.team_home_id, first.team_away_id} == {arg.id, fra.id}
    assert first.provider_fixture_id == 9001


def test_assign_knockout_teams_apisports(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany"])
    raw = json.loads((_TESTDATA / "wc_ko_matches_apisports.json").read_text())
    api_matches = to_feed(raw)

    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["assigned"] >= 2
    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    assert r16[0].provider_fixture_id == 7001


def test_assign_never_fabricates_and_freezes_after_in_play(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France"])
    api_matches = [
        {
            "stage": "LAST_16",
            "homeTeam": {"name": "Argentina"},
            "awayTeam": {"name": "France"},
            "status": "IN_PLAY",
            "id": 5001,
            "score": {"fullTime": {"home": 0, "away": 0}, "duration": "REGULAR"},
        }
    ]
    assign_knockout_teams(db_session, api_matches)
    row = db_session.query(Match).filter(Match.match_no == 89).one()
    row.status = "in_play"
    db_session.commit()
    # A correction with different teams must NOT overwrite a live row
    api_matches[0]["homeTeam"] = {"name": "Brazil"}
    assign_knockout_teams(db_session, api_matches)
    db_session.refresh(row)
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    assert arg.id in {row.team_home_id, row.team_away_id}


def test_unmapped_stage_is_skipped_and_counted(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France"])
    api_matches = [
        {
            "stage": "GROUP_STAGE",
            "homeTeam": {"name": "Argentina"},
            "awayTeam": {"name": "France"},
            "status": "SCHEDULED",
            "id": 6001,
            "score": {"fullTime": {"home": None, "away": None}, "duration": "REGULAR"},
        }
    ]
    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["unmapped_stage"] == 1
    assert summary["assigned"] == 0
