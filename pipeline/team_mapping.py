"""Canonical team-name mapping.

Different data sources spell national teams differently ("Korea Republic" vs
"South Korea", "IR Iran" vs "Iran", "West Germany" vs "Germany"). Mismatches
silently corrupt joins and ratings, so EVERY team name from EVERY source must
pass through `normalize_team_name()` before it touches the database.

This is the PRD's #1 silent-bug guard (§9.4). Add aliases here as new sources
surface new spellings.
"""
from __future__ import annotations

# alias (lowercased) -> canonical name. Keep canonical names consistent with the
# WC2026 seed data (pipeline/data/wc26_teams.json).
_ALIASES: dict[str, str] = {
    # Koreas
    "korea republic": "South Korea",
    "republic of korea": "South Korea",
    "korea, south": "South Korea",
    "south korea": "South Korea",
    "korea dpr": "North Korea",
    "korea, north": "North Korea",
    "north korea": "North Korea",
    # Germany (historical continuity: West Germany -> Germany)
    "west germany": "Germany",
    "germany fr": "Germany",
    # USA
    "usa": "United States",
    "united states of america": "United States",
    "united states": "United States",
    # Iran
    "ir iran": "Iran",
    "iran": "Iran",
    # Ivory Coast
    "côte d'ivoire": "Ivory Coast",
    "cote d'ivoire": "Ivory Coast",
    "ivory coast": "Ivory Coast",
    # China
    "china pr": "China",
    "china": "China",
    # Czechia
    "czech republic": "Czechia",
    "czechia": "Czechia",
    # Turkey
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "turkey": "Turkey",
    # Cape Verde
    "cabo verde": "Cape Verde",
    "cape verde": "Cape Verde",
    "cape verde islands": "Cape Verde",  # football-data.org's spelling
    # Ireland
    "republic of ireland": "Ireland",
    "ireland": "Ireland",
    # North Macedonia
    "fyr macedonia": "North Macedonia",
    "macedonia": "North Macedonia",
    "north macedonia": "North Macedonia",
    # DR Congo
    "dr congo": "DR Congo",
    "congo dr": "DR Congo",
    "democratic republic of the congo": "DR Congo",
    # Bosnia
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "bosnia-herzegovina": "Bosnia and Herzegovina",
    "bosnia & herzegovina": "Bosnia and Herzegovina",  # api-sports' spelling
}


def normalize_team_name(raw: str) -> str:
    """Return the canonical team name for a raw source spelling.

    Unknown names are returned trimmed but otherwise unchanged, so new teams
    still flow through — they just won't be merged with an alias until added here.
    """
    if raw is None:
        return ""
    cleaned = " ".join(raw.strip().split())  # collapse internal whitespace
    return _ALIASES.get(cleaned.lower(), cleaned)


def known_aliases() -> dict[str, str]:
    """Expose the alias table (for tests / debugging)."""
    return dict(_ALIASES)
