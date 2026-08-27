from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.catalog.models import Job, JobLevel
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_TABLES = {
    "sources",
    "crawl_runs",
    "raw_job_snapshots",
    "jobs",
    "extraction_results",
    "job_embeddings",
    "resume_profiles",
    "job_matches",
    "alert_rules",
    "alert_deliveries",
    "source_recipes",
    "source_recipe_previews",
}


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def _assert_constraint_rejects(session: Session, instance: object, constraint_name: str) -> None:
    session.add(instance)
    with pytest.raises(IntegrityError) as captured:
        session.commit()
    session.rollback()
    assert constraint_name in str(captured.value.orig)


def _approved_source(name: str, host: str, reviewed_at: datetime) -> Source:
    return Source(
        name=name,
        base_url=f"https://{host}/careers",
        adapter_key=f"{name.lower()}_adapter",
        approval_status=SourceApprovalStatus.APPROVED,
        rate_limit_policy={"requests_per_second": 0.5, "concurrency": 1},
        allowed_hosts=[host],
        robots_reviewed_at=reviewed_at,
    )


@pytest.mark.postgresql
def test_migration_and_domain_invariants_on_postgresql(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    alembic_config = _alembic_config()

    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    head_engine = create_engine(fresh_postgresql_url)
    head_tables = inspect(head_engine).get_table_names()
    head_engine.dispose()
    assert "agent_runs" not in head_tables
    assert "custom_source_profiles" not in head_tables

    command.downgrade(alembic_config, "f4a6c2d8e901")
    historical_engine = create_engine(fresh_postgresql_url)
    historical_tables = inspect(historical_engine).get_table_names()
    historical_engine.dispose()
    assert "agent_runs" in historical_tables

    command.upgrade(alembic_config, "head")
    restored_head_engine = create_engine(fresh_postgresql_url)
    restored_head_tables = inspect(restored_head_engine).get_table_names()
    restored_head_engine.dispose()
    assert "agent_runs" not in restored_head_tables

    command.check(alembic_config)

    engine = create_engine(fresh_postgresql_url)
    inspector = inspect(engine)
    assert DOMAIN_TABLES <= set(inspector.get_table_names())

    expected_checks = {
        "sources": {"ck_sources_approved_has_robots_review", "ck_sources_approval_status"},
        "crawl_runs": {
            "ck_crawl_runs_status_time_boundary",
            "ck_crawl_runs_coverage_status",
            "ck_crawl_runs_counters_non_negative",
        },
        "raw_job_snapshots": {
            "ck_raw_job_snapshots_content_hash",
            "ck_raw_job_snapshots_parse_status",
        },
        "jobs": {"ck_jobs_salary_range", "ck_jobs_levels_allowed_values"},
        "extraction_results": {
            "ck_extraction_results_input_hash",
            "ck_extraction_results_status",
        },
        "job_embeddings": {
            "ck_job_embeddings_input_hash",
            "ck_job_embeddings_provider",
            "ck_job_embeddings_model_revision",
            "ck_job_embeddings_dimension",
            "ck_job_embeddings_latency",
        },
        "resume_profiles": {
            "ck_resume_profiles_owner_hash",
            "ck_resume_profiles_content_hash",
            "ck_resume_profiles_source_format",
            "ck_resume_profiles_extraction_status",
            "ck_resume_profiles_retention_mode",
            "ck_resume_profiles_expires_after_creation",
            "ck_resume_profiles_structured_arrays",
        },
        "job_matches": {
            "ck_job_matches_score_range",
            "ck_job_matches_evidence_coverage_range",
            "ck_job_matches_hash_shape",
            "ck_job_matches_embedding_identity",
            "ck_job_matches_structured_bounds",
        },
        "alert_rules": {
            "ck_alert_rules_owner_hash",
            "ck_alert_rules_name_not_blank",
            "ck_alert_rules_has_predicate",
            "ck_alert_rules_match_score",
            "ck_alert_rules_match_profile",
            "ck_alert_rules_channel",
        },
        "alert_deliveries": {
            "ck_alert_deliveries_idempotency_key",
            "ck_alert_deliveries_job_content_hash",
            "ck_alert_deliveries_status",
            "ck_alert_deliveries_attempts",
            "ck_alert_deliveries_provider_reference",
            "ck_alert_deliveries_error_code",
        },
        "source_recipes": {
            "ck_source_recipes_status",
            "ck_source_recipes_schedule",
            "ck_source_recipes_budgets",
            "ck_source_recipes_seniority_filter",
            "ck_source_recipes_https_listing_url",
        },
        "source_recipe_previews": {
            "ck_source_recipe_previews_status",
            "ck_source_recipe_previews_payloads",
            "ck_source_recipe_previews_screenshot_size",
            "ck_source_recipe_previews_expiry",
        },
    }
    for table_name, constraint_names in expected_checks.items():
        reflected_names = {
            constraint["name"] for constraint in inspector.get_check_constraints(table_name)
        }
        assert constraint_names <= reflected_names

    now = datetime.now(UTC)
    with Session(engine) as session:
        source = _approved_source("VNG", "careers.vng.com.vn", now)
        session.add(source)
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
            adapter_version="fixture-v1",
            config_version="source-v1",
        )
        session.add(crawl_run)
        session.flush()

        snapshot = RawJobSnapshot(
            crawl_run_id=crawl_run.id,
            source_id=source.id,
            source_url="https://careers.vng.com.vn/job/123",
            external_id="123",
            fetched_at=now,
            http_status=200,
            content_type="text/html; charset=utf-8",
            raw_content_hash="a" * 64,
            raw_content="<html>fixture</html>",
            parse_status=ParseStatus.PARSED,
        )
        session.add(snapshot)
        session.flush()

        job = Job(
            source_id=source.id,
            external_id="123",
            canonical_url="https://careers.vng.com.vn/job/123",
            title="Senior Backend Engineer",
            company_name="VNG",
            salary_raw="30-50 triệu VND/tháng",
            salary_min=Decimal("30000000"),
            salary_max=Decimal("50000000"),
            currency="VND",
            salary_period="month",
            level_raw="Senior",
            levels=[JobLevel.SENIOR.value],
            first_seen_at=now,
            last_seen_at=now,
            current_snapshot_id=snapshot.id,
            job_content_hash="b" * 64,
        )
        session.add(job)
        session.commit()

        persisted_job = session.scalar(select(Job).where(Job.id == job.id))
        assert persisted_job is not None
        assert persisted_job.source_id == source.id
        assert persisted_job.salary_raw == "30-50 triệu VND/tháng"
        assert persisted_job.levels == [JobLevel.SENIOR.value]

        _assert_constraint_rejects(
            session,
            Source(
                name="Missing policy evidence",
                base_url="https://example.test/jobs",
                adapter_key="missing_policy",
                approval_status=SourceApprovalStatus.APPROVED,
                rate_limit_policy={"concurrency": 1},
                allowed_hosts=["example.test"],
            ),
            "ck_sources_approved_has_robots_review",
        )

        _assert_constraint_rejects(
            session,
            Job(
                source_id=source.id,
                external_id="salary-invalid",
                canonical_url="https://careers.vng.com.vn/job/salary-invalid",
                title="Invalid salary",
                company_name="VNG",
                salary_min=Decimal("50000000"),
                salary_max=Decimal("30000000"),
                levels=[],
                first_seen_at=now,
                last_seen_at=now,
                current_snapshot_id=snapshot.id,
                job_content_hash="c" * 64,
            ),
            "ck_jobs_salary_range",
        )

        second_source = _approved_source("NAVER", "recruit.navercorp.com", now)
        session.add(second_source)
        session.commit()

        _assert_constraint_rejects(
            session,
            Job(
                source_id=second_source.id,
                external_id="wrong-provenance",
                canonical_url="https://recruit.navercorp.com/job/wrong-provenance",
                title="Wrong provenance",
                company_name="NAVER",
                levels=[],
                first_seen_at=now,
                last_seen_at=now,
                current_snapshot_id=snapshot.id,
                job_content_hash="d" * 64,
            ),
            "fk_jobs_current_snapshot_source",
        )

        _assert_constraint_rejects(
            session,
            Job(
                source_id=source.id,
                external_id="123",
                canonical_url="https://careers.vng.com.vn/job/duplicate-id",
                title="Duplicate external ID",
                company_name="VNG",
                levels=[],
                first_seen_at=now,
                last_seen_at=now,
                current_snapshot_id=snapshot.id,
                job_content_hash="e" * 64,
            ),
            "uq_jobs_source_external_id",
        )

    engine.dispose()
    command.downgrade(alembic_config, "base")

    downgraded_engine = create_engine(fresh_postgresql_url)
    assert not (DOMAIN_TABLES & set(inspect(downgraded_engine).get_table_names()))
    downgraded_engine.dispose()

    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
