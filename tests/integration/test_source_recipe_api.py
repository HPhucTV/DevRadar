from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from devradar.api.errors import ApiContractError
from devradar.api.source_recipe_imports import (
    _document_upload_from_form,
    read_document_upload,
)
from devradar.auth.models import AuthRole, User
from devradar.auth.service import (
    AUTH_ENABLED_ENV,
    OPERATOR_PASSWORD_HASH_ENV,
    OPERATOR_USERNAME_ENV,
    hash_password,
)
from devradar.catalog.models import Job, JobChange
from devradar.ingestion.models import CrawlRun, RawJobSnapshot, Source
from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine
from devradar.source_recipes.browser_preview import build_browser_artifact
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    SourceRecipePreview,
)
from devradar.source_recipes.service import recipe_config_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "source-recipe-test-password"


@pytest.fixture
def source_recipe_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, str]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv(AUTH_ENABLED_ENV, "true")
    monkeypatch.setenv(OPERATOR_USERNAME_ENV, "operator")
    monkeypatch.setenv(OPERATOR_PASSWORD_HASH_ENV, hash_password(PASSWORD))
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_RATE_LIMIT_ENABLED", "false")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": PASSWORD},
        )
        assert login.status_code == 200
        yield client, fresh_postgresql_url, login.json()["data"]["csrfToken"]
    _database_engine(fresh_postgresql_url).dispose()
    _database_engine.cache_clear()


def _payload(*, listing_url: str = "https://example.test/jobs?role=backend") -> dict[str, object]:
    return {
        "name": "Example recipe",
        "listingUrl": listing_url,
        "seniorityFilter": ["intern", "senior"],
        "scheduleKind": "manual",
        "timezone": "Asia/Ho_Chi_Minh",
    }


def _csrf(token: str) -> dict[str, str]:
    return {"X-DevRadar-CSRF": token}


def _document_headers(csrf: str, key: str = "document-import-1") -> dict[str, str]:
    return {**_csrf(csrf), "Idempotency-Key": key}


def _document_payload(*, title: str = "Backend Intern") -> bytes:
    return (
        "title,company,url,level\n"
        f"{title},Example,https://example.test/careers/1,intern\n"
        "Senior Data,Example,https://example.test/careers/2,senior\n"
    ).encode()


def _create_blocked_recipe(
    client: TestClient,
    *,
    database_url: str,
    csrf: str,
) -> str:
    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(),
        headers=_csrf(csrf),
    )
    assert created.status_code == 201
    data = created.json()["data"]
    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(data["id"]))
        assert recipe is not None
        recipe.status = RecipeStatus.BLOCKED
        recipe.block_reason = "access_denied"
        session.commit()
    return str(data["id"])


def _seed_successful_preview(
    database_url: str,
    *,
    recipe_id: str,
    proposed_hosts: list[str],
    proposed_path_prefixes: list[str],
) -> UUID:
    now = datetime.now(UTC)
    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        assert recipe is not None
        preview = SourceRecipePreview(
            recipe_id=recipe.id,
            status=PreviewStatus.SUCCEEDED,
            config_hash=recipe_config_hash(recipe),
            candidate_jobs=[
                {
                    "external_id": str(index),
                    "job_url": f"https://detail.example.test/jobs/{index}",
                    "title": f"Engineer {index}",
                    "company": "Example",
                    "confidence": 0.94,
                    "provenance": [],
                    "warnings": [],
                    "parser_version": "source-recipe-parser-v1",
                }
                for index in range(3)
            ],
            warnings=[],
            element_map={
                "proposed_hosts": proposed_hosts,
                "proposed_path_prefixes": proposed_path_prefixes,
            },
            requested_at=now,
            started_at=now,
            finished_at=now,
            expires_at=now + timedelta(hours=24),
        )
        session.add(preview)
        session.flush()
        recipe.status = RecipeStatus.PREVIEW_READY
        recipe.latest_successful_preview_id = preview.id
        recipe.latest_successful_preview_hash = "a" * 64
        session.commit()
        return preview.id


def _mapping_artifact() -> tuple[dict[str, object], dict[str, str | None]]:
    card = ".result-row:nth-of-type(1)"
    nodes: list[dict[str, object]] = [
        {
            "selector": card,
            "cardSelector": card,
            "tag": "section",
            "role": "article",
            "text": "Example job",
            "signature": {"tag": "section", "class_tokens": ["result-row"]},
            "bounds": {"x": 0, "y": 0, "width": 500, "height": 140},
        },
        {
            "selector": f"{card} .position-name",
            "cardSelector": card,
            "tag": "h2",
            "role": "heading",
            "text": "Backend Intern",
            "signature": {"tag": "h2", "class_tokens": ["position-name"]},
            "bounds": {"x": 10, "y": 10, "width": 240, "height": 30},
        },
        {
            "selector": f"{card} .org-name",
            "cardSelector": card,
            "tag": "p",
            "role": "",
            "text": "Example Company",
            "signature": {"tag": "p", "class_tokens": ["org-name"]},
            "bounds": {"x": 10, "y": 50, "width": 220, "height": 24},
        },
        {
            "selector": f"{card} .detail-link",
            "cardSelector": card,
            "tag": "a",
            "role": "link",
            "text": "Open job",
            "signature": {"tag": "a", "class_tokens": ["detail-link"]},
            "bounds": {"x": 10, "y": 90, "width": 180, "height": 24},
        },
    ]
    artifact = build_browser_artifact(
        page_url="https://topdev.vn/viec-lam-it",
        raw_nodes=nodes,
        screenshot=b"webp",
        screenshot_media_type="image/webp",
        proposed_hosts=(),
    )
    element_map = artifact.to_private_element_map()
    elements = element_map["elements"]
    assert isinstance(elements, dict)
    by_selector = {value["selector"]: key for key, value in elements.items()}
    return element_map, {
        "cardElementId": by_selector[card],
        "titleElementId": by_selector[f"{card} .position-name"],
        "companyElementId": by_selector[f"{card} .org-name"],
        "locationElementId": None,
        "jobUrlElementId": by_selector[f"{card} .detail-link"],
        "paginationElementId": None,
    }


def test_source_recipe_feature_is_fail_closed_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/source-catalog")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "source_recipes_disabled"


@pytest.mark.postgresql
def test_create_and_queue_preview_without_terms_or_canonical_rows(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    catalog = client.get("/api/v1/source-catalog")
    assert catalog.status_code == 200
    assert len(catalog.json()["data"]["entries"]) == 10
    assert set(catalog.json()["data"]["entries"][0]) == {"name", "origin", "listingHint"}

    rejected = client.post(
        "/api/v1/source-recipes",
        json={**_payload(), "url": "https://attacker.test/proxy", "selector": ".job"},
        headers=_csrf(csrf),
    )
    assert rejected.status_code == 422

    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(),
        headers=_csrf(csrf),
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["listingUrl"] == "https://example.test/jobs?role=backend"
    assert not {
        "termsNotice",
        "termsNoticeVersion",
        "termsEvidenceUrl",
        "termsAcknowledgementRequired",
        "termsAcknowledged",
    } & set(data)
    assert data["cooldownUntil"] is None
    assert "fieldMapping" not in data
    recipe_id = data["id"]

    removed_create_field = client.post(
        "/api/v1/source-recipes",
        json={**_payload(), "acknowledgedNoticeVersion": "0" * 64},
        headers=_csrf(csrf),
    )
    assert removed_create_field.status_code == 422
    removed_patch_field = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={"acknowledgedNoticeVersion": "0" * 64},
        headers=_csrf(csrf),
    )
    assert removed_patch_field.status_code == 422

    queued = client.post(
        f"/api/v1/source-recipes/{recipe_id}/previews",
        json={},
        headers=_csrf(csrf),
    )
    assert queued.status_code == 202
    preview_id = queued.json()["data"]["id"]
    polled = client.get(f"/api/v1/source-recipes/{recipe_id}/previews/{preview_id}")
    assert polled.status_code == 200
    assert polled.json()["data"]["status"] == "pending"
    assert polled.json()["data"]["proposedHosts"] == []
    assert polled.json()["data"]["proposedPathPrefixes"] == []
    assert "selector" not in polled.text.casefold()
    assert "<html" not in polled.text.casefold()

    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        assert recipe is not None
        assert recipe.config_version == "source-recipe-config-v2"
        assert session.scalar(select(func.count()).select_from(Source)) == 0
        assert session.scalar(select(func.count()).select_from(CrawlRun)) == 0
        assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(JobChange)) == 0


@pytest.mark.postgresql
def test_exact_route_confirmation_resets_preview_and_keeps_listing_boundary(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    listing_url = "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs?content=true"
    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(listing_url=listing_url),
        headers=_csrf(csrf),
    )
    assert created.status_code == 201
    recipe_id = created.json()["data"]["id"]
    preview_id = _seed_successful_preview(
        database_url,
        recipe_id=recipe_id,
        proposed_hosts=["boards.greenhouse.io"],
        proposed_path_prefixes=["/navervietnam/jobs"],
    )

    polled = client.get(f"/api/v1/source-recipes/{recipe_id}/previews/{preview_id}")
    assert polled.status_code == 200
    assert polled.json()["data"]["proposedHosts"] == ["boards.greenhouse.io"]
    assert polled.json()["data"]["proposedPathPrefixes"] == ["/navervietnam/jobs"]

    premature = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={"status": "enabled"},
        headers=_csrf(csrf),
    )
    assert premature.status_code == 409
    assert premature.json()["error"]["code"] == "preview_hosts_confirmation_required"

    response = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={
            "allowedHosts": ["boards-api.greenhouse.io", "boards.greenhouse.io"],
            "allowedPathPrefixes": [
                "/v1/boards/navervietnam/jobs",
                "/navervietnam/jobs",
            ],
        },
        headers=_csrf(csrf),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "draft"
    assert data["allowedHosts"] == [
        "boards-api.greenhouse.io",
        "boards.greenhouse.io",
    ]
    assert data["allowedPathPrefixes"] == [
        "/v1/boards/navervietnam/jobs",
        "/navervietnam/jobs",
    ]
    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        assert recipe is not None
        assert recipe.latest_successful_preview_id is None
        assert recipe.latest_successful_preview_hash is None


@pytest.mark.postgresql
def test_route_confirmation_rejects_missing_replacement_superset_and_fourth_host(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(
            listing_url=(
                "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs?content=true"
            )
        ),
        headers=_csrf(csrf),
    )
    recipe_id = created.json()["data"]["id"]
    _seed_successful_preview(
        database_url,
        recipe_id=recipe_id,
        proposed_hosts=["boards.greenhouse.io"],
        proposed_path_prefixes=["/navervietnam/jobs"],
    )
    invalid_payloads = [
        {
            "allowedHosts": ["boards-api.greenhouse.io"],
            "allowedPathPrefixes": ["/v1/boards/navervietnam/jobs"],
        },
        {
            "allowedHosts": ["boards.greenhouse.io"],
            "allowedPathPrefixes": ["/navervietnam/jobs"],
        },
        {
            "allowedHosts": [
                "boards-api.greenhouse.io",
                "boards.greenhouse.io",
                "extra.test",
            ],
            "allowedPathPrefixes": [
                "/v1/boards/navervietnam/jobs",
                "/navervietnam/jobs",
            ],
        },
        {
            "allowedHosts": [
                "boards-api.greenhouse.io",
                "boards.greenhouse.io",
                "third.test",
                "fourth.test",
            ],
            "allowedPathPrefixes": [
                "/v1/boards/navervietnam/jobs",
                "/navervietnam/jobs",
            ],
        },
    ]
    for payload in invalid_payloads:
        response = client.patch(
            f"/api/v1/source-recipes/{recipe_id}",
            json=payload,
            headers=_csrf(csrf),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "preview_hosts_confirmation_invalid"


@pytest.mark.postgresql
def test_route_confirmation_rejects_stale_preview(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(),
        headers=_csrf(csrf),
    )
    recipe_id = created.json()["data"]["id"]
    _seed_successful_preview(
        database_url,
        recipe_id=recipe_id,
        proposed_hosts=["detail.example.test"],
        proposed_path_prefixes=["/jobs/detail"],
    )
    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        assert recipe is not None
        recipe.latest_successful_preview_id = None
        session.commit()

    response = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={
            "allowedHosts": ["example.test", "detail.example.test"],
            "allowedPathPrefixes": ["/jobs", "/jobs/detail"],
        },
        headers=_csrf(csrf),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_hosts_confirmation_invalid"


@pytest.mark.postgresql
def test_create_cannot_seed_extra_route_boundaries(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, _, csrf = source_recipe_api
    response = client.post(
        "/api/v1/source-recipes",
        json={
            **_payload(),
            "allowedHosts": ["example.test", "attacker.test"],
            "allowedPathPrefixes": ["/jobs", "/proxy"],
        },
        headers=_csrf(csrf),
    )
    assert response.status_code == 422


@pytest.mark.postgresql
def test_recipe_and_preview_ids_are_owner_scoped(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(listing_url="https://topdev.vn/viec-lam-it"),
        headers=_csrf(csrf),
    )
    recipe_id = created.json()["data"]["id"]
    preview = client.post(
        f"/api/v1/source-recipes/{recipe_id}/previews",
        json={},
        headers=_csrf(csrf),
    )
    preview_id = preview.json()["data"]["id"]
    with Session(_database_engine(database_url)) as session:
        session.add(
            User(
                username="other-owner",
                password_hash=hash_password("other owner password"),
                role=AuthRole.OWNER.value,
                is_active=True,
            )
        )
        session.commit()

    with TestClient(app) as other:
        login = other.post(
            "/api/v1/auth/login",
            json={"username": "other-owner", "password": "other owner password"},
        )
        assert login.status_code == 200
        assert other.get(f"/api/v1/source-recipes/{recipe_id}").status_code == 404
        assert (
            other.get(f"/api/v1/source-recipes/{recipe_id}/previews/{preview_id}").status_code
            == 404
        )


@pytest.mark.postgresql
def test_mapping_payload_is_sanitized_and_enable_gates_crawl_requests(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    created = client.post(
        "/api/v1/source-recipes",
        json=_payload(listing_url="https://topdev.vn/viec-lam-it"),
        headers=_csrf(csrf),
    )
    recipe_id = created.json()["data"]["id"]
    queued = client.post(
        f"/api/v1/source-recipes/{recipe_id}/previews",
        json={},
        headers=_csrf(csrf),
    )
    preview_id = queued.json()["data"]["id"]
    element_map, selection = _mapping_artifact()
    now = datetime.now(UTC)
    engine = _database_engine(database_url)
    with Session(engine) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        preview = session.get(SourceRecipePreview, UUID(preview_id))
        assert recipe is not None and preview is not None
        recipe.status = RecipeStatus.DRAFT
        preview.status = PreviewStatus.FAILED
        preview.started_at = now
        preview.finished_at = now
        preview.error_code = "preview_insufficient_jobs"
        preview.element_map = element_map
        preview.screenshot = b"webp"
        preview.screenshot_media_type = "image/webp"
        session.commit()

    artifact_response = client.get(f"/api/v1/source-recipes/{recipe_id}/previews/{preview_id}")
    assert artifact_response.status_code == 200
    artifact_data = artifact_response.json()["data"]
    assert artifact_data["screenshotDataUrl"].startswith("data:image/webp;base64,")
    assert len(artifact_data["elements"]) == 4
    assert "selector" not in artifact_response.text.casefold()
    assert ".result-row" not in artifact_response.text

    rejected_mapping = client.post(
        f"/api/v1/source-recipes/{recipe_id}/previews/{preview_id}/mapping",
        json={**selection, "selector": ".result-row"},
        headers=_csrf(csrf),
    )
    assert rejected_mapping.status_code == 422
    mapped = client.post(
        f"/api/v1/source-recipes/{recipe_id}/previews/{preview_id}/mapping",
        json=selection,
        headers=_csrf(csrf),
    )
    assert mapped.status_code == 202
    mapped_preview_id = mapped.json()["data"]["id"]

    premature = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={"status": "enabled"},
        headers=_csrf(csrf),
    )
    assert premature.status_code == 409
    with Session(engine) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        preview = session.get(SourceRecipePreview, UUID(mapped_preview_id))
        assert recipe is not None and preview is not None
        preview.status = PreviewStatus.SUCCEEDED
        preview.started_at = now
        preview.finished_at = now + timedelta(seconds=1)
        preview.error_code = None
        preview.candidate_jobs = [{"title": str(index)} for index in range(3)]
        recipe.status = RecipeStatus.PREVIEW_READY
        recipe.schedule_kind = RecipeScheduleKind.EVERY_6_HOURS
        recipe.latest_successful_preview_id = preview.id
        recipe.latest_successful_preview_hash = "b" * 64
        session.commit()

    enabled = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={"status": "enabled"},
        headers=_csrf(csrf),
    )
    assert enabled.status_code == 200
    assert enabled.json()["data"]["sourceId"] is not None
    next_run_at = datetime.fromisoformat(enabled.json()["data"]["nextRunAt"])
    assert next_run_at > datetime.now(UTC)
    assert next_run_at <= datetime.now(UTC) + timedelta(hours=6)

    rejected_run = client.post(
        f"/api/v1/source-recipes/{recipe_id}/crawl-runs",
        json={"url": "https://attacker.test/proxy"},
        headers={**_csrf(csrf), "Idempotency-Key": "recipe-run-123"},
    )
    assert rejected_run.status_code == 422
    headers = {**_csrf(csrf), "Idempotency-Key": "recipe-run-123"}
    first = client.post(
        f"/api/v1/source-recipes/{recipe_id}/crawl-runs",
        json={},
        headers=headers,
    )
    second = client.post(
        f"/api/v1/source-recipes/{recipe_id}/crawl-runs",
        json={},
        headers=headers,
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    history = client.get(f"/api/v1/source-recipes/{recipe_id}/crawl-runs")
    assert history.status_code == 200
    assert history.json()["pagination"]["totalItems"] == 1


def test_document_import_closes_invalid_multipart_parts() -> None:
    first = UploadFile(BytesIO(b"first"), filename="first.csv")
    second = UploadFile(BytesIO(b"second"), filename="second.csv")
    form = FormData([("file", first), ("file", second)])

    with pytest.raises(ApiContractError) as raised:
        asyncio.run(_document_upload_from_form(form))

    assert raised.value.code == "document_import_multipart_invalid"
    assert first.file.closed
    assert second.file.closed


def test_document_import_caps_chunked_request_before_multipart_parse() -> None:
    received = 0

    async def receive() -> dict[str, object]:
        nonlocal received
        received += 1
        return {
            "type": "http.request",
            "body": b"x" * (2 * 1024 * 1024 if received == 1 else 128 * 1024),
            "more_body": received == 1,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/source-recipes/00000000-0000-0000-0000-000000000000/document-imports",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
        },
        receive,
    )

    with pytest.raises(ApiContractError) as raised:
        asyncio.run(read_document_upload(request))

    assert raised.value.status_code == 413
    assert raised.value.code == "document_import_too_large"
    assert received == 2


def test_document_import_disabled_gate_runs_before_form_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", raising=False)

    async def unexpected_form_parse(*args: object, **kwargs: object) -> FormData:
        del args, kwargs
        raise AssertionError("multipart parsing ran before the document import gate")

    monkeypatch.setattr(Request, "form", unexpected_form_parse)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/source-recipes/00000000-0000-0000-0000-000000000000/document-imports",
            headers={"Idempotency-Key": "document-import-1"},
            files={"file": ("jobs.csv", _document_payload(), "text/csv")},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_import_disabled"


@pytest.mark.postgresql
def test_document_import_api_is_owner_scoped_idempotent_and_sanitized(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    recipe_id = _create_blocked_recipe(
        client,
        database_url=database_url,
        csrf=csrf,
    )
    url = f"/api/v1/source-recipes/{recipe_id}/document-imports"
    headers = _document_headers(csrf)

    first = client.post(
        url,
        headers=headers,
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )
    replay = client.post(
        url,
        headers=headers,
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )

    assert first.status_code == replay.status_code == 200
    data = first.json()["data"]
    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        assert recipe is not None and recipe.source_id is not None
        persisted_source_id = recipe.source_id
    assert UUID(data["sourceId"]) == persisted_source_id
    assert replay.json()["data"]["crawlRunId"] == data["crawlRunId"]
    assert data["jobsFound"] == data["jobsNew"] == 2
    assert data["jobsUpdated"] == data["jobsUnchanged"] == 0
    assert data["itemsFilteredOut"] == 0
    assert data["coverage"] == "incomplete"
    assert len(data["documentHashPrefix"]) == 12
    assert "Backend Intern" not in first.text
    assert "jobs.csv" not in first.text

    conflict = client.post(
        url,
        headers=headers,
        files={
            "file": (
                "jobs.csv",
                _document_payload(title="Backend Intern Updated"),
                "text/csv",
            )
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    missing_csrf = client.post(
        url,
        headers={"Idempotency-Key": "document-import-2"},
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    with Session(_database_engine(database_url)) as session:
        session.add(
            User(
                username="document-import-other",
                password_hash=hash_password("other document password"),
                role=AuthRole.OWNER.value,
                is_active=True,
            )
        )
        session.commit()
    with TestClient(app) as other:
        login = other.post(
            "/api/v1/auth/login",
            json={
                "username": "document-import-other",
                "password": "other document password",
            },
        )
        other_csrf = login.json()["data"]["csrfToken"]
        hidden = other.post(
            url,
            headers=_document_headers(other_csrf, "document-import-other"),
            files={"file": ("jobs.csv", _document_payload(), "text/csv")},
        )
    assert hidden.status_code == 404

    with Session(_database_engine(database_url)) as session:
        assert session.scalar(select(func.count()).select_from(CrawlRun)) == 1
        assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(Job)) == 2
        assert session.scalar(select(func.count()).select_from(JobChange)) == 2


@pytest.mark.postgresql
def test_document_import_api_rejects_boundary_abuse(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    recipe_id = _create_blocked_recipe(
        client,
        database_url=database_url,
        csrf=csrf,
    )
    url = f"/api/v1/source-recipes/{recipe_id}/document-imports"

    missing_key = client.post(
        url,
        headers=_csrf(csrf),
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )
    invalid_key = client.post(
        url,
        headers=_document_headers(csrf, "short"),
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )
    multiple = client.post(
        url,
        headers=_document_headers(csrf, "document-import-multiple"),
        files=[
            ("file", ("one.csv", _document_payload(), "text/csv")),
            ("file", ("two.csv", _document_payload(), "text/csv")),
        ],
    )
    extra = client.post(
        url,
        headers=_document_headers(csrf, "document-import-extra"),
        data={"selector": ".job"},
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )

    assert missing_key.status_code == invalid_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "idempotency_key_required"
    assert invalid_key.json()["error"]["code"] == "idempotency_key_invalid"
    assert multiple.json()["error"]["code"] == "document_import_multipart_invalid"
    assert extra.json()["error"]["code"] == "document_import_multipart_invalid"

    cases = [
        (
            "document-import-type",
            ("jobs.zip", b"PK\x03\x04", "application/zip"),
            415,
            "document_import_type_unsupported",
        ),
        (
            "document-import-utf8",
            ("jobs.csv", b"\xff", "text/csv"),
            422,
            "document_import_invalid",
        ),
        (
            "document-import-challenge",
            (
                "jobs.html",
                b"<html><body>Verify you are human CAPTCHA</body></html>",
                "text/html",
            ),
            422,
            "document_import_challenge_detected",
        ),
        (
            "document-import-host",
            (
                "jobs.csv",
                b"title,company,url\nA,Example,https://other.test/jobs/1\n",
                "text/csv",
            ),
            422,
            "document_import_route_blocked",
        ),
        (
            "document-import-field-bound",
            (
                "jobs.json",
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "valid",
                                "title": "Valid",
                                "company": "Example",
                                "url": "https://example.test/jobs/valid",
                            },
                            {
                                "id": "invalid",
                                "title": "x" * 501,
                                "company": "Example",
                                "url": "https://example.test/jobs/invalid",
                            },
                        ]
                    }
                ).encode(),
                "application/json",
            ),
            422,
            "document_import_invalid",
        ),
    ]
    for key, file_part, expected_status, expected_code in cases:
        response = client.post(
            url,
            headers=_document_headers(csrf, key),
            files={"file": file_part},
        )
        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == expected_code

    oversized = client.post(
        url,
        headers=_document_headers(csrf, "document-import-oversized"),
        files={"file": ("jobs.csv", b"x" * (2 * 1024 * 1024 + 1), "text/csv")},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "document_import_too_large"

    with Session(_database_engine(database_url)) as session:
        recipe = session.get(SourceRecipe, UUID(recipe_id))
        assert recipe is not None
        recipe.status = RecipeStatus.RETIRED
        session.commit()
    retired = client.post(
        url,
        headers=_document_headers(csrf, "document-import-retired"),
        files={"file": ("jobs.csv", _document_payload(), "text/csv")},
    )
    assert retired.status_code == 409
    assert retired.json()["error"]["code"] == "document_import_recipe_invalid"

    with Session(_database_engine(database_url)) as session:
        assert session.scalar(select(func.count()).select_from(CrawlRun)) == 0
        assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 0
