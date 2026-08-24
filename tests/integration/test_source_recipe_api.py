from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

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
from devradar.ingestion.models import CrawlRun, RawJobSnapshot, Source
from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine
from devradar.source_recipes.browser_preview import build_browser_artifact
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipePreview,
)

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
def test_create_acknowledge_and_queue_preview_without_canonical_rows(
    source_recipe_api: tuple[TestClient, str, str],
) -> None:
    client, database_url, csrf = source_recipe_api
    catalog = client.get("/api/v1/source-catalog")
    assert catalog.status_code == 200
    assert len(catalog.json()["data"]["entries"]) == 10

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
    assert data["termsNotice"] == "not_reviewed"
    assert data["termsAcknowledgementRequired"] is True
    assert data["termsAcknowledged"] is False
    assert "fieldMapping" not in data
    recipe_id = data["id"]

    blocked = client.post(
        f"/api/v1/source-recipes/{recipe_id}/previews",
        json={},
        headers=_csrf(csrf),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "terms_notice_acknowledgement_required"

    stale = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={"acknowledgedNoticeVersion": "0" * 64},
        headers=_csrf(csrf),
    )
    assert stale.status_code == 409
    acknowledged = client.patch(
        f"/api/v1/source-recipes/{recipe_id}",
        json={"acknowledgedNoticeVersion": data["termsNoticeVersion"]},
        headers=_csrf(csrf),
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["data"]["termsAcknowledged"] is True

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
    assert "selector" not in polled.text.casefold()
    assert "<html" not in polled.text.casefold()

    with Session(_database_engine(database_url)) as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0
        assert session.scalar(select(func.count()).select_from(CrawlRun)) == 0
        assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(JobChange)) == 0


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
