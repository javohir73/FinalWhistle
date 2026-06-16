# Unify Simulators on the Dixon-Coles Engine (+ Knockout Fixes) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Monte-Carlo simulators sample scorelines from the same tuned Dixon-Coles engine the match cards use, and fix the knockout shootout + host-advantage models.

**Architecture:** Add one shared scoreline sampler in `ml/models/poisson.py` (`score_cdf` build-once + `sample_scoreline_from_cdf`). Thread the tuned `rho` (keyword-only, **required** — no silent default) through `simulate_group`/`simulate_tournament`, replacing raw `rng.poisson()` draws. Make the penalty shootout a capped, shrinkable `pk_beta` param (ship coin-flip). Ingest the official KO venue schedule so the bracket can apply host advantage by actual venue/team pairing.

**Tech Stack:** Python (NumPy, SQLAlchemy, pytest). Run tests from repo root: `python -m pytest` (config `pytest.ini`, `pythonpath = backend .`).

**Spec:** `docs/superpowers/specs/2026-06-16-unify-simulators-design.md`

**Scorer/engine invariants (keep identical everywhere):** scoreline sampling always goes through `score_cdf`/`sample_scoreline_from_cdf` with the same `MAX_GOALS` as `score_matrix`. `rho` is always passed explicitly from `model_params.json`.

---

### Task 1: Shared scoreline sampler in `poisson.py`

**Files:**
- Modify: `ml/models/poisson.py` (add `import numpy as np` near the top imports; add functions after `score_matrix`, ~line 81)
- Test: `ml/models/poisson_sampler_test.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `ml/models/poisson_sampler_test.py`:
```python
import numpy as np
import pytest

import ml.models.poisson as poisson
from ml.models.poisson import (
    score_cdf, sample_scoreline_from_cdf, sample_scoreline,
    score_matrix, outcome_probabilities,
)


def test_sampler_matches_score_matrix_distribution():
    rng = np.random.default_rng(0)
    lh, la, rho = 1.6, 1.1, -0.06
    cdf = score_cdf(lh, la, rho)
    n = 60000
    hw = d = aw = 0
    for _ in range(n):
        sh, sa = sample_scoreline_from_cdf(rng, cdf)
        if sh > sa: hw += 1
        elif sh == sa: d += 1
        else: aw += 1
    exp_h, exp_d, exp_a = outcome_probabilities(score_matrix(lh, la, rho=rho))
    assert abs(hw / n - exp_h) < 0.02
    assert abs(d / n - exp_d) < 0.02
    assert abs(aw / n - exp_a) < 0.02


def test_cdf_is_normalized_and_monotonic():
    cdf = score_cdf(1.5, 1.2, -0.05)
    assert abs(cdf[-1] - 1.0) < 1e-9
    assert np.all(np.diff(cdf) >= 0)


def test_dixon_coles_raises_draw_rate_vs_plain_poisson():
    _, d_plain, _ = outcome_probabilities(score_matrix(1.3, 1.3, rho=0.0))
    _, d_dc, _ = outcome_probabilities(score_matrix(1.3, 1.3, rho=-0.1))
    assert d_dc > d_plain


def test_score_cdf_raises_on_zero_mass(monkeypatch):
    monkeypatch.setattr(poisson, "score_matrix", lambda *a, **k: [[0.0, 0.0], [0.0, 0.0]])
    with pytest.raises(ValueError):
        score_cdf(1.0, 1.0, 0.0, max_goals=1)


def test_convenience_wrapper_returns_valid_scoreline():
    rng = np.random.default_rng(3)
    sh, sa = sample_scoreline(rng, 1.4, 1.0, -0.05)
    assert 0 <= sh <= poisson.MAX_GOALS and 0 <= sa <= poisson.MAX_GOALS
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/models/poisson_sampler_test.py -q`
Expected: FAIL — `ImportError: cannot import name 'score_cdf'`.

- [ ] **Step 3: Implement the sampler**

In `ml/models/poisson.py`, add `import numpy as np` with the other imports. After `score_matrix` (line ~81), add:
```python
def score_cdf(lam_home, lam_away, rho=0.0, max_goals=MAX_GOALS):
    """Flattened, normalized CDF over the (max_goals+1)^2 Dixon-Coles grid.
    Build ONCE per fixture; reuse across sims via sample_scoreline_from_cdf.
    Guards against NaN/negative cells and raises on a degenerate (zero-mass) grid."""
    flat = np.asarray(score_matrix(lam_home, lam_away, max_goals=max_goals, rho=rho),
                      dtype=float).ravel()
    flat[~np.isfinite(flat)] = 0.0
    np.clip(flat, 0.0, None, out=flat)
    total = flat.sum()
    if total <= 0.0:
        raise ValueError("degenerate score grid: non-positive total mass")
    return np.cumsum(flat / total)


def sample_scoreline_from_cdf(rng, cdf, max_goals=MAX_GOALS):
    """One rng.random() + searchsorted into a prebuilt CDF -> (home, away)."""
    idx = int(np.searchsorted(cdf, rng.random(), side="right"))
    idx = min(idx, len(cdf) - 1)
    width = max_goals + 1
    return idx // width, idx % width


def sample_scoreline(rng, lam_home, lam_away, rho=0.0, max_goals=MAX_GOALS):
    """Convenience wrapper. NOT for per-sim loops (rebuilds the grid each call)."""
    return sample_scoreline_from_cdf(rng, score_cdf(lam_home, lam_away, rho, max_goals), max_goals)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ml/models/poisson_sampler_test.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**
```bash
git add ml/models/poisson.py ml/models/poisson_sampler_test.py
git commit -m "feat(ml): shared Dixon-Coles scoreline sampler (score_cdf + sample_scoreline)"
```

---

### Task 2: Thread `rho` + sampler through `group_sim`

**Files:**
- Modify: `ml/simulate/group_sim.py`
- Modify: `pipeline/generate_predictions.py` (`_simulate_standings`, line ~159)
- Test: `ml/simulate/group_sim_test.py` (create or append)

- [ ] **Step 1: Write the failing tests**

Create `ml/simulate/group_sim_rho_test.py`:
```python
import pytest

from ml.simulate.group_sim import simulate_group, GroupFixture


def test_simulate_group_requires_rho_keyword():
    with pytest.raises(TypeError):
        simulate_group({1: 1500, 2: 1500}, [GroupFixture(1, 2)], n_sims=10)  # no rho=


def test_simulate_group_runs_with_rho():
    res = simulate_group(
        {1: 1600, 2: 1400, 3: 1500, 4: 1500},
        [GroupFixture(1, 2), GroupFixture(3, 4), GroupFixture(1, 3)],
        n_sims=300, seed=1, rho=-0.06,
    )
    assert set(res) == {1, 2, 3, 4}
    assert all(0.0 <= res[t]["qualification_prob"] <= 1.0 for t in res)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/simulate/group_sim_rho_test.py -q`
Expected: FAIL — `simulate_group` currently accepts the call without `rho` (no TypeError) / wrong signature.

- [ ] **Step 3: Implement**

In `ml/simulate/group_sim.py`:
- Update the import (line 17):
```python
from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, expected_goals_from_elo, score_cdf, sample_scoreline_from_cdf
```
- Change the signature (line 45-53) to make `rho` a **required keyword-only** arg:
```python
def simulate_group(
    team_elos: dict[int, float],
    fixtures: list[GroupFixture],
    n_sims: int = 10000,
    seed: int | None = None,
    advance_count: int = 2,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
    *,
    rho: float,
) -> dict[int, dict]:
```
- Replace the lambda precompute (lines 63-73): build a CDF per unplayed fixture instead of storing `(lh, la)`:
```python
    sampled = []  # (home_id, away_id, cdf) for each unplayed fixture
    for fx in fixtures:
        if fx.score is not None:
            _apply_result(base_points, base_gf, base_ga,
                          fx.home_id, fx.away_id, fx.score[0], fx.score[1])
        else:
            lh, la = expected_goals_from_elo(
                team_elos[fx.home_id], team_elos[fx.away_id], home_adv=fx.home_adv,
                base=base, beta=beta,
            )
            sampled.append((fx.home_id, fx.away_id, score_cdf(lh, la, rho)))
```
  (Delete the old `lams = []` line and rename usages to `sampled`.)
- Replace the per-sim draw (lines 85-88):
```python
        for home_id, away_id, cdf in sampled:
            sh, sa = sample_scoreline_from_cdf(rng, cdf)
            _apply_result(points, gf, ga, home_id, away_id, sh, sa)
```

In `pipeline/generate_predictions.py`, update the `simulate_group` call (line 159-162) to pass `rho`:
```python
    results = simulate_group(
        team_elos, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ml/simulate/group_sim_rho_test.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the broader simulate + pipeline tests for regressions**

Run: `python -m pytest ml/simulate -q && python -m pytest backend/ -q -k "predict or standings or pipeline"`
Expected: PASS. (Fix any test that called `simulate_group` without `rho=` by adding `rho=-0.06` or `rho=0.0`.)

- [ ] **Step 6: Commit**
```bash
git add ml/simulate/group_sim.py ml/simulate/group_sim_rho_test.py pipeline/generate_predictions.py
git commit -m "feat(ml): group sim samples from Dixon-Coles engine (rho required)"
```

---

### Task 3: Thread `rho` + sampler through `bracket`

**Files:**
- Modify: `ml/simulate/bracket.py`
- Modify: `pipeline/generate_predictions.py` (`_simulate_tournament`, line ~219)
- Test: `ml/simulate/bracket_rho_test.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ml/simulate/bracket_rho_test.py`:
```python
import pytest

from ml.simulate.bracket import simulate_tournament, GroupFixture


def _full_groups():
    groups, fixtures, elos = {}, {}, {}
    tid = 1
    for letter in "ABCDEFGHIJKL":
        members = [tid, tid + 1, tid + 2, tid + 3]
        groups[letter] = members
        for t in members:
            elos[t] = 1500 + (t % 7) * 20
        fixtures[letter] = [GroupFixture(members[0], members[1]),
                            GroupFixture(members[2], members[3]),
                            GroupFixture(members[0], members[2])]
        tid += 4
    return elos, groups, fixtures


def test_simulate_tournament_requires_rho_keyword():
    elos, groups, fixtures = _full_groups()
    with pytest.raises(TypeError):
        simulate_tournament(elos, groups, fixtures, n_sims=2)  # no rho=


def test_simulate_tournament_runs_with_rho():
    elos, groups, fixtures = _full_groups()
    res = simulate_tournament(elos, groups, fixtures, n_sims=20, seed=2026, rho=-0.06)
    assert len(res) == 48
    total_title = sum(r["win_title"] for r in res.values())
    assert abs(total_title - 1.0) < 0.001  # exactly one champion per sim
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/simulate/bracket_rho_test.py -q`
Expected: FAIL — `simulate_tournament` accepts the no-`rho` call (no TypeError).

- [ ] **Step 3: Implement**

In `ml/simulate/bracket.py`:
- Update import (line 23):
```python
from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, expected_goals_from_elo, score_cdf, sample_scoreline_from_cdf, sample_scoreline
```
- Signature (line 118-126): add required keyword-only `rho`:
```python
def simulate_tournament(
    team_elos: dict[int, float],
    groups: dict[str, list[int]],
    group_fixtures: dict[str, list[GroupFixture]],
    n_sims: int = 2000,
    seed: int | None = 2026,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
    *,
    rho: float,
) -> dict[int, dict]:
```
- In the group precompute (lines 153-158), store a CDF instead of `(lh, la)`:
```python
            else:
                lh, la = expected_goals_from_elo(
                    team_elos[fx.home_id], team_elos[fx.away_id], home_adv=fx.home_adv,
                    base=base, beta=beta,
                )
                lams.append((fx.home_id, fx.away_id, score_cdf(lh, la, rho)))
```
- Group-stage sampling loop (lines 184-185):
```python
            for home_id, away_id, cdf in sampled[letter]:
                sh, sa = sample_scoreline_from_cdf(rng, cdf)
```
- Knockout `play()` (lines 162-172): sample via the shared engine (KO matchups are dynamic, so build per call):
```python
    def play(h: int, a: int) -> int:
        """One knockout match (neutral). Draw -> penalties via Elo logistic."""
        lh, la = expected_goals_from_elo(team_elos[h], team_elos[a], home_adv=0.0,
                                         base=base, beta=beta)
        sh, sa = sample_scoreline(rng, lh, la, rho)
        if sh > sa:
            return h
        if sa > sh:
            return a
        p_home = 1.0 / (1.0 + math.exp(-PK_BETA * (team_elos[h] - team_elos[a])))
        return h if rng.random() < p_home else a
```

In `pipeline/generate_predictions.py`, update the `simulate_tournament` call (line 219-222):
```python
    results = simulate_tournament(
        team_elos, groups, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ml/simulate/bracket_rho_test.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Regression sweep**

Run: `python -m pytest ml/simulate -q`
Expected: PASS. (Add `rho=` to any other `simulate_tournament` call in tests.)

- [ ] **Step 6: Commit**
```bash
git add ml/simulate/bracket.py ml/simulate/bracket_rho_test.py pipeline/generate_predictions.py
git commit -m "feat(ml): bracket sim samples from Dixon-Coles engine (rho required)"
```

---

### Task 4: Penalty shootout — capped, shrinkable `pk_beta` param (ship coin-flip)

**Files:**
- Modify: `ml/models/params.py` (add `pk_beta`)
- Modify: `ml/models/model_params.json` (add `"pk_beta": 0.0`)
- Modify: `ml/simulate/bracket.py` (`play()` + `simulate_tournament` signature; add `fit_pk_beta` + `_shootout_p`)
- Modify: `pipeline/generate_predictions.py` (pass `pk_beta=params.pk_beta`)
- Test: `ml/simulate/shootout_test.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `ml/simulate/shootout_test.py`:
```python
from ml.simulate.bracket import shootout_p, fit_pk_beta


def test_equal_teams_are_a_coin_flip():
    assert abs(shootout_p(1500, 1500, pk_beta=0.002) - 0.5) < 1e-9


def test_favorite_edge_is_capped_well_below_old_value():
    # Old PK_BETA=0.0025 gave ~0.562 for a 100-Elo gap. Capped band [0.45, 0.55].
    p = shootout_p(1600, 1500, pk_beta=0.0025)
    assert p <= 0.55
    assert 0.50 < p  # still favors the stronger side a touch


def test_zero_beta_is_pure_coin_flip():
    assert shootout_p(1700, 1400, pk_beta=0.0) == 0.5


def test_fit_pk_beta_shrinks_toward_zero_on_thin_data():
    # 3 samples is far below the prior weight -> shrunk hard toward 0.
    samples = [(200, True), (150, True), (-100, False)]  # (elo_gap, favorite_won)
    assert abs(fit_pk_beta(samples)) < 0.001


def test_fit_pk_beta_returns_zero_on_empty():
    assert fit_pk_beta([]) == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/simulate/shootout_test.py -q`
Expected: FAIL — `cannot import name 'shootout_p'`.

- [ ] **Step 3: Implement**

In `ml/simulate/bracket.py`, replace the `PK_BETA = 0.0025` line (79) with:
```python
# Penalty shootout: near coin-flip. Strength enters via a small, capped logistic
# (pk_beta loaded from model_params.json; default 0.0 = pure coin-flip). The win
# probability is clamped to PK_BAND so no parameter drift can re-introduce a
# large skill bias (shootouts are empirically close to random).
PK_BAND = (0.45, 0.55)
PK_PRIOR_WEIGHT = 200  # shrinkage strength for fit_pk_beta (samples are thin)


def shootout_p(elo_h: float, elo_a: float, pk_beta: float) -> float:
    """P(home wins the shootout), clamped to PK_BAND."""
    p = 1.0 / (1.0 + math.exp(-pk_beta * (elo_h - elo_a)))
    lo, hi = PK_BAND
    return min(hi, max(lo, p))


def fit_pk_beta(samples: list[tuple[float, bool]]) -> float:
    """Fit a tiny logistic slope from historical penalty-decided knockouts, then
    SHRINK toward 0 by n/(n+PK_PRIOR_WEIGHT). `samples` = (elo_gap favorite-minus-
    underdog, favorite_won). Returns 0.0 when data is empty/thin (-> coin-flip)."""
    n = len(samples)
    if n == 0:
        return 0.0
    # Single Newton step of logistic slope through the origin (intercept fixed 0),
    # which is plenty given we immediately shrink hard toward 0.
    num = den = 0.0
    for gap, won in samples:
        p = 1.0 / (1.0 + math.exp(-0.0 * gap))  # start at beta=0 -> p=0.5
        num += gap * ((1.0 if won else 0.0) - p)
        den += (gap * gap) * p * (1.0 - p)
    raw = (num / den) if den > 0 else 0.0
    return raw * (n / (n + PK_PRIOR_WEIGHT))
```
- Change `simulate_tournament` to accept `pk_beta` (keyword-only, default `0.0` so existing tests/callers stay coin-flip):
```python
    *,
    rho: float,
    pk_beta: float = 0.0,
```
- In `play()`, replace the `p_home` line (171) with:
```python
        return h if rng.random() < shootout_p(team_elos[h], team_elos[a], pk_beta) else a
```

In `ml/models/params.py`:
- Add field to `ModelParams` (after `temperature`): `pk_beta: float = 0.0`
- Add to `DEFAULT_PARAMS`: `pk_beta=0.0,`
- In `load_params`, add: `pk_beta=float(data.get("pk_beta", 0.0)),`

In `ml/models/model_params.json`, add `"pk_beta": 0.0` (ship coin-flip; the historical fit is opt-in via `fit_pk_beta`).

In `pipeline/generate_predictions.py`, update the `simulate_tournament` call to also pass `pk_beta=params.pk_beta`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ml/simulate/shootout_test.py -q && python -m pytest backend/ -q -k params`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ml/simulate/bracket.py ml/models/params.py ml/models/model_params.json pipeline/generate_predictions.py ml/simulate/shootout_test.py
git commit -m "feat(ml): capped, shrinkable penalty-shootout model (ship coin-flip)"
```

---

### Task 5: Ingest the official KO venue schedule (matches 73-104)

**Files:**
- Create: `pipeline/ingest/ko_venues.py` (data map + `apply_ko_venues`)
- Test: `pipeline/ingest/ko_venues_test.py` (create)

Authoritative source (FIFA / Wikipedia 2026 KO schedule). Country is what matters for host advantage; the host-country matches are: **Mexico** = 75, 79, 92; **Canada** = 83, 85, 96; all others **United States**.

- [ ] **Step 1: Write the failing test**

Create `pipeline/ingest/ko_venues_test.py`:
```python
from app.models import Match
from pipeline.ingest.ko_venues import KO_VENUES, apply_ko_venues
from pipeline.ingest.wc26_structure import load_structure


def test_map_covers_all_knockout_matches():
    assert set(KO_VENUES) == set(range(73, 105))
    assert all(c in {"United States", "Mexico", "Canada"} for _, c in KO_VENUES.values())
    # Spot-check the host-country matches.
    assert KO_VENUES[79][1] == "Mexico"
    assert KO_VENUES[85][1] == "Canada"
    assert KO_VENUES[104][1] == "United States"  # final at East Rutherford


def test_apply_ko_venues_populates_country(db_session):
    load_structure(db_session)
    n = apply_ko_venues(db_session)
    assert n == 32
    m79 = db_session.get(Match, 79)
    assert m79.venue_country == "Mexico"
    m104 = db_session.get(Match, 104)
    assert m104.venue_country == "United States"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest pipeline/ingest/ko_venues_test.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `pipeline/ingest/ko_venues.py`:
```python
"""Official 2026 World Cup knockout venue schedule (matches 73-104).

KO Match rows ship with venue_country = NULL; this populates city + country so
the bracket simulator can apply host advantage by actual venue/team pairing.
Source: FIFA / Wikipedia 2026 FIFA World Cup knockout stage. Country is the field
that drives host advantage (USA/Canada/Mexico are the three co-hosts)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Match

# match_no -> (city, country). Host-country KO matches: Mexico {75,79,92},
# Canada {83,85,96}; every other knockout match is in the United States.
KO_VENUES: dict[int, tuple[str, str]] = {
    73: ("Inglewood", "United States"), 74: ("Foxborough", "United States"),
    75: ("Monterrey", "Mexico"), 76: ("Houston", "United States"),
    77: ("East Rutherford", "United States"), 78: ("Arlington", "United States"),
    79: ("Mexico City", "Mexico"), 80: ("Atlanta", "United States"),
    81: ("Santa Clara", "United States"), 82: ("Seattle", "United States"),
    83: ("Toronto", "Canada"), 84: ("Inglewood", "United States"),
    85: ("Vancouver", "Canada"), 86: ("Miami Gardens", "United States"),
    87: ("Kansas City", "United States"), 88: ("Arlington", "United States"),
    89: ("Philadelphia", "United States"), 90: ("Houston", "United States"),
    91: ("East Rutherford", "United States"), 92: ("Mexico City", "Mexico"),
    93: ("Arlington", "United States"), 94: ("Seattle", "United States"),
    95: ("Atlanta", "United States"), 96: ("Vancouver", "Canada"),
    97: ("Foxborough", "United States"), 98: ("Inglewood", "United States"),
    99: ("Miami Gardens", "United States"), 100: ("Kansas City", "United States"),
    101: ("Arlington", "United States"), 102: ("Atlanta", "United States"),
    103: ("Miami Gardens", "United States"), 104: ("East Rutherford", "United States"),
}


def apply_ko_venues(db: Session) -> int:
    """Populate venue_city/venue_country on KO Match rows (id == match_no).
    Returns the number of rows updated."""
    updated = 0
    for match_no, (city, country) in KO_VENUES.items():
        m = db.get(Match, match_no)
        if m is None:
            continue
        m.venue_city = city
        m.venue_country = country
        updated += 1
    db.commit()
    return updated
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest pipeline/ingest/ko_venues_test.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Apply to the local dev DB + commit**

Run (populate the running Postgres so local sims can use it):
```bash
PYTHONPATH=backend:. python -c "from app.db import SessionLocal; from pipeline.ingest.ko_venues import apply_ko_venues; db=SessionLocal(); print('updated', apply_ko_venues(db)); db.close()"
```
Expected: `updated 32`.
```bash
git add pipeline/ingest/ko_venues.py pipeline/ingest/ko_venues_test.py
git commit -m "feat(data): ingest official 2026 WC knockout venue schedule"
```

---

### Task 6: Apply host advantage in the bracket by venue/team pairing

**Files:**
- Modify: `ml/simulate/bracket.py` (`play(mno, h, a)` + `simulate_tournament` accepts `ko_host_by_match`)
- Modify: `pipeline/generate_predictions.py` (`_simulate_tournament` builds the map + passes `home_adv`)
- Test: `ml/simulate/bracket_host_test.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ml/simulate/bracket_host_test.py`:
```python
from ml.simulate.bracket import simulate_tournament
from ml.simulate.bracket_rho_test import _full_groups


def test_host_team_gets_a_knockout_boost_at_its_venue():
    elos, groups, fixtures = _full_groups()
    # Make team 1 a clear group winner and the host of every KO slot it could reach.
    elos[1] = 1700
    ko_host = {mno: 1 for mno in range(73, 105)}  # team 1 hosts every KO match
    base = simulate_tournament(elos, groups, fixtures, n_sims=400, seed=7,
                               rho=-0.06, home_adv=0.0, ko_host_by_match={})
    boosted = simulate_tournament(elos, groups, fixtures, n_sims=400, seed=7,
                                  rho=-0.06, home_adv=80.0, ko_host_by_match=ko_host)
    assert boosted[1]["win_title"] > base[1]["win_title"]


def test_no_host_map_is_neutral():
    elos, groups, fixtures = _full_groups()
    a = simulate_tournament(elos, groups, fixtures, n_sims=200, seed=5,
                            rho=-0.06, home_adv=80.0, ko_host_by_match={})
    b = simulate_tournament(elos, groups, fixtures, n_sims=200, seed=5,
                            rho=-0.06, home_adv=0.0, ko_host_by_match={})
    assert a == b  # empty map -> home_adv never applied -> identical
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/simulate/bracket_host_test.py -q`
Expected: FAIL — `simulate_tournament` has no `home_adv`/`ko_host_by_match` kwargs.

- [ ] **Step 3: Implement**

In `ml/simulate/bracket.py`:
- Extend the signature (keyword-only, defaults preserve current neutral behavior):
```python
    *,
    rho: float,
    pk_beta: float = 0.0,
    home_adv: float = 0.0,
    ko_host_by_match: dict[int, int] | None = None,
) -> dict[int, dict]:
```
- Near the top of the body: `ko_host = ko_host_by_match or {}`
- Change `play` to take the match number and resolve host advantage the same way as `_host_adv` (`+home_adv` to the slot's host team, `-home_adv` to its opponent, `0` if neither):
```python
    def play(mno: int, h: int, a: int) -> int:
        host = ko_host.get(mno)
        adv = home_adv if host == h else -home_adv if host == a else 0.0
        lh, la = expected_goals_from_elo(team_elos[h], team_elos[a], home_adv=adv,
                                         base=base, beta=beta)
        sh, sa = sample_scoreline(rng, lh, la, rho)
        if sh > sa:
            return h
        if sa > sh:
            return a
        return h if rng.random() < shootout_p(team_elos[h], team_elos[a], pk_beta) else a
```
- Update the three `play(...)` call sites to pass the match number:
  - R32 loop (line 226): `w = play(mno, h, a)`
  - R16/QF/SF loop (line 232): `w = play(mno, winners[s1], winners[s2])`
  - Final (line 236): `champion = play(104, winners[FINAL[0]], winners[FINAL[1]])`

In `pipeline/generate_predictions.py`, in `_simulate_tournament`, before the `simulate_tournament(...)` call, build the KO host map from the DB (venue_country -> the co-host team for that country) and pass it through:
```python
    hosts = {t.name: t.id for t in db.query(Team).filter_by(is_host=True).all()}
    country_to_team = {"United States": hosts.get("United States"),
                       "Mexico": hosts.get("Mexico"),
                       "Canada": hosts.get("Canada")}
    ko_host_by_match: dict[int, int] = {}
    for m in db.query(Match).filter(Match.group_id.is_(None), Match.venue_country.isnot(None)).all():
        team_id = country_to_team.get(m.venue_country)
        if team_id is not None:
            ko_host_by_match[m.id] = team_id

    results = simulate_tournament(
        team_elos, groups, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
        pk_beta=params.pk_beta, home_adv=params.home_adv,
        ko_host_by_match=ko_host_by_match,
    )
```
(Confirm `Team` and `Match` are imported in `generate_predictions.py` — `Match` already is; add `Team` if missing.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ml/simulate/bracket_host_test.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add ml/simulate/bracket.py ml/simulate/bracket_host_test.py pipeline/generate_predictions.py
git commit -m "feat(ml): bracket host advantage by knockout venue/team pairing"
```

---

### Task 7: Consistency test + full verification + re-baseline

**Files:**
- Test: `ml/simulate/engine_consistency_test.py` (create)

- [ ] **Step 1: Write the key consistency test**

Create `ml/simulate/engine_consistency_test.py`:
```python
import numpy as np

from ml.models.poisson import score_cdf, sample_scoreline_from_cdf, score_matrix, outcome_probabilities


def test_sampler_wdl_matches_predict_match_engine():
    """The sims and the match cards now speak one language: the sampler's implied
    W/D/L over many draws == the card engine's W/D/L for the same (lambda, rho)."""
    rng = np.random.default_rng(11)
    lh, la, rho = 1.7, 0.9, -0.06
    exp_h, exp_d, exp_a = outcome_probabilities(score_matrix(lh, la, rho=rho))
    cdf = score_cdf(lh, la, rho)
    n = 80000
    hw = d = aw = 0
    for _ in range(n):
        sh, sa = sample_scoreline_from_cdf(rng, cdf)
        if sh > sa: hw += 1
        elif sh == sa: d += 1
        else: aw += 1
    assert abs(hw / n - exp_h) < 0.015
    assert abs(d / n - exp_d) < 0.015
    assert abs(aw / n - exp_a) < 0.015
```

- [ ] **Step 2: Run it**

Run: `python -m pytest ml/simulate/engine_consistency_test.py -q`
Expected: PASS.

- [ ] **Step 3: Full suite**

Run: `python -m pytest -q`
Expected: PASS. Fix any remaining test that called `simulate_group`/`simulate_tournament` without `rho=` (add `rho=0.0` for legacy-behavior tests or `rho=-0.06` to match production).

- [ ] **Step 4: Re-baseline tournament outputs (manual verification)**

Run a real tournament sim against the dev DB and confirm the expected qualitative shifts (more draws/ties, penalty near coin-flip, hosts boosted in KO):
```bash
PYTHONPATH=backend:. python -c "
from app.db import SessionLocal
from pipeline.generate_predictions import _simulate_tournament
from ml.models.params import load_params
db=SessionLocal()
n=_simulate_tournament(db, n_sims=2000, params=load_params())
print('teams with odds written:', n)
db.close()
"
```
Expected: writes odds for 48 teams without error; spot-check that a co-host's `win_title` rose vs the old run and that no probability is NaN.

- [ ] **Step 5: Commit**
```bash
git add ml/simulate/engine_consistency_test.py
git commit -m "test(ml): consistency — sampler W/D/L matches the card engine"
```

- [ ] **Step 6: Finish the branch**

Use `superpowers:finishing-a-development-branch`. Note: tournament numbers (qualification %, win-title %) intentionally shift — re-baseline cached leaderboard/odds and explain the change.

---

## Notes for the implementer
- **Run all commands from the repo root** (`pytest.ini` sets `pythonpath`).
- `rho` is **required keyword-only** in both simulators — if a test or caller breaks with `TypeError: missing ... 'rho'`, that's the guardrail working; add `rho=` (0.0 for legacy, `params.rho`/`-0.06` for production behavior).
- Keep the scoreline path going through `score_cdf`/`sample_scoreline_from_cdf` everywhere — never reintroduce a raw `rng.poisson()` scoreline draw.
- `pk_beta` ships at `0.0` (coin-flip); the `fit_pk_beta` helper is the opt-in "tiny fitted edge" for when penalty-decided-KO data is wired up.
- Temperature stays OUT of the sampler (it scales a W/D/L triple, not a single scoreline).
