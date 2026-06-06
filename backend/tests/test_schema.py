"""Schema-builds test (task 2.10): the ORM metadata creates all MVP tables."""
from sqlalchemy import create_engine, inspect

from app.db import Base
import app.models  # noqa: F401


def test_all_mvp_tables_build():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "tournaments", "teams", "groups", "group_teams", "matches",
        "historical_matches", "team_stats", "predictions", "standings", "odds",
    }
    assert expected.issubset(tables)
