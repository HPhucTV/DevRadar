from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import devradar.intelligence.extraction as extraction_module
from devradar.catalog.models import Job
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
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    ExtractionCacheKey,
    ProviderMetadata,
    ProviderRequest,
    extract_job,
    load_accepted_cache,
    persist_extraction_result,
)
from devradar.intelligence.models import (
    ExtractionInputType,
    ExtractionResult,
    ExtractionType,
    ExtractionValidationStatus,
)
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.fixture
def extraction_engine(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Engine]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def extraction_session(extraction_engine: Engine) -> Iterator[Session]:
    with Session(extraction_engine) as session:
        yield session


@pytest.fixture
def seeded_job(extraction_engine: Engine) -> UUID:
    now = datetime.now(UTC)
    with Session(extraction_engine) as session:
        source = Source(
            name="Extraction Test Source",
            base_url="https://careers.example.test/jobs",
            adapter_key="extraction_test",
            approval_status=SourceApprovalStatus.APPROVED,
            rate_limit_policy={"requests_per_second": 1, "concurrency": 1},
            allowed_hosts=["careers.example.test"],
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
            external_id="1",
            fetched_at=now,
            http_status=200,
            content_type="text/html",
            raw_content_hash="b" * 64,
            raw_content="fixture",
            parse_status=ParseStatus.PARSED,
        )
        session.add(snapshot)
        session.flush()
        job = Job(
            source_id=source.id,
            external_id="1",
            canonical_url="https://careers.example.test/jobs/1",
            title="Backend Engineer",
            company_name="Example",
            description_text="Join the team.",
            levels=["senior"],
            first_seen_at=now,
            last_seen_at=now,
            current_snapshot_id=snapshot.id,
            job_content_hash="a" * 64,
        )
        session.add(job)
        session.commit()
        return job.id


def _cache_key(job: Job) -> ExtractionCacheKey:
    return ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=job.id,
        input_hash=job.job_content_hash,
        extractor_type=ExtractionType.LLM,
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="test-prompt-v1",
        model="test-model",
        canonicalization_version=CANONICALIZATION_VERSION,
    )


def _payload() -> dict[str, object]:
    return {
        "levels": ["senior"],
        "experience": {"minimumYears": 3, "maximumYears": None},
        "salary": {
            "minimum": 30000000,
            "maximum": 40000000,
            "currency": "VND",
            "period": "month",
        },
        "location": {
            "city": "Ho Chi Minh City",
            "province": "Ho Chi Minh City",
            "workMode": "hybrid",
        },
        "skills": [],
    }


@pytest.mark.postgresql
def test_extraction_result_table_and_constraints_on_fresh_postgresql(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    alembic_config = _alembic_config()

    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)

    engine = create_engine(fresh_postgresql_url)
    try:
        inspector = inspect(engine)
        assert "extraction_results" in inspector.get_table_names()
        check_names = {
            check["name"] for check in inspector.get_check_constraints("extraction_results")
        }
        assert {
            "ck_extraction_results_input_hash",
            "ck_extraction_results_status",
            "ck_extraction_results_confidence",
            "ck_extraction_results_non_negative_metrics",
        } <= check_names
        indexes = {index["name"] for index in inspector.get_indexes("extraction_results")}
        assert "uq_extraction_results_accepted_cache" in indexes
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_rejected_and_needs_review_are_audit_rows_but_never_cache_hits(
    extraction_session: Session, seeded_job: UUID
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None
    key = _cache_key(job)

    first, _ = persist_extraction_result(
        extraction_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.REJECTED,
        validation_errors=[{"code": "bad", "path": "skills", "type": "invalid"}],
    )
    second, _ = persist_extraction_result(
        extraction_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.NEEDS_REVIEW,
        validation_errors=[{"code": "timeout", "path": "provider", "type": "transient"}],
    )
    extraction_session.commit()

    assert first.id != second.id
    assert load_accepted_cache(extraction_session, key) is None
    assert extraction_session.scalar(select(Job).where(Job.id == seeded_job)) is not None


@pytest.mark.postgresql
def test_accepted_cache_read_after_write_returns_same_result(
    extraction_session: Session, seeded_job: UUID
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None
    key = _cache_key(job)

    first, first_hit = persist_extraction_result(
        extraction_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    extraction_session.commit()
    second, second_hit = persist_extraction_result(
        extraction_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )

    assert first_hit is False
    assert second_hit is True
    assert second.id == first.id


@pytest.mark.postgresql
def test_complete_deterministic_job_never_calls_provider(
    extraction_session: Session, seeded_job: UUID
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None
    job.description_text = "Build APIs with Python and PostgreSQL; Docker is a plus."
    extraction_session.commit()
    calls = 0

    def provider(_request: ProviderRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _payload()

    outcome = extract_job(
        extraction_session,
        job=job,
        provider=provider,
        provider_metadata=ProviderMetadata(
            extractor_version="provider-boundary-v1",
            schema_version=EXTRACTION_SCHEMA_VERSION,
            prompt_version="test-prompt-v1",
            model="test-model",
            canonicalization_version=CANONICALIZATION_VERSION,
        ),
    )

    assert outcome.result.extractor_type == ExtractionType.RULE.value
    assert outcome.result.validation_status == ExtractionValidationStatus.ACCEPTED.value
    assert calls == 0


@pytest.mark.postgresql
def test_incomplete_extraction_without_provider_persists_needs_review(
    extraction_session: Session, seeded_job: UUID
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None

    outcome = extract_job(
        extraction_session,
        job=job,
        provider=None,
        provider_metadata=None,
    )

    assert outcome.result.extractor_type == ExtractionType.LLM.value
    assert outcome.result.validation_status == ExtractionValidationStatus.NEEDS_REVIEW.value
    assert outcome.result.validation_errors == [
        {"code": "provider_not_configured", "path": "provider", "type": "missing"}
    ]


@pytest.mark.postgresql
def test_accepted_cache_hit_never_calls_provider(
    extraction_session: Session, seeded_job: UUID
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None
    extraction_session.commit()
    metadata = ProviderMetadata(
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="test-prompt-v1",
        model="test-model",
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    key = _cache_key(job)
    seed, _ = persist_extraction_result(
        extraction_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    extraction_session.commit()
    calls = 0

    def provider(_request: ProviderRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _payload()

    outcome = extract_job(
        extraction_session,
        job=job,
        provider=provider,
        provider_metadata=metadata,
    )

    assert outcome.result.id == seed.id
    assert outcome.cache_hit is True
    assert calls == 0


@pytest.mark.postgresql
def test_failed_transaction_leaves_no_half_result(
    extraction_session: Session, seeded_job: UUID
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None
    persist_extraction_result(
        extraction_session,
        key=_cache_key(job),
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    extraction_session.rollback()

    assert extraction_session.scalar(select(ExtractionResult)) is None


@pytest.mark.postgresql
def test_duplicate_accepted_insert_re_reads_winner(
    extraction_engine: Engine,
    extraction_session: Session,
    seeded_job: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = extraction_session.get(Job, seeded_job)
    assert job is not None
    key = _cache_key(job)
    winner, _ = persist_extraction_result(
        extraction_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    extraction_session.commit()

    real_lookup = extraction_module.load_accepted_cache
    lookup_calls = 0

    def simulated_race(session: Session, cache_key: ExtractionCacheKey) -> ExtractionResult | None:
        nonlocal lookup_calls
        lookup_calls += 1
        if lookup_calls == 1:
            return None
        return real_lookup(session, cache_key)

    monkeypatch.setattr(extraction_module, "load_accepted_cache", simulated_race)
    with Session(extraction_engine) as second_session:
        second, cache_hit = persist_extraction_result(
            second_session,
            key=key,
            output_data=_payload(),
            status=ExtractionValidationStatus.ACCEPTED,
            validation_errors=None,
        )

    assert second.id == winner.id
    assert cache_hit is True
    assert lookup_calls == 2
