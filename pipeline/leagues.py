"""League registry for the football-league pipeline branch (League Score
Predictions design doc, 2026-07-24 -- "Pipeline" section: run_pipeline's
league branch "iterates a configured league list").

One entry per league the pipeline knows how to run end-to-end: the
provider-facing identity (API-Football league id + season) and the
Tournament/Group identity, plus the checked-in teams JSON -- the same values
pipeline/ingest/league_structure.py used to hardcode as its own module
constants (TOURNAMENT_NAME/LEAGUE_ID/SEASON/GROUP_NAME), now collected here so
pipeline/run_pipeline.py's _run_league_pipeline can loop over them instead of
hardcoding a single load_league_structure(db) call.

Lives here rather than app/config.py by repo precedent: app.config stays the
single "whichever competition is currently live" switch used by odds/
live-scores/injuries (see league_structure.py's own comment on LEAGUE_ID/
SEASON), not a per-competition registry.

Phase 1 (design doc): ACTIVE_LEAGUES lists exactly one code, "epl". Phase 2
(La Liga id 140, Bundesliga id 78) is meant to be purely additive LEAGUES
entries plus more ACTIVE_LEAGUES elements -- no loop/code changes.
"""
from __future__ import annotations

from typing import TypedDict

from pipeline.ingest import league_structure as _epl


class LeagueConfig(TypedDict):
    tournament_name: str
    group_name: str
    league_id: int
    season: int
    teams_file: str


# EPL's values are read off league_structure.py's own module constants
# (rather than repeated here as separate literals) so there is exactly one
# place that names the Premier League's API-Football id/season/teams file --
# league_structure.py's constants stay its documented back-compat defaults
# for a bare load_league_structure(db) call (see its own module docstring).
LEAGUES: dict[str, LeagueConfig] = {
    "epl": {
        "tournament_name": _epl.TOURNAMENT_NAME,
        "group_name": _epl.GROUP_NAME,
        "league_id": _epl.LEAGUE_ID,
        "season": _epl.SEASON,
        "teams_file": _epl.DEFAULT_TEAMS_FILE,
    },
}

# Phase 1 config (design doc): exactly ["epl"]. Phase 2 adds "laliga"/
# "bundesliga" here once their LEAGUES entries + teams JSONs are in place
# (LEAGUE-PIVOT-PLAN Phase 2, gated on the API-Football quota check) --
# additive only, no code change required in run_pipeline.
ACTIVE_LEAGUES: list[str] = ["epl"]
