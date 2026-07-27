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

Phase 2 was activated locally on 2026-07-27 after validating the 2026-27
provider fixture sets, API quota, ten-season SP1/D1 history, provider-name
aliases, and league-specific home-advantage fits. Production remains governed
by the repository stop gate: this registry change does not switch
``PIPELINE_TARGET`` or deploy anything by itself.
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
    # Minimum historical rows expected before the daily league pipeline can
    # skip the idempotent football-data.co.uk backfill.
    history_min_matches: int
    # League-specific value selected by the held-out fit documented below.
    home_advantage: float
    # Current-roster clubs with no top-flight row in the ten-season source
    # window. They intentionally use the model's documented cold start.
    cold_start_teams: tuple[str, ...]


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
        "history_min_matches": 3_000,
        "home_advantage": 60.0,
        "cold_start_teams": (),
    },
    # Phase 2 (La Liga id 140, Bundesliga id 78). teams_file is None on
    # purpose: neither
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
        "history_min_matches": 3_000,
        "home_advantage": 80.0,
        "cold_start_teams": ("Racing Santander",),
    },
    "bundesliga": {
        "tournament_name": "Bundesliga 2026-27",
        "group_name": "Bundesliga",
        "league_id": 78,
        "season": 2026,
        "teams_file": None,
        "club_competition": "Bundesliga",
        "club_division": "D1",
        "history_min_matches": 2_500,
        "home_advantage": 60.0,
        "cold_start_teams": ("SV Elversberg",),
    },
}

# All locally activated football leagues, in the display/pipeline order shared
# with frontend/lib/leagueConfig.ts.
ACTIVE_LEAGUES: list[str] = ["epl", "laliga", "bundesliga"]

# Retained as an explicit compatibility/status field for tooling that reported
# the former activation gate.
PHASE_2_PENDING_ACTIVATION: list[str] = []

# The real activation checklist, in order. Replaces this module's former
# "one-line follow-up" / "single, obviously-safe, additive edit" framing,
# which understated what activating a Phase 2 league actually requires
# (Opus review: the human stop-gate relies on exactly this comment, so an
# inaccurate one invites shipping uninformed predictions -- see
# team_mapping.py's SP1/D1 alias section and compute_club_elo.py's
# unrated_roster_teams() for the reconciliation half of this).
# Steps 1-3 are now enforced by team_mapping.py, league_activation.py, the
# per-league fitted values above, and run_pipeline.py's roster audit. The tuple
# remains as the durable explanation of the activation evidence.
PHASE_2_ACTIVATION_CHECKLIST: tuple[str, ...] = (
    "1. Club-name reconciliation: add football-data.co.uk <-> API-Football "
    "spelling aliases for the league's full current roster in "
    "pipeline/team_mapping.py, then confirm "
    "compute_club_elo.unrated_roster_teams(db, tournament_name, group_name) "
    "returns only configured cold_start_teams after step 2.",
    "2. Historical backfill: load_club_results(competition=cfg["
    "\"club_competition\"]) against cfg[\"club_division\"] (SP1/D1) for every "
    "SEASON_CODE.",
    "3. Home-advantage fit: fit_home_advantage() against this league's "
    "OWN SP1/D1 CSVs (passing its own competition) and pass the winner into "
    "compute_and_store_club_elo -- EPL's CLUB_HOME_ADVANTAGE (60.0) is not "
    "assumed to carry over (see that module's docstring).",
    "4. Founder API-Football-quota check (design doc Phasing section): "
    "verified that three active leagues fit the configured daily allowance.",
)


def club_competitions() -> frozenset[str]:
    """Every league's club_competition discriminator, across ALL registered
    LEAGUES (not just ACTIVE_LEAGUES -- a registered-but-inactive league's
    string is still reserved and must never be treated as an international
    row if it ever appears). pipeline/compute_elo.py's international Elo
    replay excludes this full set; pipeline/compute_club_elo.py's per-league
    replay includes exactly one member of it at a time."""
    return frozenset(cfg["club_competition"] for cfg in LEAGUES.values())
