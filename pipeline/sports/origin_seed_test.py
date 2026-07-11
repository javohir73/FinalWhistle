"""Tests for the one-time TheSportsDB -> seed-file transformer.

transform_events is strict, NOT best-effort: the seed file is committed and
must be 100% clean, so anything unexpected raises instead of being skipped.
"""
import pytest

from pipeline.sports.origin_seed import _MANUAL_SEASONS, transform_events, validate_season

# Verified live shape from
# https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=5835&s=1990
def _event(round_no, home="New South Wales Blues", away="Queensland Maroons",
           hs="8", as_="0", date="1990-05-09", venue=""):
    return {"strEvent": f"{home} vs {away}", "dateEvent": date,
            "intRound": str(round_no), "strHomeTeam": home, "strAwayTeam": away,
            "intHomeScore": hs, "intAwayScore": as_, "strVenue": venue}


def test_transform_three_games_canonical_names_and_feed_format_kickoff():
    events = [_event(2, date="1990-06-13"), _event(1), _event(3, date="1990-07-11")]
    matches = transform_events(events, 1990)
    assert [m["round"] for m in matches] == [1, 2, 3]      # sorted by round
    assert matches[0] == {
        "season": 1990, "round": 1, "match_no": 1,
        "kickoff_utc": "1990-05-09 09:30:00Z",              # DateUtc feed format
        "venue": None,                                       # "" -> None
        "home_team": "NSW Blues", "away_team": "QLD Maroons",
        "score_home": 8, "score_away": 0,
    }


def test_transform_keeps_venue_and_parses_string_scores():
    m = transform_events(
        [_event(1, venue="Suncorp Stadium", hs="18", as_="18"),
         _event(2), _event(3)], 1999)[0]
    assert m["venue"] == "Suncorp Stadium"
    assert m["score_home"] == 18 and m["score_away"] == 18   # draws are real


def test_transform_unknown_team_raises():
    with pytest.raises(ValueError, match="unrecognized"):
        transform_events([_event(1, home="Fiji Bati"), _event(2), _event(3)], 2001)


def test_validate_wrong_game_count_raises():
    with pytest.raises(ValueError, match="expected 3 games"):
        validate_season([{"round": 1}, {"round": 2}], 1980)


def test_validate_wrong_rounds_raise():
    with pytest.raises(ValueError, match="rounds"):
        validate_season([{"round": 1}, {"round": 1}, {"round": 3}], 2003)


def test_manual_2016_override_is_valid_and_canonical():
    matches = _MANUAL_SEASONS[2016]
    validate_season(matches, 2016)  # doesn't raise
    team_fields = [m["home_team"] for m in matches] + [m["away_team"] for m in matches]
    assert all(name in {"NSW Blues", "QLD Maroons"} for name in team_fields)
    assert [(m["score_home"], m["score_away"]) for m in matches] == [
        (4, 6), (26, 16), (18, 14),
    ]  # QLD won the series 2-1
