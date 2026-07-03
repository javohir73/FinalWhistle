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
