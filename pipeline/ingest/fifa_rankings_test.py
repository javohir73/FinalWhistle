"""Tests for FIFA rankings application (task 2.10)."""
import pandas as pd

from app.models import Team
from pipeline.ingest.fifa_rankings import apply_rankings


def test_apply_updates_existing_and_reports_unmatched(db_session):
    db_session.add_all([Team(name="Brazil"), Team(name="France")])
    db_session.commit()

    df = pd.DataFrame(
        [
            {"team": "Brazil", "rank": 5},
            {"team": "France", "rank": 2},
            {"team": "Korea Republic", "rank": 23},  # not in DB -> unmatched
        ]
    )
    summary = apply_rankings(db_session, df)

    assert summary["updated"] == 2
    assert summary["unmatched"] == ["South Korea"]  # normalized name reported
    assert db_session.query(Team).filter_by(name="Brazil").one().fifa_rank == 5


def test_apply_rejects_missing_columns(db_session):
    import pytest

    with pytest.raises(ValueError):
        apply_rankings(db_session, pd.DataFrame({"team": ["Brazil"]}))
