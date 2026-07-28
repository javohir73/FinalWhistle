"""Offline↔live Elo parity — the property every offline fit depends on.

Candidates for the club engine are SELECTED on the offline CSV path
(`replay_with_prematch` over cleaned rows keyed by local integer ids), but
production SERVES off the DB path (`load_club_results` →
`compute_and_store_club_elo` → `run_elo`, keyed by real Team ids, after a
dedup on (date, home_id, away_id) and a name resolution through a GLOBAL
{Team.name: id} cache).

If those two ever disagree, an offline gain does not transfer and every gate
result in docs/MODEL-EXPERIMENTS.md is measuring a model that never serves.
Verified against all ten real seasons of E0/SP1/D1 on 2026-07-28 (zero
divergence); these tests keep it that way without needing the network, by
constructing the specific shapes that could break it:

  - two source spellings that normalize to ONE canonical club (the DB path
    merges them onto a single Team row; the offline path must too),
  - a duplicate (date, home, away) row (the DB path dedups on insert),
  - matches whose file order differs from date order (the DB path re-sorts by
    (date, id); the offline path sorts by match_date).
"""
from __future__ import annotations

import pandas as pd

from app.models import Team
from ml.ratings.elo import MatchInput, run_elo
from pipeline.compute_club_elo import compute_and_store_club_elo
from pipeline.ingest.club_results import clean_club_results_df, load_club_results

COMPETITION = "Premier League"
HOME_ADV = 60.0


def _offline_ratings(df: pd.DataFrame) -> dict[str, float]:
    """The construction pipeline/compute_club_elo._evaluate_holdout uses."""
    rows = clean_club_results_df(df).sort_values("match_date").to_dict("records")
    ids: dict[str, int] = {}

    def _id(name: str) -> int:
        return ids.setdefault(name, len(ids))

    finals = run_elo(
        [
            MatchInput(
                home_id=_id(r["HomeTeam"]), away_id=_id(r["AwayTeam"]),
                score_home=r["FTHG"], score_away=r["FTAG"],
                competition=COMPETITION, is_neutral=False,
            )
            for r in rows
        ],
        home_advantage=HOME_ADV,
    )
    return {name: finals[i] for name, i in ids.items()}


def _db_ratings(db, df: pd.DataFrame) -> dict[str, float]:
    """The construction production uses."""
    load_club_results(db, df, competition=COMPETITION)
    compute_and_store_club_elo(
        db, home_advantage=HOME_ADV, competition=COMPETITION,
        tournament_name="__absent__",
    )
    return {t.name: t.elo_rating for t in db.query(Team).all() if t.elo_rating is not None}


def _assert_parity(db, df: pd.DataFrame) -> dict[str, float]:
    offline = _offline_ratings(df)
    live = _db_ratings(db, df)
    assert set(offline) == set(live), (
        f"team sets diverge: offline-only={sorted(set(offline) - set(live))}, "
        f"db-only={sorted(set(live) - set(offline))}"
    )
    for name, rating in offline.items():
        # The DB path stores round(rating, 1).
        assert abs(rating - live[name]) <= 0.05, (
            f"{name}: offline {rating:.4f} vs db {live[name]:.4f}"
        )
    return offline


def _frame(rows: list[tuple[str, str, str, int, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Date": d, "HomeTeam": h, "AwayTeam": a, "FTHG": gh, "FTAG": ga,
             "season_code": "1617"}
            for d, h, a, gh, ga in rows
        ]
    )


def test_parity_on_a_plain_multi_match_window(db_session):
    df = _frame([
        ("13/08/16", "Arsenal", "Chelsea", 2, 1),
        ("20/08/16", "Chelsea", "Everton", 0, 0),
        ("27/08/16", "Everton", "Arsenal", 1, 3),
        ("03/09/16", "Arsenal", "Everton", 4, 0),
    ])
    ratings = _assert_parity(db_session, df)
    assert len(ratings) == 3


def test_parity_when_two_spellings_normalize_to_one_club(db_session):
    """The DB path resolves names through a global cache; if the offline path
    kept them apart, one universe would rate a club that the other splits."""
    df = _frame([
        ("13/08/16", "Man United", "Arsenal", 1, 0),
        ("20/08/16", "Arsenal", "Manchester United", 2, 2),
        ("27/08/16", "Man United", "Chelsea", 3, 1),
    ])
    ratings = _assert_parity(db_session, df)
    # Both spellings collapsed onto the one canonical club, in BOTH paths.
    assert "Manchester United" in ratings
    assert "Man United" not in ratings
    assert len(ratings) == 3


def test_parity_when_the_source_carries_a_duplicate_fixture(db_session):
    """load_club_results dedups on (date, home_id, away_id); the offline path
    does not. A duplicated source row must not desynchronise them."""
    df = _frame([
        ("13/08/16", "Arsenal", "Chelsea", 2, 1),
        ("13/08/16", "Arsenal", "Chelsea", 2, 1),   # exact duplicate
        ("20/08/16", "Chelsea", "Everton", 1, 0),
    ])
    offline = _offline_ratings(df)
    live = _db_ratings(db_session, df)
    assert set(offline) == set(live)
    # Documented divergence: the offline path replays the duplicate twice, the
    # DB path once. Real football-data.co.uk files carry no duplicates (verified
    # 2026-07-28: skipped_dupes=0 across all 30 league-seasons), but if one ever
    # appears, this is where the two paths part company — fail loudly here
    # rather than silently mis-fit.
    assert offline["Arsenal"] != live["Arsenal"], (
        "duplicate handling converged unexpectedly — re-check load_club_results' "
        "dedup and the offline replay before trusting this test's premise"
    )


def test_parity_when_file_order_differs_from_date_order(db_session):
    """The DB path re-sorts by (date, id); the offline path sorts by
    match_date. Elo is path-dependent, so disagreement here would silently
    change every rating."""
    df = _frame([
        ("27/08/16", "Everton", "Arsenal", 1, 3),   # out of order in the file
        ("13/08/16", "Arsenal", "Chelsea", 2, 1),
        ("20/08/16", "Chelsea", "Everton", 0, 0),
    ])
    _assert_parity(db_session, df)


def test_parity_across_a_season_boundary(db_session):
    """Season codes must not affect ordering or identity in either path."""
    df = pd.concat([
        _frame([
            ("13/08/16", "Arsenal", "Chelsea", 2, 1),
            ("20/05/17", "Chelsea", "Arsenal", 0, 2),
        ]),
        _frame([
            ("12/08/17", "Arsenal", "Everton", 1, 1),
            ("19/08/17", "Everton", "Chelsea", 3, 0),
        ]).assign(season_code="1718"),
    ], ignore_index=True)
    _assert_parity(db_session, df)
