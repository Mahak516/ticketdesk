"""Engine, session factory and the FastAPI database dependency.

The engine is created lazily so importing the app never needs a live database.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings
from .decorators import retry


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


@retry(times=10, delay=1.0, exceptions=(OperationalError,))
def init_db(engine: Engine | None = None) -> None:
    """Create tables. Retries so the API can start while PostgreSQL is still booting."""
    from . import models  # noqa: F401  (registers the tables on Base.metadata)

    Base.metadata.create_all(engine or get_engine())
