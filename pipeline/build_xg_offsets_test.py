"""Tests for the re-anchor + kappa-blend that produces team_offsets_xg.json.

Pure unit tests over small synthetic offset dicts (no DB, no fit_offsets call)
— they exercise only the blend math documented in
docs/superpowers/specs/2026-07-04-xg-team-offsets-design.md (the fit (ML core),
lines 73-110): re-anchor removes the goals-fit/xG-fit zero-point mismatch over
the shared coverage set S, then kappa blends the re-anchored xG residual onto
the goals prior, capped and shrunk exactly like fit_offsets' own output (which
these synthetic fixtures stand in for).
"""
import math

import pytest

from ml.models.team_offsets import FULL_WEIGHT_EFF_MATCHES, OFFSET_CAP
from pipeline.build_xg_offsets import blend_offsets, reanchor


def _offs(atk, dfn, n_matches=10, n_eff=10.0):
    return {"atk": atk, "def": dfn, "n_matches": n_matches, "n_eff": n_eff}


def test_reanchor_removes_zero_point_shift():
    """goals-fit and xG-fit offsets over the shared set S differ by a constant
    scalar shift; reanchor's delta must recover that shift (weighted by
    n_eff_xg) so the re-anchored xG residual is mean-zero over S."""
    goals = {
        1: _offs(0.05, -0.02, n_eff=40.0),
        2: _offs(-0.01, 0.03, n_eff=40.0),
        3: _offs(0.02, 0.00, n_eff=5.0),  # not in S (no xG coverage)
    }
    shift = 0.10
    xg = {
        1: _offs(0.05 - shift, -0.02 - shift, n_eff=40.0),
        2: _offs(-0.01 - shift, 0.03 - shift, n_eff=20.0),
    }
    delta = reanchor(goals, xg)
    # Per-channel: both atk and def were shifted by the same scalar here, so
    # each channel's own delta recovers it.
    assert delta["atk"] == pytest.approx(shift)
    assert delta["def"] == pytest.approx(shift)

    reanchored = {t: xg[t]["atk"] + delta["atk"] for t in xg}
    # Shared-set gap (goals atk - reanchored xG atk), weighted by n_eff_xg, is
    # mean-zero by construction.
    num = sum(xg[t]["n_eff"] * (goals[t]["atk"] - reanchored[t]) for t in xg)
    den = sum(xg[t]["n_eff"] for t in xg)
    assert num / den == pytest.approx(0.0, abs=1e-9)


def test_blend_kappa_zero_is_goals_identity():
    """A team absent from the xG fit (n_eff_xg=0, i.e. not in S) gets kappa=0
    and its blended offset must equal the goals-fit offset EXACTLY — the
    shadow-first identity that lets kappa=0 teams reproduce today's numbers."""
    goals = {1: _offs(0.04, -0.03, n_matches=12), 2: _offs(-0.02, 0.01, n_matches=8)}
    xg = {1: _offs(0.30, -0.30, n_eff=50.0)}  # team 2 has no xG coverage at all
    delta = reanchor(goals, xg)
    blended = blend_offsets(goals, xg, delta)

    assert blended[2]["atk"] == goals[2]["atk"]
    assert blended[2]["def"] == goals[2]["def"]
    assert blended[2]["n_matches"] == goals[2]["n_matches"]


def test_blend_stays_capped():
    """BOTH channels of every blended offset stay within OFFSET_CAP at full
    kappa=1 and the opposite-signed extreme. With the per-channel re-anchor,
    def is no longer shifted by atk's delta, so it is genuinely capped (not just
    rescued by offsets_for's load-time clamp)."""
    goals = {1: _offs(OFFSET_CAP, -OFFSET_CAP, n_eff=100.0)}
    xg = {1: _offs(-OFFSET_CAP, OFFSET_CAP, n_eff=100.0)}  # opposite-signed extreme
    delta = reanchor(goals, xg)
    blended = blend_offsets(goals, xg, delta)
    assert abs(blended[1]["atk"]) <= OFFSET_CAP + 1e-12
    assert abs(blended[1]["def"]) <= OFFSET_CAP + 1e-12  # the channel that used to breach

    # kappa itself must saturate at 1 once n_eff_xg reaches the full-weight count.
    kappa = min(1.0, math.sqrt(100.0 / FULL_WEIGHT_EFF_MATCHES))
    assert kappa == 1.0


def test_blend_clamps_delta_driven_breach():
    """A multi-team re-anchor delta that does NOT cancel per team can push a
    well-covered team's (x + delta) past the cap; the blend must clamp it. Here
    team A's gap is 0 but team B's large gap drags delta up to 0.075 on each
    channel, so team A's uncapped blend would be 2x OFFSET_CAP -- the clamp is
    the real enforcement, not convexity."""
    goals = {
        1: _offs(OFFSET_CAP, OFFSET_CAP * 0.5, n_eff=100.0),   # team A, gap 0
        2: _offs(OFFSET_CAP, OFFSET_CAP * 0.5, n_eff=100.0),   # team B, big gap below
    }
    xg = {
        1: _offs(OFFSET_CAP, OFFSET_CAP * 0.5, n_eff=100.0),     # A: x == g (gap 0)
        2: _offs(-OFFSET_CAP, -OFFSET_CAP * 0.5, n_eff=100.0),   # B: opposite sign
    }
    delta = reanchor(goals, xg)
    assert delta["atk"] == pytest.approx(OFFSET_CAP)          # (0 + 0.15)/2
    assert delta["def"] == pytest.approx(OFFSET_CAP * 0.5)
    blended = blend_offsets(goals, xg, delta)
    # Team A's raw blend would be g + (x + delta - g) = x + delta = 2*cap; clamped.
    assert blended[1]["atk"] == pytest.approx(OFFSET_CAP)
    assert blended[1]["def"] == pytest.approx(OFFSET_CAP)
    for entry in blended.values():
        assert abs(entry["atk"]) <= OFFSET_CAP + 1e-12
        assert abs(entry["def"]) <= OFFSET_CAP + 1e-12


def test_blend_stays_capped_same_signed_inputs():
    """The realistic case the spec's convexity argument covers: goals and xG
    offsets both already capped with the SAME sign (attack and defence move
    together for a genuinely strong/weak team) stay within the cap post-blend
    for both stats, at any kappa up to 1."""
    goals = {1: _offs(OFFSET_CAP, -OFFSET_CAP, n_eff=100.0)}
    xg = {1: _offs(OFFSET_CAP, -OFFSET_CAP, n_eff=100.0)}
    delta = reanchor(goals, xg)
    assert delta["atk"] == pytest.approx(0.0)
    assert delta["def"] == pytest.approx(0.0)
    blended = blend_offsets(goals, xg, delta)
    assert abs(blended[1]["atk"]) <= OFFSET_CAP + 1e-12
    assert abs(blended[1]["def"]) <= OFFSET_CAP + 1e-12


def test_empty_S_writes_goals_store():
    """No team has any xG coverage -> S is empty -> delta is undefined -> the
    blend must skip the xG nudge entirely and reproduce the goals store
    (the kill-switch: a null xG signal is a no-op, not a crash)."""
    goals = {1: _offs(0.05, -0.01, n_matches=9), 2: _offs(-0.02, 0.02, n_matches=7)}
    xg: dict[int, dict] = {}
    delta = reanchor(goals, xg)
    assert delta == {"atk": 0.0, "def": 0.0}

    blended = blend_offsets(goals, xg, delta)
    assert blended == {
        1: {"atk": goals[1]["atk"], "def": goals[1]["def"], "n_matches": goals[1]["n_matches"]},
        2: {"atk": goals[2]["atk"], "def": goals[2]["def"], "n_matches": goals[2]["n_matches"]},
    }
