"""market_odds_snapshots: hourly exchange odds rows for the intel panel."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import MarketOddsSnapshot


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _row(**overrides):
    base = dict(
        sport="football", source="polymarket", market_type="match_winner",
        match_id=7, team_id=None, outcome="home", implied_prob=0.62,
        external_id="will-france-win", fetched_at=datetime(2026, 7, 10, 14, 0),
    )
    base.update(overrides)
    return MarketOddsSnapshot(**base)


def test_roundtrip():
    db = _session()
    db.add(_row())
    db.commit()
    row = db.query(MarketOddsSnapshot).one()
    assert (row.sport, row.source, row.outcome) == ("football", "polymarket", "home")
    assert row.implied_prob == 0.62
    assert row.match_id == 7 and row.team_id is None


def test_unique_key_rejects_duplicate_snapshot():
    db = _session()
    db.add(_row())
    db.commit()
    db.add(_row(implied_prob=0.63))  # same (source, external_id, outcome, fetched_at)
    with pytest.raises(IntegrityError):
        db.commit()
