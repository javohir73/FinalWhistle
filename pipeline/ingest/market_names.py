"""Team-name normalization for mapping exchange markets onto our teams.

Exchanges write display names ("USA", "South Korea", "Ivory Coast"); our
teams table uses FIFA-style names ("United States", "Korea Republic",
"Côte d'Ivoire"). normalize() lowercases, strips accents and punctuation,
then folds known exchange spellings onto the normalized FIFA name via
_ALIASES. Unknown names simply won't match — callers skip those markets
(never guess a mapping).
"""
from __future__ import annotations

import re
import unicodedata

#: normalized exchange spelling -> normalized FIFA-style name (as stored in
#: teams.name / sport_teams.name). Extend as unmapped names show up in the
#: market-intel run logs.
_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "america": "united states",
    "south korea": "korea republic",
    "korea": "korea republic",
    "iran": "ir iran",
    "ivory coast": "cote divoire",
    "bosnia": "bosnia and herzegovina",
    "uae": "united arab emirates",
    "dr congo": "congo dr",
    "czech republic": "czechia",
}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    return _ALIASES.get(s, s)


def build_team_index(teams: list[tuple[int, str]]) -> dict[str, int]:
    """{normalized team name -> team id} for one sport's teams."""
    return {normalize(name): team_id for team_id, name in teams}
