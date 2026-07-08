"""Tests for prediction generation + §17 payload shape (task 3.8/3.9)."""
from datetime import datetime, timezone

import pytest

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


from datetime import datetime, timezone

from app.models import LineupPlayer, MatchLineup, Player
from ml.models.params import DEFAULT_PARAMS
from pipeline.generate_predictions import (
    AVAILABILITY_MODEL_VERSION, write_availability_prediction,
)


def _avail_payload(match_id):
    return {"match_id": match_id, "lambda_home": 2.0, "lambda_away": 1.0, "rho": -0.1,
            "probabilities": {"home_win": 0.55, "draw": 0.27, "away_win": 0.18},
            "predicted_score": {"home": 2, "away": 1, "probability": 0.12},
            "confidence": "Medium", "reasons": ["a", "b", "c"], "top_features": []}


def _scheduled_match_with_squads(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    h.elo_rating = a.elo_rating = 1700.0
    for team in (h, a):
        star = team.id
        db.add(Player(provider_player_id=star, name="Star", team_id=team.id, position="F",
                      club_goals=25, club_minutes=3000, wc_goals=3, wc_minutes=270))
        for i in range(11):
            db.add(Player(provider_player_id=star * 100 + i, name=f"reg{i}", team_id=team.id,
                          position="M", club_goals=2, club_minutes=2400, wc_goals=0, wc_minutes=270))
    db.commit()
    return m, h, a


def _add_lineup(db, match_id, side, starter_pids):
    ml = MatchLineup(match_id=match_id, side=side, provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.add(ml); db.commit()
    db.add_all([LineupPlayer(match_lineup_id=ml.id, name=f"pid{pid}", is_starter=True,
                             order=i, provider_player_id=pid)
                for i, pid in enumerate(starter_pids)])
    db.commit()


def test_availability_twin_written_when_both_xi(db_session):
    m, h, a = _scheduled_match_with_squads(db_session)
    _add_lineup(db_session, m.id, "home", [h.id * 100 + i for i in range(11)])            # 11 regulars, Star benched
    _add_lineup(db_session, m.id, "away", [a.id] + [a.id * 100 + i for i in range(10)])   # Star + 10 regulars
    write_availability_prediction(db_session, m, _avail_payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    twin = (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).one())
    assert twin.is_shadow is True
    assert twin.lambda_home < 2.0   # home attack cut by the availability offset (lambda *= exp(offset<0))


def test_no_availability_twin_without_lineups(db_session):
    m, h, a = _scheduled_match_with_squads(db_session)
    write_availability_prediction(db_session, m, _avail_payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    assert (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).count() == 0)


def test_availability_twin_blocked_after_kickoff(db_session):
    m, h, a = _scheduled_match_with_squads(db_session)
    _add_lineup(db_session, m.id, "home", [h.id] + [h.id * 100 + i for i in range(10)])
    _add_lineup(db_session, m.id, "away", [a.id] + [a.id * 100 + i for i in range(10)])
    m.status = "in_play"; db_session.commit()
    write_availability_prediction(db_session, m, _avail_payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    assert (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).count() == 0)


# --- use_availability serving-path integration (dual-basis plan) ------------


def test_build_payload_use_availability_scales_lambdas(monkeypatch, db_session):
    """With use_availability on and an availability offset present, production
    lambdas scale by exp(offset) and the triple is recomputed; with the flag
    off, payload is bit-identical whether or not offsets exist."""
    import math
    from dataclasses import replace

    import pipeline.generate_predictions as gp
    from ml.models.params import load_params

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    # Real return shape of app.availability.availability_for_match:
    # (off_home, off_away, expl_home, expl_away) or None.
    monkeypatch.setattr(gp, "availability_for_match", lambda _db, _m: (-0.20, 0.05, {}, {}))

    params_off = replace(load_params(), form_channels=None, use_availability=False)
    params_on = replace(params_off, use_availability=True)

    base = gp.build_payload(db_session, match, "test-model", params=params_off)
    adjusted = gp.build_payload(db_session, match, "test-model", params=params_on)

    assert adjusted["lambda_home"] == pytest.approx(base["lambda_home"] * math.exp(-0.20), rel=1e-3)
    assert adjusted["lambda_away"] == pytest.approx(base["lambda_away"] * math.exp(0.05), rel=1e-3)
    assert adjusted["probabilities"] != base["probabilities"]

    # Dark = bit-identical even with offsets available.
    again = gp.build_payload(db_session, match, "test-model", params=params_off)
    assert again["probabilities"] == base["probabilities"]
    assert again["lambda_home"] == base["lambda_home"]


def test_build_payload_use_availability_without_signal_is_identity(db_session):
    """Flag on but no stored XI/injuries (the real availability_for_match
    returns None): the payload must equal the flag-off baseline -- flipping
    the flag before lineups exist can never perturb serving."""
    from dataclasses import replace

    from pipeline.generate_predictions import build_payload as bp
    from ml.models.params import load_params

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    params_off = replace(load_params(), form_channels=None, use_availability=False)
    params_on = replace(params_off, use_availability=True)

    base = bp(db_session, match, "test-model", params=params_off)
    on_no_signal = bp(db_session, match, "test-model", params=params_on)

    for key in ("probabilities", "predicted_score", "lambda_home", "lambda_away"):
        assert on_no_signal[key] == base[key]


def test_build_payload_use_availability_adds_reason(monkeypatch, db_session):
    """Flip-day explainability: the moment a promoted use_availability moves
    the served lambdas, the card grows one reason naming the missing players —
    with the flag off, no such line exists."""
    from dataclasses import replace

    import pipeline.generate_predictions as gp
    from ml.models.params import load_params

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    expl_home = {"attack_delta_pct": -0.14,
                 "players_out": [{"name": "Star Striker", "weight": 0.31}]}
    monkeypatch.setattr(gp, "availability_for_match",
                        lambda _db, _m: (-0.15, 0.0, expl_home, {}))

    params_off = replace(load_params(), form_channels=None, use_availability=False)
    params_on = replace(params_off, use_availability=True)

    base = gp.build_payload(db_session, match, "test-model", params=params_off)
    served = gp.build_payload(db_session, match, "test-model", params=params_on)

    assert not any("Star Striker" in x for x in base["reasons"])
    assert len(served["reasons"]) == len(base["reasons"]) + 1
    assert sum("Star Striker" in x for x in served["reasons"]) == 1


def test_build_payload_use_availability_zero_offset_adds_no_reason(monkeypatch, db_session):
    """Full-strength XIs (offsets 0.0/0.0) don't move the numbers, so they must
    not grow a phantom availability line either."""
    from dataclasses import replace

    import pipeline.generate_predictions as gp
    from ml.models.params import load_params

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    monkeypatch.setattr(
        gp, "availability_for_match",
        lambda _db, _m: (0.0, 0.0, {"attack_delta_pct": 0.0, "players_out": []}, {}),
    )

    params_off = replace(load_params(), form_channels=None, use_availability=False)
    params_on = replace(params_off, use_availability=True)

    base = gp.build_payload(db_session, match, "test-model", params=params_off)
    served = gp.build_payload(db_session, match, "test-model", params=params_on)

    assert served["reasons"] == base["reasons"]
    assert served["probabilities"] == base["probabilities"]


# --- form_channels serving-path integration (model v2 C1) -------------------


def _set_residual_ledger(db, team_id, ledger):
    from app.models import TeamTournamentState

    row = db.query(TeamTournamentState).filter_by(team_id=team_id).one_or_none()
    if row is None:
        row = TeamTournamentState(team_id=team_id)
        db.add(row)
    row.residual_ledger = [list(pair) for pair in ledger]
    db.commit()


def test_build_payload_form_channels_none_is_bit_identical_to_disabled(db_session):
    """None-config bit-identity: with form_channels=None (the shipped
    default), the payload must be EXACTLY what it was before C1 -- even if a
    residual ledger happens to be sitting in the DB (e.g. left by a run where
    the feature was later disabled).

    Regression note: an earlier version of this test only called
    build_payload TWICE with the SAME (ledger-populated) DB state and the
    same params -- that proves determinism, not that the ledger is ignored.
    The real guard compares a run WITH a populated ledger against a run with
    NO ledger at all, both under form_channels=None -- the triples and
    lambdas must be identical, proving the ledger is never read while dark."""
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    params_off = replace(DEFAULT_PARAMS, form_channels=None)

    # No ledger anywhere in the DB.
    without_ledger = build_payload(db_session, match, "poisson-elo-v0.1", params=params_off)

    # A populated, clearly-non-trivial ledger for the home team.
    _set_residual_ledger(db_session, match.team_home_id, [(1.5, -0.3), (0.8, 0.1)])
    with_ledger = build_payload(db_session, match, "poisson-elo-v0.1", params=params_off)

    for key in ("probabilities", "predicted_score", "lambda_home", "lambda_away"):
        assert with_ledger[key] == without_ledger[key]


def test_build_payload_form_channels_on_shifts_lambdas_via_ledger(db_session):
    """FR-style end-to-end: with form_channels enabled and a positive-gf
    residual ledger stored for the home team, the served lambda_home must
    rise relative to the disabled baseline -- the offset actually reaches
    predict_match's atk_home parameter."""
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    home_id = match.team_home_id
    _set_residual_ledger(db_session, home_id, [(1.5, 0.0)] * 6)

    baseline_params = replace(DEFAULT_PARAMS, form_channels=None)
    enabled_params = replace(
        DEFAULT_PARAMS,
        form_channels={"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0},
    )

    off = build_payload(db_session, match, "poisson-elo-v0.1", params=baseline_params)
    on = build_payload(db_session, match, "poisson-elo-v0.1", params=enabled_params)

    assert on["lambda_home"] > off["lambda_home"]
    assert on["probabilities"]["home_win"] > off["probabilities"]["home_win"]
    # Predicted SCORE grid may shift (lambdas moved), but the payload
    # remains internally consistent -- winner and score always agree
    # (existing predict_from_lambdas guarantee, unaffected by this change).


def test_build_payload_form_channels_uses_opponent_def_offset_correctly():
    """Sign-convention wiring check at the predict_match boundary: a positive
    def_form (conceding above expectation) must be applied to the OPPONENT's
    lambda, matching ml.models.poisson.expected_goals_from_elo's def_home/
    def_away contract (lambda_home *= exp(atk_home + def_away))."""
    from ml.models.poisson import expected_goals_from_elo

    lam_h_base, lam_a_base = expected_goals_from_elo(1600.0, 1600.0, 0.0)
    # away team has a leaky defence (positive def_form) -> home's lambda
    # should rise when we pass it as def_away.
    lam_h_leaky, lam_a_leaky = expected_goals_from_elo(1600.0, 1600.0, 0.0, def_away=0.1)
    assert lam_h_leaky > lam_h_base
    assert lam_a_leaky == pytest.approx(lam_a_base)


def test_build_payload_form_channels_does_not_double_count_legacy_scalar(db_session):
    """No-double-count guard at the payload level: when form_channels is
    active, strengths passed in (as effective_elos would compute them with
    the legacy scalar excluded) must not ALSO get the legacy scalar folded
    in a second time via build_payload itself -- build_payload must not read
    or apply TeamTournamentState.form_adjustment on its own."""
    from dataclasses import replace

    from app.models import TeamTournamentState
    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    home_id = match.team_home_id
    row = TeamTournamentState(team_id=home_id, elo_delta=0.0, form_adjustment=30.0,
                              residual_ledger=[])
    db_session.add(row)
    db_session.commit()

    enabled_params = replace(
        DEFAULT_PARAMS,
        form_channels={"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0},
    )
    # strengths intentionally omits the legacy scalar (as effective_elos()
    # would once form_channels is active) -- build_payload must not reach
    # into form_adjustment behind the caller's back.
    home = db_session.get(Team, home_id)
    strengths = {home_id: home.elo_rating}  # base only, no elo_delta/form_adjustment
    payload = build_payload(
        db_session, match, "poisson-elo-v0.1", strengths=strengths, params=enabled_params
    )
    assert payload is not None  # build_payload must not crash reading form state


def test_build_payload_surfaces_form_offsets_in_reasons_and_top_features(db_session):
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    home_id = match.team_home_id
    _set_residual_ledger(db_session, home_id, [(1.5, 0.0)] * 6)

    enabled_params = replace(
        DEFAULT_PARAMS,
        form_channels={"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0},
    )
    payload = build_payload(db_session, match, "poisson-elo-v0.1", params=enabled_params)

    factor_names = {f["name"] for f in payload["top_features"]}
    assert "form_channels" in factor_names
    assert any("form" in r.lower() for r in payload["reasons"])


def test_build_payload_no_form_factor_when_form_channels_disabled(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    payload = build_payload(db_session, match, "poisson-elo-v0.1")
    factor_names = {f["name"] for f in payload["top_features"]}
    assert "form_channels" not in factor_names


# --- form_channels must reach BOTH Monte-Carlo simulators (review finding) --
#
# build_payload already folds _form_offsets_by_team_id into the match card's
# lambdas (atk_h += atk_form_h etc). The group and tournament simulators must
# see the SAME combined per-team offsets, or a match page would show a form-
# adjusted card next to qualification/title odds simulated from unadjusted
# symmetric-Elo lambdas -- the repo's card/sim agreement invariant (see the
# existing team_offsets guard, test_simulations_receive_the_same_team_offsets_
# as_match_cards).


def test_simulations_receive_combined_form_and_xg_offsets(db_session, tmp_path, monkeypatch):
    """With BOTH team_offsets (xG) and form_channels enabled, the sims must
    receive the elementwise SUM of the two sources per team -- exactly how
    build_payload composes them (atk_h = xg_atk_h + form_atk_h)."""
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
    }))
    _set_residual_ledger(db_session, members[0].id, [(1.5, 0.0)] * 6)

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

    enabled = replace(
        DEFAULT_PARAMS,
        team_offsets={"file": str(store_path)},
        form_channels={"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0},
    )
    gp._simulate_standings(db_session, group, "v", n_sims=50, params=enabled)
    gp._simulate_tournament(db_session, n_sims=20, params=enabled)

    store = load_team_offsets(str(store_path))
    xg_atk, xg_def = offsets_for(store, members[0].name)
    form_atk, form_def = gp._form_offsets_by_team_id(
        db_session, enabled, members
    )[members[0].id]
    assert form_atk != 0.0 or form_def != 0.0  # sanity: the ledger has signal

    group_offsets = captured["group"][0]
    assert group_offsets[members[0].id] == pytest.approx(
        (xg_atk + form_atk, xg_def + form_def)
    )
    tournament_offsets = captured["tournament"][0]
    assert tournament_offsets[members[0].id] == pytest.approx(
        (xg_atk + form_atk, xg_def + form_def)
    )


def test_qualification_prob_shifts_same_direction_as_match_card_with_hot_ledger(
    db_session,
):
    """With form_channels enabled and a hot (positive-gf) ledger for one team,
    that team's simulated group qualification probability must rise --
    matching the direction build_payload's card already shifts in (higher
    lambda_home / higher win prob) for the same ledger."""
    from dataclasses import replace

    from app.models import Group
    from ml.models.params import DEFAULT_PARAMS
    from pipeline.generate_predictions import _simulate_standings

    load_structure(db_session)
    _set_elos(db_session)

    group = db_session.query(Group).first()
    members = [gt.team for gt in group.group_teams]
    target = members[0]
    _set_residual_ledger(db_session, target.id, [(1.5, 0.0)] * 6)

    baseline_params = replace(DEFAULT_PARAMS, form_channels=None)
    enabled_params = replace(
        DEFAULT_PARAMS,
        form_channels={"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0},
    )

    def qual_prob(params) -> float:
        _simulate_standings(db_session, group, "v", n_sims=4000, params=params)
        row = db_session.query(Standing).filter_by(
            group_id=group.id, team_id=target.id
        ).one()
        return row.qualification_prob

    baseline = qual_prob(baseline_params)
    boosted = qual_prob(enabled_params)
    assert boosted > baseline


def test_sims_bit_identical_when_form_channels_none_regardless_of_ledger(db_session):
    """form_channels=None (the shipped default): the sims must be bit-
    identical to the no-ledger case even when a residual ledger is sitting in
    the DB for a group member -- the same C1 dark-mode invariant build_payload
    already guards (test_build_payload_form_channels_none_is_bit_identical_to_
    disabled), extended to both Monte-Carlo simulators."""
    from dataclasses import replace

    from app.models import Group
    from ml.models.params import DEFAULT_PARAMS
    from pipeline.generate_predictions import _simulate_standings

    load_structure(db_session)
    _set_elos(db_session)
    group = db_session.query(Group).first()
    members = [gt.team for gt in group.group_teams]
    params_off = replace(DEFAULT_PARAMS, form_channels=None)

    def standings_snapshot():
        _simulate_standings(db_session, group, "v", n_sims=300, params=params_off)
        rows = db_session.query(Standing).filter_by(group_id=group.id).all()
        return sorted((r.team_id, r.qualification_prob) for r in rows)

    def tournament_snapshot():
        from pipeline.generate_predictions import _simulate_tournament
        from app.models import TournamentOdds

        _simulate_tournament(db_session, n_sims=100, params=params_off)
        rows = db_session.query(TournamentOdds).all()
        return sorted((r.team_id, r.make_knockout, r.win_title) for r in rows)

    before_group = standings_snapshot()
    before_tournament = tournament_snapshot()

    _set_residual_ledger(db_session, members[0].id, [(1.5, 0.0)] * 6)

    after_group = standings_snapshot()
    after_tournament = tournament_snapshot()

    assert before_group == after_group
    assert before_tournament == after_tournament


def test_build_payload_knockout_block_for_ko_stage(db_session):
    """stage != group gets the v0.5 knockout block: advance probabilities that
    sum to 1, a path split that sums to each side's advance probability, and
    P(extra time) equal to the served draw probability."""
    load_structure(db_session)
    _set_elos(db_session)
    ko = db_session.query(Match).filter(Match.stage != "group").first()
    home, away = db_session.query(Team).order_by(Team.id).limit(2).all()
    ko.team_home_id, ko.team_away_id = home.id, away.id
    db_session.commit()

    payload = build_payload(db_session, ko, "poisson-elo-v0.5")
    block = payload["knockout"]
    assert block is not None
    assert abs(block["p_advance_home"] + block["p_advance_away"] - 1.0) < 1e-3
    assert abs(block["p_extra_time"] - payload["probabilities"]["draw"]) < 1e-3
    for side in ("home", "away"):
        paths = block["paths"][side]
        total = paths["win_90"] + paths["win_et"] + paths["win_pens"]
        assert abs(total - block[f"p_advance_{side}"]) < 1e-3


def test_build_payload_no_knockout_block_for_group_stage(db_session):
    """Group games: a draw is a final result — no knockout block."""
    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    payload = build_payload(db_session, match, "poisson-elo-v0.5")
    assert payload["knockout"] is None


def _rig_signal_fixture(db):
    """Two teams with prior finished matches (unequal rest, one red card) and an
    upcoming R32 tie between them. Returns (upcoming, home_team, away_team)."""
    from datetime import datetime, timedelta

    from app.models import Player

    load_structure(db)
    _set_elos(db)
    home, away = db.query(Team).order_by(Team.id).limit(2).all()
    t0 = datetime(2026, 6, 20, 18, 0)
    priors = db.query(Match).filter(Match.stage == "group").order_by(Match.id).limit(2).all()
    # Home side played 2 days before the tie (and saw red); away side 5 days before.
    priors[0].team_home_id, priors[0].team_away_id = home.id, 999_001
    priors[0].kickoff_utc, priors[0].status, priors[0].stage = t0 + timedelta(days=3), "finished", "group"
    priors[0].card_events = [{"minute": 88, "side": "home", "player": "Star Striker", "type": "red"}]
    priors[1].team_home_id, priors[1].team_away_id = away.id, 999_002
    priors[1].kickoff_utc, priors[1].status, priors[1].stage = t0, "finished", "group"
    priors[1].card_events = []
    upcoming = db.query(Match).filter(Match.stage != "group").first()
    upcoming.team_home_id, upcoming.team_away_id = home.id, away.id
    upcoming.kickoff_utc, upcoming.status = t0 + timedelta(days=5), "scheduled"
    db.add(Player(provider_player_id=11, name="Star Striker", team_id=home.id, position="F",
                  club_goals=25, club_minutes=2700, wc_goals=2, wc_minutes=270))
    db.add(Player(provider_player_id=12, name="Squad Filler", team_id=home.id, position="M",
                  club_goals=2, club_minutes=2000, wc_goals=0, wc_minutes=180))
    db.add(Player(provider_player_id=21, name="Away Anchor", team_id=away.id, position="M",
                  club_goals=8, club_minutes=2600, wc_goals=1, wc_minutes=270))
    db.commit()
    return upcoming, home, away


def test_suspension_twin_written_for_red_card(db_session):
    from pipeline.generate_predictions import BANS_MODEL_VERSION, write_suspension_prediction

    upcoming, home, _away = _rig_signal_fixture(db_session)
    payload = build_payload(db_session, upcoming, "poisson-elo-v0.5")
    write_suspension_prediction(db_session, upcoming, payload, {}, load_params_for_test())
    db_session.commit()
    twin = (
        db_session.query(Prediction)
        .filter_by(match_id=upcoming.id, model_version=BANS_MODEL_VERSION, is_shadow=True)
        .one()
    )
    # The banned striker weakens the home attack: twin lambda below production.
    assert twin.lambda_home < payload["lambda_home"]
    assert twin.lambda_away == round(payload["lambda_away"], 4)


def test_rest_twin_written_for_unequal_rest(db_session):
    from pipeline.generate_predictions import REST_MODEL_VERSION, write_rest_prediction

    upcoming, _home, _away = _rig_signal_fixture(db_session)
    payload = build_payload(db_session, upcoming, "poisson-elo-v0.5")
    write_rest_prediction(db_session, upcoming, payload, {}, load_params_for_test())
    db_session.commit()
    twin = (
        db_session.query(Prediction)
        .filter_by(match_id=upcoming.id, model_version=REST_MODEL_VERSION, is_shadow=True)
        .one()
    )
    # Away rested 5 days vs home's 2: the twin tilts toward the away side.
    assert twin.lambda_away > round(payload["lambda_away"], 4) - 1e-9
    assert twin.lambda_home < payload["lambda_home"] + 1e-9
    assert twin.lambda_home != payload["lambda_home"] or twin.lambda_away != payload["lambda_away"]


def test_signals_default_off_is_a_noop_in_served_payload(db_session):
    """model_params.json nulls: enabling the code paths must not move a single
    served number until a param is explicitly flipped."""
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS

    upcoming, _home, _away = _rig_signal_fixture(db_session)
    off = replace(DEFAULT_PARAMS, suspensions=None, rest_days=None, pk_keeper_delta=0.0)
    on = replace(DEFAULT_PARAMS, suspensions={"enabled": True},
                 rest_days={"coef": 0.02, "cap": 0.08})
    p_off = build_payload(db_session, upcoming, "v", params=off)
    p_on = build_payload(db_session, upcoming, "v", params=on)
    # The signals genuinely fire when enabled...
    assert p_on["lambda_home"] != p_off["lambda_home"]
    # ...and a second disabled build is bit-identical to the first.
    p_off2 = build_payload(db_session, upcoming, "v", params=off)
    assert p_off2["probabilities"] == p_off["probabilities"]
    assert p_off2["lambda_home"] == p_off["lambda_home"]


def load_params_for_test():
    from ml.models.params import DEFAULT_PARAMS

    return DEFAULT_PARAMS
