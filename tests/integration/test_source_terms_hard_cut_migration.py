from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from devradar.auth.models import User
from devradar.catalog.models import Job, JobChange, JobChangeType, JobStatus
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    ParseStatus,
    RawJobSnapshot,
    Source,
    SourceApprovalStatus,
)
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.models import RecipeStatus, SourceRecipe, TermsNotice

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "e8f2a4c6d901"
TARGET_REVISION = "f1a3c5e7b902"
PRESERVED_TABLES = (
    "source_recipes",
    "sources",
    "crawl_runs",
    "raw_job_snapshots",
    "jobs",
    "job_changes",
)
REMOVED_RECIPE_COLUMNS = {
    "terms_acknowledged_at",
    "terms_reviewed_at",
    "terms_evidence_url",
    "terms_notice_version",
    "terms_notice",
}


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def _table_counts(session: Session, table_names: tuple[str, ...]) -> dict[str, int]:
    return {
        table_name: int(session.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one())
        for table_name in table_names
    }


def _table_ids(session: Session, table_names: tuple[str, ...]) -> dict[str, set[UUID]]:
    return {
        table_name: set(session.execute(text(f'SELECT id FROM "{table_name}"')).scalars())
        for table_name in table_names
    }


def _seed_graph(session: Session) -> dict[str, UUID]:
    now = datetime.now(UTC)
    owner = User(username="terms-hard-cut-owner", password_hash="a" * 64)
    source = Source(
        name="Terms hard cut source",
        base_url="https://jobs.example.test",
        adapter_key="terms_hard_cut",
        approval_status=SourceApprovalStatus.APPROVED,
        rate_limit_policy={"requests_per_second": 0.5, "concurrency": 1},
        allowed_hosts=["jobs.example.test"],
        terms_reviewed_at=now,
        robots_reviewed_at=now,
    )
    session.add_all([owner, source])
    session.flush()

    recipe = SourceRecipe(
        owner_user_id=owner.id,
        source_id=source.id,
        name="Terms hard cut recipe",
        status=RecipeStatus.ENABLED,
        listing_url="https://jobs.example.test/listings",
        origin="https://jobs.example.test",
        allowed_hosts=["jobs.example.test"],
        allowed_path_prefixes=["/"],
        terms_notice=TermsNotice.RESTRICTED_TERMS,
        terms_notice_version="terms-hard-cut-v1",
        terms_evidence_url="https://jobs.example.test/terms",
        terms_reviewed_at=now,
        terms_acknowledged_at=now,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=["all"],
        config_version="terms-hard-cut-v1",
        item_budget=10,
        page_budget=1,
        request_budget=10,
        byte_budget=100_000,
        time_budget_seconds=60,
        requests_per_minute=2,
    )
    session.add(recipe)
    session.flush()

    crawl_run = CrawlRun(
        source_id=source.id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        pages_found=1,
        items_found=1,
        adapter_version="terms-hard-cut-v1",
        config_version="terms-hard-cut-v1",
    )
    session.add(crawl_run)
    session.flush()

    snapshot = RawJobSnapshot(
        crawl_run_id=crawl_run.id,
        source_id=source.id,
        source_url="https://jobs.example.test/listings/1",
        external_id="terms-hard-cut-1",
        fetched_at=now,
        http_status=200,
        content_type="application/json",
        raw_content_hash="b" * 64,
        raw_content='{"title":"Backend Engineer"}',
        parse_status=ParseStatus.PARSED,
    )
    session.add(snapshot)
    session.flush()

    job = Job(
        source_id=source.id,
        external_id="terms-hard-cut-1",
        canonical_url=snapshot.source_url,
        title="Backend Engineer",
        company_name="Example",
        levels=["mid"],
        first_seen_at=now,
        last_seen_at=now,
        status=JobStatus.ACTIVE,
        current_snapshot_id=snapshot.id,
        job_content_hash="c" * 64,
    )
    session.add(job)
    session.flush()
    change = JobChange(
        job_id=job.id,
        crawl_run_id=crawl_run.id,
        to_snapshot_id=snapshot.id,
        field_name="job",
        old_value=None,
        new_value={"created": True},
        change_type=JobChangeType.CREATED,
        detected_at=now,
    )
    session.add(change)
    session.commit()
    return {
        "recipe_id": recipe.id,
        "source_id": source.id,
        "crawl_run_id": crawl_run.id,
        "snapshot_id": snapshot.id,
        "job_id": job.id,
        "change_id": change.id,
    }


@pytest.mark.postgresql
def test_source_terms_hard_cut_preserves_canonical_graph(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(fresh_postgresql_url)
    try:
        with Session(engine) as session:
            ids = _seed_graph(session)
            before = _table_counts(session, PRESERVED_TABLES)
            before_ids = _table_ids(session, PRESERVED_TABLES)

        command.upgrade(config, TARGET_REVISION)

        with Session(engine) as session:
            assert _table_counts(session, PRESERVED_TABLES) == before
            assert _table_ids(session, PRESERVED_TABLES) == before_ids
            assert session.get(Job, ids["job_id"]) is not None

        inspector = inspect(engine)
        recipe_columns = {column["name"] for column in inspector.get_columns("source_recipes")}
        source_columns = {column["name"] for column in inspector.get_columns("sources")}
        source_checks = {
            constraint["name"] for constraint in inspector.get_check_constraints("sources")
        }
        assert not REMOVED_RECIPE_COLUMNS & recipe_columns
        assert "terms_reviewed_at" not in source_columns
        assert "ck_sources_approved_has_robots_review" in source_checks

        command.downgrade(config, PREVIOUS_REVISION)

        downgraded_inspector = inspect(engine)
        downgraded_recipe_columns = {
            column["name"] for column in downgraded_inspector.get_columns("source_recipes")
        }
        downgraded_source_columns = {
            column["name"] for column in downgraded_inspector.get_columns("sources")
        }
        downgraded_source_checks = {
            constraint["name"]
            for constraint in downgraded_inspector.get_check_constraints("sources")
        }
        assert REMOVED_RECIPE_COLUMNS <= downgraded_recipe_columns
        assert "terms_reviewed_at" in downgraded_source_columns
        assert "ck_sources_approved_has_policy_reviews" in downgraded_source_checks
        with Session(engine) as session:
            restored_recipe = session.execute(
                text(
                    "SELECT terms_notice, terms_notice_version, terms_acknowledged_at "
                    "FROM source_recipes WHERE id = :recipe_id"
                ),
                {"recipe_id": ids["recipe_id"]},
            ).one()
            assert restored_recipe == ("not_reviewed", "0" * 64, None)

        command.upgrade(config, TARGET_REVISION)

        with Session(engine) as session:
            assert _table_counts(session, PRESERVED_TABLES) == before
            assert _table_ids(session, PRESERVED_TABLES) == before_ids
            assert session.get(Job, ids["job_id"]) is not None
    finally:
        engine.dispose()
