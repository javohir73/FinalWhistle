"""probability_snapshots stores one row per (sport, entity, market, ref, date)."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ProbabilitySnapshot


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_snapshot_roundtrip():
    db = _session()
    db.add(ProbabilitySnapshot(
        sport="football", entity_id=1, market="win_title",
        ref_id=None, prob=0.14, snapshot_date=date(2026, 7, 9),
    ))
    db.commit()
    row = db.query(ProbabilitySnapshot).one()
    assert row.market == "win_title"
    assert row.prob == 0.14
    assert row.snapshot_date == date(2026, 7, 9)
