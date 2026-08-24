from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine
from integration.test_read_api import ApiSeed, _seed_database

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def visibility_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, ApiSeed]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    engine = _database_engine(fresh_postgresql_url)
    with Session(engine) as session:
        seed = _seed_database(session)
    with TestClient(app) as client:
        yield client, seed
    engine.dispose()
    _database_engine.cache_clear()


@pytest.mark.postgresql
def test_local_recipe_feature_widens_read_and_analytics_consistently(
    visibility_api: tuple[TestClient, ApiSeed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seed = visibility_api

    hidden_jobs = client.get(
        "/api/v1/jobs",
        params={"sourceId": str(seed.custom_source_id)},
    )
    hidden_skills = client.get(
        "/api/v1/skills",
        params={"sourceId": str(seed.custom_source_id)},
    )
    assert hidden_jobs.json()["pagination"]["totalItems"] == 0
    assert hidden_skills.json()["meta"]["cohortSize"] == 0

    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")

    jobs = client.get("/api/v1/jobs", params={"sourceId": str(seed.custom_source_id)})
    source = client.get(f"/api/v1/sources/{seed.custom_source_id}")
    job = client.get(f"/api/v1/jobs/{seed.custom_job_id}")
    changes = client.get(f"/api/v1/jobs/{seed.custom_job_id}/changes")
    runs = client.get("/api/v1/crawl-runs", params={"sourceId": str(seed.custom_source_id)})
    run = client.get(f"/api/v1/crawl-runs/{seed.custom_run_id}")
    skills = client.get("/api/v1/skills", params={"sourceId": str(seed.custom_source_id)})

    assert jobs.json()["pagination"]["totalItems"] == 1
    assert source.status_code == job.status_code == changes.status_code == run.status_code == 200
    assert source.json()["data"]["approvalStatus"] == "owner_authorized_local"
    assert runs.json()["pagination"]["totalItems"] == 1
    assert skills.json()["meta"]["cohortSize"] == 1
    assert [item["name"] for item in skills.json()["data"]] == ["private-skill"]
