"""Tests for the league registry (League Score Predictions design doc; Phase 2
adds La Liga/Bundesliga entries -- see the module docstring for why
ACTIVE_LEAGUES does NOT grow in the same commit)."""
from pipeline import leagues as leagues_mod
from pipeline.leagues import ACTIVE_LEAGUES, LEAGUES, PHASE_2_PENDING_ACTIVATION, club_competitions


def test_active_leagues_stays_epl_only():
    """Activation is a separate, stop-gated step (design doc Phasing section:
    gated on a founder API-Football-quota check) -- registering laliga/
    bundesliga below must not silently turn them on."""
    assert ACTIVE_LEAGUES == ["epl"]


def test_laliga_and_bundesliga_are_registered_but_not_active():
    assert set(PHASE_2_PENDING_ACTIVATION) == {"laliga", "bundesliga"}
    for code in PHASE_2_PENDING_ACTIVATION:
        assert code in LEAGUES
        assert code not in ACTIVE_LEAGUES


def test_laliga_config_matches_the_design_doc():
    cfg = LEAGUES["laliga"]
    assert cfg["league_id"] == 140
    assert cfg["season"] == 2026
    assert cfg["tournament_name"] == "La Liga 2026-27"
    assert cfg["teams_file"] is None  # no hand-curated roster -- derived at ingest time
    assert cfg["club_division"] == "SP1"


def test_bundesliga_config_matches_the_design_doc():
    cfg = LEAGUES["bundesliga"]
    assert cfg["league_id"] == 78
    assert cfg["season"] == 2026
    assert cfg["tournament_name"] == "Bundesliga 2026-27"
    assert cfg["teams_file"] is None
    assert cfg["club_division"] == "D1"


def test_epl_config_is_unchanged():
    cfg = LEAGUES["epl"]
    assert cfg["teams_file"] == "pipeline/data/epl2627_teams.json"
    assert cfg["league_id"] == 39
    assert cfg["club_competition"] == "Premier League"
    assert cfg["club_division"] == "E0"


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
            "club_division": "X1",
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
