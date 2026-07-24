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

    # --- Club football (league pivot, docs/LEAGUE-PIVOT-PLAN.md D2/D3) ---
    # football-data.co.uk's EPL (E0) spellings that differ from the canonical
    # names in pipeline/data/epl2627_teams.json. Names not listed here already
    # match (e.g. "Arsenal", "Brighton", "Newcastle") or belong to a team not
    # currently in the league (auto-created unchanged by load_historical /
    # club_results — no alias needed until it collides with a canonical name).
    "man united": "Manchester United",
    "man utd": "Manchester United",
    "man city": "Manchester City",
    "nott'm forest": "Nottingham Forest",
    "nottm forest": "Nottingham Forest",

    # --- La Liga (SP1) / Bundesliga (D1), League Score Predictions Phase 2
    # (docs/superpowers/specs/2026-07-24-league-score-predictions-design.md)
    # ---
    # football-data.co.uk (the historical-backfill/club-Elo-replay source,
    # pipeline/ingest/club_results.py) and API-Football (the live fixtures/
    # roster source, pipeline/ingest/league_structure.py's derive-from-
    # fixtures path) spell a number of Spanish/German clubs differently.
    # Without an alias here, the two providers' rows for the SAME club land
    # on two DIFFERENT Team names: the fixtures-derived one (what
    # generate_predictions actually reads elo_rating off) never gets the
    # replayed club Elo (what the CSV backfill + compute_and_store_club_elo
    # write), so it silently keeps the 1500 cold-start default forever
    # (ml/features/build_features.py's estimate_strength). See
    # pipeline/compute_club_elo.py's unrated_roster_teams() -- the
    # reconciliation check this table exists to satisfy.
    #
    # THIS IS A STARTING SET, NOT A COMPLETE ROSTER MAPPING. Only the pairs
    # below have been confirmed. Before La Liga/Bundesliga activation
    # (pipeline/leagues.py's PHASE_2_ACTIVATION_CHECKLIST), run
    # unrated_roster_teams() against a real ingest of each league and add
    # whatever other current-roster clubs are still missing -- never guess a
    # spelling you haven't seen in an actual provider payload.
    "ath madrid": "Atletico Madrid",
    "betis": "Real Betis",
    "ath bilbao": "Athletic Club",
    "bayern munich": "Bayern München",
    "dortmund": "Borussia Dortmund",
    "leverkusen": "Bayer Leverkusen",
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
