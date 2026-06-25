from app.models import Match


def test_match_has_nullable_match_no_column(db_session):
    m = Match(tournament_id=1, stage="R32", match_no=73, is_neutral=True)
    db_session.add(m)
    db_session.commit()
    got = db_session.query(Match).filter_by(match_no=73).one()
    assert got.match_no == 73
