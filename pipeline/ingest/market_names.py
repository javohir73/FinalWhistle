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


def _strip(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    return re.sub(r"\s+", " ", s)


def normalize(name: str) -> str:
    s = _strip(name)
    return _ALIASES.get(s, s)


#: One alternation over every alias, longest phrase first so "south korea"
#: matches whole before "korea" could claim just the tail of it. A single
#: compiled pattern (not a loop of sequential re.sub calls) matters here: a
#: loop would let a later, shorter alias re-match text an earlier alias just
#: substituted in (e.g. "korea" re-matching inside the "korea republic" that
#: "south korea" had already produced) and double-expand it.
_ALIAS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in sorted(_ALIASES, key=len, reverse=True)) + r")\b"
)


def normalize_text(text: str) -> str:
    """Free-text variant of normalize() for market questions/titles, where
    the team name is one substring among others rather than the whole
    string — so the exact-match lookup in normalize() never fires. Expands
    every known exchange alias found as a whole word/phrase within the text,
    in one single pass, so `normalize(team) in normalize_text(question)`
    still matches aliased spellings (e.g. home="Korea" against question
    "Will Korea win?").
    """
    s = _strip(text)
    return _ALIAS_PATTERN.sub(lambda m: _ALIASES[m.group(1)], s)


def build_team_index(teams: list[tuple[int, str]]) -> dict[str, int]:
    """{normalized team name -> team id} for one sport's teams."""
    return {normalize(name): team_id for team_id, name in teams}
