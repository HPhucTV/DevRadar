from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from devradar.auth.models import AuthRole, User
from devradar.auth.service import (
    AUTH_ENABLED_ENV,
    OPERATOR_PASSWORD_HASH_ENV,
    OPERATOR_USERNAME_ENV,
    hash_password,
)
from devradar.catalog.models import Job, JobChange
from devradar.custom_sources.models import CustomSourceProfile, CustomSourceStatus
from devradar.custom_sources.parser import CustomCandidate, CustomFieldProvenance, CustomParseResult
from devradar.ingestion.models import CrawlRun, Source
from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "custom-source-test-password"


def test_patch_openapi_only_advertises_owner_status_transitions() -> None:
    with TestClient(app) as client:
        document = client.get("/api/v1/openapi.json").json()

    status_schema = document["components"]["schemas"]["CustomSourcePatch"]["properties"]["status"]
    assert status_schema["anyOf"][0]["enum"] == ["enabled", "paused"]


@pytest.fixture
def custom_source_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, str]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv(AUTH_ENABLED_ENV, "true")
    monkeypatch.setenv(OPERATOR_USERNAME_ENV, "operator")
    monkeypatch.setenv(OPERATOR_PASSWORD_HASH_ENV, hash_password(PASSWORD))
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_RATE_LIMIT_ENABLED", "false")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": PASSWORD}
        )
        assert login.status_code == 200
        yield client, fresh_postgresql_url, login.json()["data"]["csrfToken"]
    _database_engine(fresh_postgresql_url).dispose()
    _database_engine.cache_clear()


@pytest.fixture
def local_no_login_custom_source_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv(AUTH_ENABLED_ENV, "false")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_RATE_LIMIT_ENABLED", "false")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    with TestClient(app) as client:
        yield client, fresh_postgresql_url
    _database_engine(fresh_postgresql_url).dispose()
    _database_engine.cache_clear()


def _payload() -> dict[str, object]:
    return {
        "name": f"Example {uuid4().hex[:8]}",
        "baseUrl": "https://example.test/jobs",
        "parserMode": "auto",
        "fieldMapping": {},
        "scheduleKind": "interval",
        "intervalMinutes": 360,
        "timezone": "Asia/Ho_Chi_Minh",
        "itemBudget": 500,
        "byteBudget": 2000000,
        "requestsPerMinute": 2,
        "permissionAcknowledged": True,
    }


def test_feature_flag_blocks_custom_source_api_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/custom-sources")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "custom_sources_disabled"


@pytest.mark.postgresql
def test_custom_sources_work_in_explicit_local_no_login_mode(
    local_no_login_custom_source_api: tuple[TestClient, str],
) -> None:
    client, database_url = local_no_login_custom_source_api

    created = client.post("/api/v1/custom-sources", json=_payload())
    listed = client.get("/api/v1/custom-sources")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == created.json()["data"]["id"]
    with Session(_database_engine(database_url)) as session:
        profile = session.get(CustomSourceProfile, UUID(created.json()["data"]["id"]))
        operator = session.scalar(select(User).where(User.username == "local-operator"))
        assert profile is not None
        assert operator is not None
        assert profile.owner_user_id == operator.id


@pytest.mark.postgresql
def test_local_no_login_custom_source_mutation_rejects_foreign_origin(
    local_no_login_custom_source_api: tuple[TestClient, str],
) -> None:
    client, _ = local_no_login_custom_source_api

    response = client.post(
        "/api/v1/custom-sources",
        json=_payload(),
        headers={"Origin": "https://attacker.test"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_origin_invalid"


@pytest.mark.postgresql
def test_create_profile_is_owner_scoped_and_starts_draft(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = custom_source_api
    created = client.post(
        "/api/v1/custom-sources",
        json=_payload(),
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["status"] == "draft"
    assert data["baseUrl"] == "https://example.test/jobs"
    assert data["permissionAcknowledged"] is True
    assert "rawContent" not in created.text

    with Session(_database_engine(database_url)) as session:
        profile = session.get(CustomSourceProfile, UUID(data["id"]))
        assert profile is not None
        assert profile.owner_user_id is not None
        source = session.get(Source, profile.source_id)
        assert source is not None
        assert source.approval_status.value == "owner_authorized_local"


@pytest.mark.postgresql
def test_preview_does_not_create_job_missing_removed_or_change_event(
    custom_source_api: tuple[TestClient, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database_url, csrf = custom_source_api
    created = client.post(
        "/api/v1/custom-sources", json=_payload(), headers={"X-DevRadar-CSRF": csrf}
    )
    profile_id = created.json()["data"]["id"]
    monkeypatch.setattr(
        "devradar.custom_sources.service._run_preview",
        lambda profile: CustomParseResult(
            candidates=(
                CustomCandidate(
                    external_id="fixture-1",
                    job_url="https://example.test/jobs/fixture-1",
                    title="Fixture Engineer",
                    company="Example",
                    provenance=(CustomFieldProvenance("title", "json:$.title", "json"),),
                    confidence=0.91,
                    warnings=("coverage_unknown",),
                ),
            ),
            final_url="https://example.test/jobs/final",
            redirect_chain=("https://example.test/jobs/final",),
        ),
    )
    response = client.post(
        f"/api/v1/custom-sources/{profile_id}/preview",
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert response.status_code == 200
    assert response.json()["data"]["candidates"][0]["externalId"] == "fixture-1"
    assert response.json()["data"]["candidates"][0]["warnings"] == ["coverage_unknown"]
    assert response.json()["data"]["finalUrl"] == "https://example.test/jobs/final"
    assert response.json()["data"]["redirectChain"] == ["https://example.test/jobs/final"]
    assert response.json()["data"]["coverageStatus"] == "unknown"
    with Session(_database_engine(database_url)) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(JobChange)) == 0
        assert session.scalar(select(func.count()).select_from(CrawlRun)) == 0


@pytest.mark.postgresql
def test_cross_owner_profile_id_returns_not_found_or_forbidden_without_leakage(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = custom_source_api
    created = client.post(
        "/api/v1/custom-sources", json=_payload(), headers={"X-DevRadar-CSRF": csrf}
    )
    profile_id = created.json()["data"]["id"]
    with Session(_database_engine(database_url)) as session:
        session.add(
            User(
                username=f"owner{uuid4().hex[:8]}",
                password_hash=hash_password("owner-password"),
                role=AuthRole.OWNER.value,
            )
        )
        session.commit()
    owner = TestClient(app)
    login = owner.post(
        "/api/v1/auth/login",
        json={
            "username": session.scalar(select(User.username).order_by(User.username.desc())),
            "password": "owner-password",
        },
    )
    assert login.status_code == 200
    response = owner.get(f"/api/v1/custom-sources/{profile_id}")
    assert response.status_code == 404
    assert "Example" not in response.text


@pytest.mark.postgresql
def test_arbitrary_url_field_and_unapproved_status_transition_are_rejected(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, _, csrf = custom_source_api
    invalid = {**_payload(), "url": "https://attacker.test/proxy"}
    response = client.post(
        "/api/v1/custom-sources",
        json=invalid,
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert response.status_code == 422
    unsupported_page_budget = client.post(
        "/api/v1/custom-sources",
        json={**_payload(), "pageBudget": 10},
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert unsupported_page_budget.status_code == 422
    created = client.post(
        "/api/v1/custom-sources", json=_payload(), headers={"X-DevRadar-CSRF": csrf}
    )
    profile_id = created.json()["data"]["id"]
    enabled = client.patch(
        f"/api/v1/custom-sources/{profile_id}",
        json={"status": "enabled"},
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert enabled.status_code == 409
    assert enabled.json()["error"]["code"] == "preview_required"


@pytest.mark.postgresql
def test_custom_crawl_request_is_idempotent_and_owner_scoped(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = custom_source_api
    created = client.post(
        "/api/v1/custom-sources", json=_payload(), headers={"X-DevRadar-CSRF": csrf}
    )
    profile_id = created.json()["data"]["id"]
    with Session(_database_engine(database_url)) as session:
        profile = session.get(CustomSourceProfile, UUID(profile_id))
        assert profile is not None
        profile.status = CustomSourceStatus.ENABLED
        session.commit()
    headers = {"X-DevRadar-CSRF": csrf, "Idempotency-Key": "custom-run-123"}
    first = client.post(f"/api/v1/custom-sources/{profile_id}/crawl-runs", headers=headers)
    second = client.post(f"/api/v1/custom-sources/{profile_id}/crawl-runs", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    history = client.get(f"/api/v1/custom-sources/{profile_id}/crawl-runs")
    assert history.status_code == 200
    assert history.json()["pagination"]["totalItems"] == 1


@pytest.mark.postgresql
def test_daily_schedule_create_and_patch_clear_interval_boundary(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, _, csrf = custom_source_api
    daily = _payload()
    daily["scheduleKind"] = "daily_at"
    daily["dailyAt"] = "09:30:00"
    daily.pop("intervalMinutes")
    created_daily = client.post(
        "/api/v1/custom-sources", json=daily, headers={"X-DevRadar-CSRF": csrf}
    )
    assert created_daily.status_code == 201
    assert created_daily.json()["data"]["intervalMinutes"] is None

    created_interval = client.post(
        "/api/v1/custom-sources", json=_payload(), headers={"X-DevRadar-CSRF": csrf}
    )
    profile_id = created_interval.json()["data"]["id"]
    created_updated_at = datetime.fromisoformat(created_interval.json()["data"]["updatedAt"])
    patched = client.patch(
        f"/api/v1/custom-sources/{profile_id}",
        json={"scheduleKind": "daily_at", "dailyAt": "09:30:00"},
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["intervalMinutes"] is None
    assert datetime.fromisoformat(patched.json()["data"]["updatedAt"]) > created_updated_at


@pytest.mark.postgresql
def test_patch_rejects_invalid_domain_values_and_workflow_status(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, _, csrf = custom_source_api
    created = client.post(
        "/api/v1/custom-sources", json=_payload(), headers={"X-DevRadar-CSRF": csrf}
    )
    profile_id = created.json()["data"]["id"]

    invalid_url = client.patch(
        f"/api/v1/custom-sources/{profile_id}",
        json={"baseUrl": "http://127.0.0.1/admin"},
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert invalid_url.status_code == 422

    unmanaged_status = client.patch(
        f"/api/v1/custom-sources/{profile_id}",
        json={"status": "preview_ready"},
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert unmanaged_status.status_code == 422


@pytest.mark.postgresql
def test_create_rejects_paths_that_cannot_reach_the_fetch_boundary(
    custom_source_api: tuple[TestClient, str, str],
) -> None:
    client, _, csrf = custom_source_api

    for base_url in (
        "https://example.test/công-việc",
        "https://example.test/jobs%2farchive",
        "https://example.test/jobs%25archive",
    ):
        payload = _payload()
        payload["baseUrl"] = base_url
        response = client.post(
            "/api/v1/custom-sources",
            json=payload,
            headers={"X-DevRadar-CSRF": csrf},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "custom_source_invalid"
