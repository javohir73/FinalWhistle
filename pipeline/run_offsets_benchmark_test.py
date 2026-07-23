from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Prediction, Team, Tournament
from ml.evaluation.offsets_benchmark import benchmark_offsets
from pipeline.generate_predictions import OFFSETS_MODEL_VERSION
from pipeline.run_offsets_benchmark import _verdict, offsets_record

_EMPTY_LEDGER = {"n_matches": 0, "verdict": "insufficient", "production": None,
                 "offsets": None, "diff_log_loss": None, "diff_ci95": None,
                 "offsets_win_rate": None}
_EMPTY = {**_EMPTY_LEDGER, "club": _EMPTY_LEDGER}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _finished(db, wc, home, away, sh, sa):
    m = Match(tournament_id=wc.id, stage="group", status="finished",
              team_home_id=home.id, team_away_id=away.id, score_home=sh, score_away=sa)
    db.add(m); db.flush()
    return m


def _pred(db, m, mv, probs, *, is_shadow):
    db.add(Prediction(match_id=m.id, model_version=mv,
                      prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                      predicted_score_home=2, predicted_score_away=0, is_shadow=is_shadow))
    db.flush()


def _fixture(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    return wc, home, away


def test_scores_matches_with_both_rows():
    db = _session()
    wc, home, away = _fixture(db)
    m = _finished(db, wc, home, away, 2, 0)  # home win
    _pred(db, m, "poisson-elo-v0.2", (0.55, 0.25, 0.20), is_shadow=False)   # published
    _pred(db, m, OFFSETS_MODEL_VERSION, (0.70, 0.18, 0.12), is_shadow=True)  # twin, surer on H
    db.commit()

    rec = offsets_record(db)
    direct = benchmark_offsets([(0.55, 0.25, 0.20)], [(0.70, 0.18, 0.12)], ["H"])
    assert {k: rec[k] for k in direct} == direct          # same numbers as calling the scorer directly
    assert rec["verdict"] == "offsets_beats_published"  # twin surer on the actual winner


def test_excludes_match_missing_twin():
    # A valid BOTH-rows match alongside a published-only (twinless) match: the
    # twinless one must be dropped WHILE the valid one survives — proving
    # exclusion, not merely an empty result an empty DB would also produce.
    db = _session()
    wc, home, away = _fixture(db)
    good = _finished(db, wc, home, away, 2, 0)
    _pred(db, good, "poisson-elo-v0.2", (0.55, 0.25, 0.20), is_shadow=False)
    _pred(db, good, OFFSETS_MODEL_VERSION, (0.70, 0.18, 0.12), is_shadow=True)
    twinless = _finished(db, wc, home, away, 1, 0)
    _pred(db, twinless, "poisson-elo-v0.2", (0.5, 0.3, 0.2), is_shadow=False)  # no twin
    db.commit()
    assert offsets_record(db)["n_matches"] == 1


def test_honest_empty_with_no_data():
    assert offsets_record(_session()) == _EMPTY


# --- league pivot ledger scoping (same leak as the shadow fix, PR #171) ------

def _club_fixture(db):
    epl = Tournament(name="Premier League 2026-27", year=2026)
    home, away = Team(name="Arsenal"), Team(name="Chelsea")
    db.add_all([epl, home, away]); db.flush()
    return epl, home, away


def test_club_ledger_never_pools_into_wc26():
    """A WC26 pair and an EPL pair in the same DB: the top-level record must
    hold ONLY the WC26 pair (its sample cannot move because an EPL match
    finished), with the EPL pair reported separately under "club"."""
    db = _session()
    wc, home, away = _fixture(db)
    m = _finished(db, wc, home, away, 2, 0)
    _pred(db, m, "poisson-elo-v0.2", (0.55, 0.25, 0.20), is_shadow=False)
    _pred(db, m, OFFSETS_MODEL_VERSION, (0.70, 0.18, 0.12), is_shadow=True)
    epl, ars, che = _club_fixture(db)
    em = _finished(db, epl, ars, che, 3, 1)
    _pred(db, em, "poisson-elo-club-v0.1", (0.50, 0.30, 0.20), is_shadow=False)
    _pred(db, em, "poisson-elo-club-v0.1+xg", (0.62, 0.24, 0.14), is_shadow=True)
    db.commit()

    rec = offsets_record(db)
    assert rec["n_matches"] == 1  # the WC26 pair only
    assert rec["verdict"] == "offsets_beats_published"
    assert rec["club"]["n_matches"] == 1  # the EPL pair, own ledger
    assert rec["club"]["verdict"] == "offsets_beats_published"


def test_club_match_with_frozen_wc26_tag_twin_pairs_nowhere():
    """The pre-fix corruption shape: an EPL twin wrongly tagged with the frozen
    WC26 constant must not pair into EITHER ledger — the club production row
    only ever pairs with its own derived "+xg" tag."""
    db = _session()
    epl, ars, che = _club_fixture(db)
    em = _finished(db, epl, ars, che, 3, 1)
    _pred(db, em, "poisson-elo-club-v0.1", (0.50, 0.30, 0.20), is_shadow=False)
    _pred(db, em, OFFSETS_MODEL_VERSION, (0.62, 0.24, 0.14), is_shadow=True)
    db.commit()

    rec = offsets_record(db)
    assert rec["n_matches"] == 0
    assert rec["club"]["n_matches"] == 0


def test_verdict_covers_all_three_branches():
    assert _verdict((-0.05, -0.01)) == "offsets_beats_published"  # CI hi < 0
    assert _verdict((0.01, 0.05)) == "published_beats_offsets"    # CI lo > 0
    assert _verdict((-0.02, 0.03)) == "no_credible_difference"    # straddles 0
