from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.catalog.models import Job, JobLevel, JobStatus
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
from devradar.matching.models import JobMatch, ResumeProfile
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOB_MATCH_BASE_REVISION = "d5e8f1a4c602"


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def _graph(session: Session, now: datetime) -> tuple[Job, ResumeProfile]:
    source = Source(
        name="V5 fixture",
        base_url="https://careers.example.test/careers",
        adapter_key="fixture_adapter",
        approval_status=SourceApprovalStatus.APPROVED,
        rate_limit_policy={"requests_per_second": 0.5, "concurrency": 1},
        allowed_hosts=["careers.example.test"],
        terms_reviewed_at=now,
        robots_reviewed_at=now,
    )
    session.add(source)
    session.flush()
    run = CrawlRun(
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
    session.add(run)
    session.flush()
    snapshot = RawJobSnapshot(
        crawl_run_id=run.id,
        source_id=source.id,
        source_url="https://careers.example.test/jobs/1",
        external_id="job-1",
        fetched_at=now,
        http_status=200,
        content_type="text/html",
        raw_content_hash="a" * 64,
        raw_content="<html>fixture</html>",
        parse_status=ParseStatus.PARSED,
    )
    session.add(snapshot)
    session.flush()
    job = Job(
        source_id=source.id,
        external_id="job-1",
        canonical_url="https://careers.example.test/jobs/1",
        title="Backend Engineer",
        company_name="Example",
        levels=[JobLevel.MID.value],
        first_seen_at=now,
        last_seen_at=now,
        current_snapshot_id=snapshot.id,
        job_content_hash="b" * 64,
        status=JobStatus.ACTIVE,
    )
    profile = ResumeProfile(
        owner_hash="c" * 64,
        content_hash="d" * 64,
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
    session.add_all([job, profile])
    session.flush()
    return job, profile


def _match(job: Job, profile: ResumeProfile, *, job_hash: str | None = None) -> JobMatch:
    return JobMatch(
        resume_profile_id=profile.id,
        job_id=job.id,
        profile_content_hash=profile.content_hash,
        profile_parser_version=profile.parser_version,
        job_content_hash=job_hash or job.job_content_hash,
        scoring_version="job-match-scoring-v1",
        profile_embedding_input_version="resume-match-embedding-input-v1",
        job_embedding_input_schema_version="job-embedding-input-v2",
        extraction_version="deterministic-job-v2",
        extraction_schema_version="job-extraction-schema-v1",
        extraction_canonicalization_version="extraction-canonicalization-v1",
        overall_score=Decimal("0.7900"),
        evidence_coverage=Decimal("1.0000"),
        skill_score=Decimal("0.6000"),
        semantic_score=Decimal("0.8000"),
        experience_score=Decimal("1.0000"),
        location_score=Decimal("1.0000"),
        role_score=Decimal("1.0000"),
        matched_skills=["python"],
        missing_skills=["postgresql"],
        explanation=["skill_partial", "semantic_available"],
        embedding_provider="local_fastembed",
        embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedding_revision="f" * 40,
        embedding_dimension=384,
    )


@pytest.mark.postgresql
def test_job_match_migration_schema_stale_identity_and_round_trip(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(fresh_postgresql_url)
    inspector = inspect(engine)
    assert "job_matches" in inspector.get_table_names()
    assert {
        "id",
        "resume_profile_id",
        "job_id",
        "profile_content_hash",
        "profile_parser_version",
        "job_content_hash",
        "scoring_version",
        "profile_embedding_input_version",
        "job_embedding_input_schema_version",
        "extraction_version",
        "extraction_schema_version",
        "extraction_canonicalization_version",
        "overall_score",
        "evidence_coverage",
        "skill_score",
        "semantic_score",
        "experience_score",
        "location_score",
        "role_score",
        "matched_skills",
        "missing_skills",
        "explanation",
        "embedding_provider",
        "embedding_model",
        "embedding_revision",
        "embedding_dimension",
        "created_at",
    } <= {column["name"] for column in inspector.get_columns("job_matches")}
    checks = {item["name"] for item in inspector.get_check_constraints("job_matches")}
    assert {
        "ck_job_matches_score_range",
        "ck_job_matches_evidence_coverage_range",
        "ck_job_matches_hash_shape",
        "ck_job_matches_embedding_identity",
        "ck_job_matches_structured_bounds",
    } <= checks
    indexes = {item["name"] for item in inspector.get_indexes("job_matches")}
    assert {"uq_job_matches_logical_key", "ix_job_matches_profile_score_job"} <= indexes

    now = datetime.now(UTC)
    with Session(engine) as session:
        job, profile = _graph(session, now)
        persisted = _match(job, profile)
        session.add(persisted)
        session.commit()
        loaded = session.scalar(select(JobMatch).where(JobMatch.id == persisted.id))
        assert loaded is not None
        assert loaded.overall_score == Decimal("0.7900")

        current = session.scalar(
            select(JobMatch)
            .join(Job, Job.id == JobMatch.job_id)
            .where(
                JobMatch.profile_content_hash == profile.content_hash,
                JobMatch.job_content_hash == Job.job_content_hash,
                JobMatch.scoring_version == "job-match-scoring-v1",
            )
        )
        assert current is not None
        job.job_content_hash = "e" * 64
        session.commit()
        stale = session.scalar(
            select(JobMatch)
            .join(Job, Job.id == JobMatch.job_id)
            .where(
                JobMatch.job_content_hash == Job.job_content_hash,
            )
        )
        assert stale is None

        refreshed = _match(job, profile)
        session.add(refreshed)
        session.commit()
        assert session.scalar(select(JobMatch).where(JobMatch.id == refreshed.id)) is not None

    engine.dispose()


@pytest.mark.postgresql
def test_extraction_identity_migration_keeps_historical_rows_stale(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, JOB_MATCH_BASE_REVISION)
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        job, profile = _graph(session, now)
        session.execute(
            text(
                """
                INSERT INTO job_matches (
                    id, resume_profile_id, job_id, profile_content_hash,
                    profile_parser_version, job_content_hash, scoring_version,
                    profile_embedding_input_version, job_embedding_input_schema_version,
                    overall_score, evidence_coverage, skill_score, semantic_score,
                    experience_score, location_score, role_score, matched_skills,
                    missing_skills, explanation, embedding_provider, embedding_model,
                    embedding_revision, embedding_dimension
                ) VALUES (
                    :id, :profile_id, :job_id, :profile_hash, :parser_version,
                    :job_hash, 'job-match-scoring-v1',
                    'resume-match-embedding-input-v1', 'job-embedding-input-v2',
                    0.5000, 1.0000, 0.5000, 0.5000, 0.5000, 0.5000, 0.5000,
                    CAST(:matched AS jsonb), CAST(:missing AS jsonb),
                    CAST(:explanation AS jsonb), 'local_fastembed',
                    'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                    :revision, 384
                )
                """
            ),
            {
                "id": uuid4(),
                "profile_id": profile.id,
                "job_id": job.id,
                "profile_hash": profile.content_hash,
                "parser_version": profile.parser_version,
                "job_hash": job.job_content_hash,
                "matched": '["python"]',
                "missing": "[]",
                "explanation": '["legacy"]',
                "revision": "f" * 40,
            },
        )
        session.commit()
    command.upgrade(config, "head")
    with Session(engine) as session:
        row = session.scalar(select(JobMatch))
        assert row is not None
        assert row.extraction_version == "legacy-pre-extraction-identity"
        assert row.extraction_schema_version == "legacy-pre-extraction-identity"
        assert row.extraction_canonicalization_version == "legacy-pre-extraction-identity"
    engine.dispose()


@pytest.mark.postgresql
def test_job_match_constraints_and_parent_delete_cascade(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        job, profile = _graph(session, now)
        session.commit()
        invalid = _match(job, profile)
        invalid.overall_score = Decimal("1.0001")
        session.add(invalid)
        with pytest.raises(IntegrityError, match="ck_job_matches_score_range"):
            session.commit()
        session.rollback()

        persisted = _match(job, profile)
        session.add(persisted)
        session.commit()
        persisted_id = persisted.id
        session.delete(profile)
        session.commit()
        assert session.scalar(select(JobMatch).where(JobMatch.id == persisted_id)) is None

        profile = ResumeProfile(
            owner_hash="1" * 64,
            content_hash="2" * 64,
            file_name_sanitized="profile.pdf",
            source_format="pdf",
            parser_version="resume-profile-parser-v1",
            extraction_status="accepted",
            skills=[],
            roles=[],
            locations=[],
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        session.add(profile)
        session.flush()
        persisted = _match(job, profile)
        session.add(persisted)
        session.commit()
        persisted_id = persisted.id
        session.delete(job)
        session.commit()
        assert session.scalar(select(JobMatch).where(JobMatch.id == persisted_id)) is None
    engine.dispose()
