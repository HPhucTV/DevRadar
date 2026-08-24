from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from devradar.alerts.models import AlertDelivery, AlertRule
from devradar.auth.models import AuthSession, User
from devradar.catalog.models import Job, JobChange, JobChangeType, JobLevel, JobStatus
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRunStatus,
    CrawlTriggerType,
    ParseStatus,
    RawJobSnapshot,
    Source,
    SourceApprovalStatus,
)
from devradar.intelligence.models import ExtractionResult, JobEmbedding
from devradar.matching.models import JobMatch, ResumeProfile
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "f9b3c1d7e2a4"
RESET_REVISION = "b4c6d8e0f2a1"

PURGED_TABLES = (
    "alert_deliveries",
    "job_matches",
    "job_embeddings",
    "extraction_results",
    "job_changes",
    "jobs",
    "raw_job_snapshots",
    "crawl_runs",
    "custom_source_profiles",
    "sources",
)

PRESERVED_TABLES = (
    "auth_users",
    "auth_sessions",
    "resume_profiles",
    "alert_rules",
)


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def _seed_complete_legacy_graph(session: Session) -> dict[str, object]:
    now = datetime.now(UTC)
    user = User(username="reset-owner", password_hash="x" * 64)
    source = Source(
        name="Legacy custom source",
        base_url="https://example.test/jobs",
        adapter_key="custom_source",
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        rate_limit_policy={"requests_per_minute": 2, "concurrency": 1},
        allowed_hosts=["example.test"],
    )
    profile = ResumeProfile(
        owner_hash="a" * 64,
        content_hash="b" * 64,
        file_name_sanitized="profile.pdf",
        source_format="pdf",
        parser_version="resume-profile-parser-v1",
        extraction_status="accepted",
        skills=["python"],
        roles=["backend"],
        locations=["Ho Chi Minh City"],
        experience_years=Decimal("3"),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    alert_rule = AlertRule(
        owner_hash="c" * 64,
        name="Standalone preserved rule",
        company_query="Example",
    )
    session.add_all([user, source, profile, alert_rule])
    session.flush()

    auth_session = AuthSession(
        user_id=user.id,
        token_hash="d" * 64,
        csrf_hash="e" * 64,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=8),
    )
    crawl_run_id = uuid4()
    session.add(auth_session)
    session.flush()
    session.execute(
        text(
            "INSERT INTO custom_source_profiles ("
            "id, source_id, owner_user_id, name, status, base_url, allowed_hosts, "
            "allowed_path_prefixes, parser_mode, field_mapping, schedule_kind, "
            "interval_minutes, timezone, item_budget, byte_budget, requests_per_minute, "
            "permission_acknowledged_at"
            ") VALUES ("
            ":id, :source_id, :owner_user_id, :name, 'enabled', :base_url, "
            "CAST(:allowed_hosts AS jsonb), CAST(:allowed_paths AS jsonb), 'auto', "
            "'{}'::jsonb, 'interval', 360, 'Asia/Ho_Chi_Minh', 500, 2000000, 2, :now"
            ")"
        ),
        {
            "id": uuid4(),
            "source_id": source.id,
            "owner_user_id": user.id,
            "name": "Legacy profile",
            "base_url": "https://example.test/jobs",
            "allowed_hosts": '["example.test"]',
            "allowed_paths": '["/jobs"]',
            "now": now,
        },
    )
    session.execute(
        text(
            "INSERT INTO crawl_runs ("
            "id, source_id, trigger_type, status, coverage_status, started_at, finished_at, "
            "pages_found, items_found, adapter_version, config_version"
            ") VALUES ("
            ":id, :source_id, :trigger_type, :status, :coverage_status, :started_at, :finished_at, "
            ":pages_found, :items_found, :adapter_version, :config_version"
            ")"
        ),
        {
            "id": crawl_run_id,
            "source_id": source.id,
            "trigger_type": CrawlTriggerType.MANUAL.value,
            "status": CrawlRunStatus.SUCCEEDED.value,
            "coverage_status": CoverageStatus.COMPLETE.value,
            "started_at": now,
            "finished_at": now + timedelta(seconds=1),
            "pages_found": 1,
            "items_found": 1,
            "adapter_version": "legacy-v1",
            "config_version": "legacy-v1",
        },
    )

    snapshot = RawJobSnapshot(
        crawl_run_id=crawl_run_id,
        source_id=source.id,
        source_url="https://example.test/jobs/1",
        external_id="job-1",
        fetched_at=now,
        http_status=200,
        content_type="text/html",
        raw_content_hash="f" * 64,
        raw_content="fixture",
        parse_status=ParseStatus.PARSED,
    )
    session.add(snapshot)
    session.flush()

    job = Job(
        source_id=source.id,
        external_id="job-1",
        canonical_url="https://example.test/jobs/1",
        title="Backend Engineer",
        company_name="Example",
        levels=[JobLevel.MID.value],
        first_seen_at=now,
        last_seen_at=now,
        status=JobStatus.ACTIVE,
        current_snapshot_id=snapshot.id,
        job_content_hash="1" * 64,
    )
    session.add(job)
    session.flush()

    session.add_all(
        [
            JobChange(
                job_id=job.id,
                crawl_run_id=crawl_run_id,
                to_snapshot_id=snapshot.id,
                field_name="job",
                old_value=None,
                new_value={"created": True},
                change_type=JobChangeType.CREATED,
                detected_at=now,
            ),
            ExtractionResult(
                input_type="job",
                input_ref=job.id,
                input_hash=job.job_content_hash,
                extractor_type="rule",
                extractor_version="deterministic-job-v2",
                schema_version="job-extraction-schema-v1",
                canonicalization_version="extraction-canonicalization-v1",
                output_data={"skills": []},
                validation_status="accepted",
            ),
            JobEmbedding(
                job_id=job.id,
                input_hash=job.job_content_hash,
                input_schema_version="job-embedding-input-v2",
                provider="local_fastembed",
                model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                model_revision="2" * 40,
                dimension=384,
                embedding=[0.0] * 384,
            ),
            JobMatch(
                resume_profile_id=profile.id,
                job_id=job.id,
                profile_content_hash=profile.content_hash,
                profile_parser_version=profile.parser_version,
                job_content_hash=job.job_content_hash,
                scoring_version="job-match-scoring-v1",
                profile_embedding_input_version="resume-match-embedding-input-v1",
                job_embedding_input_schema_version="job-embedding-input-v2",
                extraction_version="deterministic-job-v2",
                extraction_schema_version="job-extraction-schema-v1",
                extraction_canonicalization_version="extraction-canonicalization-v1",
                overall_score=Decimal("0.8"),
                evidence_coverage=Decimal("1"),
                matched_skills=["python"],
                missing_skills=[],
                explanation=["fixture"],
                embedding_provider="local_fastembed",
                embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                embedding_revision="2" * 40,
                embedding_dimension=384,
            ),
            AlertDelivery(
                alert_rule_id=alert_rule.id,
                job_id=job.id,
                job_content_hash=job.job_content_hash,
                idempotency_key="3" * 64,
            ),
        ]
    )
    session.commit()
    return {
        "user_id": user.id,
        "auth_session_id": auth_session.id,
        "resume_profile_id": profile.id,
        "alert_rule_id": alert_rule.id,
    }


def _table_counts(session: Session, table_names: tuple[str, ...]) -> dict[str, int]:
    return {
        table_name: int(session.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one())
        for table_name in table_names
    }


@pytest.mark.postgresql
def test_reset_purges_source_graph_and_preserves_local_owner_data(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(fresh_postgresql_url)
    try:
        with Session(engine) as session:
            preserved_ids = _seed_complete_legacy_graph(session)
            assert all(count == 1 for count in _table_counts(session, PURGED_TABLES).values())

        command.upgrade(config, RESET_REVISION)
        with Session(engine) as session:
            assert _table_counts(session, PURGED_TABLES) == dict.fromkeys(PURGED_TABLES, 0)
            assert all(count == 1 for count in _table_counts(session, PRESERVED_TABLES).values())
            assert session.get(User, preserved_ids["user_id"]) is not None
            assert session.get(AuthSession, preserved_ids["auth_session_id"]) is not None
            assert session.get(ResumeProfile, preserved_ids["resume_profile_id"]) is not None
            assert session.get(AlertRule, preserved_ids["alert_rule_id"]) is not None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_reset_rolls_back_all_deletes_when_migration_fails(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(fresh_postgresql_url)
    try:
        with Session(engine) as session:
            _seed_complete_legacy_graph(session)
            before = _table_counts(session, PURGED_TABLES + PRESERVED_TABLES)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION fail_source_reset() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN RAISE EXCEPTION 'forced_source_reset_failure'; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER fail_source_reset BEFORE DELETE ON sources "
                    "FOR EACH STATEMENT EXECUTE FUNCTION fail_source_reset()"
                )
            )

        with pytest.raises(DBAPIError, match="forced_source_reset_failure"):
            command.upgrade(config, RESET_REVISION)

        with Session(engine) as session:
            assert _table_counts(session, PURGED_TABLES + PRESERVED_TABLES) == before
            assert session.scalar(select(func.count()).select_from(Source)) == 1
            current_revision = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert current_revision == PREVIOUS_REVISION
    finally:
        engine.dispose()
