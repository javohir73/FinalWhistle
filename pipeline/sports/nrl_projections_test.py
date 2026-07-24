"""Tests for the Wave 1 finals-projections Monte Carlo
(pipeline/sports/nrl_projections.py)."""
import random
from datetime import datetime, timezone

from app.models import NrlProjection, SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams, predict
from pipeline.sports.nrl_projections import load_season_state, run, simulate

PARAMS = NrlParams()


def test_simulate_with_no_remaining_fixtures_is_deterministic():
    """No remaining matches -> every run ranks the SAME starting standings,
    so each team's top8/top4/minor_premiership must be exactly 0.0 or 1.0."""
    team_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    starting = {t: {"points": (10 - t) * 2, "diff": (10 - t) * 10} for t in team_ids}
    probs = simulate(team_ids, starting, remaining=[], elos={}, params=PARAMS, n_runs=50)

    # Team 1 has the most points -> always rank 1 -> minor premiers every run.
    assert probs[1]["minor_premiership"] == 1.0
    assert probs[1]["top8"] == 1.0
    assert probs[1]["top4"] == 1.0
    # Team 9 has the fewest points -> always last (rank 9) -> never top 8.
    assert probs[9]["top8"] == 0.0
    assert probs[9]["minor_premiership"] == 0.0


def test_simulate_heavy_favourite_wins_minor_premiership_almost_always():
    """With only 2 teams, top8/top4 are trivially 1.0 for both (any rank in a
    2-team field is <= 8 and <= 4) -- minor_premiership (rank == 1) is the
    only metric that's actually selective between exactly two candidates."""
    team_ids = [1, 2]
    starting = {1: {"points": 0, "diff": 0}, 2: {"points": 0, "diff": 0}}
    elos = {1: 1900.0, 2: 1100.0}  # enormous gap -> team 1 wins almost every sim
    remaining = [
        SportMatch(id=1, sport="nrl", season=2026, round=20, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled")
    ]
    probs = simulate(team_ids, starting, remaining, elos, PARAMS,
                      n_runs=500, rng=random.Random(42))
    assert probs[1]["minor_premiership"] > 0.95
    assert probs[1]["top8"] == 1.0  # trivial in a 2-team field, sanity check only


def test_simulate_zero_runs_returns_zeroed_counts():
    probs = simulate([1, 2], {}, [], {}, PARAMS, n_runs=0)
    assert probs == {1: {"top8": 0, "top4": 0, "minor_premiership": 0},
                      2: {"top8": 0, "top4": 0, "minor_premiership": 0}}


def test_run_writes_and_replaces_projection_rows(db_session):
    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db_session.add_all([a, b]); db_session.flush()
    db_session.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                              kickoff_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id,
                              status="finished", score_home=20, score_away=10))
    db_session.add(SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                              kickoff_utc=datetime(2026, 3, 8, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.commit()

    n = run(db_session, season=2026, n_runs=25, rng=random.Random(1))
    assert n == 2
    rows = db_session.query(NrlProjection).all()
    assert {r.team for r in rows} == {"Storm", "Eels"}
    assert all(0.0 <= r.top8 <= 1.0 for r in rows)

    # Re-run must REPLACE, not accumulate.
    run(db_session, season=2026, n_runs=25, rng=random.Random(2))
    assert db_session.query(NrlProjection).count() == 2


def test_run_with_no_nrl_data_writes_nothing(db_session):
    assert run(db_session) == 0


# --- Slice 3: `forced` outcomes + `load_season_state` -----------------------

def test_simulate_forced_outcome_swings_top8_probability():
    """A team forced to beat a rival for the last finals spot in EVERY
    remaining fixture must end up strictly more likely to make the top 8
    than the same team forced to lose those same fixtures -- the whole
    point of `forced`. 7 teams start miles clear on points (always top 7
    regardless), so only team 1 vs team 2 contest the 8th spot."""
    team_ids = list(range(1, 10))
    starting = {t: {"points": 100, "diff": 0} for t in team_ids}
    starting[1] = {"points": 0, "diff": 0}
    starting[2] = {"points": 2, "diff": 0}
    remaining = [
        SportMatch(id=100, sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled"),
        SportMatch(id=101, sport="nrl", season=2026, round=2, match_no=2,
                   home_team_id=1, away_team_id=2, status="scheduled"),
    ]
    probs_win = simulate(team_ids, starting, remaining, elos={}, params=PARAMS,
                          n_runs=100, rng=random.Random(1),
                          forced={100: "home", 101: "home"})  # team 1 sweeps team 2
    probs_loss = simulate(team_ids, starting, remaining, elos={}, params=PARAMS,
                           n_runs=100, rng=random.Random(1),
                           forced={100: "away", 101: "away"})  # team 1 loses both
    assert probs_win[1]["top8"] > probs_loss[1]["top8"]
    # Fully determined (both fixtures forced, no other team has a remaining
    # match) -- team 1 ends on 4 points (in) vs 0 points (out), no diff tie
    # possible against team 2's 2/6, so the swing is the full 1.0 -> 0.0.
    assert probs_win[1]["top8"] == 1.0
    assert probs_loss[1]["top8"] == 0.0


def test_simulate_fully_forced_season_yields_deterministic_ladder():
    """When every remaining fixture is forced, the final standings never
    depend on the RNG -- each team's probabilities collapse to exactly 0.0
    or 1.0, same shape as the no-remaining-fixtures case above."""
    team_ids = list(range(1, 10))
    starting = {t: {"points": 100, "diff": 0} for t in team_ids}
    starting[1] = {"points": 0, "diff": 0}
    starting[2] = {"points": 2, "diff": 0}
    remaining = [
        SportMatch(id=100, sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled"),
        SportMatch(id=101, sport="nrl", season=2026, round=2, match_no=2,
                   home_team_id=1, away_team_id=2, status="scheduled"),
    ]
    probs = simulate(team_ids, starting, remaining, elos={}, params=PARAMS,
                      n_runs=100, rng=random.Random(7), forced={100: "home", 101: "home"})
    for t in team_ids:
        for key in ("top8", "top4", "minor_premiership"):
            assert probs[t][key] in (0.0, 1.0)


def test_simulate_empty_forced_dict_matches_unforced_behavior():
    """Empty picks must equal the unconditioned simulation -- `forced={}`
    and `forced=None` roll the exact same RNG sequence, so two independently
    seeded runs are byte-for-byte identical."""
    team_ids = [1, 2]
    starting = {1: {"points": 0, "diff": 0}, 2: {"points": 0, "diff": 0}}
    elos = {1: 1900.0, 2: 1100.0}
    remaining = [
        SportMatch(id=1, sport="nrl", season=2026, round=20, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled")
    ]
    probs_none = simulate(team_ids, starting, remaining, elos, PARAMS,
                           n_runs=500, rng=random.Random(42), forced=None)
    probs_empty = simulate(team_ids, starting, remaining, elos, PARAMS,
                            n_runs=500, rng=random.Random(42), forced={})
    assert probs_none == probs_empty


def test_simulate_track_expected_adds_keys_only_when_requested():
    """`track_expected` is opt-in and additive -- the default 3-key shape
    (needed for nrl_projections_test.py's exact-dict-equality assertions
    above) must be untouched when it isn't passed."""
    team_ids = [1, 2]
    starting = {1: {"points": 0, "diff": 0}, 2: {"points": 0, "diff": 0}}
    remaining = [
        SportMatch(id=1, sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled")
    ]
    default = simulate(team_ids, starting, remaining, elos={}, params=PARAMS,
                        n_runs=50, rng=random.Random(3))
    assert set(default[1].keys()) == {"top8", "top4", "minor_premiership"}

    tracked = simulate(team_ids, starting, remaining, elos={}, params=PARAMS,
                        n_runs=50, rng=random.Random(3), track_expected=True)
    assert set(tracked[1].keys()) == {
        "top8", "top4", "minor_premiership", "expected_points", "expected_remaining_wins",
    }
    assert tracked[1]["expected_points"] >= 0
    assert 0 <= tracked[1]["expected_remaining_wins"] <= 1  # exactly one match remains


def test_simulate_forced_pick_leaves_uninvolved_team_unchanged_with_common_random_numbers():
    """Common random numbers (Slice 3 fix): the conditional-projections API
    seeds baseline (forced={}) and every conditioned request from the SAME
    seed (backend/app/api/nrl_intel.py's `_seed_for` no longer folds `picks`
    into the seed), and every match consumes EXACTLY one rng.random() roll
    plus one rng.gauss() margin draw every run -- regardless of whether it's
    forced, and regardless of whether the outcome is a draw (the margin
    draw simply goes unused for a draw) -- so the two runs' rng streams stay
    call-for-call aligned for every fixture NOT in `forced`, even across the
    real model's p_draw > 0. A team playing only in an unpicked fixture must
    therefore land on the EXACT same probabilities whether or not some OTHER
    match is forced, proving a delta the frontend shows for an uninvolved
    team is real cascade signal, never independent-2000-run-sample noise.
    Uses the real (non-zero) `PARAMS.p_draw` on purpose -- an earlier,
    incomplete version of this fix (roll consumed for a forced match, but
    the margin draw still skipped on a real draw) left a residual desync
    exactly when a draw was possible, which this asserts is now gone.

    Teams 1/2 (the forced match) and teams 3/4 (the uninvolved match) are
    kept in separate, non-overlapping points brackets -- with 5 filler teams
    (fixed points, no remaining fixtures) buffering between them -- so
    ranking competition can never let team1's forced result bump team3/4's
    rank: any residual delta there could ONLY be RNG desync, never a real
    ripple effect, unlike the closer-together contest
    test_simulate_forced_outcome_swings_top8_probability above exercises."""
    team_ids = list(range(1, 10))
    starting = {t: {"points": 50, "diff": 0} for t in team_ids}  # 5 filler teams, no remaining matches
    starting[1] = {"points": 0, "diff": 0}
    starting[2] = {"points": 0, "diff": 0}
    starting[3] = {"points": 200, "diff": 0}
    starting[4] = {"points": 200, "diff": 0}
    remaining = [
        SportMatch(id=100, sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled"),
        SportMatch(id=101, sport="nrl", season=2026, round=1, match_no=2,
                   home_team_id=3, away_team_id=4, status="scheduled"),
    ]
    elos = {1: 1550.0, 2: 1450.0, 3: 1600.0, 4: 1400.0}

    baseline = simulate(team_ids, starting, remaining, elos, PARAMS,
                        n_runs=2000, rng=random.Random("crn-seed"), forced={})
    forced = simulate(team_ids, starting, remaining, elos, PARAMS,
                       n_runs=2000, rng=random.Random("crn-seed"), forced={100: "home"})

    # Team 1 (forced) moves -- the whole point of `forced`.
    assert forced[1]["top8"] != baseline[1]["top8"]
    # Team 3/4's minor_premiership is genuinely selective (0 < p < 1, always
    # rank 1 or 2 between just the two of them) -- not trivially 0/1 -- yet
    # must land EXACTLY on the baseline given the points-bracket isolation.
    assert 0.0 < baseline[3]["minor_premiership"] < 1.0
    for t in (3, 4):
        for key in ("top8", "top4", "minor_premiership"):
            assert forced[t][key] == baseline[t][key]


def _simulate_predict_not_hoisted(team_ids, starting, remaining, elos, params, n_runs, rng):
    """Reference copy of simulate()'s pre-hoist inner loop -- predict() is
    called fresh for every (fixture, run) pair instead of once per fixture --
    used ONLY by test_simulate_predict_hoist_matches_unhoisted_seeded_output
    below to prove the hoist is pure refactoring. predict() never touches
    `rng`, so this differs from simulate() in nothing but WHEN predict() is
    called; every rng.random()/rng.gauss() call happens in the identical
    order, so the two must produce bit-identical output for the same seed."""
    counts = {t: {"top8": 0, "top4": 0, "minor_premiership": 0} for t in team_ids}
    points_total = {t: 0.0 for t in team_ids}
    wins_total = {t: 0 for t in team_ids}
    for _ in range(n_runs):
        points = {t: starting.get(t, {}).get("points", 0) for t in team_ids}
        diff = {t: starting.get(t, {}).get("diff", 0) for t in team_ids}
        wins = {t: 0 for t in team_ids}
        for m in remaining:
            if m.home_team_id not in points or m.away_team_id not in points:
                continue
            out = predict(elos.get(m.home_team_id, 1500.0), elos.get(m.away_team_id, 1500.0), params)
            roll = rng.random()
            if roll < out["p_home"]:
                outcome = "home"
            elif roll < out["p_home"] + out["p_draw"]:
                outcome = "draw"
            else:
                outcome = "away"
            margin = max(1.0, abs(rng.gauss(out["expected_margin"], params.margin_sigma)))
            if outcome == "draw":
                points[m.home_team_id] += 1
                points[m.away_team_id] += 1
                continue
            if outcome == "home":
                points[m.home_team_id] += 2
                diff[m.home_team_id] += margin
                diff[m.away_team_id] -= margin
                wins[m.home_team_id] += 1
            else:
                points[m.away_team_id] += 2
                diff[m.away_team_id] += margin
                diff[m.home_team_id] -= margin
                wins[m.away_team_id] += 1
        ranked = sorted(team_ids, key=lambda t: (-points[t], -diff[t], t))
        for rank, t in enumerate(ranked, start=1):
            if rank <= 8:
                counts[t]["top8"] += 1
            if rank <= 4:
                counts[t]["top4"] += 1
            if rank == 1:
                counts[t]["minor_premiership"] += 1
        for t in team_ids:
            points_total[t] += points[t]
            wins_total[t] += wins[t]
    result = {t: {k: v / n_runs for k, v in c.items()} for t, c in counts.items()}
    for t in team_ids:
        result[t]["expected_points"] = points_total[t] / n_runs
        result[t]["expected_remaining_wins"] = wins_total[t] / n_runs
    return result


def test_simulate_predict_hoist_matches_unhoisted_seeded_output():
    """Hoisting predict() out of the run loop (perf fix, DoS blast-radius
    reduction on nrl_intel.py's per-request path) must not change a single
    seeded output byte -- predict() never touches the rng, so precomputing
    it once per fixture instead of once per (fixture, run) is pure
    refactoring, verified here against a reference copy of the old
    call-every-run shape (`_simulate_predict_not_hoisted` above)."""
    team_ids = [1, 2, 3]
    starting = {1: {"points": 0, "diff": 0}, 2: {"points": 0, "diff": 0}, 3: {"points": 0, "diff": 0}}
    elos = {1: 1620.0, 2: 1480.0, 3: 1500.0}
    remaining = [
        SportMatch(id=1, sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled"),
        SportMatch(id=2, sport="nrl", season=2026, round=2, match_no=1,
                   home_team_id=2, away_team_id=3, status="scheduled"),
        SportMatch(id=3, sport="nrl", season=2026, round=3, match_no=1,
                   home_team_id=3, away_team_id=1, status="scheduled"),
    ]
    hoisted = simulate(team_ids, starting, remaining, elos, PARAMS,
                        n_runs=200, rng=random.Random(99), track_expected=True)
    reference = _simulate_predict_not_hoisted(team_ids, starting, remaining, elos, PARAMS,
                                               n_runs=200, rng=random.Random(99))
    assert hoisted == reference


def test_load_season_state_returns_none_when_no_data(db_session):
    assert load_season_state(db_session) is None
    assert load_season_state(db_session, season=2026) is None


def test_load_season_state_loads_run_inputs_for_a_season(db_session):
    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db_session.add_all([a, b]); db_session.flush()
    db_session.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                              kickoff_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id,
                              status="finished", score_home=20, score_away=10))
    db_session.add(SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                              kickoff_utc=datetime(2026, 3, 8, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.commit()

    state = load_season_state(db_session, season=2026)
    assert state is not None
    season, team_ids, teams, starting, remaining, elos, params = state
    assert season == 2026
    assert team_ids == sorted([a.id, b.id])
    assert teams == {a.id: "Storm", b.id: "Eels"}
    assert starting[a.id]["points"] == 2  # Storm won the one finished match
    assert len(remaining) == 1
    assert isinstance(params, NrlParams)


def test_load_season_state_orders_remaining_matches_deterministically(db_session):
    """simulate() consumes its seeded rng once per fixture in `remaining`
    order, so the conditional-projections API's "identical request ->
    identical body" cache-determinism promise depends on `remaining` coming
    back in a FIXED order -- not whatever the DB's un-ordered season_matches
    query happens to return (unspecified by SQL, and can shift on Postgres
    after e.g. a status UPDATE). Insert fixtures out of (round, match_no)
    order on purpose so this fails if the query's ORDER BY is ever dropped."""
    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db_session.add_all([a, b]); db_session.flush()
    db_session.add(SportMatch(sport="nrl", season=2026, round=3, match_no=1,
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.add(SportMatch(sport="nrl", season=2026, round=1, match_no=2,
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.add(SportMatch(sport="nrl", season=2026, round=2, match_no=1,
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.commit()

    state = load_season_state(db_session, season=2026)
    assert state is not None
    _, _, _, _, remaining, _, _ = state
    assert [(m.round, m.match_no) for m in remaining] == [(1, 2), (2, 1), (3, 1)]
