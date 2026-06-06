"""Shared pytest fixtures.

Provides an isolated in-memory SQLite database per test so the suite never needs
a running Postgres. The same ORM models run on both engines (they are
deliberately DB-agnostic).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
import app.models  # noqa: F401  (registers all models on Base.metadata)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
