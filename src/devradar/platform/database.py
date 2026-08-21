"""PostgreSQL metadata and connection configuration."""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

DATABASE_URL_ENV = "DEVRADAR_DATABASE_URL"


class Base(DeclarativeBase):
    """Base for all SQLAlchemy mappings in the monolith."""

    metadata = MetaData()


def get_database_url() -> str:
    """Return the explicitly configured PostgreSQL URL."""

    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        raise RuntimeError(f"{DATABASE_URL_ENV} must be set")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError(f"{DATABASE_URL_ENV} must use postgresql+psycopg://")
    return database_url


@lru_cache(maxsize=1)
def _database_engine(database_url: str) -> Engine:
    return create_engine(database_url)


def get_database_session() -> Iterator[Session]:
    """Yield one synchronous read/write session scoped to an API request."""

    with Session(_database_engine(get_database_url())) as session:
        yield session
