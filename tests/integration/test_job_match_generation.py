from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
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
from devradar.intelligence.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_PROVIDER,
    EmbeddingModelUnavailable,
)
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    DETERMINISTIC_EXTRACTOR_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)
from devradar.intelligence.models import ExtractionResult, JobEmbedding
from devradar.matching.job_matches import (
    PROFILE_EMBEDDING_INPUT_VERSION,
    MatchProfileUnavailable,
    generate_job_matches,
)
from devradar.matching.models import JobMatch, ResumeProfile
from devradar.matching.scoring import SCORING_VERSION
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _payload(*, skills: bool = True) -> dict[str, object]:
    return {
        "levels": ["mid"],
        "experience": {"minimumYears": None, "maximumYears": None},
        "salary": {"minimum": None, "maximum": None, "currency": None, "period": None},
        "location": {"city": "Ho Chi Minh City", "province": "Ho Chi Minh City", "workMode": None},
        "skills": (
            [{"name": "python", "requirementType": "required", "evidence": "Python"}]
            if skills
            else [{"invalid": True}]
        ),
    }


def _seed(session: Session, *, job_count: int = 1) -> tuple[ResumeProfile, list[Job]]:
    now = datetime.now(UTC)
    source = Source(
        name="Generation fixture",
        base_url="https://careers.example.test/careers",
        adapter_key="generation_fixture",
        approval_status=SourceApprovalStatus.APPROVED,
        rate_limit_policy={"requests_per_second": 1, "concurrency": 1},
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
        finished_at=now,
        pages_found=1,
        items_found=job_count,
        adapter_version="fixture-v1",
        config_version="fixture-v1",
    )
    session.add(run)
    session.flush()
    snapshot = RawJobSnapshot(
        crawl_run_id=run.id,
        source_id=source.id,
        source_url="https://careers.example.test/jobs/0",
        external_id="0",
        fetched_at=now,
        http_status=200,
        content_type="text/html",
        raw_content_hash="a" * 64,
        raw_content="fixture",
        parse_status=ParseStatus.PARSED,
    )
    session.add(snapshot)
    session.flush()
    jobs: list[Job] = []
    for index in range(job_count):
        job = Job(
            source_id=source.id,
            external_id=str(index),
            canonical_url=f"https://careers.example.test/jobs/{index}",
            title="Backend Engineer",
            company_name="Example",
            description_text="Python API work",
            levels=[JobLevel.MID.value],
            experience_min=Decimal("2"),
            location_raw="Ho Chi Minh City",
            location_city="Ho Chi Minh City",
            location_province="Ho Chi Minh City",
            first_seen_at=now,
            last_seen_at=now,
            status=JobStatus.ACTIVE,
            current_snapshot_id=snapshot.id,
            job_content_hash=(f"{index + 1:064x}"),
        )
        jobs.append(job)
    profile = ResumeProfile(
        owner_hash="b" * 64,
        content_hash="c" * 64,
        file_name_sanitized="private-profile.pdf",
        source_format="pdf",
        parser_version="resume-profile-parser-v1",
        extraction_status="accepted",
        skills=["python", "fastapi"],
        roles=["backend"],
        locations=["Ho Chi Minh City"],
        experience_years=Decimal("3"),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add_all([*jobs, profile])
    session.commit()
    for index, job in enumerate(jobs):
        vector = [0.0] * EMBEDDING_DIMENSION
        vector[0] = 1.0
        vector[1] = 1.0 - (index / max(job_count, 1))
        session.add(
            JobEmbedding(
                job_id=job.id,
                input_hash=job.job_content_hash,
                input_schema_version=EMBEDDING_INPUT_SCHEMA_VERSION,
                provider=EMBEDDING_PROVIDER,
                model=EMBEDDING_MODEL_ID,
                model_revision=EMBEDDING_MODEL_REVISION,
                dimension=EMBEDDING_DIMENSION,
                embedding=vector,
            )
        )
    session.add(
        ExtractionResult(
            input_type="job",
            input_ref=jobs[0].id,
            input_hash=jobs[0].job_content_hash,
            extractor_type="rule",
            extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
            schema_version=EXTRACTION_SCHEMA_VERSION,
            canonicalization_version=CANONICALIZATION_VERSION,
            output_data=_payload(),
            validation_status="accepted",
        )
    )
    session.commit()
    return profile, jobs


@pytest.mark.postgresql
def test_generation_is_bounded_private_and_replay_idempotent(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    captured: list[str] = []
    with Session(engine) as session:
        profile, jobs = _seed(session, job_count=105)

        def embed_profile(text_value: str) -> tuple[float, ...]:
            assert session.in_transaction() is False
            captured.append(text_value)
            return tuple([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1))

        first = generate_job_matches(
            session,
            profile_id=profile.id,
            owner_hash=profile.owner_hash,
            now=profile.created_at,
            embed_profile=embed_profile,
        )
        second = generate_job_matches(
            session,
            profile_id=profile.id,
            owner_hash=profile.owner_hash,
            now=profile.created_at,
            embed_profile=embed_profile,
        )

        assert first.considered_jobs == 105
        assert first.available_jobs == 105
        assert first.stored_matches == 100
        assert first.created_matches == 100
        assert second.created_matches == 0
        assert second.reused_matches == 100
        assert session.scalar(select(func.count()).select_from(JobMatch)) == 100
        assert {
            (row.scoring_version, row.profile_embedding_input_version)
            for row in session.scalars(select(JobMatch))
        } == {(SCORING_VERSION, PROFILE_EMBEDDING_INPUT_VERSION)}
        assert len(captured) == 2
        assert "private-profile.pdf" not in captured[0]
        assert profile.owner_hash not in captured[0]
        assert profile.content_hash not in captured[0]

        rows = session.scalars(
            select(JobMatch).order_by(JobMatch.overall_score.desc(), JobMatch.job_id.asc())
        ).all()
        assert len(rows) == 100
        assert rows[0].job_id == jobs[0].id
    engine.dispose()


@pytest.mark.postgresql
def test_generation_rejects_model_failure_without_partial_rows(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        profile, _ = _seed(session)

        def fail(_text: str) -> tuple[float, ...]:
            raise EmbeddingModelUnavailable

        with pytest.raises(EmbeddingModelUnavailable):
            generate_job_matches(
                session,
                profile_id=profile.id,
                owner_hash=profile.owner_hash,
                now=profile.created_at,
                embed_profile=fail,
            )
        assert session.scalar(select(func.count()).select_from(JobMatch)) == 0
    engine.dispose()


@pytest.mark.postgresql
def test_generation_only_considers_active_jobs_with_current_compatible_embeddings(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        profile, jobs = _seed(session, job_count=3)
        jobs[1].removed_at = datetime.now(UTC)
        jobs[1].status = JobStatus.REMOVED
        jobs[2].job_content_hash = "e" * 64
        session.commit()

        report = generate_job_matches(
            session,
            profile_id=profile.id,
            owner_hash=profile.owner_hash,
            now=profile.created_at,
            embed_profile=lambda _text: tuple([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)),
        )

        assert report.considered_jobs == 2
        assert report.available_jobs == 1
        assert report.unavailable_jobs == 1
        assert report.stored_matches == 1
        assert session.scalar(select(JobMatch.job_id)) == jobs[0].id
    engine.dispose()


@pytest.mark.postgresql
def test_profile_invalidation_during_inference_stores_no_rows(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        profile, _ = _seed(session)

        def invalidate(_text: str) -> tuple[float, ...]:
            with Session(engine) as other:
                row = other.get(ResumeProfile, profile.id)
                assert row is not None
                row.deleted_at = profile.created_at + timedelta(seconds=1)
                other.commit()
            return tuple([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1))

        with pytest.raises(MatchProfileUnavailable):
            generate_job_matches(
                session,
                profile_id=profile.id,
                owner_hash=profile.owner_hash,
                now=profile.created_at,
                embed_profile=invalidate,
            )
        assert session.scalar(select(func.count()).select_from(JobMatch)) == 0
    engine.dispose()


@pytest.mark.postgresql
def test_profile_expiry_during_inference_stores_no_rows(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        profile, _ = _seed(session)

        class FutureClock:
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> datetime:
                return datetime.now(tz) + timedelta(days=2)

        monkeypatch.setattr("devradar.matching.job_matches.datetime", FutureClock)
        vector = tuple([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1))

        with pytest.raises(MatchProfileUnavailable):
            generate_job_matches(
                session,
                profile_id=profile.id,
                owner_hash=profile.owner_hash,
                now=profile.created_at,
                embed_profile=lambda _text: vector,
            )
        assert session.scalar(select(func.count()).select_from(JobMatch)) == 0
    engine.dispose()


@pytest.mark.postgresql
def test_malformed_extraction_makes_skill_unavailable_and_hash_change_is_stale(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        profile, jobs = _seed(session)
        extraction = session.scalar(
            select(ExtractionResult).where(ExtractionResult.input_ref == jobs[0].id)
        )
        assert extraction is not None
        extraction.output_data = {"invalid": True}
        session.commit()
        vector = tuple([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1))
        generate_job_matches(
            session,
            profile_id=profile.id,
            owner_hash=profile.owner_hash,
            now=profile.created_at,
            embed_profile=lambda _text: vector,
        )
        first = session.scalar(select(JobMatch))
        assert first is not None
        assert first.skill_score is None

        old_hash = jobs[0].job_content_hash
        jobs[0].job_content_hash = "e" * 64
        session.add(
            JobEmbedding(
                job_id=jobs[0].id,
                input_hash=jobs[0].job_content_hash,
                input_schema_version=EMBEDDING_INPUT_SCHEMA_VERSION,
                provider=EMBEDDING_PROVIDER,
                model=EMBEDDING_MODEL_ID,
                model_revision=EMBEDDING_MODEL_REVISION,
                dimension=EMBEDDING_DIMENSION,
                embedding=list(vector),
            )
        )
        session.commit()
        generate_job_matches(
            session,
            profile_id=profile.id,
            owner_hash=profile.owner_hash,
            now=profile.created_at,
            embed_profile=lambda _text: vector,
        )
        assert session.scalar(select(func.count()).select_from(JobMatch)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobMatch)
                .where(JobMatch.job_content_hash == old_hash)
            )
            == 1
        )
    engine.dispose()
