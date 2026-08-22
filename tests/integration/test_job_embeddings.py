from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from devradar.catalog.models import Job, JobStatus
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
    EmbeddingKey,
    backfill_job_embeddings,
    load_job_embedding,
    persist_job_embedding,
)
from devradar.intelligence.models import JobEmbedding
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def embedding_engine(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def seeded_job(embedding_engine: Engine) -> UUID:
    now = datetime.now(UTC)
    with Session(embedding_engine) as session:
        source = Source(
            name="Embedding Test",
            base_url="https://careers.example.test",
            adapter_key="embedding_test",
            approval_status=SourceApprovalStatus.APPROVED,
            rate_limit_policy={"requests_per_second": 1},
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
            items_found=1,
            adapter_version="fixture-v1",
            config_version="fixture-v1",
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
            canonical_url=snapshot.source_url,
            title="Backend Engineer",
            company_name="Example",
            description_text="Python FastAPI PostgreSQL",
            levels=["senior"],
            first_seen_at=now,
            last_seen_at=now,
            status=JobStatus.ACTIVE,
            current_snapshot_id=snapshot.id,
            job_content_hash="a" * 64,
        )
        session.add(job)
        session.commit()
        return job.id


@pytest.mark.postgresql
def test_pgvector_migration_has_fixed_extension_and_dimension(embedding_engine: Engine) -> None:
    inspector = inspect(embedding_engine)
    assert "job_embeddings" in inspector.get_table_names()
    constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("job_embeddings")
    }
    assert {
        "ck_job_embeddings_input_hash",
        "ck_job_embeddings_provider",
        "ck_job_embeddings_model_revision",
        "ck_job_embeddings_dimension",
        "ck_job_embeddings_latency",
    } <= constraints

    with Session(embedding_engine) as session:
        assert (
            session.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
            == "0.8.6"
        )
        assert (
            session.scalar(
                text(
                    "SELECT format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a "
                    "WHERE a.attrelid = 'job_embeddings'::regclass "
                    "AND a.attname = 'embedding'"
                )
            )
            == f"vector({EMBEDDING_DIMENSION})"
        )


@pytest.mark.postgresql
def test_current_embedding_is_idempotent_and_stale_hash_is_not_a_hit(
    embedding_engine: Engine,
    seeded_job: UUID,
) -> None:
    with Session(embedding_engine) as session:
        job = session.get_one(Job, seeded_job)
        key = EmbeddingKey.for_job(job)
        vector = [0.0] * EMBEDDING_DIMENSION
        vector[0] = 1.0

        first, first_hit = persist_job_embedding(
            session,
            key=key,
            vector=vector,
            latency_ms=12,
        )
        session.commit()
        second, second_hit = persist_job_embedding(
            session,
            key=key,
            vector=vector,
            latency_ms=99,
        )

        assert first_hit is False
        assert second_hit is True
        assert second.id == first.id
        assert second.latency_ms == 12
        cached = load_job_embedding(session, key)
        assert cached is not None
        assert cached.id == first.id
        stale = EmbeddingKey(
            job_id=key.job_id,
            input_hash="c" * 64,
            input_schema_version=key.input_schema_version,
            provider=key.provider,
            model=key.model,
            model_revision=key.model_revision,
            dimension=key.dimension,
        )
        assert load_job_embedding(session, stale) is None
        assert session.scalars(select(JobEmbedding)).all() == [first]


@pytest.mark.postgresql
def test_embedding_backfill_is_idempotent_and_runs_model_outside_transaction(
    embedding_engine: Engine,
    seeded_job: UUID,
) -> None:
    del seeded_job
    calls: list[str] = []
    with Session(embedding_engine) as session:

        def embed_passage(text_value: str) -> tuple[float, ...]:
            assert session.in_transaction() is False
            calls.append(text_value)
            vector = [0.0] * EMBEDDING_DIMENSION
            vector[0] = 1.0
            return tuple(vector)

        first = backfill_job_embeddings(session, embed_passage=embed_passage, max_items=1)
        second = backfill_job_embeddings(session, embed_passage=embed_passage, max_items=1)

        assert first.selected == 1
        assert first.created == 1
        assert first.stale_skipped == 0
        assert second.selected == 0
        assert second.created == 0
        assert len(calls) == 1
        assert "Python FastAPI PostgreSQL" in calls[0]
        assert session.scalar(select(JobEmbedding)) is not None
