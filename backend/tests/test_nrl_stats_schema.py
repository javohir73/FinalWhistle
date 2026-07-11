"""Wave 2 schema: the ORM metadata builds nrl_match_stats + nrl_try_events
(same pattern as backend/tests/test_schema.py)."""
from sqlalchemy import create_engine, inspect

from app.db import Base
import app.models  # noqa: F401  (registers all models on Base.metadata)


def test_nrl_stats_tables_build():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"nrl_match_stats", "nrl_try_events"}.issubset(tables)

    stat_cols = {c["name"] for c in inspector.get_columns("nrl_match_stats")}
    assert {"id", "match_id", "team", "tries", "conversions", "penalties_conceded",
            "errors", "set_restarts", "run_metres", "line_breaks", "tackles",
            "tackle_efficiency", "created_at"} <= stat_cols

    try_cols = {c["name"] for c in inspector.get_columns("nrl_try_events")}
    assert {"id", "match_id", "team", "player", "minute",
            "score_home", "score_away"} <= try_cols

    uqs = {u["name"] for u in inspector.get_unique_constraints("nrl_match_stats")}
    assert "uq_nrl_match_stats_match_team" in uqs
