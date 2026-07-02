import json
from pathlib import Path

from app.models import Match, Team
from app.scoring import knockout_results_from_db, recompute_scores, _ADVANCE_NOS
from pipeline.ingest.wc26_structure import load_structure
from pipeline.ingest.ko_venues import apply_ko_venues, KO_VENUES
from pipeline.ingest.live_scores import assign_knockout_teams, update_live_scores
from pipeline.ingest.api_football import to_feed

_TESTDATA = Path(__file__).resolve().parents[2] / "pipeline" / "ingest" / "testdata"


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
    # Placement keys on kickoff, not feed order: 9001 (21:00Z) matches match 89's
    # official kickoff, 9002 (17:00Z) matches match 90's.
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    assert r16[0].match_no == 89
    assert {r16[0].team_home_id, r16[0].team_away_id} == {arg.id, fra.id}
    assert r16[0].provider_fixture_id == 9001
    assert r16[1].match_no == 90
    assert {r16[1].team_home_id, r16[1].team_away_id} == {bra.id, ger.id}
    assert r16[1].provider_fixture_id == 9002


def test_assign_knockout_teams_apisports(db_session):
    load_structure(db_session)
    _seed_teams(db_session, ["Argentina", "France", "Brazil", "Germany"])
    raw = json.loads((_TESTDATA / "wc_ko_matches_apisports.json").read_text())
    api_matches = to_feed(raw)

    summary = assign_knockout_teams(db_session, api_matches)
    # 2 R16 fixtures assigned (date ordering, not id ordering)
    assert summary["assigned"] == 2
    r16 = db_session.query(Match).filter(Match.stage == "R16").order_by(Match.match_no).all()
    # Placement keys on kickoff: 7001 (21:00Z) -> match 89, 7002 (17:00Z) -> match 90
    # (api-sports fixture.date is forwarded as utcDate by to_feed).
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    arg = db_session.query(Team).filter_by(name="Argentina").one()
    fra = db_session.query(Team).filter_by(name="France").one()
    assert r16[0].match_no == 89
    assert {r16[0].team_home_id, r16[0].team_away_id} == {arg.id, fra.id}
    assert r16[0].provider_fixture_id == 7001
    assert r16[1].match_no == 90
    assert {r16[1].team_home_id, r16[1].team_away_id} == {bra.id, ger.id}
    assert r16[1].provider_fixture_id == 7002


def test_assign_r32_places_by_kickoff_not_feed_order(db_session):
    """Regression (official-bracket seeding): an R32 fixture must land on the
    match_no whose OFFICIAL kickoff matches the fixture — not be zipped onto
    match_no order. Match 76 (Jun 29 17:00Z) kicks off BEFORE 74 (Jun 29 20:30Z)
    and 75 (Jun 30 01:00Z), so the old "sort feed by kickoff, zip onto match_no
    order" placed the 2nd-earliest fixture on 74 instead of 76 — putting same-group
    qualifiers in the same quarter. Placement must key on kickoff, not feed order."""
    load_structure(db_session)
    _seed_teams(db_session, ["Brazil", "Germany", "Spain", "Portugal"])
    # Two real R32 fixtures, fed scrambled vs match_no order. Each utcDate is the
    # official kickoff of the match_no it truly belongs to (76 and 73).
    api_matches = [
        {"stage": "ROUND_OF_32", "utcDate": "2026-06-29T17:00:00Z", "id": 1076,
         "homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Germany"}},
        {"stage": "ROUND_OF_32", "utcDate": "2026-06-28T19:00:00Z", "id": 1073,
         "homeTeam": {"name": "Spain"}, "awayTeam": {"name": "Portugal"}},
    ]
    summary = assign_knockout_teams(db_session, api_matches)
    assert summary["assigned"] == 2

    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    spa = db_session.query(Team).filter_by(name="Spain").one()
    por = db_session.query(Team).filter_by(name="Portugal").one()
    m73 = db_session.query(Match).filter(Match.match_no == 73).one()
    m74 = db_session.query(Match).filter(Match.match_no == 74).one()
    m76 = db_session.query(Match).filter(Match.match_no == 76).one()
    # Brazil v Germany belongs on 76 (its kickoff), NOT 74 (the old zip's 2nd slot).
    assert {m76.team_home_id, m76.team_away_id} == {bra.id, ger.id}
    assert m76.provider_fixture_id == 1076
    # Spain v Portugal on 73 (its kickoff).
    assert {m73.team_home_id, m73.team_away_id} == {spa.id, por.id}
    # 74 must stay empty — its real teams aren't determined yet.
    assert m74.team_home_id is None and m74.team_away_id is None


def test_assign_clears_stale_scheduled_slot_on_reseed(db_session):
    """Deploy-transition guard: a slot misplaced by the old logic must not linger.
    Pre-seed match 74 with a stale pair (as the old zip left Brazil/Japan on 74);
    feeding that pair at its TRUE kickoff (match 76) must fill 76 AND clear 74 —
    so the team never appears in two slots at once."""
    load_structure(db_session)
    _seed_teams(db_session, ["Brazil", "Germany"])
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    m74 = db_session.query(Match).filter(Match.match_no == 74).one()
    m74.team_home_id, m74.team_away_id = bra.id, ger.id  # stale misplacement
    db_session.commit()

    assign_knockout_teams(db_session, [
        {"stage": "ROUND_OF_32", "utcDate": "2026-06-29T17:00:00Z", "id": 1076,
         "homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Germany"}},
    ])
    db_session.refresh(m74)
    m76 = db_session.query(Match).filter(Match.match_no == 76).one()
    assert {m76.team_home_id, m76.team_away_id} == {bra.id, ger.id}  # placed on 76
    assert m74.team_home_id is None and m74.team_away_id is None     # stale 74 cleared


def test_rebuild_preserves_live_and_finished_rows(db_session):
    """The scheduled-row rebuild must never wipe a live/finished match. Match 73 is
    in_play; a feed that includes the R32 stage but no fixture for 73's kickoff must
    leave 73's teams intact while still clearing a stale scheduled slot (74)."""
    load_structure(db_session)
    _seed_teams(db_session, ["Brazil", "Germany", "Spain", "Portugal"])
    bra = db_session.query(Team).filter_by(name="Brazil").one()
    ger = db_session.query(Team).filter_by(name="Germany").one()
    spa = db_session.query(Team).filter_by(name="Spain").one()
    por = db_session.query(Team).filter_by(name="Portugal").one()
    m73 = db_session.query(Match).filter(Match.match_no == 73).one()
    m73.team_home_id, m73.team_away_id, m73.status = bra.id, ger.id, "in_play"
    m74 = db_session.query(Match).filter(Match.match_no == 74).one()
    m74.team_home_id, m74.team_away_id = spa.id, por.id  # stale scheduled
    db_session.commit()

    # R32-stage feed item whose kickoff matches no row -> triggers rebuild, assigns nothing.
    assign_knockout_teams(db_session, [
        {"stage": "ROUND_OF_32", "utcDate": "2026-06-28T08:00:00Z", "id": 999,
         "homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Germany"}},
    ])
    db_session.refresh(m73)
    db_session.refresh(m74)
    assert m73.status == "in_play"
    assert {m73.team_home_id, m73.team_away_id} == {bra.id, ger.id}  # live row kept
    assert m74.team_home_id is None and m74.team_away_id is None     # scheduled cleared


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
            "utcDate": "2026-07-04T21:00:00Z",  # match 89's official kickoff
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


def test_canary_in_play_ko_is_not_label_in_bracket():
    """Canary: any KO in_play row must serialize with a real team_id on at least one side."""
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
    _seed_teams(db, ["Brazil", "Germany"])

    # Simulate the assigned + live state the cron would produce.
    row = db.query(Match).filter(Match.match_no == 90).one()
    bra = db.query(Team).filter_by(name="Brazil").one()
    ger = db.query(Team).filter_by(name="Germany").one()
    row.team_home_id, row.team_away_id = bra.id, ger.id
    row.status, row.score_home, row.score_away, row.minute = "in_play", 1, 0, 57
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
    ties = {t["match_no"]: t for t in resp.json()["ties"]}
    for t in ties.values():
        if t["status"] == "in_play":
            # at least one real team -> the frontend renders it as in_play, not labels
            assert t["home"]["team_id"] is not None or t["away"]["team_id"] is not None, t["match_no"]


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


def test_knockout_played_carries_participants_and_winner(db_session):
    from app.scoring import knockout_played_from_db

    load_structure(db_session)
    _seed_teams(db_session, ["A", "B", "C", "D", "E", "F"])

    # 89: 2-1 -> home wins by score.
    _, h89, a89 = _ko_row(db_session, 89, "A", "B", status="finished",
                          score_home=2, score_away=1)
    # 90: 1-1 pens 2-4 -> away wins on pens.
    _, h90, a90 = _ko_row(db_session, 90, "C", "D", status="finished",
                          score_home=1, score_away=1, penalty_home=2, penalty_away=4)
    # 91: still level -> omitted (no decided winner).
    _ko_row(db_session, 91, "E", "F", status="finished",
            score_home=0, score_away=0, penalty_home=3, penalty_away=3)

    played = knockout_played_from_db(db_session)
    assert played[89] == (h89.id, a89.id, h89.id)   # home won
    assert played[90] == (h90.id, a90.id, a90.id)   # away won on penalties
    assert 91 not in played


def test_no_cross_stage_collision_when_same_pair_in_group_and_ko(db_session):
    """Regression: provider_fixture_id keying must route each feed item to the
    correct row even when the same two teams appear in both a group row AND an
    assigned KO row (same frozenset key — old pair-only lookup collides)."""
    load_structure(db_session)
    _seed_teams(db_session, ["France", "Argentina"])

    fra = db_session.query(Team).filter_by(name="France").one()
    arg = db_session.query(Team).filter_by(name="Argentina").one()

    # A group row with France vs Argentina, fixture id 1111.
    group_row = db_session.query(Match).filter(Match.stage == "group").first()
    group_row.team_home_id = fra.id
    group_row.team_away_id = arg.id
    group_row.provider_fixture_id = 1111
    group_row.status = "scheduled"

    # KO row (final, match_no 104) assigned France vs Argentina, fixture id 2222.
    ko_row = db_session.query(Match).filter(Match.match_no == 104).one()
    ko_row.team_home_id = fra.id
    ko_row.team_away_id = arg.id
    ko_row.provider_fixture_id = 2222
    ko_row.status = "scheduled"
    db_session.commit()

    # Two feed items for the SAME team pair but different fixture ids and scores.
    api_matches = [
        {
            "id": 1111,
            "homeTeam": {"name": "France"},
            "awayTeam": {"name": "Argentina"},
            "status": "FINISHED",
            "score": {
                "fullTime": {"home": 1, "away": 0},
                "duration": "REGULAR",
            },
        },
        {
            "id": 2222,
            "homeTeam": {"name": "France"},
            "awayTeam": {"name": "Argentina"},
            "status": "FINISHED",
            "score": {
                "fullTime": {"home": 3, "away": 2},
                "duration": "REGULAR",
            },
        },
    ]
    update_live_scores(db_session, api_matches)
    db_session.refresh(group_row)
    db_session.refresh(ko_row)

    # Each row must have received its OWN fixture's score.
    assert group_row.score_home == 1 and group_row.score_away == 0, (
        f"group row got {group_row.score_home}-{group_row.score_away}, expected 1-0"
    )
    assert ko_row.score_home == 3 and ko_row.score_away == 2, (
        f"KO row got {ko_row.score_home}-{ko_row.score_away}, expected 3-2"
    )


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
