from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import devradar.source_recipes.scheduler as source_recipe_scheduler
from devradar.auth.models import User
from devradar.automation.run_requests import RunRequestError, request_source_recipe_run
from devradar.automation.worker import work_one_source_recipe
from devradar.catalog.models import Job, JobStatus
from devradar.ingestion.contracts import FetchResult, JobSourceAdapter
from devradar.ingestion.models import (
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceApprovalStatus,
)
from devradar.ingestion.safe_http import FetchError, FetchErrorCode
from devradar.ingestion.source_registry import SourceConfig
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.adapter import RecipeAdapter
from devradar.source_recipes.catalog import resolve_terms_notice
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    SourceRecipePreview,
)
from devradar.source_recipes.preview import request_preview
from devradar.source_recipes.scheduler import claim_due_source_recipe
from devradar.source_recipes.service import recipe_config_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREVIEW_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "source_recipes" / "jobs_json.html"


def _result(url: str, payload: bytes, *, content_type: str) -> FetchResult:
    return FetchResult(
        final_url=url,
        fetched_at=datetime.now(UTC),
        http_status=200,
        content_type=content_type,
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


def _enabled_recipe(session: Session, *, now: datetime) -> SourceRecipe:
    owner = User(username=f"recipe-{uuid4().hex[:8]}", password_hash="x" * 64)
    session.add(owner)
    session.flush()
    notice = resolve_terms_notice("https://example.test/jobs")
    source = Source(
        name=f"Recipe source {uuid4().hex[:8]}",
        base_url="https://example.test",
        adapter_key=RecipeAdapter.adapter_key,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        rate_limit_policy={"requests_per_minute": 2, "concurrency": 1},
        allowed_hosts=["example.test"],
    )
    session.add(source)
    session.flush()
    recipe = SourceRecipe(
        owner_user_id=owner.id,
        source_id=source.id,
        name="Scheduled recipe",
        status=RecipeStatus.ENABLED,
        listing_url="https://example.test/jobs",
        origin="https://example.test",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        terms_notice=notice.notice,
        terms_notice_version=notice.version,
        terms_evidence_url=notice.evidence_url,
        terms_acknowledged_at=now,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=["all"],
        schedule_kind=RecipeScheduleKind.EVERY_6_HOURS,
        timezone="Asia/Ho_Chi_Minh",
        next_run_at=now - timedelta(minutes=1),
        mapping_version="a" * 64,
        config_version="recipe-config-v1",
        item_budget=500,
        page_budget=20,
        request_budget=100,
        byte_budget=2_000_000,
        time_budget_seconds=600,
        requests_per_minute=2,
        created_at=now,
        updated_at=now,
    )
    session.add(recipe)
    session.commit()
    return recipe


@pytest.mark.postgresql
def test_due_recipe_is_enqueued_once_with_stable_slot(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            expected_slot = recipe.next_run_at
        with Session(engine) as session:
            first = claim_due_source_recipe(session, now=now)
            assert first is not None
            assert first.recipe_id == recipe.id
            assert first.slot == expected_slot
            loaded_after_schedule = session.get(SourceRecipe, recipe.id)
            assert loaded_after_schedule is not None
            assert loaded_after_schedule.last_used_at == now
            assert first.trigger_key == (
                f"scheduled:recipe:{recipe.id}:{expected_slot.isoformat()}"
            )
        with Session(engine) as session:
            second = claim_due_source_recipe(session, now=now)
            assert second is None
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 1
            crawl_run = session.scalar(select(CrawlRun))
            assert crawl_run is not None
            assert crawl_run.trigger_type is CrawlTriggerType.SCHEDULED
            assert crawl_run.config_version == recipe_config_hash(recipe)
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_manual_recipe_request_is_owner_bound_and_idempotent(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            with pytest.raises(RunRequestError) as wrong_owner:
                request_source_recipe_run(
                    session,
                    recipe_id=recipe.id,
                    owner_user_id=uuid4(),
                    idempotency_key="recipe-run-123",
                    requested_at=now,
                )
            assert wrong_owner.value.code == "recipe_not_found"
            first = request_source_recipe_run(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="recipe-run-123",
                requested_at=now,
            )
            second = request_source_recipe_run(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="recipe-run-123",
                requested_at=now + timedelta(seconds=1),
            )

            assert first.reused is False
            assert second.reused is True
            assert first.crawl_run.id == second.crawl_run.id
            assert first.crawl_run.requested_by == f"recipe:{recipe.owner_user_id}"
            assert first.crawl_run.config_version == recipe_config_hash(recipe)
            loaded_after_manual = session.get(SourceRecipe, recipe.id)
            assert loaded_after_manual is not None
            assert loaded_after_manual.last_used_at == now
            recipe.seniority_filter = ["senior"]
            session.commit()
            with pytest.raises(RunRequestError) as changed_request:
                request_source_recipe_run(
                    session,
                    recipe_id=recipe.id,
                    owner_user_id=recipe.owner_user_id,
                    idempotency_key="recipe-run-123",
                    requested_at=now + timedelta(seconds=2),
                )
            assert changed_request.value.code == "idempotency_conflict"
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_worker_cancels_pending_run_when_recipe_config_changes(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            recipe.schedule_kind = RecipeScheduleKind.MANUAL
            recipe.next_run_at = None
            session.commit()
            queued = request_source_recipe_run(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="recipe-config-old",
                requested_at=now,
            )
            old_config_hash = queued.crawl_run.config_version
            recipe.seniority_filter = ["senior"]
            session.commit()

            def unexpected_factory(recipe: SourceRecipe, config: SourceConfig) -> JobSourceAdapter:
                pytest.fail("stale pending run reached the adapter")

            result = work_one_source_recipe(
                session,
                deadline=now + timedelta(minutes=5),
                adapter_factory=unexpected_factory,
                clock=lambda: now,
            )

            assert result is None
            session.rollback()
            stale_run = session.get(CrawlRun, queued.crawl_run.id)
            refreshed = session.get(SourceRecipe, recipe.id)
            assert stale_run is not None and refreshed is not None
            assert stale_run.status is CrawlRunStatus.CANCELLED
            assert stale_run.error_code == "source_recipe_config_mismatch"
            assert stale_run.started_at == stale_run.finished_at == now
            assert old_config_hash != recipe_config_hash(refreshed)
            replacement = request_source_recipe_run(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="recipe-config-new",
                requested_at=now + timedelta(seconds=1),
            )
            assert replacement.reused is False
    finally:
        engine.dispose()


@pytest.mark.postgresql
@pytest.mark.parametrize("status", [RecipeStatus.PAUSED, RecipeStatus.RETIRED])
def test_worker_cancels_pending_run_when_recipe_is_no_longer_enabled(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
    status: RecipeStatus,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            recipe.schedule_kind = RecipeScheduleKind.MANUAL
            recipe.next_run_at = None
            session.commit()
            queued = request_source_recipe_run(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key=f"recipe-status-{status.value}",
                requested_at=now,
            )
            recipe.status = status
            session.commit()

            assert (
                work_one_source_recipe(
                    session,
                    deadline=now + timedelta(minutes=5),
                    clock=lambda: now,
                )
                is None
            )
            session.rollback()
            stale_run = session.get(CrawlRun, queued.crawl_run.id)
            assert stale_run is not None
            assert stale_run.status is CrawlRunStatus.CANCELLED
            assert stale_run.error_code == "source_recipe_not_runnable"
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_worker_cancels_pending_run_when_terms_notice_drifts(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            recipe.schedule_kind = RecipeScheduleKind.MANUAL
            recipe.next_run_at = None
            session.commit()
            queued = request_source_recipe_run(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="recipe-notice-drift",
                requested_at=now,
            )
            current = resolve_terms_notice(recipe.listing_url)
            monkeypatch.setattr(
                source_recipe_scheduler,
                "resolve_terms_notice",
                lambda value: replace(current, version="f" * 64),
            )

            assert (
                work_one_source_recipe(
                    session,
                    deadline=now + timedelta(minutes=5),
                    clock=lambda: now,
                )
                is None
            )
            session.rollback()
            stale_run = session.get(CrawlRun, queued.crawl_run.id)
            assert stale_run is not None
            assert stale_run.status is CrawlRunStatus.CANCELLED
            assert stale_run.error_code == "source_recipe_not_runnable"
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_manual_recipe_request_rejects_stale_notice_and_cooldown(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            recipe.terms_notice_version = "f" * 64
            session.commit()
            with pytest.raises(RunRequestError) as stale_notice:
                request_source_recipe_run(
                    session,
                    recipe_id=recipe.id,
                    owner_user_id=recipe.owner_user_id,
                    idempotency_key="recipe-run-stale",
                    requested_at=now,
                )
            assert stale_notice.value.code == "terms_notice_acknowledgement_stale"

            recipe.terms_notice_version = resolve_terms_notice(recipe.listing_url).version
            recipe.cooldown_until = now + timedelta(minutes=5)
            session.commit()
            with pytest.raises(RunRequestError) as cooldown:
                request_source_recipe_run(
                    session,
                    recipe_id=recipe.id,
                    owner_user_id=recipe.owner_user_id,
                    idempotency_key="recipe-run-cooldown",
                    requested_at=now,
                )
            assert cooldown.value.code == "recipe_cooldown_active"
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_worker_processes_preview_and_purges_expired_artifacts(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)
    payload = PREVIEW_FIXTURE.read_bytes()
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            recipe.status = RecipeStatus.DRAFT
            recipe.next_run_at = None
            expired = SourceRecipePreview(
                recipe_id=recipe.id,
                status=PreviewStatus.FAILED,
                config_hash="f" * 64,
                candidate_jobs=[],
                warnings=[],
                element_map={"private": "selector"},
                screenshot=b"old",
                screenshot_media_type="image/webp",
                error_code="preview_insufficient_jobs",
                requested_at=now - timedelta(days=2),
                started_at=now - timedelta(days=2),
                finished_at=now - timedelta(days=2),
                expires_at=now - timedelta(days=1),
            )
            session.add(expired)
            session.commit()
            pending = request_preview(session, recipe_id=recipe.id, now=now)
            result = work_one_source_recipe(
                session,
                deadline=now + timedelta(minutes=5),
                preview_fetch=lambda url, policy: _result(
                    url,
                    payload,
                    content_type="application/json",
                ),
                browser_render=None,
                clock=lambda: now,
            )

            assert result is not None
            assert result.preview_processed is True
            assert result.orchestration is None
            session.rollback()
            refreshed_pending = session.get(SourceRecipePreview, pending.id)
            refreshed_expired = session.get(SourceRecipePreview, expired.id)
            refreshed_recipe = session.get(SourceRecipe, recipe.id)
            assert refreshed_pending is not None
            assert refreshed_pending.status is PreviewStatus.SUCCEEDED
            assert refreshed_expired is not None
            assert refreshed_expired.screenshot is None
            assert refreshed_expired.screenshot_media_type is None
            assert refreshed_expired.element_map == {}
            assert refreshed_recipe is not None
            assert refreshed_recipe.status is RecipeStatus.PREVIEW_READY
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_worker_ingests_then_applies_rate_limit_cooldown_and_technical_block(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    listing_payload = (
        b'{"@type":"JobPosting","id":"1","title":"Senior Engineer",'
        b'"company":"Example","url":"https://example.test/jobs/1",'
        b'"level":"Senior","description":"Build services"}'
    )

    def success_factory(recipe: SourceRecipe, config: SourceConfig) -> JobSourceAdapter:
        responses = {
            recipe.listing_url: _result(
                recipe.listing_url,
                listing_payload,
                content_type="application/json",
            ),
            "https://example.test/jobs/1": _result(
                "https://example.test/jobs/1",
                listing_payload,
                content_type="application/json",
            ),
        }
        return RecipeAdapter(
            recipe=recipe,
            config=config,
            http_fetch=lambda url, policy: responses[url],
        )

    def error_factory(
        code: FetchErrorCode,
        *,
        status: int | None = None,
    ) -> Callable[[SourceRecipe, SourceConfig], JobSourceAdapter]:
        def build(recipe: SourceRecipe, config: SourceConfig) -> JobSourceAdapter:
            def fail(url: str, policy: object) -> FetchResult:
                raise FetchError(
                    code,
                    "Source request failed safely.",
                    retryable=code is FetchErrorCode.RATE_LIMITED,
                    http_status=status,
                    retry_after_seconds=120 if code is FetchErrorCode.RATE_LIMITED else None,
                )

            return RecipeAdapter(recipe=recipe, config=config, http_fetch=fail)

        return build

    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _enabled_recipe(session, now=now)
            session.rollback()
            success = work_one_source_recipe(
                session,
                deadline=now + timedelta(minutes=5),
                adapter_factory=success_factory,
                clock=lambda: now,
            )
            assert success is not None and success.orchestration is not None
            assert success.orchestration.final_report.status is CrawlRunStatus.SUCCEEDED
            assert success.orchestration.final_report.items_new == 1
            job = session.scalar(select(Job))
            assert job is not None and job.status is JobStatus.ACTIVE

            session.rollback()
            refreshed = session.get(SourceRecipe, recipe.id)
            assert refreshed is not None
            refreshed.next_run_at = now - timedelta(seconds=1)
            session.commit()
            rate_limited = work_one_source_recipe(
                session,
                deadline=now + timedelta(minutes=5),
                adapter_factory=error_factory(FetchErrorCode.RATE_LIMITED),
                clock=lambda: now,
            )
            assert rate_limited is not None and rate_limited.orchestration is not None
            assert len(rate_limited.orchestration.reports) == 1
            assert rate_limited.orchestration.final_report.error_code == "rate_limited"
            session.rollback()
            refreshed = session.get(SourceRecipe, recipe.id)
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.ENABLED
            assert refreshed.cooldown_until == now + timedelta(seconds=120)

            refreshed.cooldown_until = None
            refreshed.next_run_at = now - timedelta(seconds=2)
            session.commit()
            blocked = work_one_source_recipe(
                session,
                deadline=now + timedelta(minutes=5),
                adapter_factory=error_factory(FetchErrorCode.HTTP_ERROR, status=403),
                clock=lambda: now,
            )
            assert blocked is not None and blocked.orchestration is not None
            assert len(blocked.orchestration.reports) == 1
            assert blocked.orchestration.final_report.error_code == "access_denied"
            session.rollback()
            refreshed = session.get(SourceRecipe, recipe.id)
            job = session.scalar(select(Job))
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.BLOCKED
            assert refreshed.block_reason == "access_denied"
            assert job is not None and job.status is JobStatus.ACTIVE
    finally:
        engine.dispose()
