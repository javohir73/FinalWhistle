"""Tests for the club walk-forward selection harness."""
from __future__ import annotations

import pytest

from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
    loss_1x2,
    loss_totals,
    replay,
    season_clustered_ci,
    seasons_of,
    walk_forward,
)
from ml.ratings.elo import BASE_RATING, MatchInput, k_factor, replay_with_prematch

COMP = "Premier League"


def _matches() -> list[ClubMatch]:
    """Two seasons, four clubs, with one club appearing only in season two."""
    return [
        ClubMatch("1617", "Arsenal", "Chelsea", 2, 1),
        ClubMatch("1617", "Chelsea", "Everton", 0, 0),
        ClubMatch("1617", "Everton", "Arsenal", 1, 3),
        ClubMatch("1617", "Arsenal", "Everton", 4, 0),
        ClubMatch("1718", "Chelsea", "Arsenal", 1, 1),
        ClubMatch("1718", "Fulham", "Everton", 2, 0),
        ClubMatch("1718", "Arsenal", "Fulham", 3, 2),
        ClubMatch("1718", "Everton", "Chelsea", 0, 2),
    ]


def test_replay_is_identical_to_elo_module_when_nothing_is_enabled():
    """The safety property: enabling no option changes no rating.

    If this ever fails, every offline fit selected with this harness is
    measuring something production does not do.
    """
    ms = _matches()
    ids: dict[str, int] = {}

    def _id(name: str) -> int:
        return ids.setdefault(name, len(ids))

    reference_rows, _ = replay_with_prematch(
        [MatchInput(_id(m.home), _id(m.away), m.goals_home, m.goals_away, COMP, False)
         for m in ms],
        home_advantage=60.0,
    )
    ours = replay(ms, EloConfig(home_adv=60.0), COMP)

    assert len(ours) == len(reference_rows)
    for (ph, pa), ref in zip(ours, reference_rows):
        assert ph == ref["pre_home"]
        assert pa == ref["pre_away"]


def test_k_override_matching_k_factor_is_a_no_op():
    """Threading K explicitly must reproduce the implicit lookup exactly."""
    ms = _matches()
    implicit = replay(ms, EloConfig(k=None), COMP)
    explicit = replay(ms, EloConfig(k=k_factor(COMP)), COMP)
    assert implicit == explicit


def test_k_override_changes_ratings_when_it_differs():
    ms = _matches()
    low = replay(ms, EloConfig(k=10.0), COMP)
    high = replay(ms, EloConfig(k=50.0), COMP)
    # First match is everyone's cold start, so it can't differ; later ones must.
    assert low[0] == high[0]
    assert low[-1] != high[-1]


def test_shrinkage_pulls_ratings_toward_base_at_the_season_boundary():
    ms = _matches()
    none = replay(ms, EloConfig(shrinkage=0.0), COMP)
    half = replay(ms, EloConfig(shrinkage=0.5), COMP)

    # Season one is untouched — shrinkage only fires on a season change.
    assert none[:4] == half[:4]

    # Arsenal leads season one; at the boundary it must move toward BASE_RATING.
    arsenal_none = none[4][1]  # match 5 is Chelsea v Arsenal -> Arsenal away
    arsenal_half = half[4][1]
    assert arsenal_none > BASE_RATING
    assert BASE_RATING < arsenal_half < arsenal_none
    assert arsenal_half == pytest.approx(
        BASE_RATING + 0.5 * (arsenal_none - BASE_RATING)
    )


def test_promoted_prior_applies_only_to_clubs_new_after_the_opening_season():
    ms = _matches()
    seeded = replay(ms, EloConfig(promoted_prior=1400.0), COMP)
    plain = replay(ms, EloConfig(), COMP)

    # Season one clubs are the starting population, not promotions.
    assert seeded[0] == plain[0] == (BASE_RATING, BASE_RATING)

    # Fulham first appears in 1718 (match index 5, at home).
    assert plain[5][0] == BASE_RATING
    assert seeded[5][0] == 1400.0


def test_seasons_of_is_chronological():
    assert seasons_of(_matches()) == ["1617", "1718"]


def test_losses_are_per_match_and_positive():
    ms = _matches()
    pre = replay(ms, EloConfig(), COMP)
    wdl = loss_1x2(ms, pre, EloConfig(), GridConfig())
    ou = loss_totals(ms, pre, EloConfig(), GridConfig())
    assert len(wdl) == len(ou) == len(ms)
    assert all(x > 0 for x in wdl)
    assert all(x > 0 for x in ou)


def test_totals_loss_responds_to_base_in_the_right_direction():
    """A higher lambda sum must raise P(over), lowering the loss on an over."""
    ms = [ClubMatch("1617", "A", "B", 3, 2)]  # total 5 -> over 2.5
    pre = replay(ms, EloConfig(), COMP)
    low = loss_totals(ms, pre, EloConfig(), GridConfig(base=1.0))[0]
    high = loss_totals(ms, pre, EloConfig(), GridConfig(base=1.6))[0]
    assert high < low


def test_walk_forward_refuses_the_confirmation_season_when_asked_explicitly():
    ms = _matches() + [ClubMatch(CONFIRM_SEASON, "Arsenal", "Chelsea", 1, 0)]
    with pytest.raises(ValueError, match="quarantined"):
        walk_forward(
            ms,
            grid_points=[(1.2,)],
            build=lambda p: (EloConfig(), GridConfig(base=p[0])),
            control=(EloConfig(), GridConfig()),
            loss=loss_1x2,
            competition=COMP,
            scored_seasons=[CONFIRM_SEASON],
        )


def test_walk_forward_excludes_the_confirmation_season_by_default():
    """The safe path is the one you get by not thinking about it."""
    ms = _matches() + [ClubMatch(CONFIRM_SEASON, "Arsenal", "Chelsea", 1, 0)]
    out = walk_forward(
        ms,
        grid_points=[(1.2,), (1.4,)],
        build=lambda p: (EloConfig(), GridConfig(base=p[0])),
        control=(EloConfig(), GridConfig()),
        loss=loss_1x2,
        competition=COMP,
    )
    assert CONFIRM_SEASON not in out["scored_seasons"]
    assert out["scored_seasons"] == ["1718"]


def test_walk_forward_allows_the_confirmation_season_when_opted_in():
    ms = _matches() + [ClubMatch(CONFIRM_SEASON, "Arsenal", "Chelsea", 1, 0)]
    out = walk_forward(
        ms,
        grid_points=[(1.2,), (1.4,)],
        build=lambda p: (EloConfig(), GridConfig(base=p[0])),
        control=(EloConfig(), GridConfig()),
        loss=loss_1x2,
        competition=COMP,
        scored_seasons=[CONFIRM_SEASON],
        allow_confirm_season=True,
    )
    assert out["scored_seasons"] == [CONFIRM_SEASON]


def test_walk_forward_never_scores_the_first_season():
    """Nothing precedes it, so there is nothing leak-free to fit on."""
    out = walk_forward(
        _matches(),
        grid_points=[(1.2,), (1.4,)],
        build=lambda p: (EloConfig(), GridConfig(base=p[0])),
        control=(EloConfig(), GridConfig()),
        loss=loss_1x2,
        competition=COMP,
    )
    assert out["scored_seasons"] == ["1718"]
    assert "1617" not in out["deltas"]


def test_walk_forward_selects_using_only_prior_seasons():
    """Changing ONLY the scored season's results must not change the pick."""
    base_ms = _matches()

    def pick(ms):
        return walk_forward(
            ms,
            grid_points=[(1.0,), (1.2,), (1.6,)],
            build=lambda p: (EloConfig(), GridConfig(base=p[0])),
            control=(EloConfig(), GridConfig()),
            loss=loss_totals,
            competition=COMP,
        )["chosen"]["1718"]

    original = pick(base_ms)

    # Rewrite every 1718 scoreline to a goal-fest. If selection leaked, the
    # chosen base would jump; it must not.
    tampered = [
        ClubMatch(m.season, m.home, m.away, 5, 4) if m.season == "1718" else m
        for m in base_ms
    ]
    assert pick(tampered) == original


def test_control_delta_is_zero_when_the_grid_is_only_the_control():
    out = walk_forward(
        _matches(),
        grid_points=[(1.2,)],
        build=lambda p: (EloConfig(), GridConfig(base=p[0])),
        control=(EloConfig(), GridConfig(base=1.2)),
        loss=loss_1x2,
        competition=COMP,
    )
    assert all(v == 0.0 for vals in out["deltas"].values() for v in vals)


def test_season_clustered_ci_verdicts():
    better = season_clustered_ci({"a": [-1.0] * 20, "b": [-1.1] * 20, "c": [-0.9] * 20})
    assert better["ci95"][1] < 0
    assert "BETTER" in better["verdict"]

    worse = season_clustered_ci({"a": [1.0] * 20, "b": [1.1] * 20, "c": [0.9] * 20})
    assert "WORSE" in worse["verdict"]

    noise = season_clustered_ci({"a": [-1.0] * 20, "b": [1.0] * 20, "c": [0.0] * 20})
    assert "NO CREDIBLE DIFFERENCE" in noise["verdict"]


def test_season_clustered_ci_is_deterministic():
    d = {"a": [0.1, -0.2, 0.3], "b": [-0.1, 0.4, -0.3]}
    assert season_clustered_ci(d) == season_clustered_ci(d)


def test_season_clustered_ci_handles_no_data():
    assert season_clustered_ci({})["n"] == 0
