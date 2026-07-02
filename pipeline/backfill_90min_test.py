"""Tests for the 90-minute score backfill (FR-2.3): already-finished matches
gain score_home_90/score_away_90 where it is derivable — group matches never
have extra time (copy the final), knockout matches derive from goal-event
minutes when the events reconcile exactly with the stored final score, and
anything unreconcilable is left NULL (evaluation falls back to the final)."""
from app.models import Match
from pipeline.backfill_90min import backfill_90min_scores


def _goals(*items):
    return [
        {"minute": minute, "side": side, "player": "P", "type": "goal"}
        for minute, side in items
    ]


def test_group_match_copies_final_score(db_session):
    m = Match(tournament_id=1, stage="group", status="finished",
              team_home_id=1, team_away_id=2, score_home=2, score_away=0)
    db_session.add(m)
    db_session.commit()

    n = backfill_90min_scores(db_session)

    assert n == 1
    assert (m.score_home_90, m.score_away_90) == (2, 0)


def test_ko_match_derives_from_reconciling_goal_events(db_session):
    # Final 3-2 after extra time; regulation ended 1-1.
    m = Match(tournament_id=1, stage="R32", status="finished",
              team_home_id=1, team_away_id=2, score_home=3, score_away=2,
              goal_events=_goals((10, "home"), (80, "away"), (95, "home"),
                                 (100, "home"), (110, "away")))
    db_session.add(m)
    db_session.commit()

    backfill_90min_scores(db_session)

    assert (m.score_home_90, m.score_away_90) == (1, 1)


def test_ko_match_with_unreconcilable_events_is_left_null(db_session):
    # Events don't add up to the stored final (missing/contaminated) — no guess.
    m = Match(tournament_id=1, stage="R32", status="finished",
              team_home_id=1, team_away_id=2, score_home=2, score_away=1,
              goal_events=_goals((10, "home")))
    db_session.add(m)
    db_session.commit()

    n = backfill_90min_scores(db_session)

    assert n == 0
    assert m.score_home_90 is None and m.score_away_90 is None


def test_existing_capture_is_never_overwritten(db_session):
    m = Match(tournament_id=1, stage="group", status="finished",
              team_home_id=1, team_away_id=2, score_home=2, score_away=0,
              score_home_90=1, score_away_90=0)  # live capture already ran
    db_session.add(m)
    db_session.commit()

    n = backfill_90min_scores(db_session)

    assert n == 0
    assert (m.score_home_90, m.score_away_90) == (1, 0)
