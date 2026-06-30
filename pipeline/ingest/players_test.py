from pipeline.ingest.api_football import parse_lineups


def test_parse_lineups_keeps_provider_player_id():
    response = [
        {
            "team": {"name": "Brazil"},
            "formation": "4-3-3",
            "coach": {"name": "Dorival"},
            "startXI": [
                {"player": {"id": 1179, "name": "Vinicius", "number": 7, "pos": "F", "grid": "4:1"}},
            ],
            "substitutes": [
                {"player": {"id": 2040, "name": "Endrick", "number": 9, "pos": "F", "grid": None}},
            ],
        }
    ]
    teams = parse_lineups(response)
    rows = teams[0]["players"]
    starter = next(r for r in rows if r["name"] == "Vinicius")
    bench = next(r for r in rows if r["name"] == "Endrick")
    assert starter["player_id"] == 1179
    assert bench["player_id"] == 2040
