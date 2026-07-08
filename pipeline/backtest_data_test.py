"""Tests for build_enriched_rows' leak-free residual-ledger enrichment (model
v2 design doc §5 / C1). Each row carries ledger_home/ledger_away: the time-
ordered (gf_residual, ga_residual) history of that side's team, capped at the
last 15 matches, computed against the model's own pre-match expectation so a
match never sees its own result.
"""
from datetime import datetime, timezone

from app.models import HistoricalMatch, Team
from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, expected_goals_from_elo
from pipeline.backtest_data import LEDGER_CAP, build_enriched_rows


def _seed(db, matches):
    """matches: list of (home_name, away_name, score_home, score_away, date)."""
    names = {name for m in matches for name in (m[0], m[1])}
    teams = {n: Team(name=n) for n in names}
    db.add_all(teams.values())
    db.flush()
    for home, away, sh, sa, d in matches:
        db.add(
            HistoricalMatch(
                date=d, team_a_id=teams[home].id, team_b_id=teams[away].id,
                score_a=sh, score_b=sa, competition="Friendly", is_neutral=True,
            )
        )
    db.commit()
    return teams


def _d(y, m, day):
    return datetime(y, m, day, tzinfo=timezone.utc)


def test_rows_carry_ledger_keys(db_session):
    _seed(db_session, [("Alpha", "Beta", 2, 0, _d(2020, 1, 1))])
    rows = build_enriched_rows(db_session)
    assert len(rows) == 1
    assert "ledger_home" in rows[0]
    assert "ledger_away" in rows[0]


def test_first_ever_match_has_empty_ledgers(db_session):
    """A team's first match has no prior history at all."""
    _seed(db_session, [("Alpha", "Beta", 2, 0, _d(2020, 1, 1))])
    rows = build_enriched_rows(db_session)
    assert rows[0]["ledger_home"] == []
    assert rows[0]["ledger_away"] == []


def test_leakage_second_match_sees_only_strictly_prior_result(db_session):
    """Explicit leakage guard: a match's own residual must not appear in its
    own ledger, only in matches that come strictly after it."""
    _seed(
        db_session,
        [
            ("Alpha", "Beta", 3, 0, _d(2020, 1, 1)),
            ("Alpha", "Gamma", 1, 1, _d(2020, 6, 1)),
        ],
    )
    rows = build_enriched_rows(db_session)
    first, second = rows[0], rows[1]

    # First match: Alpha has no prior history yet.
    assert first["ledger_home"] == []

    # Second match: Alpha's ledger has exactly ONE entry (the first match),
    # never the second match's own (1-1) result.
    assert len(second["ledger_home"]) == 1

    # The one ledger entry must reflect the FIRST match's residual, computed
    # from Alpha's PRE-match Elo at the time of that first match (1500, since
    # it was Alpha's own first match too) — not anything from match two.
    # build_enriched_rows defaults to the SERVED goals scale (model v2 review
    # finding), so the expectation here must be computed on that same scale.
    from ml.models.params import load_params

    served = load_params()
    pre_home_at_match1 = first["pre_home"]
    pre_away_at_match1 = first["pre_away"]
    lam_home, lam_away = expected_goals_from_elo(
        pre_home_at_match1, pre_away_at_match1, base=served.base, beta=served.beta,
    )
    expected_gf_residual = 3 - lam_home  # Alpha scored 3
    expected_ga_residual = 0 - lam_away  # Alpha conceded 0
    gf, ga = second["ledger_home"][0]
    assert abs(gf - expected_gf_residual) < 1e-9
    assert abs(ga - expected_ga_residual) < 1e-9


def test_ledger_is_time_ordered_most_recent_last(db_session):
    _seed(
        db_session,
        [
            ("Alpha", "Beta", 1, 0, _d(2020, 1, 1)),
            ("Alpha", "Gamma", 2, 0, _d(2020, 3, 1)),
            ("Alpha", "Delta", 0, 0, _d(2020, 6, 1)),
        ],
    )
    rows = build_enriched_rows(db_session)
    # Third row (Alpha vs Delta) should see both prior Alpha matches, in order.
    third = rows[2]
    assert len(third["ledger_home"]) == 2
    # Sanity: second entry (most recent) corresponds to the Jan-3rd-vs-Gamma
    # match, where Alpha scored 2 — its gf_residual should be higher than the
    # first (1-0 win) entry's, since a 2-0 beats expectation more than 1-0.
    assert third["ledger_home"][1][0] > third["ledger_home"][0][0]


def test_ledger_caps_at_last_15_matches(db_session):
    matches = [
        ("Alpha", f"Opp{i}", 1, 0, _d(2015 + i // 12, (i % 12) + 1, 1))
        for i in range(20)
    ]
    _seed(db_session, matches)
    rows = build_enriched_rows(db_session)
    # The 20th (last) row's ledger caps at 15 prior entries, not 19.
    last = rows[-1]
    assert len(last["ledger_home"]) == LEDGER_CAP
    assert LEDGER_CAP == 15


def test_ledger_uses_away_side_residual_convention(db_session):
    """The away team's ledger entry, when it is the away side of a later
    match, must reflect ITS gf/ga (not the home side's)."""
    _seed(
        db_session,
        [
            ("Alpha", "Beta", 0, 3, _d(2020, 1, 1)),  # Beta wins away 3-0
            ("Gamma", "Beta", 1, 1, _d(2020, 6, 1)),  # Beta now plays away again
        ],
    )
    rows = build_enriched_rows(db_session)
    second = rows[1]
    assert len(second["ledger_away"]) == 1
    gf, ga = second["ledger_away"][0]
    # Beta scored 3, conceded 0 in the first match (as the away side there).
    # Served-scale default (model v2 review finding) -- see the leakage test above.
    from ml.models.params import load_params

    served = load_params()
    first = rows[0]
    lam_home, lam_away = expected_goals_from_elo(
        first["pre_home"], first["pre_away"], base=served.base, beta=served.beta,
    )
    assert abs(gf - (3 - lam_away)) < 1e-9
    assert abs(ga - (0 - lam_home)) < 1e-9


def test_ledger_parameterized_by_base_and_beta(db_session):
    """Passing non-default base/beta changes the residuals (parameterized per
    the variant that will use them), proving the ledger isn't hardcoded to
    v0.1 constants internally even though they are the default."""
    _seed(
        db_session,
        [
            ("Alpha", "Beta", 3, 0, _d(2020, 1, 1)),
            ("Alpha", "Gamma", 1, 1, _d(2020, 6, 1)),
        ],
    )
    default_rows = build_enriched_rows(db_session)
    custom_rows = build_enriched_rows(db_session, base=1.6, beta=0.003)

    default_gf, _ = default_rows[1]["ledger_home"][0]
    custom_gf, _ = custom_rows[1]["ledger_home"][0]
    assert abs(default_gf - custom_gf) > 1e-6


def test_default_base_beta_match_served_params(db_session):
    """Default call uses the SERVED goals params (ml.models.params.load_params()),
    not the hardcoded v0.1 constants (model v2 review finding: ablation
    validity requires every ledger builder to measure residuals on the same
    scale the model actually serves predictions on)."""
    from ml.models.params import load_params

    _seed(db_session, [("Alpha", "Beta", 3, 0, _d(2020, 1, 1)),
                        ("Alpha", "Gamma", 1, 1, _d(2020, 6, 1))])
    served = load_params()
    rows = build_enriched_rows(db_session)
    lam_home, lam_away = expected_goals_from_elo(
        rows[0]["pre_home"], rows[0]["pre_away"], base=served.base, beta=served.beta,
    )
    gf, ga = rows[1]["ledger_home"][0]
    assert abs(gf - (3 - lam_home)) < 1e-9
    assert abs(ga - (0 - lam_away)) < 1e-9


def test_default_base_beta_differs_from_v01_constants_when_served_params_are_tuned(
    db_session, monkeypatch
):
    """Regression guard for the fix itself: if the served params' base/beta
    differ from the v0.1 constants, the default ledger must reflect the
    served values, not silently fall back to BASE_GOALS/ELO_TO_GOALS_BETA."""
    import pipeline.backtest_data as bd_mod
    from ml.models.params import DEFAULT_PARAMS

    tuned = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(), "base": 1.2, "beta": 0.0021}
    )
    monkeypatch.setattr(bd_mod, "load_params", lambda: tuned)

    _seed(db_session, [("Alpha", "Beta", 3, 0, _d(2020, 1, 1)),
                        ("Alpha", "Gamma", 1, 1, _d(2020, 6, 1))])
    rows = build_enriched_rows(db_session)
    lam_home_served, _ = expected_goals_from_elo(
        rows[0]["pre_home"], rows[0]["pre_away"], base=tuned.base, beta=tuned.beta,
    )
    lam_home_v01, _ = expected_goals_from_elo(
        rows[0]["pre_home"], rows[0]["pre_away"], base=BASE_GOALS, beta=ELO_TO_GOALS_BETA,
    )
    assert abs(lam_home_served - lam_home_v01) > 1e-6  # sanity: the two scales differ
    gf, _ = rows[1]["ledger_home"][0]
    assert abs(gf - (3 - lam_home_served)) < 1e-9


def test_existing_row_keys_unaffected(db_session):
    """Backwards-compat: the many existing callers of build_enriched_rows key
    off pre_home/pre_away/is_neutral/date/competition/score_home/score_away —
    those must be untouched by the ledger addition."""
    _seed(db_session, [("Alpha", "Beta", 2, 1, _d(2020, 1, 1))])
    rows = build_enriched_rows(db_session)
    row = rows[0]
    for key in ("home_id", "away_id", "pre_home", "pre_away", "is_neutral",
                "competition", "score_home", "score_away", "date"):
        assert key in row
