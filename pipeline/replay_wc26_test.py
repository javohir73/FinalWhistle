"""Tests for the WC26 group-stage leak-free replay (model v2 §5).

Re-predicts finished WC26 group matches using ONLY information available
pre-kickoff of each match: effective ratings are rebuilt from the historical
base + a replay_tournament() prefix of strictly-prior finished tournament
matches (mirroring pipeline/learning_loop.py's TournamentMatch construction,
including host home_adv). Read-only against the DB — no writes.
"""
from datetime import datetime, timezone

from app.models import Match, Team, Tournament
from ml.ratings.elo import HOME_ADVANTAGE
from pipeline.replay_wc26 import build_wc26_rows, replay_wc26


def _wc(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    db.add(wc)
    db.flush()
    return wc


def _team(db, name, elo=1600.0):
    t = Team(name=name, elo_rating=elo)
    db.add(t)
    db.flush()
    return t


def _finished(db, wc, home, away, sh, sa, ko, host=None):
    m = Match(
        tournament_id=wc.id, team_home_id=home.id, team_away_id=away.id,
        stage="group", status="finished", score_home=sh, score_away=sa,
        kickoff_utc=ko, is_neutral=host is None, host_team_id=host.id if host else None,
    )
    db.add(m)
    db.flush()
    return m


def test_build_wc26_rows_returns_one_row_per_finished_group_match(db_session):
    wc = _wc(db_session)
    mex, rsa, kor = (_team(db_session, n) for n in ("Mexico", "South Africa", "Korea"))
    _finished(db_session, wc, mex, rsa, 2, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    _finished(db_session, wc, kor, rsa, 1, 1, datetime(2026, 6, 12, 18, tzinfo=timezone.utc))
    db_session.commit()

    rows = build_wc26_rows(db_session)
    assert len(rows) == 2
    for r in rows:
        for key in ("pre_home", "pre_away", "is_neutral", "score_home", "score_away",
                    "date", "competition", "ledger_home", "ledger_away"):
            assert key in r


def test_first_match_effective_rating_equals_historical_base(db_session):
    """The tournament's first match has no prior finished matches, so the
    effective pre-match rating must equal the plain historical base (+ host
    bonus applied by the caller via is_neutral, not baked into pre_home)."""
    wc = _wc(db_session)
    mex, rsa = _team(db_session, "Mexico", elo=1800.0), _team(db_session, "South Africa", elo=1600.0)
    _finished(db_session, wc, mex, rsa, 2, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    db_session.commit()

    rows = build_wc26_rows(db_session)
    assert rows[0]["pre_home"] == 1800.0
    assert rows[0]["pre_away"] == 1600.0
    assert rows[0]["is_neutral"] is False  # host match


def test_second_match_effective_rating_reflects_prior_result(db_session):
    """Mexico's SECOND match must use base + elo_delta from replaying ONLY
    the first (prior) match — not the raw historical base again."""
    wc = _wc(db_session)
    mex = _team(db_session, "Mexico", elo=1800.0)
    rsa = _team(db_session, "South Africa", elo=1600.0)
    kor = _team(db_session, "Korea", elo=1750.0)
    _finished(db_session, wc, mex, rsa, 3, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    _finished(db_session, wc, mex, kor, 1, 1, datetime(2026, 6, 17, 18, tzinfo=timezone.utc), host=mex)
    db_session.commit()

    rows = build_wc26_rows(db_session)
    second = rows[1]
    # Mexico won its opener big, so its effective rating in match 2 must be
    # STRICTLY ABOVE its raw historical base (1800) — the win nudged it up.
    assert second["pre_home"] > 1800.0


def test_leakage_first_match_ledgers_have_no_in_tournament_entries(db_session):
    """A team's ledger going into its FIRST tournament match must contain no
    in-tournament residuals (there are none yet) — only whatever pre-
    tournament history is present (none here, so empty)."""
    wc = _wc(db_session)
    mex, rsa = _team(db_session, "Mexico"), _team(db_session, "South Africa")
    _finished(db_session, wc, mex, rsa, 2, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    db_session.commit()

    rows = build_wc26_rows(db_session)
    assert rows[0]["ledger_home"] == []
    assert rows[0]["ledger_away"] == []


def test_leakage_second_match_ledger_has_exactly_one_in_tournament_entry(db_session):
    wc = _wc(db_session)
    mex = _team(db_session, "Mexico", elo=1800.0)
    rsa = _team(db_session, "South Africa", elo=1600.0)
    kor = _team(db_session, "Korea", elo=1750.0)
    _finished(db_session, wc, mex, rsa, 3, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    _finished(db_session, wc, mex, kor, 1, 1, datetime(2026, 6, 17, 18, tzinfo=timezone.utc), host=mex)
    db_session.commit()

    rows = build_wc26_rows(db_session)
    assert len(rows[1]["ledger_home"]) == 1  # Mexico's opener, nothing from match 2 itself


def test_in_tournament_ledger_residual_uses_served_goals_scale(db_session, monkeypatch):
    """Model v2 review finding (ablation validity): the in-tournament residual
    appended to the running ledger must be measured against the SERVED goals
    params (ml.models.params.load_params()), not the hardcoded v0.1
    constants -- otherwise this file's ledger and the served model disagree
    on what counts as "above expectation"."""
    import pipeline.replay_wc26 as rw_mod
    from ml.models.params import DEFAULT_PARAMS
    from ml.models.poisson import expected_goals_from_elo

    tuned = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(), "base": 1.2, "beta": 0.0021}
    )
    monkeypatch.setattr(rw_mod, "load_params", lambda: tuned)

    wc = _wc(db_session)
    mex = _team(db_session, "Mexico", elo=1800.0)
    rsa = _team(db_session, "South Africa", elo=1600.0)
    kor = _team(db_session, "Korea", elo=1750.0)
    _finished(db_session, wc, mex, rsa, 3, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    _finished(db_session, wc, mex, kor, 1, 1, datetime(2026, 6, 17, 18, tzinfo=timezone.utc), host=mex)
    db_session.commit()

    rows = build_wc26_rows(db_session)
    second = rows[1]
    gf, ga = second["ledger_home"][0]  # Mexico's opener residual, seen going into match 2

    first = rows[0]
    lam_home_served, lam_away_served = expected_goals_from_elo(
        first["pre_home"], first["pre_away"], 0.0 if first["is_neutral"] else HOME_ADVANTAGE,
        base=tuned.base, beta=tuned.beta,
    )
    lam_home_v01, _ = expected_goals_from_elo(
        first["pre_home"], first["pre_away"], 0.0 if first["is_neutral"] else HOME_ADVANTAGE,
    )
    assert abs(lam_home_served - lam_home_v01) > 1e-6  # sanity: scales actually differ
    assert abs(gf - (first["score_home"] - lam_home_served)) < 1e-9
    assert abs(ga - (first["score_away"] - lam_away_served)) < 1e-9


def test_pretournament_ledger_tail_uses_served_goals_scale(db_session, monkeypatch):
    """Same invariant as the in-tournament case, for the pre-tournament tail
    (_pretournament_ledger_tails / build_enriched_rows' own default)."""
    import pipeline.replay_wc26 as rw_mod
    from app.models import HistoricalMatch, Team as TeamModel
    from ml.models.params import DEFAULT_PARAMS
    from ml.models.poisson import expected_goals_from_elo
    from pipeline.replay_wc26 import _pretournament_ledger_tails

    tuned = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(), "base": 1.2, "beta": 0.0021}
    )
    monkeypatch.setattr(rw_mod, "load_params", lambda: tuned)

    alpha, beta_team = TeamModel(name="Alpha"), TeamModel(name="Beta")
    db_session.add_all([alpha, beta_team])
    db_session.commit()
    db_session.add(HistoricalMatch(
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        team_a_id=alpha.id, team_b_id=beta_team.id, score_a=3, score_b=0,
        competition="Friendly", is_neutral=True,
    ))
    db_session.commit()

    tails = _pretournament_ledger_tails(db_session, tuned)
    gf, ga = tails[alpha.id][0]

    lam_home_served, lam_away_served = expected_goals_from_elo(
        1500.0, 1500.0, 0.0, base=tuned.base, beta=tuned.beta,
    )
    assert abs(gf - (3 - lam_home_served)) < 1e-9
    assert abs(ga - (0 - lam_away_served)) < 1e-9


# --- home_adv sign must mirror production's _host_adv (review finding) -----
#
# pipeline/generate_predictions.py's _host_adv returns +HOME_ADVANTAGE when
# the HOME side is host, -HOME_ADVANTAGE when the AWAY side is host, and 0.0
# on neutral ground. build_wc26_rows' own in-tournament residual computation
# (the `adv` local feeding the ledger append) must use the exact same signed
# convention -- not `0.0 if is_neutral else HOME_ADVANTAGE`, which always
# boosts the home side even when the AWAY team is actually the host.


def test_in_tournament_ledger_residual_uses_signed_host_adv_when_host_is_away(
    db_session,
):
    """Host-as-away fixture: South Africa hosts but plays AWAY against
    Mexico. The row's own residual (appended to the ledger for later rows)
    must be computed with adv = -HOME_ADVANTAGE (boosting the away/host
    side), matching production's _host_adv sign convention -- not
    +HOME_ADVANTAGE, which the old `0.0 if is_neutral else HOME_ADVANTAGE`
    convention would wrongly apply to the home (non-host) side."""
    from ml.models.poisson import expected_goals_from_elo
    from ml.models.params import load_params

    wc = _wc(db_session)
    mex = _team(db_session, "Mexico", elo=1800.0)
    rsa = _team(db_session, "South Africa", elo=1600.0)
    kor = _team(db_session, "Korea", elo=1750.0)
    # Match 1: Mexico (home) vs South Africa (away) -- South Africa is HOST
    # despite playing away. Match 2: Mexico vs Korea, gives us a later row
    # whose ledger_home reflects match 1's appended residual.
    _finished(
        db_session, wc, mex, rsa, 1, 1,
        datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=rsa,
    )
    _finished(
        db_session, wc, mex, kor, 2, 0,
        datetime(2026, 6, 17, 18, tzinfo=timezone.utc),
    )
    db_session.commit()

    served = load_params()
    rows = build_wc26_rows(db_session)
    first = rows[0]
    assert first["is_neutral"] is False  # a host played -- not a neutral match

    # Match 2's ledger_home is Mexico's appended residual from match 1, which
    # must be computed with adv = -HOME_ADVANTAGE (South Africa, the AWAY
    # side, is host) -- the signed production convention.
    second = rows[1]
    gf, ga = second["ledger_home"][0]

    lam_home_signed, lam_away_signed = expected_goals_from_elo(
        first["pre_home"], first["pre_away"], -HOME_ADVANTAGE,
        base=served.base, beta=served.beta,
    )
    assert abs(gf - (first["score_home"] - lam_home_signed)) < 1e-9
    assert abs(ga - (first["score_away"] - lam_away_signed)) < 1e-9

    # Regression guard: the OLD unsigned convention (+HOME_ADVANTAGE whenever
    # not neutral) must NOT match -- proving the fixture actually exercises
    # the sign bug rather than passing by coincidence.
    lam_home_unsigned, _ = expected_goals_from_elo(
        first["pre_home"], first["pre_away"], HOME_ADVANTAGE,
        base=served.base, beta=served.beta,
    )
    assert abs(lam_home_signed - lam_home_unsigned) > 1e-6
    assert abs(gf - (first["score_home"] - lam_home_unsigned)) > 1e-9


def test_pretournament_ledger_tail_residual_uses_signed_host_adv(db_session):
    """Same sign convention, for _pretournament_ledger_tails' OWN residual
    append (the pre-tournament side of the boundary-continuity ledger) --
    reuses build_enriched_rows, so this documents the invariant rather than
    re-testing build_enriched_rows' own (separately-owned) home_adv handling;
    the guard here is that a host-as-away historical match feeds a
    correctly-signed residual into the tail, matching build_wc26_rows'
    in-tournament convention above."""
    from app.models import HistoricalMatch, Team as TeamModel
    from ml.models.params import load_params
    from ml.models.poisson import expected_goals_from_elo
    from pipeline.replay_wc26 import _pretournament_ledger_tails

    alpha, beta_team = TeamModel(name="Alpha"), TeamModel(name="Beta")
    db_session.add_all([alpha, beta_team])
    db_session.commit()
    # Alpha hosts historically but the historical_matches convention (unlike
    # WC26 Match rows) has no host_team_id -- is_neutral=False here means
    # "the home side (Alpha) had a home advantage", which build_enriched_rows
    # already handles correctly (it is the OTHER two call sites, not this
    # one, that had the bug). This test pins that build_wc26_rows' fix
    # doesn't regress the (already-correct) pre-tournament tail. Elo replay
    # starts both sides at the default 1500 rating (build_enriched_rows
    # replays historical_matches from scratch, independent of teams.elo_rating).
    db_session.add(HistoricalMatch(
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        team_a_id=alpha.id, team_b_id=beta_team.id, score_a=2, score_b=1,
        competition="Friendly", is_neutral=False,
    ))
    db_session.commit()

    served = load_params()
    tails = _pretournament_ledger_tails(db_session, served)
    gf, ga = tails[alpha.id][0]

    lam_home, lam_away = expected_goals_from_elo(
        1500.0, 1500.0, HOME_ADVANTAGE, base=served.base, beta=served.beta,
    )
    assert abs(gf - (2 - lam_home)) < 1e-9
    assert abs(ga - (1 - lam_away)) < 1e-9


def test_matches_ordered_by_kickoff(db_session):
    wc = _wc(db_session)
    a, b, c = (_team(db_session, n) for n in ("A", "B", "C"))
    # Insert out of kickoff order to prove the replay sorts by kickoff, not id.
    _finished(db_session, wc, b, c, 1, 0, datetime(2026, 6, 15, tzinfo=timezone.utc))
    _finished(db_session, wc, a, b, 2, 0, datetime(2026, 6, 11, tzinfo=timezone.utc))
    db_session.commit()

    rows = build_wc26_rows(db_session)
    # SQLite round-trips datetimes tz-naive; compare naive components.
    assert rows[0]["date"].replace(tzinfo=None) == datetime(2026, 6, 11)
    assert rows[1]["date"].replace(tzinfo=None) == datetime(2026, 6, 15)


def test_only_finished_group_matches_are_included(db_session):
    wc = _wc(db_session)
    a, b = _team(db_session, "A"), _team(db_session, "B")
    _finished(db_session, wc, a, b, 1, 0, datetime(2026, 6, 11, tzinfo=timezone.utc))
    scheduled = Match(tournament_id=wc.id, team_home_id=a.id, team_away_id=b.id,
                       stage="group", status="scheduled", kickoff_utc=datetime(2026, 6, 20, tzinfo=timezone.utc))
    db_session.add(scheduled)
    db_session.commit()

    rows = build_wc26_rows(db_session)
    assert len(rows) == 1


def test_replay_wc26_returns_metrics_and_production_reference(db_session):
    """replay_wc26 scores variants AND recomputes the stored production
    ledger numbers (from prediction_results) for reference — never
    hardcoded."""
    from app.models import Prediction, PredictionResult

    wc = _wc(db_session)
    mex, rsa = _team(db_session, "Mexico", elo=1800.0), _team(db_session, "South Africa", elo=1600.0)
    m = _finished(db_session, wc, mex, rsa, 2, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    pred = Prediction(match_id=m.id, model_version="poisson-elo-v0.2",
                       prob_home_win=0.6, prob_draw=0.25, prob_away_win=0.15,
                       predicted_score_home=2, predicted_score_away=0, is_shadow=False)
    db_session.add(pred)
    db_session.flush()
    db_session.add(PredictionResult(
        match_id=m.id, prediction_id=pred.id, model_version="poisson-elo-v0.2",
        is_shadow=False, actual_score_home=2, actual_score_away=0, outcome="home",
        winner_correct=True, exact_score_correct=True, prob_assigned=0.6,
        brier=0.34, log_loss=0.51, goal_error=0,
    ))
    db_session.commit()

    result = replay_wc26(db_session, variant_names=["v0.1-raw"])
    assert result["n_matches"] == 1
    assert "v0.1-raw" in result["variants"]
    assert result["production_reference"]["n"] == 1
    assert result["production_reference"]["accuracy"] == 1.0
    assert abs(result["production_reference"]["brier"] - 0.34) < 1e-9
    assert abs(result["production_reference"]["log_loss"] - 0.51) < 1e-9


def test_replay_wc26_no_writes_to_db(db_session):
    """Read-only guarantee: replay_wc26 must not add/commit any rows."""
    wc = _wc(db_session)
    mex, rsa = _team(db_session, "Mexico", elo=1800.0), _team(db_session, "South Africa", elo=1600.0)
    _finished(db_session, wc, mex, rsa, 2, 0, datetime(2026, 6, 11, 18, tzinfo=timezone.utc), host=mex)
    db_session.commit()

    before = {cls: db_session.query(cls).count() for cls in (Match, Team, Tournament)}
    replay_wc26(db_session, variant_names=["v0.1-raw"])
    after = {cls: db_session.query(cls).count() for cls in (Match, Team, Tournament)}
    assert before == after
