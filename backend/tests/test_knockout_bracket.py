from app.models import Match
from pipeline.ingest.wc26_structure import load_structure

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
