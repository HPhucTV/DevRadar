from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import URL, make_url

TEST_DATABASE_URL_ENV = "DEVRADAR_TEST_DATABASE_URL"


@pytest.fixture
def fresh_postgresql_url() -> Iterator[str]:
    configured_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not configured_url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not set")

    sqlalchemy_url = make_url(configured_url)
    if sqlalchemy_url.drivername != "postgresql+psycopg":
        pytest.fail(f"{TEST_DATABASE_URL_ENV} must use postgresql+psycopg://")

    database_name = f"devradar_test_{uuid4().hex}"
    admin_url = _psycopg_url(sqlalchemy_url, database="postgres")

    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    test_url = sqlalchemy_url.set(database=database_name).render_as_string(hide_password=False)
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _psycopg_url(url: URL, *, database: str) -> str:
    return url.set(drivername="postgresql", database=database).render_as_string(hide_password=False)
