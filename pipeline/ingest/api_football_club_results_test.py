from datetime import datetime, timezone

from app.models import HistoricalMatch, Team
from pipeline.ingest.api_football_club_results import (
    download_finished_fixtures,
    load_api_football_club_results,
    parse_finished_fixtures,
)


def _fixture(
    fixture_id=10,
    *,
    status="FT",
    round_="League Stage - 1",
    fulltime=(2, 1),
    goals=(2, 1),
):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2025-09-17T19:00:00+00:00",
            "status": {"short": status},
        },
        "league": {"round": round_},
        "teams": {
            "home": {"id": 42, "name": "Arsenal"},
            "away": {"id": 541, "name": "Real Madrid"},
        },
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {
            "fulltime": {"home": fulltime[0], "away": fulltime[1]},
            "extratime": {"home": None, "away": None},
            "penalty": {"home": None, "away": None},
        },
    }


def test_parser_uses_regulation_score_and_marks_only_final_neutral():
    aet = _fixture(
        status="AET", round_="Semi-finals", fulltime=(1, 1), goals=(2, 1)
    )
    final = _fixture(fixture_id=11, round_="Final")
    scheduled = _fixture(fixture_id=12, status="NS")

    rows = parse_finished_fixtures([aet, final, scheduled])

    assert [(row["score_home"], row["score_away"]) for row in rows] == [(1, 1), (2, 1)]
    assert [row["is_neutral"] for row in rows] == [False, True]


def test_download_uses_only_the_explicit_seasons():
    calls = []

    def fetcher(api_key, league, season):
        calls.append((api_key, league, season))
        return [_fixture(fixture_id=season)]

    rows = download_finished_fixtures(
        "secret", league=2, seasons=(2024, 2025), fetcher=fetcher
    )

    assert calls == [("secret", 2, 2024), ("secret", 2, 2025)]
    assert [row["fixture_id"] for row in rows] == [2024, 2025]


def test_loader_is_idempotent_and_reuses_provider_team_rows(db_session):
    existing = Team(name="Arsenal", provider_team_id=42, is_host=False)
    db_session.add(existing)
    db_session.commit()
    rows = parse_finished_fixtures([_fixture()])

    first = load_api_football_club_results(
        db_session, rows, competition="UEFA Champions League"
    )
    second = load_api_football_club_results(
        db_session, rows, competition="UEFA Champions League"
    )

    assert first["matches_inserted"] == 1
    assert second["matches_inserted"] == 0
    assert db_session.query(Team).filter_by(provider_team_id=42).count() == 1
    historical = db_session.query(HistoricalMatch).one()
    assert historical.date.replace(tzinfo=timezone.utc) == datetime(
        2025, 9, 17, 19, 0, tzinfo=timezone.utc
    )
    assert historical.competition == "UEFA Champions League"
