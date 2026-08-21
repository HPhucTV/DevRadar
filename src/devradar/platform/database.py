"""PostgreSQL metadata and connection configuration."""

from __future__ import annotations

import os

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

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
