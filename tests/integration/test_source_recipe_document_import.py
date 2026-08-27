from __future__ import annotations

import json
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

from devradar.auth.models import User
from devradar.catalog.models import Job, JobChange, JobStatus
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    RawJobSnapshot,
    Source,
    SourceHealthStatus,
)
from devradar.ingestion.runner import _create_run
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.adapter import recipe_source_config
from devradar.source_recipes.document_import import (
    DocumentImportAdapter,
    DocumentImportError,
    PreparedDocumentImport,
    _document_request_hash,
    import_recipe_document,
    prepare_document_import,
)
from devradar.source_recipes.models import (
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
)
from devradar.source_recipes.service import ensure_recipe_source

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _recipe(session: Session, *, now: datetime) -> SourceRecipe:
    owner = User(username=f"document-import-{uuid4().hex[:8]}", password_hash="x" * 64)
    session.add(owner)
    session.flush()
    recipe = SourceRecipe(
        owner_user_id=owner.id,
        name="Document import fixture",
        status=RecipeStatus.BLOCKED,
        listing_url="https://example.test/jobs",
        origin="https://example.test",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        field_mapping={},
        pagination_mapping={},
        seniority_filter=["all"],
        schedule_kind=RecipeScheduleKind.MANUAL,
        timezone="Asia/Ho_Chi_Minh",
        config_version="recipe-config-v1",
        item_budget=500,
        page_budget=20,
        request_budget=100,
        byte_budget=2_000_000,
        time_budget_seconds=600,
        requests_per_minute=2,
        block_reason="access_denied",
        created_at=now,
        updated_at=now,
    )
    session.add(recipe)
    session.commit()
    return recipe


def _prepared(
    recipe: SourceRecipe, *, first_title: str = "Backend Intern"
) -> PreparedDocumentImport:
    payload = (
        "title,company,url,level\n"
        f"{first_title},Example,https://example.test/careers/1,intern\n"
        "Fresher Python,Example,https://example.test/careers/2,fresher\n"
        "Senior Data,Example,https://example.test/careers/3,senior\n"
    ).encode()
    return prepare_document_import(
        filename="jobs.csv",
        declared_content_type="text/csv",
        payload=payload,
        recipe=recipe,
    )


@pytest.mark.postgresql
def test_document_import_is_idempotent_incomplete_and_health_neutral(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            recipe = _recipe(session, now=now)
            prepared = _prepared(recipe)

            first = import_recipe_document(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="document-import-1",
                prepared=prepared,
                imported_at=now,
            )
            replay = import_recipe_document(
                session,
                recipe_id=recipe.id,
                owner_user_id=recipe.owner_user_id,
                idempotency_key="document-import-1",
                prepared=prepared,
                imported_at=now,
            )

            assert first.status is CrawlRunStatus.SUCCEEDED
            assert first.coverage_status is CoverageStatus.INCOMPLETE
            assert first.items_new == first.items_found == 3
            assert first.items_missing == first.items_removed == 0
            assert replay.run_id == first.run_id
            assert replay.reused is True
            loaded_after_import = session.get(SourceRecipe, recipe.id)
            assert loaded_after_import is not None
            assert loaded_after_import.last_used_at == now

            loaded_recipe = session.get(SourceRecipe, recipe.id)
            assert loaded_recipe is not None
            assert loaded_recipe.status is RecipeStatus.BLOCKED
            assert loaded_recipe.block_reason == "access_denied"
            assert loaded_recipe.latest_successful_preview_id is None
            source = session.get(Source, loaded_recipe.source_id)
            assert source is not None
            assert source.health_status is SourceHealthStatus.UNKNOWN
            assert source.last_crawled_at is None
            assert source.last_success_at is None
            assert source.baseline_items_found is None
            assert source.consecutive_failures == 0
            assert source.quarantined_at is None

            with pytest.raises(DocumentImportError) as conflict:
                import_recipe_document(
                    session,
                    recipe_id=loaded_recipe.id,
                    owner_user_id=loaded_recipe.owner_user_id,
                    idempotency_key="document-import-1",
                    prepared=_prepared(loaded_recipe, first_title="Changed title"),
                    imported_at=now,
                )
            assert conflict.value.code == "idempotency_conflict"

            unchanged = import_recipe_document(
                session,
                recipe_id=loaded_recipe.id,
                owner_user_id=loaded_recipe.owner_user_id,
                idempotency_key="document-import-2",
                prepared=prepared,
                imported_at=now + timedelta(seconds=1),
            )
            changed = import_recipe_document(
                session,
                recipe_id=loaded_recipe.id,
                owner_user_id=loaded_recipe.owner_user_id,
                idempotency_key="document-import-3",
                prepared=_prepared(loaded_recipe, first_title="Backend Intern Updated"),
                imported_at=now + timedelta(seconds=2),
            )

            assert unchanged.items_found == 3
            assert unchanged.items_new == unchanged.items_updated == 0
            assert changed.items_updated == 1
            assert changed.items_missing == changed.items_removed == 0
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 3
            assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 9
            assert session.scalar(select(func.count()).select_from(Job)) == 3
            assert session.scalar(select(func.count()).select_from(JobChange)) == 4
            assert all(job.status is JobStatus.ACTIVE for job in session.scalars(select(Job)))

            snapshots = session.scalars(select(RawJobSnapshot)).all()
            assert {snapshot.source_url for snapshot in snapshots} == {
                "https://example.test/careers/1",
                "https://example.test/careers/2",
                "https://example.test/careers/3",
            }
            assert all(json.loads(snapshot.raw_content)["document_hash"] for snapshot in snapshots)
            runs = session.scalars(select(CrawlRun)).all()
            assert all(run.request_hash and len(run.request_hash) == 64 for run in runs)
            assert all(
                run.requested_by == f"document-import:{loaded_recipe.owner_user_id}" for run in runs
            )

            active_prepared = _prepared(loaded_recipe)
            source = ensure_recipe_source(session, loaded_recipe)
            session.commit()
            request_hash = _document_request_hash(loaded_recipe, active_prepared)
            config = replace(
                recipe_source_config(loaded_recipe, source),
                config_version=request_hash,
            )
            active_key = "document-import-active"
            trigger_key = (
                "document-import:"
                + sha256(
                    f"{loaded_recipe.owner_user_id}:{loaded_recipe.id}:{active_key}".encode()
                ).hexdigest()
            )
            _create_run(
                session,
                source_id=source.id,
                config=config,
                adapter=DocumentImportAdapter(
                    recipe=loaded_recipe,
                    config=config,
                    prepared=active_prepared,
                    imported_at=now,
                ),
                started_at=now,
                trigger_type=CrawlTriggerType.MANUAL,
                trigger_key=trigger_key,
                requested_by=f"document-import:{loaded_recipe.owner_user_id}",
                request_hash=request_hash,
                scheduled_for=None,
                retry_of_run_id=None,
                attempt_number=1,
            )

            with pytest.raises(DocumentImportError) as in_progress:
                import_recipe_document(
                    session,
                    recipe_id=loaded_recipe.id,
                    owner_user_id=loaded_recipe.owner_user_id,
                    idempotency_key=active_key,
                    prepared=active_prepared,
                    imported_at=now,
                )
            assert in_progress.value.code == "document_import_in_progress"

            with pytest.raises(DocumentImportError) as active_conflict:
                import_recipe_document(
                    session,
                    recipe_id=loaded_recipe.id,
                    owner_user_id=loaded_recipe.owner_user_id,
                    idempotency_key=active_key,
                    prepared=_prepared(loaded_recipe, first_title="Changed while active"),
                    imported_at=now,
                )
            assert active_conflict.value.code == "idempotency_conflict"
    finally:
        engine.dispose()
