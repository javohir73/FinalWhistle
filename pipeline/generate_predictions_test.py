"""Tests for prediction generation + §17 payload shape (task 3.8/3.9)."""
from datetime import datetime, timezone

from app.models import Match, Prediction, Standing, Team
from pipeline.generate_predictions import build_payload, generate_predictions
from pipeline.ingest.wc26_structure import load_structure


def _set_elos(db):
    """Give every loaded team a plausible Elo so cold-start isn't triggered."""
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40  # spread 1500..1940
    db.commit()


def test_payload_matches_prd_section_17_shape(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    payload = build_payload(db_session, match, "poisson-elo-v0.1")

    # Top-level keys from PRD §17
    for key in [
        "match_id", "model_version", "generated_at", "teams", "is_neutral",
        "probabilities", "predicted_score", "confidence", "reasons",
        "top_features", "head_to_head", "odds_comparison", "disclaimer",
    ]:
        assert key in payload, f"missing key {key}"

    probs = payload["probabilities"]
    assert abs(probs["home_win"] + probs["draw"] + probs["away_win"] - 1.0) < 0.01
    assert payload["confidence"] in {"High", "Medium", "Low"}
    assert len(payload["reasons"]) >= 3
    assert payload["odds_comparison"] == {"available": False}


def test_build_payload_applies_calibrator_blob_end_to_end(db_session):
    """A vector-scaling blob with a positive draw bias must lift the served draw
    probability through the whole card path: blob -> ModelParams.calibrator ->
    calibrate() inside predict_match -> §17 payload. Guards the build_payload
    forwarding line (calibrator=params.calibrator) that wires production serving
    to the calibrator — if it were dropped, this is the only test that fails.

    Both payloads use ModelParams built from the same base/beta/rho/home_adv/
    temperature so ONLY the calibrator differs. The baseline is constructed with
    calibrator=None rather than via load_params(), keeping the test hermetic from
    whatever model_params.json happens to hold on disk."""
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS, ModelParams

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )

    # Identical engine params for both; only the calibrator field differs.
    baseline = replace(DEFAULT_PARAMS, version="poisson-elo-v0.1", calibrator=None)
    assert isinstance(baseline, ModelParams) and baseline.calibrator is None
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 1.0, 0.0]}
    lifted = replace(baseline, calibrator=blob)

    base = build_payload(db_session, match, "poisson-elo-v0.1", params=baseline)
    cal = build_payload(db_session, match, "poisson-elo-v0.1", params=lifted)

    assert cal["probabilities"]["draw"] > base["probabilities"]["draw"]
    p = cal["probabilities"]
    assert abs(p["home_win"] + p["draw"] + p["away_win"] - 1.0) < 0.01


def test_generate_predictions_writes_rows(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    summary = generate_predictions(db_session, n_sims=300)

    assert summary["matches_predicted"] == 72  # all group matches
    assert summary["groups_simulated"] == 12
    assert db_session.query(Prediction).filter_by(is_shadow=False).count() == 72
    # Every production row gets its shadow twin (FR-4.4) — never more, never fewer.
    assert db_session.query(Prediction).filter_by(is_shadow=True).count() == 72

    # Standings: 48 teams, qualification probs sum to ~2 per group.
    standings = db_session.query(Standing).all()
    assert len(standings) == 48


def test_generate_predictions_covers_drawn_knockout_matches(db_session):
    """KO matches with both teams drawn must get predictions too, so the bracket's
    match-detail pages resolve instead of 404'ing. Undetermined KO rows (no teams
    yet) must stay unpredicted."""
    load_structure(db_session)
    _set_elos(db_session)
    # Draw two distinct teams into an R32 placeholder (match_no 73).
    ko = db_session.query(Match).filter(Match.match_no == 73).one()
    two = db_session.query(Team).order_by(Team.id).limit(2).all()
    ko.team_home_id, ko.team_away_id = two[0].id, two[1].id
    db_session.commit()

    generate_predictions(db_session, n_sims=300)

    assert db_session.query(Prediction).filter_by(match_id=ko.id).first() is not None, (
        "a drawn knockout match must be predicted"
    )
    # An undetermined KO row (still teamless) must NOT be predicted.
    empty = db_session.query(Match).filter(Match.match_no == 104).one()
    assert db_session.query(Prediction).filter_by(match_id=empty.id).first() is None


def test_finished_matches_feed_standings_as_facts(db_session):
    """Real results must flow into projected standings: a team that has already
    won all three of its games sits on exactly 9 points with qualification
    locked at 1.0 — regardless of what the model would have predicted."""
    load_structure(db_session)
    _set_elos(db_session)

    from app.models import Group

    group = db_session.query(Group).first()
    matches = db_session.query(Match).filter_by(group_id=group.id).all()
    members = sorted({m.team_home_id for m in matches} | {m.team_away_id for m in matches})
    elo = {t: db_session.get(Team, t).elo_rating for t in members}
    target = min(members, key=lambda t: elo[t])   # weakest wins everything
    loser = max(members, key=lambda t: elo[t])    # strongest loses everything

    for m in matches:
        m.status = "finished"
        if target in (m.team_home_id, m.team_away_id):
            m.score_home, m.score_away = (1, 0) if m.team_home_id == target else (0, 1)
        elif loser in (m.team_home_id, m.team_away_id):
            m.score_home, m.score_away = (0, 1) if m.team_home_id == loser else (1, 0)
        else:
            m.score_home, m.score_away = 0, 0
    db_session.commit()

    generate_predictions(db_session, n_sims=300)

    rows = {r.team_id: r for r in db_session.query(Standing).filter_by(group_id=group.id)}
    assert rows[target].points == 9
    assert rows[target].qualification_prob == 1.0
    assert rows[loser].points == 0
    assert rows[loser].qualification_prob == 0.0


def test_qualification_probs_sum_to_two_per_group(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    generate_predictions(db_session, n_sims=500)
    from app.models import Group

    for group in db_session.query(Group).all():
        rows = db_session.query(Standing).filter_by(group_id=group.id).all()
        total = sum(r.qualification_prob for r in rows)
        assert abs(total - 2.0) < 0.05  # exactly 2 advance per group


def test_blend_off_ignores_the_booster_entirely(db_session):
    """wdl_blend=None ⇒ the booster is never consulted, even if one is supplied:
    probabilities equal the pure Poisson card. Guards against a future change that
    blends regardless of the gate flag (the stub returns a strong-home triple, so
    if it were used the probabilities would visibly diverge)."""
    from dataclasses import replace
    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (db_session.query(Match)
             .filter(Match.stage == "group", Match.team_home_id.isnot(None)).first())
    params = replace(DEFAULT_PARAMS, wdl_blend=None)

    poisson = build_payload(db_session, match, "v", params=params)
    with_stub = build_payload(db_session, match, "v", params=params, booster=_StubBooster())
    assert with_stub["probabilities"] == poisson["probabilities"]


class _StubBooster:
    """Returns a fixed, strongly-home triple regardless of features."""
    def predict_proba(self, feats):
        return {"H": 0.90, "D": 0.06, "A": 0.04}


def test_serving_features_match_training_features(db_session):
    """For the same match history, the serving feature vector equals the training
    feature row — proving no train/serve skew."""
    from datetime import date
    from app.models import HistoricalMatch, Team
    from ml.features.build_features import head_to_head
    from ml.features.training_rows import build_training_rows
    from ml.features.wdl_features import FEATURE_NAMES
    from pipeline.generate_predictions import _boost_features

    home = Team(name="Alpha"); away = Team(name="Beta"); other = Team(name="Gamma")
    db_session.add_all([home, away, other]); db_session.commit()

    # Three prior played matches, oldest first.
    hist = [
        HistoricalMatch(team_a_id=home.id, team_b_id=other.id, score_a=2, score_b=0,
                        competition="Friendly", is_neutral=False, date=date(2023, 1, 1)),
        HistoricalMatch(team_a_id=away.id, team_b_id=other.id, score_a=1, score_b=1,
                        competition="Friendly", is_neutral=False, date=date(2023, 2, 1)),
        HistoricalMatch(team_a_id=home.id, team_b_id=away.id, score_a=0, score_b=1,
                        competition="Friendly", is_neutral=True, date=date(2023, 3, 1)),
    ]
    db_session.add_all(hist); db_session.commit()

    # The "upcoming" match is home vs away — a 4th meeting. Serving features use all
    # history (every played match precedes a scheduled fixture). h2h is supplied the
    # same way build_payload does it (from build_match_features' head_to_head).
    serving = _boost_features(db_session, home, away,
                              elo_home=1500.0, elo_away=1500.0, is_neutral=True,
                              h2h=head_to_head(db_session, home.id, away.id))

    # Training: append the same upcoming pairing as the LAST enriched row; its
    # feature row must equal the serving vector. (Elo pre-match = 1500 baseline here
    # since we don't replay Elo in this hermetic test — assemble uses what we pass.)
    enriched = [
        {"home_id": home.id, "away_id": other.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": False, "competition": "Friendly", "score_home": 2, "score_away": 0,
         "date": date(2023, 1, 1)},
        {"home_id": away.id, "away_id": other.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": False, "competition": "Friendly", "score_home": 1, "score_away": 1,
         "date": date(2023, 2, 1)},
        {"home_id": home.id, "away_id": away.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": True, "competition": "Friendly", "score_home": 0, "score_away": 1,
         "date": date(2023, 3, 1)},
        {"home_id": home.id, "away_id": away.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": True, "competition": "Friendly", "score_home": 0, "score_away": 0,
         "date": date(2023, 4, 1)},
    ]
    train_row = build_training_rows(enriched)[-1]
    for name in FEATURE_NAMES:
        assert serving[name] == train_row[name], f"skew in {name}"


def test_serving_and_training_data_points_cap_at_window(db_session):
    """A team with MORE than WINDOW prior matches must report data_points capped at
    the window size identically in training and serving. Regression guard: serving
    counts via _recent_appearances(limit=WINDOW) (capped), so training must use the
    windowed count too — not an unbounded cumulative counter."""
    from datetime import date, timedelta
    from app.models import HistoricalMatch, Team
    from ml.features.build_features import head_to_head
    from ml.features.training_rows import build_training_rows, WINDOW
    from ml.features.wdl_features import FEATURE_NAMES
    from pipeline.generate_predictions import _boost_features

    home = Team(name="Home"); away = Team(name="Away")
    opponents = [Team(name=f"Opp{i}") for i in range(WINDOW + 2)]   # 12 prior matches
    db_session.add_all([home, away, *opponents]); db_session.commit()

    base_day = date(2023, 1, 1)
    hist, enriched = [], []
    for i, opp in enumerate(opponents):
        d = base_day + timedelta(days=i)
        sh, sa = (2, 0) if i % 2 == 0 else (1, 1)   # mix of wins and draws
        hist.append(HistoricalMatch(team_a_id=home.id, team_b_id=opp.id, score_a=sh,
                                    score_b=sa, competition="Friendly", is_neutral=False, date=d))
        enriched.append({"home_id": home.id, "away_id": opp.id, "pre_home": 1500.0,
                         "pre_away": 1500.0, "is_neutral": False, "competition": "Friendly",
                         "score_home": sh, "score_away": sa, "date": d})
    db_session.add_all(hist); db_session.commit()

    # Upcoming home vs away (away has no history).
    enriched.append({"home_id": home.id, "away_id": away.id, "pre_home": 1500.0,
                     "pre_away": 1500.0, "is_neutral": True, "competition": "Friendly",
                     "score_home": 0, "score_away": 0, "date": base_day + timedelta(days=99)})

    serving = _boost_features(db_session, home, away, elo_home=1500.0, elo_away=1500.0,
                              is_neutral=True, h2h=head_to_head(db_session, home.id, away.id))
    train_row = build_training_rows(enriched)[-1]

    assert serving["data_points_home"] == float(WINDOW)   # capped at 10, not 12
    for name in FEATURE_NAMES:
        assert serving[name] == train_row[name], f"skew in {name}"


def test_blend_shifts_probabilities_toward_booster(db_session):
    from dataclasses import replace
    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (db_session.query(Match)
             .filter(Match.stage == "group", Match.team_home_id.isnot(None)).first())

    off = build_payload(db_session, match, "v",
                        params=replace(DEFAULT_PARAMS, wdl_blend=None))
    # weight=1.0 ⇒ served triple becomes the booster's (then calibrated; calibrator None).
    on = build_payload(db_session, match, "v",
                       params=replace(DEFAULT_PARAMS, wdl_blend={"weight": 1.0, "calibrator": None}),
                       booster=_StubBooster())

    assert on["probabilities"]["home_win"] > off["probabilities"]["home_win"]
    p = on["probabilities"]
    assert abs(p["home_win"] + p["draw"] + p["away_win"] - 1.0) < 0.01
    # Predicted SCORE stays Poisson's — the booster never touches it.
    assert on["predicted_score"] == off["predicted_score"]


def test_build_payload_team_offsets_off_is_identity_and_on_shifts_lambdas(db_session, tmp_path):
    """FR-5.3 end-to-end: with params.team_offsets=None (the shipped default)
    the payload is exactly the no-offsets payload; with a store enabled, the
    home team's positive attack offset must lift the served lambda_home."""
    import json as _json
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    home = db_session.get(Team, match.team_home_id)

    baseline_params = replace(DEFAULT_PARAMS, team_offsets=None)
    store = tmp_path / "team_offsets.json"
    store.write_text(_json.dumps({home.name: {"atk": 0.075, "def": 0.0, "n_matches": 100}}))
    enabled_params = replace(DEFAULT_PARAMS, team_offsets={"file": str(store)})

    base = build_payload(db_session, match, "poisson-elo-v0.1", params=baseline_params)
    off = build_payload(db_session, match, "poisson-elo-v0.1", params=baseline_params)
    on = build_payload(db_session, match, "poisson-elo-v0.1", params=enabled_params)

    # Disabled twice -> identical model outputs (identity path).
    for key in ("probabilities", "predicted_score", "lambda_home", "lambda_away"):
        assert base[key] == off[key]
    # Enabled -> only the home lambda moves (away team has no store entry).
    assert on["lambda_home"] > base["lambda_home"]
    assert on["lambda_away"] == base["lambda_away"]
    assert on["probabilities"]["home_win"] > base["probabilities"]["home_win"]


def test_simulations_receive_the_same_team_offsets_as_match_cards(db_session, tmp_path, monkeypatch):
    """Review-finding guard: with team_offsets enabled, _simulate_standings and
    _simulate_tournament must hand the Monte-Carlo engines the SAME per-team
    (atk, def) offsets that build_payload applies to the match cards — otherwise
    a match page would serve offset-adjusted W/D/L next to qualification/title
    odds simulated from divergent symmetric-Elo lambdas. With the flag off (the
    shipped default) the sims must see no offsets at all."""
    import json as _json
    from dataclasses import replace

    import pipeline.generate_predictions as gp
    from app.models import Group
    from ml.models.params import DEFAULT_PARAMS
    from ml.models.team_offsets import load_team_offsets, offsets_for

    load_structure(db_session)
    _set_elos(db_session)

    group = db_session.query(Group).first()
    members = [gt.team for gt in group.group_teams]
    store_path = tmp_path / "team_offsets.json"
    store_path.write_text(_json.dumps({
        members[0].name: {"atk": 0.075, "def": -0.075, "n_matches": 100},
        members[1].name: {"atk": -0.03, "def": 0.02, "n_matches": 50},
    }))

    captured: dict[str, list] = {"group": [], "tournament": []}
    real_group, real_tournament = gp.simulate_group, gp.simulate_tournament

    def spy_group(*args, **kwargs):
        captured["group"].append(kwargs.get("team_offsets"))
        return real_group(*args, **kwargs)

    def spy_tournament(*args, **kwargs):
        captured["tournament"].append(kwargs.get("team_offsets"))
        return real_tournament(*args, **kwargs)

    monkeypatch.setattr(gp, "simulate_group", spy_group)
    monkeypatch.setattr(gp, "simulate_tournament", spy_tournament)

    enabled = replace(DEFAULT_PARAMS, team_offsets={"file": str(store_path)})
    gp._simulate_standings(db_session, group, "v", n_sims=50, params=enabled)
    gp._simulate_tournament(db_session, n_sims=20, params=enabled)

    # Exactly what build_payload would apply, keyed by team id, for every member.
    store = load_team_offsets(str(store_path))
    assert captured["group"] == [{t.id: offsets_for(store, t.name) for t in members}]
    all_members = [gt.team for g in db_session.query(Group).all() for gt in g.group_teams]
    assert captured["tournament"] == [
        {t.id: offsets_for(store, t.name) for t in all_members}
    ]
    # Sanity: the boosted team's offsets actually made it through (non-zero).
    assert captured["tournament"][0][members[0].id] == (0.075, -0.075)

    # Flag off (shipped default): the sims must run offset-free.
    captured["group"].clear()
    captured["tournament"].clear()
    disabled = replace(DEFAULT_PARAMS, team_offsets=None)
    gp._simulate_standings(db_session, group, "v", n_sims=50, params=disabled)
    gp._simulate_tournament(db_session, n_sims=20, params=disabled)
    assert not captured["group"][0]
    assert not captured["tournament"][0]


def test_prediction_log_is_append_only_across_runs(db_session):
    """ROADMAP Standing Rule #2: the prediction log is append-only. Two daily
    runs over the same scheduled match must APPEND a second production row (never
    UPDATE in place), and the earliest row's served probabilities must stay
    byte-for-byte unchanged — no retro-edit of what was frozen the first run."""
    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )

    def prod_rows():
        return (
            db_session.query(Prediction)
            .filter_by(match_id=match.id, is_shadow=False)
            .order_by(Prediction.id)
            .all()
        )

    generate_predictions(db_session, n_sims=300)
    after_first = prod_rows()
    assert len(after_first) == 1
    earliest = after_first[0]
    frozen = (earliest.prob_home_win, earliest.prob_draw, earliest.prob_away_win)

    generate_predictions(db_session, n_sims=300)
    after_second = prod_rows()
    # Appended, not replaced: the count strictly increased.
    assert len(after_second) == 2
    # The first-run row is untouched — same id, same served probabilities.
    db_session.refresh(earliest)
    assert (earliest.prob_home_win, earliest.prob_draw, earliest.prob_away_win) == frozen
    assert after_second[0].id == earliest.id


def test_no_prediction_written_after_kickoff(db_session):
    """ROADMAP Standing Rule #2: the log is frozen at kickoff. Once a match is no
    longer "scheduled", no further production row may be appended — neither via
    generate_predictions (which filters to scheduled) nor via a direct
    _write_prediction call (whose guard must skip a started/finished match)."""
    from pipeline.generate_predictions import _write_prediction

    load_structure(db_session)
    _set_elos(db_session)

    group_matches = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .order_by(Match.id)
        .all()
    )
    in_play, finished = group_matches[0], group_matches[1]
    in_play.status = "in_play"
    finished.status = "finished"
    finished.score_home, finished.score_away = 1, 0
    db_session.commit()

    generate_predictions(db_session, n_sims=300)

    # Neither the in-play nor the finished match got a production prediction.
    for started in (in_play, finished):
        assert (
            db_session.query(Prediction)
            .filter_by(match_id=started.id, is_shadow=False)
            .count()
            == 0
        ), f"a {started.status} match must not be predicted"

    # A direct _write_prediction on a started match appends nothing (guard skips).
    payload = build_payload(db_session, in_play, "poisson-elo-v0.1")
    assert payload is not None
    before = db_session.query(Prediction).count()
    _write_prediction(db_session, in_play, payload, "poisson-elo-v0.1")
    assert db_session.query(Prediction).count() == before


def test_team_offsets_shift_simulated_standings_when_enabled(db_session, tmp_path):
    """End-to-end over the standings path: enabling a store that boosts one
    team's attack AND weakens every group rival must lift that team's simulated
    qualification_prob relative to the offset-free run (same seed inside
    _simulate_standings, so the comparison uses common random numbers)."""
    import json as _json
    from dataclasses import replace

    from app.models import Group
    from ml.models.params import DEFAULT_PARAMS
    from pipeline.generate_predictions import _simulate_standings

    load_structure(db_session)
    _set_elos(db_session)

    group = db_session.query(Group).first()
    members = [gt.team for gt in group.group_teams]
    target = min(members, key=lambda t: t.elo_rating)  # weakest: room to climb
    store = {
        t.name: ({"atk": 0.075, "def": -0.075, "n_matches": 100} if t is target
                 else {"atk": -0.075, "def": 0.075, "n_matches": 100})
        for t in members
    }
    store_path = tmp_path / "team_offsets.json"
    store_path.write_text(_json.dumps(store))

    def qual_prob(params) -> float:
        _simulate_standings(db_session, group, "v", n_sims=4000, params=params)
        row = db_session.query(Standing).filter_by(
            group_id=group.id, team_id=target.id).one()
        return row.qualification_prob

    baseline = qual_prob(replace(DEFAULT_PARAMS, team_offsets=None))
    boosted = qual_prob(replace(DEFAULT_PARAMS, team_offsets={"file": str(store_path)}))
    assert boosted > baseline
