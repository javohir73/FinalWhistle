import json
from pathlib import Path

from app.models import Match, Team
from app.scoring import knockout_results_from_db, recompute_scores, _ADVANCE_NOS
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
    # 2 R16 + 1 third_place + 1 final = 4 assigned
    assert summary["assigned"] == 4
    assert summary["unmapped_stage"] == 0

    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    # utcDate order: 9002 (17:00) < 9001 (20:00) → 9002 lands on match_no 89, 9001 on 90
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    assert r16[0].match_no == 89
    assert {r16[0].team_home_id, r16[0].team_away_id} == {bra.id, ger.id}
    assert r16[0].provider_fixture_id == 9002
    assert r16[1].match_no == 90
    assert {r16[1].team_home_id, r16[1].team_away_id} == {arg.id, fra.id}
    assert r16[1].provider_fixture_id == 9001


def test_assign_knockout_teams_apisports(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany"])
    raw = json.loads((_TESTDATA / "wc_ko_matches_apisports.json").read_text())
    api_matches = to_feed(raw)

    summary = assign_knockout_teams(db_session, api_matches)
    # 2 R16 fixtures assigned (date ordering, not id ordering)
    assert summary["assigned"] == 2
    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    # fixture.date order: 7002 (17:00) < 7001 (20:00) → 7002 lands on match_no 89, 7001 on 90
    # This proves date-ordering beats id-ordering (7001 < 7002 by id but arrives second)
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    assert r16[0].match_no == 89
    assert {r16[0].team_home_id, r16[0].team_away_id} == {bra.id, ger.id}
    assert r16[0].provider_fixture_id == 7002
    assert r16[1].match_no == 90
    assert {r16[1].team_home_id, r16[1].team_away_id} == {arg.id, fra.id}
    assert r16[1].provider_fixture_id == 7001


def test_assign_never_fabricates_and_freezes_after_in_play(db_session):
    load_structure(db_session)
    # Seed ALL teams used in this test — including "Brazil" used as the correction.
    # This ensures the freeze gate (row.status == "in_play") is the ONLY thing
    # blocking the overwrite, not the unknown-team gate.
    _seed_teams(db_session, ["Argentina", "France", "Brazil"])
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
    # A correction with a different (known/seeded) team must NOT overwrite a live row.
    # Brazil IS seeded — so only the freeze gate prevents this overwrite.
    api_matches[0]["homeTeam"] = {"name": "Brazil"}
    assign_knockout_teams(db_session, api_matches)
    db_session.refresh(row)
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    # Argentina must still be on the row — the freeze held
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


def test_end_to_end_offline_assign_then_update(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany", "Spain", "Portugal"])
    api_matches = json.loads((_TESTDATA / "wc_ko_matches.json").read_text())

    assign_knockout_teams(db_session, api_matches)
    update_live_scores(db_session, api_matches)

    arg = db_session.query(Team).filter_by(name="Argentina").one()
    finished = (
        db_session.query(Match)
        .filter(Match.stage == "R16", Match.team_home_id == arg.id)
        .one_or_none()
        or db_session.query(Match)
        .filter(Match.stage == "R16", Match.team_away_id == arg.id)
        .one()
    )
    assert finished.status == "finished"
    assert {finished.score_home, finished.score_away} == {1, 1}
    assert {finished.penalty_home, finished.penalty_away} == {4, 2}


# ---------------------------------------------------------------------------
# Task 12: GET /api/knockout/bracket endpoint
# ---------------------------------------------------------------------------

def test_bracket_endpoint_serializes_null_not_tbd_and_no_store():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.main import app
    from app.db import Base, get_db

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    db = TestingSession()
    load_structure(db)
    _seed_teams(db, ["Argentina", "France"])

    # Populate match_no 89 with real teams and a result
    row = db.query(Match).filter(Match.match_no == 89).one()
    arg = db.query(Team).filter_by(name="Argentina").one()
    fra = db.query(Team).filter_by(name="France").one()
    row.team_home_id, row.team_away_id = arg.id, fra.id
    row.status, row.score_home, row.score_away = "finished", 2, 1
    db.commit()
    db.close()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get("/api/knockout/bracket")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    body = resp.json()
    ties = {t["match_no"]: t for t in body["ties"]}
    assert len(ties) == 32
    # populated tie carries team names + match_id == DB row id
    # Re-open session to get the committed row id
    db2 = TestingSession()
    row_id = db2.query(Match).filter(Match.match_no == 89).one().id
    db2.close()
    t89 = ties[89]
    assert t89["match_id"] == row_id
    assert t89["home"]["team"] == "Argentina"
    # an unassigned tie is null, never "TBD"
    t104 = ties[104]
    assert t104["home"]["team_id"] is None
    assert t104["home"]["team"] is None


# ---------------------------------------------------------------------------
# Task 11: knockout_results_from_db + recompute integration
# ---------------------------------------------------------------------------

def _ko_row(db, match_no, home, away, **kw):
    row = db.query(Match).filter(Match.match_no == match_no).one()
    h = db.query(Team).filter_by(name=home).one()
    a = db.query(Team).filter_by(name=away).one()
    row.team_home_id, row.team_away_id = h.id, a.id
    for k, v in kw.items():
        setattr(row, k, v)
    db.commit()
    return row, h, a


def test_knockout_results_score_then_penalties(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["A", "B", "C", "D", "E", "F", "G", "H"])

    # 89: 2-1 -> home wins by score
    _, h89, _ = _ko_row(db_session, 89, "A", "B", status="finished", score_home=2, score_away=1)
    # 90: 1-1 pens 4-2 -> home wins on pens
    _, h90, _ = _ko_row(db_session, 90, "C", "D", status="finished",
                        score_home=1, score_away=1, penalty_home=4, penalty_away=2)
    # 91: 0-0 pens 3-3 -> undecided, omitted
    _ko_row(db_session, 91, "E", "F", status="finished",
            score_home=0, score_away=0, penalty_home=3, penalty_away=3)
    # 92: in_play -> omitted
    _ko_row(db_session, 92, "G", "H", status="in_play", score_home=1, score_away=0)

    results = knockout_results_from_db(db_session)
    assert results[89] == h89.id
    assert results[90] == h90.id
    assert 91 not in results
    assert 92 not in results


def test_recompute_uses_knockout_results_and_103_scores_zero(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["A", "B", "C", "D"])
    # 103 (third place) finished — must not be in the points-bearing sets.
    _ko_row(db_session, 103, "A", "B", status="finished", score_home=2, score_away=0)
    results = knockout_results_from_db(db_session)
    assert results[103] == db_session.query(Team).filter_by(name="A").one().id
    assert 103 not in _ADVANCE_NOS  # 103 never awards advance points
    # recompute runs cleanly with knockout_results supplied
    assert recompute_scores(db_session, knockout_results=results) >= 0
