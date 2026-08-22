from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.mark.postgresql
def test_extraction_result_table_and_constraints_on_fresh_postgresql(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    alembic_config = _alembic_config()

    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)

    engine = create_engine(fresh_postgresql_url)
    inspector = inspect(engine)
    assert "extraction_results" in inspector.get_table_names()
    check_names = {check["name"] for check in inspector.get_check_constraints("extraction_results")}
    assert {
        "ck_extraction_results_input_hash",
        "ck_extraction_results_status",
        "ck_extraction_results_confidence",
        "ck_extraction_results_non_negative_metrics",
    } <= check_names
    indexes = {index["name"] for index in inspector.get_indexes("extraction_results")}
    assert "uq_extraction_results_accepted_cache" in indexes
