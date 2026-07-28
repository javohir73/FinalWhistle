"""Tests for the active three-league registry."""
from pipeline import leagues as leagues_mod
from pipeline.leagues import ACTIVE_LEAGUES, LEAGUES, PHASE_2_PENDING_ACTIVATION, club_competitions


def test_all_three_leagues_are_active_in_pipeline_order():
    assert ACTIVE_LEAGUES == ["epl", "laliga", "bundesliga"]


def test_no_registered_phase_2_league_remains_pending():
    assert PHASE_2_PENDING_ACTIVATION == []
    for code in ("laliga", "bundesliga"):
        assert code in LEAGUES
        assert code in ACTIVE_LEAGUES


def test_laliga_config_matches_the_design_doc():
    cfg = LEAGUES["laliga"]
    assert cfg["league_id"] == 140
    assert cfg["season"] == 2026
    assert cfg["tournament_name"] == "La Liga 2026-27"
    assert cfg["teams_file"] is None  # no hand-curated roster -- derived at ingest time
    assert cfg["club_division"] == "SP1"
    assert cfg["home_advantage"] == 80.0
    assert cfg["cold_start_teams"] == ("Racing Santander",)


def test_bundesliga_config_matches_the_design_doc():
    cfg = LEAGUES["bundesliga"]
    assert cfg["league_id"] == 78
    assert cfg["season"] == 2026
    assert cfg["tournament_name"] == "Bundesliga 2026-27"
    assert cfg["teams_file"] is None
    assert cfg["club_division"] == "D1"
    assert cfg["home_advantage"] == 60.0
    assert cfg["cold_start_teams"] == ("SV Elversberg",)


def test_epl_config_matches_the_live_2026_27_roster():
    cfg = LEAGUES["epl"]
    assert cfg["teams_file"] == "pipeline/data/epl2627_teams.json"
    assert cfg["league_id"] == 39
    assert cfg["club_competition"] == "Premier League"
    assert cfg["club_division"] == "E0"
    assert cfg["home_advantage"] == 60.0
    assert cfg["cold_start_teams"] == ("Coventry",)


def test_every_leagues_entry_has_a_unique_club_competition():
    """club_competitions()'s notin_() set only protects the international
    replay if every league's discriminator is actually distinct."""
    values = [cfg["club_competition"] for cfg in LEAGUES.values()]
    assert len(values) == len(set(values))


def test_club_competitions_covers_every_registered_league_not_just_active_ones():
    """Registered-but-inactive leagues' strings are still reserved -- the
    international exclusion in pipeline/compute_elo.py must never treat a
    not-yet-active league's rows as international just because
    ACTIVE_LEAGUES hasn't grown yet."""
    assert club_competitions() == frozenset({"Premier League", "La Liga", "Bundesliga"})


def test_club_competitions_reflects_monkeypatched_registry_additions(monkeypatch):
    """Same idiom the backend tests use for _LEAGUE_TOURNAMENT_NAMES
    (monkeypatch.setitem) -- club_competitions() is a live view, not a
    snapshot taken at import time."""
    monkeypatch.setitem(
        leagues_mod.LEAGUES, "extra",
        {
            "tournament_name": "Extra 2026-27", "group_name": "Extra", "league_id": 1,
            "season": 2026, "teams_file": None, "club_competition": "Extra League",
            "club_division": "X1", "history_min_matches": 1,
            "home_advantage": 50.0, "cold_start_teams": (),
        },
    )
    assert "Extra League" in club_competitions()


# ---------------------------------------------------------------------------
# Activation framing (Opus review, League Score Predictions Phase 2): the
# module docstring and ACTIVE_LEAGUES/PHASE_2_PENDING_ACTIVATION comments
# used to call activation "a one-line follow-up" and "a single, obviously-
# safe, additive edit" -- false, since neither club-name reconciliation nor
# the historical backfill nor a per-league home-advantage fit is automated.
# PHASE_2_ACTIVATION_CHECKLIST replaces that framing with the real list; lock
# in that it exists and actually names the undone prerequisites, not just the
# quota check the old comments singled out.
# ---------------------------------------------------------------------------

def test_phase_2_activation_checklist_documents_the_real_prerequisites():
    checklist = leagues_mod.PHASE_2_ACTIVATION_CHECKLIST
    assert len(checklist) >= 4
    joined = " ".join(checklist).lower()
    for must_mention in ("reconciliation", "backfill", "home-advantage", "quota"):
        assert must_mention in joined


# ---------------------------------------------------------------------------
# Per-league engine params (club program, docs/MODEL-EXPERIMENTS.md).
# model_params.json is fitted on INTERNATIONAL football; its goal rate does not
# transfer to club leagues. These lock in that each league gets its own gated
# overrides and that a league with none is an explicit fitted outcome rather
# than a forgotten entry.
# ---------------------------------------------------------------------------

def test_every_league_declares_model_params_even_when_empty():
    for code, cfg in LEAGUES.items():
        assert "model_params" in cfg, f"{code} is missing model_params"
        assert isinstance(cfg["model_params"], dict)


def test_model_params_overrides_name_real_engine_parameters():
    """A typo'd key must fail loudly, not silently serve the global value."""
    from dataclasses import fields

    from ml.models.params import ModelParams

    valid = {f.name for f in fields(ModelParams)}
    for code, cfg in LEAGUES.items():
        unknown = set(cfg["model_params"]) - valid
        assert not unknown, f"{code} overrides unknown engine params: {sorted(unknown)}"


def test_confirmed_base_refits_reach_the_served_params():
    epl = leagues_mod.club_params_for("epl")
    bundesliga = leagues_mod.club_params_for("bundesliga")
    assert epl.base == 1.30
    assert bundesliga.base == 1.44


def test_laliga_keeps_the_global_values_because_its_refit_lost_the_gate():
    """La Liga's base refit was credibly WORSE in selection and its home_adv
    candidate failed to replicate; both deliberately stay at the served value."""
    from ml.models.params import load_params

    assert leagues_mod.LEAGUES["laliga"]["model_params"] == {}
    assert leagues_mod.club_params_for("laliga").base == load_params().base
    assert LEAGUES["laliga"]["home_advantage"] == 80.0


def test_unconfirmed_candidates_did_not_sneak_into_any_league():
    """rho, beta, k_factor, temperature and the Track-3 signals all failed to
    clear. None may appear as an override without a new ledger entry."""
    for code, cfg in LEAGUES.items():
        for never in ("rho", "beta", "temperature", "form_channels", "rest_days"):
            assert never not in cfg["model_params"], (
                f"{code} overrides {never}, which did not clear the club gate"
            )


def test_every_league_serves_the_same_club_model_version():
    for code in LEAGUES:
        assert leagues_mod.club_params_for(code).version == leagues_mod.CLUB_MODEL_VERSION


def test_shadow_baseline_is_the_previous_version_with_no_overrides():
    from ml.models.params import load_params

    baseline = leagues_mod.club_baseline_params_for("bundesliga")
    assert baseline.version == leagues_mod.CLUB_SHADOW_BASELINE_VERSION
    assert baseline.version != leagues_mod.CLUB_MODEL_VERSION
    # The whole point of the twin: it must NOT carry the refit.
    assert baseline.base == load_params().base
    assert baseline.base != leagues_mod.club_params_for("bundesliga").base
