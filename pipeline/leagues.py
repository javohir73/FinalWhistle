"""League registry for the football-league pipeline branch (League Score
Predictions design doc, 2026-07-24 -- "Pipeline" section: run_pipeline's
league branch "iterates a configured league list").

One entry per league the pipeline knows how to run end-to-end: the
provider-facing identity (API-Football league id + season), the
Tournament/Group identity, the checked-in teams JSON (optional -- see
teams_file below), and the two club-ingest discriminators (club_competition/
club_division) pipeline/ingest/club_results.py and pipeline/compute_club_elo.py
need to keep each league's historical rows and Elo replay separate -- the same
values pipeline/ingest/league_structure.py and pipeline/ingest/club_results.py
used to hardcode as their own module constants, now collected here so
pipeline/run_pipeline.py's _run_league_pipeline can loop over them instead of
hardcoding a single call per step.

Lives here rather than app/config.py by repo precedent: app.config stays the
single "whichever competition is currently live" switch used by odds/
live-scores/injuries (see league_structure.py's own comment on LEAGUE_ID/
SEASON), not a per-competition registry.

Phase 1 (design doc): ACTIVE_LEAGUES lists exactly one code, "epl". Phase 2
(La Liga id 140, Bundesliga id 78) adds their LEAGUES entries below -- purely
additive, no loop/code changes needed elsewhere -- but activation (appending
them to ACTIVE_LEAGUES) is its OWN, separate, stop-gated step: the design
doc's Phasing section gates it on a founder API-Football-quota check (three
leagues ~= 3x fixture polling), so it does not happen in the same commit that
registers them. See PHASE_2_PENDING_ACTIVATION below.
"""
from __future__ import annotations

from typing import TypedDict

from pipeline.ingest import league_structure as _epl
from pipeline.ingest.club_results import CLUB_COMPETITION as _epl_club_competition
from pipeline.ingest.club_results import DEFAULT_DIVISION as _epl_club_division


class LeagueConfig(TypedDict):
    tournament_name: str
    group_name: str
    league_id: int
    season: int
    # None means "no curated JSON for this league" -- league_structure.py
    # derives teams from the fixtures payload instead (Phase 2: La Liga/
    # Bundesliga's 2026-27 rosters, including promoted clubs, aren't
    # reliably known ahead of what the provider itself returns at ingest
    # time -- never hand-curate one).
    teams_file: str | None
    # historical_matches.competition discriminator for this league's
    # football-data.co.uk backfill + club Elo replay (pipeline/ingest/
    # club_results.py, pipeline/compute_club_elo.py). Must be unique across
    # LEAGUES -- see club_competitions() below, which pipeline/compute_elo.py
    # relies on to keep every league's rows out of the international replay.
    club_competition: str
    # football-data.co.uk's division code for this league's CSV backfill
    # (mmz4281/{season}/{division}.csv) -- E0/SP1/D1 are public, stable
    # identifiers, not derived/guessed data.
    club_division: str


# EPL's values are read off league_structure.py's/club_results.py's own
# module constants (rather than repeated here as separate literals) so there
# is exactly one place that names the Premier League's API-Football id/
# season/teams file/competition/division -- those modules' constants stay
# their documented back-compat defaults for a bare call with no arguments
# (see each module's own docstring).
LEAGUES: dict[str, LeagueConfig] = {
    "epl": {
        "tournament_name": _epl.TOURNAMENT_NAME,
        "group_name": _epl.GROUP_NAME,
        "league_id": _epl.LEAGUE_ID,
        "season": _epl.SEASON,
        "teams_file": _epl.DEFAULT_TEAMS_FILE,
        "club_competition": _epl_club_competition,
        "club_division": _epl_club_division,
    },
    # Phase 2 (La Liga id 140, Bundesliga id 78): registered here so the
    # pipeline/backend/frontend all agree on the same tournament-name string
    # by convention, but NOT in ACTIVE_LEAGUES yet -- see
    # PHASE_2_PENDING_ACTIVATION. teams_file is None on purpose: neither
    # league has a checked-in roster (no hand-curated 2026-27 club list --
    # league_structure.py derives teams from API-Football's own fixtures
    # payload for these two). club_competition/club_division are plain
    # provider/public identifiers, not derived data, so registering them
    # ahead of activation is safe.
    "laliga": {
        "tournament_name": "La Liga 2026-27",
        "group_name": "La Liga",
        "league_id": 140,
        "season": 2026,
        "teams_file": None,
        "club_competition": "La Liga",
        "club_division": "SP1",
    },
    "bundesliga": {
        "tournament_name": "Bundesliga 2026-27",
        "group_name": "Bundesliga",
        "league_id": 78,
        "season": 2026,
        "teams_file": None,
        "club_competition": "Bundesliga",
        "club_division": "D1",
    },
}

# Phase 1 config (design doc): exactly ["epl"]. Activating La Liga/Bundesliga
# is a one-line follow-up -- append entries from PHASE_2_PENDING_ACTIVATION --
# but that line is itself a stop-gated decision (design doc Phasing section:
# gated on a founder API-Football-quota check, since 3 leagues ~= 3x fixture
# polling), so it is deliberately NOT done in this commit even though both
# leagues' LEAGUES entries above are ready to run.
ACTIVE_LEAGUES: list[str] = ["epl"]

# Registered, ready, and NOT active -- the exact list to append to
# ACTIVE_LEAGUES once the quota check clears. Kept as its own named constant
# (rather than just "the rest of LEAGUES") so the one-line follow-up reads as
# a single, obviously-safe, additive edit.
PHASE_2_PENDING_ACTIVATION: list[str] = ["laliga", "bundesliga"]


def club_competitions() -> frozenset[str]:
    """Every league's club_competition discriminator, across ALL registered
    LEAGUES (not just ACTIVE_LEAGUES -- a registered-but-inactive league's
    string is still reserved and must never be treated as an international
    row if it ever appears). pipeline/compute_elo.py's international Elo
    replay excludes this full set; pipeline/compute_club_elo.py's per-league
    replay includes exactly one member of it at a time."""
    return frozenset(cfg["club_competition"] for cfg in LEAGUES.values())
