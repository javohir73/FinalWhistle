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

The domestic Phase 2 leagues were activated locally on 2026-07-27 after
validating their provider fixture sets, API quota, ten-season SP1/D1 history,
provider-name aliases, and league-specific home-advantage fits. UCL activation
evidence is recorded separately in
docs/experiments/2026-08-01-ucl-activation/EVIDENCE-CARD.md.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from pipeline.ingest import league_structure as _epl
from pipeline.ingest.club_results import CLUB_COMPETITION as _epl_club_competition
from pipeline.ingest.club_results import DEFAULT_DIVISION as _epl_club_division

if TYPE_CHECKING:  # avoids a cycle: ml.models.params is imported lazily below
    from ml.models.params import ModelParams


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
    club_division: str | None
    # Historical ratings source. Domestic leagues use football-data.co.uk;
    # cross-border competitions such as the Champions League use the same
    # API-Football identity as their live fixture ingest because no domestic
    # division CSV can represent their field.
    history_source: NotRequired[Literal["football_data", "api_football"]]
    # Completed API-Football seasons fetched when history_source is
    # ``api_football``. Kept explicit so a refresh never guesses a season.
    history_seasons: NotRequired[tuple[int, ...]]
    # Minimum historical rows expected before the daily league pipeline can
    # skip the configured idempotent history backfill.
    history_min_matches: int
    # League-specific value selected by the held-out fit documented below.
    home_advantage: float
    # Per-league engine-parameter overrides applied on top of the global
    # ml/models/model_params.json, which is fitted on INTERNATIONAL football.
    # Empty dict = serve the global values unchanged.
    #
    # Every DOMESTIC entry here cleared the club gate in docs/MODEL-EXPERIMENTS.md
    # ("Club program"): selected walk-forward over 2016-17..2024-25 clustered
    # by season, then confirmed once on the quarantined 2025-26 season. A
    # parameter that was only selected, and failed to replicate on the
    # confirmation season, is NOT here -- see that document's post-confirmation
    # ship list before adding one.
    model_params: dict[str, float]
    model_version: NotRequired[str]
    shadow_baseline: NotRequired[bool]
    # Whether this competition owns the shared teams.elo_rating column that
    # /api/teams serves and orders by. Domestic leagues do (default). A
    # cross-border competition shares Team rows with them off a much shorter
    # replay, so it must not be the last to write that column: this flag is
    # the sort key run_pipeline._club_elo_all_leagues replays them by, non-
    # owners first. It does NOT gate the write itself -- a club no domestic
    # league covers still gets its rating from the cross-border replay.
    owns_served_rating: NotRequired[bool]
    # Current-roster clubs with no top-flight row in the ten-season source
    # window. They intentionally use the model's documented cold start.
    cold_start_teams: tuple[str, ...]
    # A cross-border qualifying field changes throughout the summer. Unknown
    # entrants may use the engine's documented 1500 cold start rather than
    # blocking predictions for the entire competition.
    allow_unrated_roster: NotRequired[bool]
    # Number of teams considered to have progressed from the shared table.
    # Domestic defaults remain two for backwards compatibility; the UCL
    # league phase advances 24 (top eight direct, 9-24 into the play-offs).
    standings_advance_count: NotRequired[int]
    # If set, only fixtures whose provider round begins with one of these
    # labels belong to the shared standings table. All fixtures are still
    # ingested and predicted.
    group_round_prefixes: NotRequired[tuple[str, ...]]


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
        # base 1.20 -> 1.30. Defect-fix bar: the served internationals base
        # left EPL's O/U 2.5 book LOSING to a constant (LL 0.6955 vs 0.6893).
        # Held-out direction favourable (-0.0094, CI [-0.0202, +0.0013]).
        "model_params": {"base": 1.30},
        # Coventry have no Premier League row in the ten-season E0 window.
        # Hull City are not a cold start: football-data.co.uk calls them
        # "Hull", reconciled in team_mapping.py.
        "cold_start_teams": ("Coventry",),
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
        # Deliberately empty. La Liga's `base` refit came back CREDIBLY WORSE
        # in selection (+0.0043, CI [+0.0015, +0.0076]) -- the served 1.20 is
        # already right and refitting it only adds variance. Its `home_adv`
        # 80->60 candidate won selection but failed to replicate on the
        # confirmation season (+0.0002, CI [-0.0056, +0.0057]), so 80 stands.
        "model_params": {},
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
        # base 1.20 -> 1.44, the one change CONFIRMED on held-out data
        # (-0.0447 O/U 2.5, CI [-0.0756, -0.0126], n=306 unseen matches).
        # The served internationals base implied 2.579 goals/match against
        # Bundesliga's realized 3.096 -- a -16.7% totals bias that left the
        # O/U book losing to a constant (LL 0.7001 vs 0.6738).
        "model_params": {"base": 1.44},
        "cold_start_teams": ("SV Elversberg",),
    },
    "ucl": {
        "tournament_name": "UEFA Champions League 2026-27",
        "group_name": "Champions League",
        # API-Football's stable UEFA Champions League identity. Its season
        # parameter is the starting calendar year, hence 2026 for 2026-27.
        "league_id": 2,
        "season": 2026,
        "teams_file": None,
        "club_competition": "UEFA Champions League",
        "club_division": None,
        "history_source": "api_football",
        # Four fully completed editions. This keeps the one-time activation
        # backfill bounded to four provider calls while spanning both the old
        # group format and the current league-phase format.
        "history_seasons": (2022, 2023, 2024, 2025),
        "history_min_matches": 450,
        # home_adv refit was NOT credible (U2_home_adv: Δ +0.0010, CI
        # straddles 0 — docs/experiments/2026-08-06-ucl-base-fit): the served
        # club default stands, same outcome as EPL's and Bundesliga's fits.
        "home_advantage": 60.0,
        # base 1.20 -> 1.44: the UCL's own Track-1 goal-rate fit
        # (pipeline/experiment_ucl_eval.py). Selection credibly better on
        # walk-forward O/U (Δ −0.0332, CI [−0.0462, −0.0191]); CONFIRMED on
        # the quarantined 2025 edition on BOTH metrics (1X2 Δ −0.0119,
        # CI [−0.0170, −0.0061]; O/U Δ −0.0356, CI [−0.0640, −0.0005]).
        # Observed 2.97 goals/match across 2022-2024 vs 2.40 implied by the
        # inherited base — docs/experiments/2026-08-06-ucl-base-fit.
        "model_params": {"base": 1.44},
        # v0.2 = the UCL's own parameter fit (same process-naming convention
        # as CLUB_MODEL_VERSION below). v0.1 — the unfitted club defaults —
        # becomes the live +baseline twin so the promotion is measurable in
        # live conditions, exactly like the domestic v0.1 -> v0.2 refit.
        "model_version": "poisson-elo-ucl-v0.2",
        "shadow_baseline": True,
        "shadow_baseline_version": "poisson-elo-ucl-v0.1",
        # Shares Team rows with epl/laliga/bundesliga. Four seasons from a 1500
        # cold start must not overwrite their ten-season served ratings.
        "owns_served_rating": False,
        "cold_start_teams": (),
        "allow_unrated_roster": True,
        "standings_advance_count": 24,
        "group_round_prefixes": ("League Stage",),
    },
}

# All locally activated football leagues, in the display/pipeline order shared
# with frontend/lib/leagueConfig.ts.
ACTIVE_LEAGUES: list[str] = ["epl", "laliga", "bundesliga", "ucl"]

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
    "verify every active competition plus any bounded one-time history "
    "backfill fits the configured daily allowance.",
)


# Served club model version. v0.1 = the global internationals-fitted params
# applied unchanged to every league. v0.2 = per-league fitted params, from the
# club program in docs/MODEL-EXPERIMENTS.md (pre-registered candidates,
# walk-forward selection clustered by season, one confirmation run on a
# quarantined season).
#
# All three domestic leagues carry the v0.2 tag even though La Liga's fitted result was
# "no change from the global values" -- v0.2 names the PROCESS (per-league
# fitting) rather than a specific delta, and a single version across the three
# keeps one ledger on the record page. Safe to renumber wholesale because no
# league match has been played yet: first kickoff is 2026-08-15.
CLUB_MODEL_VERSION = "poisson-elo-club-v0.2"

# The previous version, retained as the shadow twin so the promotion is
# measurable in live conditions rather than only offline.
CLUB_SHADOW_BASELINE_VERSION = "poisson-elo-club-v0.1"


def club_params_for(code: str) -> "ModelParams":
    """Global engine params with ``code``'s fitted overrides applied.

    model_params.json is fitted on INTERNATIONAL football; its goal rate does
    not transfer to club leagues (Bundesliga's served base implied 2.579
    goals/match against a realized 3.096). Each league's own gated overrides
    live in its LEAGUES entry; a league with none gets the global values
    unchanged, which is a real fitted outcome and not an oversight.
    """
    from dataclasses import replace

    from ml.models.params import load_params

    overrides = LEAGUES[code]["model_params"]
    version = LEAGUES[code].get("model_version", CLUB_MODEL_VERSION)
    return replace(load_params(), version=version, **overrides)


def club_baseline_params_for(code: str) -> "ModelParams | None":
    """The previous-version shadow twin, or None for a competition with no
    predecessor. The twin is always the GLOBAL params with no league
    overrides — that is what every league served before its own fit. A league
    with its own version ledger (UCL) names its predecessor explicitly via
    ``shadow_baseline_version``; the domestic leagues share the club twin."""
    from dataclasses import replace

    from ml.models.params import load_params

    if not LEAGUES[code].get("shadow_baseline", True):
        return None
    version = LEAGUES[code].get("shadow_baseline_version", CLUB_SHADOW_BASELINE_VERSION)
    return replace(load_params(), version=version)


#: Calibrator artifacts that MAY be shadowed, per league. A league absent here
#: has no enablable variant at all, which is how EPL and La Liga are excluded
#: structurally rather than by configuration: no env value can name a variant
#: that does not exist. Only Bundesliga's recut survived T1.6's
#: multiplicity-corrected gate (docs/MODEL-EXPERIMENTS.md).
AVAILABLE_SHADOW_VARIANTS: dict[str, dict[str, str]] = {
    "bundesliga": {"cal_q3": "bundesliga_q3.json"},
}

#: Env var selecting which AVAILABLE variants are live, as comma-separated
#: "league:variant" tokens (e.g. "bundesliga:cal_q3"). Unset/empty = none,
#: which is the shipped default. A token naming an unavailable league or
#: variant is IGNORED with a warning -- a typo must not silently enable
#: something else, and must not break the pipeline either.
SHADOW_VARIANTS_ENV = "CLUB_SHADOW_VARIANTS"

_CALIBRATOR_DIR = "ml/models/calibrators"


def _load_calibrator_artifact(filename: str) -> dict:
    """Read a reviewed calibrator artifact from disk, validating it is servable."""
    import json
    from pathlib import Path

    from ml.evaluation.calibration import assert_servable_calibrator

    path = Path(__file__).resolve().parents[1] / _CALIBRATOR_DIR / filename
    blob = json.loads(path.read_text())
    assert_servable_calibrator(blob)
    return blob


def enabled_shadow_variants(env_value: str | None = None) -> dict[str, set[str]]:
    """Parse the env selection into {league: {variant, ...}}.

    Filtered against AVAILABLE_SHADOW_VARIANTS, so an operator cannot enable a
    league that has no reviewed artifact. Returns {} when unset -- the default.
    """
    import logging
    import os

    raw = env_value if env_value is not None else os.getenv(SHADOW_VARIANTS_ENV, "")
    out: dict[str, set[str]] = {}
    for token in (t.strip() for t in (raw or "").split(",")):
        if not token:
            continue
        league, _, variant = token.partition(":")
        if variant and variant in AVAILABLE_SHADOW_VARIANTS.get(league, {}):
            out.setdefault(league, set()).add(variant)
        else:
            logging.getLogger(__name__).warning(
                "%s: ignoring %r -- no reviewed artifact for that league/variant "
                "(available: %s)", SHADOW_VARIANTS_ENV, token,
                {k: sorted(v) for k, v in AVAILABLE_SHADOW_VARIANTS.items()},
            )
    return out


def club_shadow_variants_for(code: str, env_value: str | None = None) -> dict[str, "ModelParams"]:
    """Named shadow-variant params for ``code``. Empty dict = none enabled.

    Each variant overrides the league's SERVED params in the calibrator ALONE,
    so the live comparison isolates the calibrator instead of confounding it
    with whatever else moved. Default is empty: enabling one is an explicit,
    reviewed operator action (docs/BUNDESLIGA-CALIBRATOR-LIVE-VALIDATION.md).
    """
    from dataclasses import replace

    wanted = enabled_shadow_variants(env_value).get(code, set())
    if not wanted:
        return {}
    served = club_params_for(code)
    return {
        name: replace(served, calibrator=_load_calibrator_artifact(
            AVAILABLE_SHADOW_VARIANTS[code][name]))
        for name in sorted(wanted)
    }


def club_competitions() -> frozenset[str]:
    """Every league's club_competition discriminator, across ALL registered
    LEAGUES (not just ACTIVE_LEAGUES -- a registered-but-inactive league's
    string is still reserved and must never be treated as an international
    row if it ever appears). pipeline/compute_elo.py's international Elo
    replay excludes this full set; pipeline/compute_club_elo.py's per-league
    replay includes exactly one member of it at a time."""
    return frozenset(cfg["club_competition"] for cfg in LEAGUES.values())
