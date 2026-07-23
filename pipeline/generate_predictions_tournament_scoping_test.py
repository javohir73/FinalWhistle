"""Regression: generate_predictions(tournament_id=...) never mixes WC26 and
EPL groups/matches once both share the same DB (league pivot D5/D6).

Without scoping, a shared DB would merge the EPL's single "Premier League"
group into the international bracket's group count (len(groups) keyed by
group.name.split()[-1]) and would re-predict/-simulate the other
tournament's matches on every call — this file pins the fix.
"""
from app.models import Group, Match, Prediction, Standing, Team, TournamentOdds
from pipeline.generate_predictions import generate_predictions
from pipeline.ingest import league_structure as ls_mod
from pipeline.ingest.league_structure import load_league_structure
from pipeline.ingest.wc26_structure import load_structure as load_wc26_structure


def _set_elos(db):
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _seed_both_tournaments(db, monkeypatch):
    load_wc26_structure(db)
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        {
            "fixture": {"id": 9001, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "NS"}},
            "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
            "goals": {"home": None, "away": None},
        }
    ])
    load_league_structure(db, api_key="x")
    _set_elos(db)


def test_league_scoped_run_only_predicts_epl_matches(db_session, monkeypatch):
    _seed_both_tournaments(db_session, monkeypatch)
    epl_group = db_session.query(Group).filter_by(name="Premier League").one()
    epl_tournament_id = epl_group.tournament_id

    wc26_predictions_before = db_session.query(Prediction).count()
    wc26_standings_before = db_session.query(Standing).count()
    assert wc26_predictions_before == 0  # nothing predicted yet in this test

    summary = generate_predictions(
        db_session, model_version="poisson-elo-club-v0.1",
        n_sims=50, tournament_sims=50, tournament_id=epl_tournament_id,
    )

    assert summary["matches_predicted"] == 1
    assert summary["groups_simulated"] == 1
    assert summary["tournament_teams"] == 0  # 1 group < 12 -> bracket sim skipped cleanly

    epl_match = db_session.query(Match).filter_by(provider_fixture_id=9001).one()
    preds = db_session.query(Prediction).filter_by(match_id=epl_match.id, is_shadow=False).all()
    assert len(preds) == 1
    assert preds[0].model_version == "poisson-elo-club-v0.1"

    # No WC26 group match got predicted or re-standing'd by this call.
    wc26_group_matches = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.tournament_id != epl_tournament_id)
        .all()
    )
    wc26_match_ids = {m.id for m in wc26_group_matches}
    assert db_session.query(Prediction).filter(
        Prediction.match_id.in_(wc26_match_ids)
    ).count() == 0
    # Standings only got written for the EPL group's 20 teams, not WC26's 48.
    assert db_session.query(Standing).count() == 20
    assert db_session.query(TournamentOdds).count() == 0
