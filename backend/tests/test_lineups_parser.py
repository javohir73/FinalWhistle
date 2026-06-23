"""Pure-parser tests for api-football /fixtures/lineups -> our row dicts.

Display-only: lineups never feed the prediction model. The parser must keep
starter grids, force bench grids to None, normalize positions to G/D/M/F, and
never fabricate a player (nameless/malformed entries are dropped)."""
from pipeline.ingest.api_football import parse_lineups


# A realistic two-team /fixtures/lineups response.
_RESPONSE = [
    {
        "team": {"id": 2382, "name": "France"},
        "formation": "4-3-3",
        "coach": {"id": 7, "name": "D. Deschamps"},
        "startXI": [
            {"player": {"id": 1, "name": "M. Maignan", "number": 16, "pos": "G", "grid": "1:1"}},
            {"player": {"id": 2, "name": "J. Kounde", "number": 5, "pos": "D", "grid": "2:4"}},
            {"player": {"id": 3, "name": "A. Tchouameni", "number": 8, "pos": "M", "grid": "3:2"}},
            {"player": {"id": 4, "name": "K. Mbappe", "number": 10, "pos": "F", "grid": "4:1"}},
        ],
        "substitutes": [
            {"player": {"id": 9, "name": "O. Giroud", "number": 9, "pos": "F", "grid": None}},
        ],
    },
    {
        "team": {"id": 25, "name": "Germany"},
        "formation": None,
        "coach": {"id": None, "name": None},
        "startXI": [
            {"player": {"id": 20, "name": "M. Neuer", "number": 1, "pos": "Goalkeeper", "grid": "1:1"}},
        ],
        "substitutes": [],
    },
]


def test_parses_team_formation_and_coach():
    parsed = parse_lineups(_RESPONSE)
    assert [b["team"] for b in parsed] == ["France", "Germany"]
    assert parsed[0]["formation"] == "4-3-3"
    assert parsed[0]["coach"] == "D. Deschamps"


def test_starters_and_bench_split_with_grid_rules():
    fr = parse_lineups(_RESPONSE)[0]
    starters = [p for p in fr["players"] if p["is_starter"]]
    bench = [p for p in fr["players"] if not p["is_starter"]]
    assert len(starters) == 4
    assert len(bench) == 1
    # Starters keep the provider grid ("row:col").
    assert [p["grid"] for p in starters] == ["1:1", "2:4", "3:2", "4:1"]
    # Bench players never carry a grid.
    assert bench[0]["grid"] is None
    assert bench[0]["name"] == "O. Giroud"
    assert bench[0]["is_starter"] is False


def test_positions_normalized_to_single_letter():
    parsed = parse_lineups(_RESPONSE)
    assert [p["position"] for p in parsed[0]["players"]] == ["G", "D", "M", "F", "F"]
    # A full position word collapses to its first letter.
    assert parsed[1]["players"][0]["position"] == "G"


def test_order_is_stable_starters_then_bench():
    fr = parse_lineups(_RESPONSE)[0]
    assert [p["order"] for p in fr["players"]] == [0, 1, 2, 3, 4]
    # Bench follows the XI in the order sequence.
    assert fr["players"][4]["name"] == "O. Giroud"


def test_missing_formation_and_coach_are_none():
    de = parse_lineups(_RESPONSE)[1]
    assert de["formation"] is None
    assert de["coach"] is None


def test_player_number_grid_and_position_optional():
    response = [
        {
            "team": {"name": "Brazil"},
            "formation": "4-4-2",
            "coach": {"name": "Coach"},
            "startXI": [
                {"player": {"name": "Numberless", "number": None, "pos": None, "grid": None}},
            ],
            "substitutes": [],
        }
    ]
    p = parse_lineups(response)[0]["players"][0]
    assert p["name"] == "Numberless"
    assert p["number"] is None
    assert p["position"] is None
    assert p["grid"] is None
    assert p["is_starter"] is True


def test_nameless_and_malformed_players_are_dropped_never_fabricated():
    response = [
        {
            "team": {"name": "Spain"},
            "formation": "4-3-3",
            "coach": {"name": "Coach"},
            "startXI": [
                {"player": {"name": "Real Player", "number": 7, "pos": "F", "grid": "4:2"}},
                {"player": {"name": "", "number": 99}},   # empty name -> dropped
                {"player": None},                          # no player object -> dropped
                {"not_a_player": True},                    # malformed entry -> dropped
            ],
            "substitutes": [],
        }
    ]
    players = parse_lineups(response)[0]["players"]
    assert len(players) == 1
    assert players[0]["name"] == "Real Player"


def test_team_without_name_is_skipped():
    response = [
        {"team": {"id": 1}, "formation": "4-3-3", "startXI": [], "substitutes": []},
        {"team": {"name": "Argentina"}, "formation": "4-4-2", "startXI": [], "substitutes": []},
    ]
    parsed = parse_lineups(response)
    assert [b["team"] for b in parsed] == ["Argentina"]


def test_empty_and_none_response():
    assert parse_lineups([]) == []
    assert parse_lineups(None) == []
