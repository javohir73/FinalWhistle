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
