"""SQLAlchemy engine, session factory, and declarative Base.

Other modules import `Base` to define models and `get_db` as a FastAPI
dependency for request-scoped sessions.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# SQLite (used for local/dev) needs check_same_thread=False because uvicorn runs
# sync endpoints in a worker thread pool. Harmless to omit for Postgres.
_connect_args = (
    {"check_same_thread": False}
    if settings.sqlalchemy_url.startswith("sqlite")
    else {}
)
engine = create_engine(
    settings.sqlalchemy_url, pool_pre_ping=True, future=True, connect_args=_connect_args
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
