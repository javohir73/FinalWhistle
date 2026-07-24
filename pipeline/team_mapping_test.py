"""Tests for canonical team-name mapping (task 2.3)."""
import pytest

from pipeline.team_mapping import normalize_team_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Korea Republic", "South Korea"),
        ("korea republic", "South Korea"),
        ("West Germany", "Germany"),
        ("IR Iran", "Iran"),
        ("USA", "United States"),
        ("China PR", "China"),
        ("Czech Republic", "Czechia"),
        ("Türkiye", "Turkey"),
        ("Cabo Verde", "Cape Verde"),
        ("Cape Verde Islands", "Cape Verde"),  # football-data.org's spelling
        ("Bosnia & Herzegovina", "Bosnia and Herzegovina"),  # api-sports' spelling
        ("Republic of Ireland", "Ireland"),
        ("Côte d'Ivoire", "Ivory Coast"),
    ],
)
def test_known_aliases_resolve(raw, expected):
    assert normalize_team_name(raw) == expected


def test_whitespace_is_collapsed_and_trimmed():
    assert normalize_team_name("  Korea   Republic  ") == "South Korea"


def test_unknown_name_returned_trimmed_unchanged():
    assert normalize_team_name("  Brazil ") == "Brazil"


def test_none_and_empty_are_safe():
    assert normalize_team_name(None) == ""
    assert normalize_team_name("") == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ath Madrid", "Atletico Madrid"),
        ("Betis", "Real Betis"),
        ("Ath Bilbao", "Athletic Club"),
        ("Bayern Munich", "Bayern München"),
        ("Dortmund", "Borussia Dortmund"),
        ("Leverkusen", "Bayer Leverkusen"),
    ],
)
def test_sp1_d1_club_aliases_resolve_to_the_api_football_spelling(raw, expected):
    """La Liga (SP1) / Bundesliga (D1) football-data.co.uk spellings ->
    API-Football's canonical name -- see team_mapping.py's own section on why
    this reconciliation matters (League Score Predictions Phase 2)."""
    assert normalize_team_name(raw) == expected
