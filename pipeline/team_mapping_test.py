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
