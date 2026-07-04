"""Tests for the offline per-team attack/defence MLE fitter (FR-5.1/FR-5.2).

The fitter learns time-decayed per-team offsets over enriched historical rows
(same shape as pipeline/backtest_data.build_enriched_rows) and writes
ml/models/team_offsets.json keyed by team NAME. It must be deterministic,
leak-free at its cutoff date, and honor the shrink/cap policy.
"""
import json
import math
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ml.models.params import DEFAULT_PARAMS
from ml.models.team_offsets import FULL_WEIGHT_EFF_MATCHES, OFFSET_CAP
from pipeline.fit_attack_defence import (
    DEFAULT_HALF_LIFE_DAYS,
    decay_weight,
    fit_and_write,
    fit_offsets,
)

_REF = date(2026, 1, 1)


def _row(home, away, sh, sa, d, pre_home=1600.0, pre_away=1600.0):
    return {
        "home_id": home, "away_id": away,
        "pre_home": pre_home, "pre_away": pre_away,
        "is_neutral": True, "competition": "Friendly",
        "score_home": sh, "score_away": sa, "date": d,
    }


def _round_robin(scores_for_team_1, others_score=(1, 1), n_rounds=20):
    """Team 1 plays teams 2..9 with fixed scorelines; teams 2..9 also play each
    other so every team has data. All equal-Elo neutral matches, recent dates."""
    rows = []
    for k in range(n_rounds):
        d = date(2025, 1 + (k % 12), 1 + (k % 27))
        for opp in range(2, 10):
            sh, sa = scores_for_team_1
            rows.append(_row(1, opp, sh, sa, d))
        for i in range(2, 9):
            rows.append(_row(i, i + 1, others_score[0], others_score[1], d))
    return rows


def test_decay_weight_halves_per_half_life():
    assert decay_weight(_REF, _REF, 730) == pytest.approx(1.0)
    one_hl = date(2024, 1, 2)  # 730 days before 2026-01-01
    assert decay_weight(one_hl, _REF, 730) == pytest.approx(0.5)
    two_hl = date(2022, 1, 2)  # 1460 days before
    assert decay_weight(two_hl, _REF, 730) == pytest.approx(0.25)
    # Per-day granularity: one day of age already discounts.
    assert decay_weight(date(2025, 12, 31), _REF, 730) == pytest.approx(0.5 ** (1 / 730))


def test_default_half_life_in_two_to_four_year_range():
    assert 2 * 365 <= DEFAULT_HALF_LIFE_DAYS <= 4 * 365


def _poisson_ll(rows, offs):
    """Log-likelihood of rows' scorelines under baseline lambdas × offsets."""
    from ml.models.poisson import expected_goals_from_elo, poisson_pmf

    zero = {"atk": 0.0, "def": 0.0}
    total = 0.0
    for r in rows:
        mu_h, mu_a = expected_goals_from_elo(
            r["pre_home"], r["pre_away"], 0.0, DEFAULT_PARAMS.base, DEFAULT_PARAMS.beta
        )
        eh = offs.get(r["home_id"], zero)
        ea = offs.get(r["away_id"], zero)
        lam_h = mu_h * math.exp(eh["atk"] + ea["def"])
        lam_a = mu_a * math.exp(ea["atk"] + eh["def"])
        total += math.log(poisson_pmf(r["score_home"], lam_h))
        total += math.log(poisson_pmf(r["score_away"], lam_a))
    return total


def test_fit_recovers_attack_and_defence_direction():
    """Team 1 always wins 3-0 on equal Elo → clearly positive attack offset and
    clearly negative (stingy) defence offset — and the fitted offsets must beat
    zero offsets on the Poisson likelihood of the training data (MLE sanity)."""
    rows = _round_robin((3, 0))
    offs = fit_offsets(rows, _REF, params=DEFAULT_PARAMS)
    assert offs[1]["atk"] > 0.02
    assert offs[1]["def"] < -0.02
    assert _poisson_ll(rows, offs) > _poisson_ll(rows, {})


def test_fit_recovers_low_scoring_team():
    """Team 1 always draws 0-0 → negative attack (scores less than Elo expects)."""
    offs = fit_offsets(_round_robin((0, 0)), _REF, params=DEFAULT_PARAMS)
    assert offs[1]["atk"] < -0.02


def test_fit_is_deterministic():
    rows = _round_robin((2, 1))
    a = fit_offsets(rows, _REF, params=DEFAULT_PARAMS)
    b = fit_offsets(rows, _REF, params=DEFAULT_PARAMS)
    assert a == b  # bit-identical, not approximately equal


def test_offsets_respect_hard_cap():
    """Even absurd scorelines cannot push any offset past the policy cap."""
    offs = fit_offsets(_round_robin((9, 0)), _REF, params=DEFAULT_PARAMS)
    for entry in offs.values():
        assert abs(entry["atk"]) <= OFFSET_CAP + 1e-12
        assert abs(entry["def"]) <= OFFSET_CAP + 1e-12


def test_low_match_count_shrinks_toward_zero():
    """A team with 2 extreme matches gets at most the √(n_eff/full) sliver."""
    rows = _round_robin((1, 1)) + [
        _row(99, 2, 8, 0, date(2025, 6, 1)),
        _row(99, 3, 8, 0, date(2025, 6, 8)),
    ]
    offs = fit_offsets(rows, _REF, params=DEFAULT_PARAMS)
    n_eff = offs[99]["n_eff"]
    assert n_eff < FULL_WEIGHT_EFF_MATCHES
    limit = OFFSET_CAP * math.sqrt(n_eff / FULL_WEIGHT_EFF_MATCHES)
    assert abs(offs[99]["atk"]) <= limit + 1e-12
    assert abs(offs[99]["def"]) <= limit + 1e-12


def test_time_decay_downweights_ancient_form():
    """A team whose 3-0 wins are all a decade old keeps a smaller attack offset
    under a 2-year half-life than under an effectively flat (huge) half-life."""
    old = [r | {"date": date(2014, 3, 1)} for r in _round_robin((3, 0), n_rounds=10)]
    recent = [
        _row(1, opp, 1, 1, date(2025, 5, 1 + opp)) for opp in range(2, 10)
    ] * 4
    rows = old + recent
    decayed = fit_offsets(rows, _REF, half_life_days=730, params=DEFAULT_PARAMS)
    flat = fit_offsets(rows, _REF, half_life_days=10_000_000, params=DEFAULT_PARAMS)
    assert decayed[1]["atk"] < flat[1]["atk"]


def test_cutoff_is_strict_no_leak():
    """Rows on/after ref_date must not influence the fit (walk-forward safety)."""
    before = _round_robin((1, 1))
    on_and_after = [
        _row(1, opp, 9, 0, date(2026, 1, 1)) for opp in range(2, 10)
    ] + [_row(1, opp, 9, 0, date(2026, 2, 1)) for opp in range(2, 10)]
    offs = fit_offsets(before + on_and_after, _REF, params=DEFAULT_PARAMS)
    assert offs == fit_offsets(before, _REF, params=DEFAULT_PARAMS)
    assert fit_offsets(on_and_after, _REF, params=DEFAULT_PARAMS) == {}


def test_fit_and_write_writes_json_keyed_by_team_name(db_session, tmp_path):
    from app.models import HistoricalMatch, Team

    names = ["Brazil", "Germany", "Japan", "Morocco"]
    teams = [Team(name=n, is_host=False) for n in names]
    db_session.add_all(teams)
    db_session.flush()
    ids = [t.id for t in teams]
    k = 0
    for yr in (2023, 2024, 2025):
        for m in range(1, 13):
            for i in range(4):
                j = (i + 1 + k) % 4
                if j == i:
                    continue
                db_session.add(HistoricalMatch(
                    date=datetime(yr, m, 1 + (k % 25), tzinfo=timezone.utc),
                    team_a_id=ids[i], team_b_id=ids[j],
                    score_a=(2 if i == 0 else 1), score_b=(0 if j == 0 else 1),
                    competition="Friendly", is_neutral=True,
                ))
                k += 1
    db_session.commit()

    out = tmp_path / "team_offsets.json"
    summary = fit_and_write(db_session, out_path=out, params=DEFAULT_PARAMS)
    data = json.loads(out.read_text())
    assert set(data) <= set(names)
    for entry in data.values():
        assert set(entry) == {"atk", "def", "n_matches"}
        assert isinstance(entry["n_matches"], int)
        assert abs(entry["atk"]) <= OFFSET_CAP
        assert abs(entry["def"]) <= OFFSET_CAP
    # Brazil (ids[0]) wins 2-0 whenever it plays — attack must lean positive.
    assert data["Brazil"]["atk"] > 0
    assert summary["teams"] == len(data)
    assert summary["matches"] > 0


def test_goal_keys_default_is_bit_identical():
    """The goal_keys refactor is a no-op on the served path: omitting it must
    equal passing the explicit default (score_home/score_away) bit-for-bit."""
    rows = _round_robin((2, 1))
    default_call = fit_offsets(rows, _REF, params=DEFAULT_PARAMS)
    explicit_call = fit_offsets(
        rows, _REF, params=DEFAULT_PARAMS, goal_keys=("score_home", "score_away")
    )
    assert default_call == explicit_call


def test_goal_keys_reads_xg_fields():
    """The SAME fitter machinery must read an alternate goal source (xg_a/xg_b)
    when goal_keys points at it, producing offsets distinct from the goals fit
    on the same fixtures — proving the parametrization actually took effect."""
    rows = _round_robin((2, 1))
    rows = [r | {"xg_a": 3.5, "xg_b": 0.2} for r in rows]
    goals_offs = fit_offsets(rows, _REF, params=DEFAULT_PARAMS)
    xg_offs = fit_offsets(
        rows, _REF, params=DEFAULT_PARAMS, goal_keys=("xg_a", "xg_b")
    )
    assert goals_offs != xg_offs


def test_fitter_never_imported_by_web_request_path():
    """FR-5.1: the MLE fit runs offline only. Importing the FastAPI app must not
    pull in the fitter (or its transitive pipeline deps) — checked in a clean
    interpreter so this test is immune to import-order pollution."""
    repo = Path(__file__).resolve().parents[1]
    code = (
        "import sys; import app.main; "
        "assert 'pipeline.fit_attack_defence' not in sys.modules"
    )
    env_path = f"{repo / 'backend'}:{repo}"
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=repo, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": env_path},
    )
    assert res.returncode == 0, res.stderr
