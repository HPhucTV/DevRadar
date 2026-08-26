from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from devradar.auth.models import User
from devradar.catalog.models import Job, JobChange
from devradar.ingestion.contracts import FetchResult
from devradar.ingestion.models import CrawlRun, RawJobSnapshot, Source
from devradar.ingestion.safe_http import FetchError, FetchErrorCode
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.browser_preview import (
    RenderedBrowserPreview,
    build_browser_artifact,
)
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeDraft,
    SourceRecipePreview,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "source_recipes"


def _preview_module() -> object:
    return importlib.import_module("devradar.source_recipes.preview")


def _recipe(
    session: Session,
    *,
    now: datetime,
    listing_url: str = "https://topdev.vn/viec-lam-it",
) -> SourceRecipe:
    owner = User(username=f"recipe{uuid4().hex[:8]}", password_hash="x" * 64)
    session.add(owner)
    session.flush()
    draft = SourceRecipeDraft.from_input(
        name="Fixture recipe",
        listing_url=listing_url,
        seniority_filter=["all"],
        acknowledged_notice_version=None,
    )
    recipe = SourceRecipe(
        owner_user_id=owner.id,
        name=draft.name,
        status=RecipeStatus.DRAFT,
        listing_url=draft.listing_url,
        origin=draft.origin,
        allowed_hosts=list(draft.allowed_hosts),
        allowed_path_prefixes=list(draft.allowed_path_prefixes),
        terms_notice=draft.terms_notice,
        terms_notice_version=draft.terms_notice_version,
        terms_evidence_url=draft.terms_evidence_url,
        terms_reviewed_at=now,
        terms_acknowledged_at=now if draft.terms_acknowledged else None,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=list(draft.seniority_filter),
        schedule_kind=draft.schedule_kind,
        schedule_local_time=draft.schedule_local_time,
        schedule_weekday=draft.schedule_weekday,
        timezone=draft.timezone,
        config_version="fixture-config-v1",
        item_budget=draft.item_budget,
        page_budget=draft.page_budget,
        request_budget=draft.request_budget,
        byte_budget=draft.byte_budget,
        time_budget_seconds=draft.time_budget_seconds,
        requests_per_minute=draft.requests_per_minute,
        created_at=now,
        updated_at=now,
    )
    session.add(recipe)
    session.commit()
    return recipe


def _fetch_result(fixture_name: str, *, now: datetime) -> FetchResult:
    payload = (FIXTURES / fixture_name).read_bytes()
    return FetchResult(
        final_url="https://topdev.vn/viec-lam-it",
        fetched_at=now,
        http_status=200,
        content_type="text/html; charset=utf-8",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


@pytest.mark.postgresql
def test_preview_queue_claims_outside_network_transaction_and_creates_no_canonical_rows(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            recipe_id = recipe.id
            listing_url = recipe.listing_url
            queued = preview.request_preview(session, recipe_id=recipe_id, now=now)  # type: ignore[attr-defined]
            assert queued.status is PreviewStatus.PENDING
            loaded_after_queue = session.get(SourceRecipe, recipe_id)
            assert loaded_after_queue is not None
            assert loaded_after_queue.last_used_at == now
            session.rollback()
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None
            assert session.in_transaction() is False

            def fetch(url: str, policy: object) -> FetchResult:
                assert session.in_transaction() is False
                assert url == listing_url
                return _fetch_result("jobs_cards.html", now=now)

            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=fetch,
                now=now,
            )
            assert finished.status is PreviewStatus.SUCCEEDED
            assert len(finished.candidate_jobs) == 3
            refreshed = session.get(SourceRecipe, recipe_id)
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.PREVIEW_READY
            assert refreshed.latest_successful_preview_id == finished.id
            for model in (Source, CrawlRun, RawJobSnapshot, Job, JobChange):
                assert session.scalar(select(func.count()).select_from(model)) == 0
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_structured_preview_proposes_cross_host_detail_route_without_fetching_it(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    listing_url = "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs?content=true"
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": str(index),
                    "title": f"Engineer {index}",
                    "company": "NAVER Vietnam",
                    "absolute_url": (f"https://boards.greenhouse.io/navervietnam/jobs/{index}"),
                }
                for index in range(101, 104)
            ]
        }
    ).encode("utf-8")
    fetched_urls: list[str] = []
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now, listing_url=listing_url)
            preview.request_preview(session, recipe_id=recipe.id, now=now)  # type: ignore[attr-defined]
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None

            def fetch(url: str, policy: object) -> FetchResult:
                fetched_urls.append(url)
                return FetchResult(
                    final_url=listing_url,
                    fetched_at=now,
                    http_status=200,
                    content_type="application/json",
                    payload=payload,
                    raw_content_hash=sha256(payload).hexdigest(),
                )

            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=fetch,
                now=now,
            )

            assert finished.status is PreviewStatus.SUCCEEDED
            assert len(finished.candidate_jobs) == 3
            assert fetched_urls == [listing_url]
            assert finished.element_map["proposed_hosts"] == ["boards.greenhouse.io"]
            assert finished.element_map["proposed_path_prefixes"] == ["/navervietnam/jobs"]
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_insufficient_preview_without_visual_artifact_blocks_as_layout_unavailable(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            recipe_id = recipe.id
            preview.request_preview(session, recipe_id=recipe_id, now=now)  # type: ignore[attr-defined]
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None
        with Session(engine) as second_session:
            assert preview.claim_pending_preview(second_session, now=now) is None  # type: ignore[attr-defined]
        with Session(engine) as session:
            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=lambda url, policy: _fetch_result("insufficient.html", now=now),
                now=now,
            )
            assert finished.status is PreviewStatus.FAILED
            assert finished.error_code == "layout_unavailable"
            assert finished.candidate_jobs == []
            refreshed = session.get(SourceRecipe, recipe_id)
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.BLOCKED
            assert refreshed.block_reason == "layout_unavailable"
            assert session.scalar(select(func.count()).select_from(SourceRecipePreview)) == 1
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_challenge_blocks_recipe_without_retry_or_canonical_rows(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            recipe_id = recipe.id
            preview.request_preview(session, recipe_id=recipe_id, now=now)  # type: ignore[attr-defined]
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None
            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=lambda url, policy: _fetch_result("challenge.html", now=now),
                now=now,
            )
            assert finished.error_code == "challenge_detected"
            refreshed = session.get(SourceRecipe, recipe_id)
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.BLOCKED
            assert refreshed.block_reason == "challenge_detected"
            assert session.scalar(select(func.count()).select_from(Job)) == 0
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_http_insufficient_uses_injected_browser_fallback_and_persists_artifact(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            preview.request_preview(session, recipe_id=recipe.id, now=now)  # type: ignore[attr-defined]
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None
            artifact = build_browser_artifact(
                page_url="https://topdev.vn/viec-lam-it",
                raw_nodes=[
                    {
                        "selector": "main",
                        "cardSelector": "main",
                        "tag": "main",
                        "role": "main",
                        "text": "Rendered jobs",
                        "signature": {"tag": "main", "class_tokens": []},
                        "bounds": {"x": 0, "y": 0, "width": 800, "height": 600},
                    }
                ],
                screenshot=b"webp",
                screenshot_media_type="image/webp",
                proposed_hosts=(),
            )

            def render(url: str, policy: object) -> RenderedBrowserPreview:
                assert session.in_transaction() is False
                assert url == claim.listing_url
                return RenderedBrowserPreview(
                    final_url=url,
                    rendered_html=(FIXTURES / "jobs_cards.html").read_text(encoding="utf-8"),
                    artifact=artifact,
                )

            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=lambda url, policy: _fetch_result("insufficient.html", now=now),
                browser_render=render,
                now=now,
            )
            assert finished.status is PreviewStatus.SUCCEEDED
            assert len(finished.candidate_jobs) == 3
            assert finished.screenshot == b"webp"
            assert len(finished.element_map["elements"]) == 1
            assert "selector" not in repr(finished.candidate_jobs).casefold()
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_insufficient_rendered_preview_requests_visual_mapping(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            recipe_id = recipe.id
            preview.request_preview(session, recipe_id=recipe_id, now=now)  # type: ignore[attr-defined]
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None
            artifact = build_browser_artifact(
                page_url=claim.listing_url,
                raw_nodes=[
                    {
                        "selector": "main",
                        "cardSelector": "main",
                        "tag": "main",
                        "role": "main",
                        "text": "Rendered jobs",
                        "signature": {"tag": "main", "class_tokens": []},
                        "bounds": {"x": 0, "y": 0, "width": 800, "height": 600},
                    }
                ],
                screenshot=b"webp",
                screenshot_media_type="image/webp",
                proposed_hosts=(),
            )
            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=lambda url, policy: _fetch_result("insufficient.html", now=now),
                browser_render=lambda url, policy: RenderedBrowserPreview(
                    final_url=url,
                    rendered_html=(FIXTURES / "insufficient.html").read_text(encoding="utf-8"),
                    artifact=artifact,
                ),
                now=now,
            )

            assert finished.status is PreviewStatus.FAILED
            assert finished.error_code == "mapping_required"
            assert finished.screenshot == b"webp"
            assert len(finished.element_map["elements"]) == 1
            refreshed = session.get(SourceRecipe, recipe_id)
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.DRAFT
            assert refreshed.block_reason is None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_unexpected_http_content_uses_browser_fallback(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    preview = _preview_module()
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            preview.request_preview(session, recipe_id=recipe.id, now=now)  # type: ignore[attr-defined]
            claim = preview.claim_pending_preview(session, now=now)  # type: ignore[attr-defined]
            assert claim is not None
            artifact = build_browser_artifact(
                page_url=claim.listing_url,
                raw_nodes=[
                    {
                        "selector": "main",
                        "cardSelector": "main",
                        "tag": "main",
                        "role": "main",
                        "text": "Rendered jobs",
                        "signature": {"tag": "main", "class_tokens": []},
                        "bounds": {"x": 0, "y": 0, "width": 800, "height": 600},
                    }
                ],
                screenshot=b"webp",
                screenshot_media_type="image/webp",
                proposed_hosts=(),
            )

            def reject_http(url: str, policy: object) -> FetchResult:
                raise FetchError(
                    FetchErrorCode.UNEXPECTED_CONTENT,
                    "safe",
                    retryable=False,
                )

            finished = preview.process_preview_claim(  # type: ignore[attr-defined]
                session,
                claim,
                fetch=reject_http,
                browser_render=lambda url, policy: RenderedBrowserPreview(
                    final_url=url,
                    rendered_html=(FIXTURES / "jobs_cards.html").read_text(encoding="utf-8"),
                    artifact=artifact,
                ),
                now=now,
            )

            assert finished.status is PreviewStatus.SUCCEEDED
            assert len(finished.candidate_jobs) == 3
            assert finished.error_code is None
    finally:
        engine.dispose()
