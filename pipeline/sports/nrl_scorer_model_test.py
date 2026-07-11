import math

from app.models import NrlTeamList, SportMatch, NrlTryEvent
from pipeline.sports.nrl_scorer_model import (
    opponent_concession_rate, player_empirical_rate, position_prior,
    project_p_anytime, project_scorer,
)


def test_player_empirical_rate_uses_last10_only_when_no_older_games():
    rate = player_empirical_rate([1, 0, 1, 0, 0], tries_season=2, games_season=5)
    assert rate == 2 / 5


def test_player_empirical_rate_weights_recent_games_double():
    last10 = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]  # 5 scored of 10
    rate = player_empirical_rate(last10, tries_season=10, games_season=20)
    older_rate = 1 - math.exp(-5 / 10)
    expected = (2 * 5 + 10 * older_rate) / (2 * 10 + 10)
    assert abs(rate - expected) < 1e-9


def test_player_empirical_rate_handles_zero_games():
    assert player_empirical_rate([], tries_season=0, games_season=0) == 0.0


def _seed_try_history(db):
    m1 = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="finished",
                     score_home=20, score_away=10)
    m2 = SportMatch(sport="nrl", season=2026, round=2, match_no=1, status="finished",
                     score_home=18, score_away=6)
    db.add_all([m1, m2]); db.flush()
    db.add_all([
        NrlTeamList(match_id=m1.id, team="Broncos", jersey=2, player="A. Wing", position="WG"),
        NrlTeamList(match_id=m1.id, team="Storm", jersey=13, player="B. Lock", position="LK"),
        NrlTeamList(match_id=m2.id, team="Broncos", jersey=2, player="A. Wing", position="WG"),
        NrlTeamList(match_id=m2.id, team="Roosters", jersey=9, player="C. Hooker", position="HK"),
    ])
    db.add_all([
        NrlTryEvent(match_id=m1.id, team="Broncos", player="A. Wing", minute=10, score_home=4, score_away=0),
        NrlTryEvent(match_id=m2.id, team="Broncos", player="A. Wing", minute=20, score_home=4, score_away=0),
    ])
    db.commit()


def test_position_prior_falls_back_when_no_tagged_history(db_session):
    assert position_prior(db_session, "FB") == 0.55


def test_position_prior_uses_tagged_history_when_present(db_session):
    _seed_try_history(db_session)
    rate = position_prior(db_session, "WG")
    assert 0.0 < rate <= 1.0


def test_opponent_concession_rate_attributes_tries_to_the_other_team(db_session):
    _seed_try_history(db_session)
    # Storm faced Broncos in m1 and conceded a WG try; Storm doesn't appear
    # in m2, so its rate reflects only m1.
    assert opponent_concession_rate(db_session, "Storm", "WG") == 1.0


def test_opponent_concession_rate_falls_back_to_position_prior_when_unseen(db_session):
    _seed_try_history(db_session)
    assert opponent_concession_rate(db_session, "Sea Eagles", "FB") == position_prior(db_session, "FB")


def test_project_p_anytime_is_clamped_to_unit_interval():
    assert project_p_anytime(1.5, 1.5, 1.5) == 1.0
    assert project_p_anytime(-1.0, -1.0, -1.0) == 0.0


def test_project_scorer_blends_all_three_signals(db_session):
    _seed_try_history(db_session)
    p = project_scorer(db_session, opponent_team="Storm", position="WG",
                        last10_tries=[1, 0, 1], tries_season=2, games_season=3)
    assert 0.0 <= p <= 1.0
