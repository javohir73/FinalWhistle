"""Tests for E1's tempo channel (offline, hermetic).

The interesting failures here are the three traps §12 of the pre-registration
names, each of which produces a plausible wrong number rather than an error:
offsets reaching `GridConfig`, a new parameter binding positionally under
`walk_forward`, and a single fit applied backwards across seasons.
"""
from __future__ import annotations

import math

import pytest

from ml.evaluation.club_tempo import (
    CAP_SENSITIVITY,
    GRID,
    TempoPoint,
    lambdas_with_offsets,
    loss_1x2_offsets,
    loss_totals_offsets,
    offset_diagnostics,
    offsets_for,
    season_cutoffs,
    walk_forward_tempo,
)
from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
    _lambdas,
    loss_totals,
    replay,
)

COMP = "Premier League"
TEAMS = ["Arsenal", "Chelsea", "Spurs", "Everton"]


def _matches(seasons=("1617", "1718", "1819")) -> list[ClubMatch]:
    out = []
    for si, season in enumerate(seasons):
        n = 0
        for i, h in enumerate(TEAMS):
            for j, a in enumerate(TEAMS):
                if i == j:
                    continue
                n += 1
                gh, ga = (2, 1) if n % 2 else (1, 1)
                out.append(ClubMatch(
                    season=season, home=h, away=a, goals_home=gh, goals_away=ga,
                    date=f"{2016 + si}-{(n % 9) + 1:02d}-{(n % 27) + 1:02d}",
                ))
    out.sort(key=lambda m: m.date)
    return out


# --- §12 trap 1: GridConfig must stay hashable and offset-free ------------

def test_gridconfig_is_still_hashable_and_carries_no_offsets():
    """`walk_forward` memoizes replays in a dict keyed by EloConfig, and grid
    points key `losses`. An unhashable field would raise TypeError at grid-scan
    time, not at import — long after a run looks like it started fine."""
    g = GridConfig()
    assert hash(g) is not None
    assert not any("offset" in f for f in g.__dataclass_fields__)


def test_tempo_point_is_hashable_so_it_can_key_a_cache():
    assert len({TempoPoint(365, 30.0), TempoPoint(365, 30.0)}) == 1


# --- §12 trap 2: every new parameter is keyword-only ---------------------

@pytest.mark.parametrize("fn", [loss_totals_offsets, loss_1x2_offsets])
def test_offsets_cannot_be_passed_positionally(fn):
    """`walk_forward` calls losses as `loss(matches, pre, elo, grid, ...)` and
    `loss_totals`'s fifth positional is `line`. If `offsets` were positional it
    would bind to whatever a caller put in slot five and score silently."""
    ms = _matches(("1617",))
    pre = replay(ms, EloConfig(), COMP)
    with pytest.raises(TypeError):
        fn(ms, pre, EloConfig(), GridConfig(), {"Arsenal": (0.05, 0.0)})


def test_signature_is_compatible_with_the_walk_forward_call_shape():
    import inspect
    sig = inspect.signature(loss_totals_offsets)
    assert sig.parameters["offsets"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["line"].kind is inspect.Parameter.KEYWORD_ONLY


# --- equivalence: no offsets must change nothing -------------------------

def test_empty_offsets_reproduce_the_served_lambdas_exactly():
    pre = (1550.0, 1480.0)
    g = GridConfig(base=1.44)
    assert lambdas_with_offsets(pre, g, 60.0, "A", "B", None) == \
        _lambdas(pre, g, 60.0, 0.0)
    assert lambdas_with_offsets(pre, g, 60.0, "A", "B", {}) == \
        _lambdas(pre, g, 60.0, 0.0)


def test_loss_totals_offsets_reduces_to_loss_totals_with_no_offsets():
    """The control column must be the existing metric, bit-for-bit, or the
    candidate is being compared against something that has never been gated."""
    ms = _matches()
    elo, g = EloConfig(), GridConfig(base=1.30)
    pre = replay(ms, elo, COMP)
    assert loss_totals_offsets(ms, pre, elo, g, offsets=None) == \
        loss_totals(ms, pre, elo, g)


def test_an_unknown_club_falls_back_to_served_behaviour_not_a_league_average():
    """§8: a zero pair is a real prediction. Never an average, never missing."""
    assert offsets_for({"Arsenal": (0.05, -0.02)}, "Nobody FC") == (0.0, 0.0)
    assert offsets_for(None, "Arsenal") == (0.0, 0.0)
    assert offsets_for({}, "Arsenal") == (0.0, 0.0)


# --- the channel actually does what §4 claims ----------------------------

def test_offsets_break_the_base_squared_identity():
    """The entire premise. Without offsets lam_h*lam_a == base**2 for every
    fixture; with them the PRODUCT moves, which is what gives totals a channel.
    """
    pre, g = (1550.0, 1480.0), GridConfig(base=1.30)
    lh, la = lambdas_with_offsets(pre, g, 60.0, "A", "B", None)
    assert lh * la == pytest.approx(g.base ** 2, rel=1e-12)
    lh2, la2 = lambdas_with_offsets(
        pre, g, 60.0, "A", "B", {"A": (0.05, 0.0), "B": (0.05, 0.0)},
    )
    assert lh2 * la2 > g.base ** 2 * 1.05


def test_tempo_moves_the_total_while_strength_moves_the_ratio():
    """§4's decomposition, as a behavioural check rather than algebra in prose.

    Two clubs given equal-and-opposite (atk, def) shifts keep their strength
    ordering but change how many goals the fixture is expected to produce.
    """
    pre, g = (1500.0, 1500.0), GridConfig(base=1.30)
    base_h, base_a = lambdas_with_offsets(pre, g, 0.0, "A", "B", None)
    # Pure tempo: both clubs attack better AND defend worse by the same amount.
    hi_h, hi_a = lambdas_with_offsets(
        pre, g, 0.0, "A", "B", {"A": (0.06, 0.06), "B": (0.06, 0.06)},
    )
    assert hi_h + hi_a > base_h + base_a          # total moved
    assert hi_h / hi_a == pytest.approx(base_h / base_a)  # ratio did not


# --- §12 trap 3: per-season refit, strictly prior -------------------------

def test_the_fitter_is_called_once_per_season_with_that_season_s_cutoff():
    ms = _matches()
    elo, g = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    cutoffs = season_cutoffs(ms)
    seen: list[tuple[str, TempoPoint]] = []

    def fake_fit(cutoff, point):
        seen.append((cutoff, point))
        return {}

    walk_forward_tempo(ms, pre, elo, g, points=(TempoPoint(365, 30.0),),
                       fit=fake_fit, loss=loss_totals_offsets,
                       scored_seasons=("1718", "1819"))
    assert sorted({c for c, _ in seen}) == sorted(cutoffs.values())


def test_season_cutoff_is_that_season_s_first_kickoff():
    ms = _matches()
    cut = season_cutoffs(ms)
    for season, iso in cut.items():
        assert iso == min(m.date for m in ms if m.season == season)


def test_a_season_is_never_selected_on_itself():
    """Selection for season S must rank points on seasons strictly BEFORE S.

    Point A is good on 1617+1718 and terrible in 1819; point B is the mirror.
    Honest selection scoring 1819 picks A — the one that looked good on the
    evidence available *before* 1819. A leak would pick B, which is only good
    in the season being scored.

    The loss is faked so the selection rule is tested directly rather than
    through the Poisson grid, where a "bad" offset's sign depends on the
    fixture data and the test would be asserting arithmetic it does not
    control.
    """
    ms = _matches()
    elo, g = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    A, B = TempoPoint(180, 10.0), TempoPoint(730, 60.0)
    quality = {  # (point, season) -> per-match loss. Lower is better.
        (A, "1617"): 1.0, (A, "1718"): 1.0, (A, "1819"): 9.0,
        (B, "1617"): 9.0, (B, "1718"): 9.0, (B, "1819"): 1.0,
    }

    def fake_loss(matches, pre_, elo_, grid_, *, offsets=None):
        season = matches[0].season
        if offsets is None:            # the control pass
            return [5.0] * len(matches)
        return [quality[(offsets["__point"], season)]] * len(matches)

    out = walk_forward_tempo(
        ms, pre, elo, g, points=(A, B),
        fit=lambda cutoff, point: {"__point": point},
        loss=fake_loss, scored_seasons=("1819",),
    )
    assert out["chosen"]["1819"] == A


def test_the_opening_season_is_never_scored():
    ms = _matches()
    elo, g = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    out = walk_forward_tempo(ms, pre, elo, g, points=(TempoPoint(365, 30.0),),
                             fit=lambda c, p: {}, loss=loss_totals_offsets)
    assert "1617" not in out["deltas"]


def test_the_confirmation_season_is_refused():
    ms = _matches()
    elo, g = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    with pytest.raises(ValueError, match=CONFIRM_SEASON):
        walk_forward_tempo(ms, pre, elo, g, points=(TempoPoint(365, 30.0),),
                           fit=lambda c, p: {}, loss=loss_totals_offsets,
                           scored_seasons=("1819", CONFIRM_SEASON))


def test_a_neutral_fit_gives_exactly_zero_deltas():
    ms = _matches()
    elo, g = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    out = walk_forward_tempo(ms, pre, elo, g, points=(TempoPoint(365, 30.0),),
                             fit=lambda c, p: {}, loss=loss_totals_offsets,
                             scored_seasons=("1718", "1819"))
    assert all(d == 0.0 for vals in out["deltas"].values() for d in vals)


# --- the frozen grid -----------------------------------------------------

def test_the_selectable_grid_is_the_nine_pre_registered_points():
    from ml.evaluation.club_tempo import CLUB_OFFSET_CAP

    assert len(GRID) == 9
    assert {p.half_life_days for p in GRID} == {180, 365, 730}
    assert {p.n0 for p in GRID} == {10.0, 30.0, 60.0}
    # The cap is FIXED, not on the selectable grid — E2 §3, carrying E1 §4's
    # rule that moving it mid-run is a second candidate wearing the first
    # one's name.
    assert {p.cap for p in GRID} == {CLUB_OFFSET_CAP}


def test_the_club_cap_is_the_pre_registered_dispersion_value():
    """E2 §1: 1 sd of observed club team-season log scoring dispersion
    (pooled 0.3068, burn-in only), rounded. Pinned so it cannot drift."""
    from ml.evaluation.club_tempo import CLUB_OFFSET_CAP

    assert CLUB_OFFSET_CAP == 0.30


def test_e1s_grid_is_preserved_and_is_not_what_e2_runs():
    """A phase that quietly re-ran the old grid would report E1's numbers under
    E2's name."""
    from ml.evaluation.club_tempo import E1_GRID

    assert {p.cap for p in E1_GRID} == {0.075}
    assert not (set(GRID) & set(E1_GRID))


def test_only_the_anchor_sensitivity_point_is_also_selectable():
    """§3: reported alongside, never eligible to win — kept in a separate tuple
    so a selection loop cannot reach one by iterating the wrong collection.

    The MIDDLE point is the frozen cap itself and therefore coincides with a
    grid point by construction: it is the bracket's anchor, not a fourth
    candidate. The two off-anchor points must not be selectable.
    """
    from ml.evaluation.club_tempo import CLUB_OFFSET_CAP

    assert len(CAP_SENSITIVITY) == 3
    assert {p.cap for p in CAP_SENSITIVITY} == {0.20, CLUB_OFFSET_CAP, 0.45}
    off_anchor = [p for p in CAP_SENSITIVITY if p.cap != CLUB_OFFSET_CAP]
    assert len(off_anchor) == 2
    assert not (set(GRID) & set(off_anchor))


def test_selection_is_deterministic_under_a_tie():
    """Two identical points must resolve by declared grid order, not by dict
    iteration, or the chosen point is not reproducible."""
    ms = _matches()
    elo, g = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    a, b = TempoPoint(180, 10.0), TempoPoint(730, 60.0)
    out = walk_forward_tempo(ms, pre, elo, g, points=(a, b),
                             fit=lambda c, p: {}, loss=loss_totals_offsets,
                             scored_seasons=("1718", "1819"))
    assert set(out["chosen"].values()) == {a}


# --- diagnostics ---------------------------------------------------------

def test_saturation_is_judged_on_the_RAW_fit_not_the_post_ramp_value():
    """The defect the review found, as a regression.

    The policy clamps to +-cap and THEN multiplies by min(1, sqrt(n_eff/n0)), so
    a pinned component emerges as cap*ramp. Comparing the post-ramp value to cap
    is a detector that cannot fire below full confidence — at Bundesliga's own
    selected point it was arithmetically pinned to 0.0% while the true rate was
    70%.
    """
    ramp = 0.87
    post = {"1819": {t: (0.075 * ramp, 0.0) for t in TEAMS}}
    raw = {"1819": {t: (2.0, 0.0) for t in TEAMS}}   # wildly clipped
    d = offset_diagnostics(post, cap=0.075, raw=raw)
    assert d["saturated_frac"] == 1.0
    assert d["saturation_measured_on_raw_fit"] is True

    loose_raw = {"1819": {t: (0.01, 0.0) for t in TEAMS}}
    loose = offset_diagnostics({"1819": {t: (0.01, 0.0) for t in TEAMS}},
                               cap=0.075, raw=loose_raw)
    assert loose["saturated_frac"] == 0.0


def test_saturation_is_none_rather_than_zero_when_the_raw_fit_is_absent():
    """Without the raw fit the rate is unknowable. Returning 0.0 would be the
    original bug wearing a different hat."""
    d = offset_diagnostics({"1819": {t: (0.075, 0.0) for t in TEAMS}}, cap=0.075)
    assert d["saturated_frac"] is None
    assert d["saturation_measured_on_raw_fit"] is False


def test_unmodelled_clubs_are_counted_against_clubs_that_PLAYED():
    """Measured over the fit dictionary alone, a club with no offset is absent
    from the denominator too, so the rate is ~0 by construction."""
    fitted = {"1819": {"Arsenal": (0.03, -0.01)}}
    played = {"1819": {"Arsenal", "Chelsea", "Spurs", "Everton"}}
    d = offset_diagnostics(fitted, cap=0.075, raw={}, played=played)
    assert d["unmodelled_club_seasons"] == 3
    assert d["scored_club_seasons"] == 4
    assert d["unmodelled_frac"] == pytest.approx(0.75)


def test_rekey_by_iso_week_produces_the_pre_registered_primary_cluster():
    """§7 pre-registered iso-week as PRIMARY and season as sensitivity. The
    first cut shipped season only — 7 clusters — undisclosed."""
    from ml.evaluation.club_tempo import iso_week_of, rekey_by_iso_week
    deltas = {"1819": [1.0, 2.0, 3.0]}
    dates = {"1819": ["2019-01-07", "2019-01-08", "2019-02-04"]}
    out = rekey_by_iso_week(deltas, dates)
    assert out["2019-W02"] == [1.0, 2.0]
    assert out["2019-W06"] == [3.0]
    assert iso_week_of("2024-12-30") == "2025-W01"   # ISO year rolls


def test_rekey_refuses_a_length_mismatch():
    from ml.evaluation.club_tempo import rekey_by_iso_week
    with pytest.raises(ValueError, match="deltas vs"):
        rekey_by_iso_week({"1819": [1.0, 2.0]}, {"1819": ["2019-01-07"]})


def test_zeroed_clubs_are_counted_not_hidden():
    fitted = {"1819": {"Arsenal": (0.0, 0.0), "Chelsea": (0.03, -0.01)}}
    d = offset_diagnostics(fitted, cap=0.075, raw={})
    assert d["zeroed"] == 1 and d["n"] == 2


def test_diagnostics_on_an_empty_fit_do_not_divide_by_zero():
    assert offset_diagnostics({}, cap=0.075, raw={})["n"] == 0


def test_tempo_spread_is_reported_because_a_flat_fit_is_a_null_by_construction():
    flat = offset_diagnostics({"1819": {t: (0.02, 0.02) for t in TEAMS}},
                              cap=0.075, raw={})
    assert flat["tempo_sd"] == pytest.approx(0.0)


def test_the_diagnostic_reports_atk_PLUS_def_as_tempo():
    """Tempo is (a+d), not (a-d). With positive def = leaky, a club that both
    scores and concedes heavily produces high-total matches. The first cut had
    these swapped and reported strength under a tempo label.

    Clubs given equal-and-opposite (atk, def) have zero tempo and large
    strength; the diagnostic must say so.
    """
    same_sign = {"1819": {"A": (0.05, 0.05), "B": (-0.05, -0.05)}}
    d = offset_diagnostics(same_sign, cap=0.075, raw={})
    assert d["tempo_sd"] > 0.05           # (a+d) = +0.10 / -0.10
    assert d["strength_sd"] == pytest.approx(0.0)   # (a-d) = 0 / 0

    opposite = {"1819": {"A": (0.05, -0.05), "B": (-0.05, 0.05)}}
    d2 = offset_diagnostics(opposite, cap=0.075, raw={})
    assert d2["tempo_sd"] == pytest.approx(0.0)
    assert d2["strength_sd"] > 0.05


# --- the guardrail metric ------------------------------------------------

def test_loss_1x2_offsets_applies_the_calibrator_like_the_control_does():
    """Comparing an uncalibrated candidate against a calibrated control would
    measure the calibrator, not the offsets."""
    ms = _matches(("1617",))
    elo = EloConfig()
    pre = replay(ms, elo, COMP)
    cal = {"method": "vector_scaling_segmented", "buckets": {},
           "default": {"t": 1.0, "b": [0.0, 0.0, -0.2]}}
    plain = loss_1x2_offsets(ms, pre, elo, GridConfig(), offsets=None)
    calib = loss_1x2_offsets(ms, pre, elo, GridConfig(calibrator=cal), offsets=None)
    assert plain != calib
    assert all(math.isfinite(x) for x in calib)
