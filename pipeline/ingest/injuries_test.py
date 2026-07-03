"""Tests for the injuries ingest (parse now; refresh added in the next task)."""
from pipeline.ingest.api_football import parse_injuries


def _rec(name, itype, reason, team):
    return {"player": {"id": 10, "name": name, "type": itype, "reason": reason},
            "team": {"id": 1, "name": team}}


def test_parse_maps_missing_fixture_to_out():
    out = parse_injuries([_rec("Neymar", "Missing Fixture", "Calf Injury", "Brazil")])
    assert out == [{"provider_player_id": 10, "name": "Neymar", "type": "out",
                    "reason": "Calf Injury", "team_name": "Brazil"}]


def test_parse_maps_everything_else_to_doubtful():
    out = parse_injuries([_rec("Vini", "Questionable", "Knock", "Brazil")])
    assert out[0]["type"] == "doubtful"


def test_parse_skips_nameless_and_malformed_rows():
    out = parse_injuries([
        {"player": {"id": 1, "name": None, "type": "Missing Fixture"}, "team": {"name": "X"}},
        "not-a-dict",
        _rec("Real", "Missing Fixture", "ACL", "Brazil"),
    ])
    assert [r["name"] for r in out] == ["Real"]


def test_parse_empty_response():
    assert parse_injuries([]) == []
    assert parse_injuries(None) == []


from datetime import datetime, timedelta, timezone

from app.models import Match, Team
from pipeline.ingest import injuries as injuries_mod
from pipeline.ingest.injuries import refresh_injuries


def _scheduled_match(db, kickoff_in_hours=24):
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", status="scheduled",
              team_home_id=h.id, team_away_id=a.id, provider_fixture_id=555,
              kickoff_utc=datetime.now(timezone.utc) + timedelta(hours=kickoff_in_hours))
    db.add(m); db.commit()
    return m, h, a


def test_refresh_sets_injuries_with_sides(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    # Raw api-sports records: one Brazil (home), one Serbia (away).
    monkeypatch.setattr(injuries_mod, "fetch_injuries", lambda key, fid: [
        {"player": {"id": 10, "name": "Neymar", "type": "Missing Fixture", "reason": "Calf"},
         "team": {"name": "Brazil"}},
        {"player": {"id": 20, "name": "Mitrovic", "type": "Questionable", "reason": "Knock"},
         "team": {"name": "Serbia"}},
    ])
    out = refresh_injuries(db_session, "key")
    got = db_session.get(Match, m.id).injuries
    assert {(i["name"], i["side"], i["type"]) for i in got} == {
        ("Neymar", "home", "out"), ("Mitrovic", "away", "doubtful")}
    assert out["matches_injuries"] == 1


def test_refresh_sets_empty_list_when_no_injuries(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    monkeypatch.setattr(injuries_mod, "fetch_injuries", lambda key, fid: [])
    refresh_injuries(db_session, "key")
    assert db_session.get(Match, m.id).injuries == []


def test_refresh_never_raises_on_fetch_error(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    def boom(key, fid):
        raise RuntimeError("feed down")
    monkeypatch.setattr(injuries_mod, "fetch_injuries", boom)
    out = refresh_injuries(db_session, "key")  # must not raise
    assert out["matches_skipped"] == 1
    assert db_session.get(Match, m.id).injuries is None  # untouched
