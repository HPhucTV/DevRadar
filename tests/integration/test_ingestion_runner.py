from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from devradar.catalog.models import Job
from devradar.ingestion.contracts import (
    FetchResult,
    FieldEvidence,
    JobSourceAdapter,
    ListingRef,
    NormalizedJobCandidates,
    ParsedJob,
    ParseFailure,
    RawJobFields,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    ParseStatus,
    RawJobSnapshot,
    Source,
)
from devradar.ingestion.runner import IngestionRunError, run_approved_source
from devradar.ingestion.source_registry import VNG_CAREERS, FetchPolicy
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_TIME = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


class FakeAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FakeVngAdapter(JobSourceAdapter):
    adapter_key = VNG_CAREERS.adapter_key
    adapter_version = "fake-vng-v1"

    def __init__(
        self,
        external_ids: tuple[str, ...],
        *,
        fetched_at: datetime,
        invalid_ids: tuple[str, ...] = (),
        discovery_error: Exception | None = None,
    ) -> None:
        self._external_ids = external_ids
        self._fetched_at = fetched_at
        self._invalid_ids = frozenset(invalid_ids)
        self._discovery_error = discovery_error
        self.discovery_calls = 0

    @staticmethod
    def _url(external_id: str) -> str:
        return f"https://career.vng.com.vn/tim-kiem-viec-lam/chi-tiet/{external_id}-fixture-role"

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        del run_context
        self.discovery_calls += 1
        if self._discovery_error is not None:
            raise self._discovery_error
        return tuple(
            ListingRef(external_id=external_id, canonical_url=self._url(external_id))
            for external_id in self._external_ids
        )

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        assert fetch_policy == VNG_CAREERS.fetch_policy
        payload = f"fixture:{listing_ref.external_id}".encode()
        return FetchResult(
            final_url=listing_ref.canonical_url,
            fetched_at=self._fetched_at,
            http_status=200,
            content_type="text/html; charset=utf-8",
            payload=payload,
            raw_content_hash=sha256(payload).hexdigest(),
        )

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        if snapshot.external_id in self._invalid_ids:
            return ParseFailure(
                error_code="fixture_parse_failed",
                stage="parse",
                safe_summary="Fixture parse failed safely.",
            )
        title = f"Backend Engineer {snapshot.external_id}"
        return ParsedJob(
            raw=RawJobFields(
                external_id=snapshot.external_id,
                canonical_url=self._url(snapshot.external_id),
                title=title,
                company_name="VNG",
                description="Build reliable services.",
                location="Ho Chi Minh City",
            ),
            normalized_candidates=NormalizedJobCandidates(
                title=title,
                company_name="VNG",
                description_text="Build reliable services.",
                location_city="Ho Chi Minh City",
            ),
            evidence=(FieldEvidence(field_name="title", source_path="fixture.title"),),
            parser_version=self.adapter_version,
        )


@pytest.mark.postgresql
def test_runner_preserves_evidence_handles_partial_and_replay_without_false_removal(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        with Session(engine) as session:
            partial = run_approved_source(
                session,
                config=VNG_CAREERS,
                adapter=FakeVngAdapter(
                    ("101", "102"),
                    fetched_at=BASE_TIME,
                    invalid_ids=("102",),
                ),
                deadline=datetime.now(UTC) + timedelta(minutes=5),
            )
            assert partial.status is CrawlRunStatus.PARTIAL
            assert partial.coverage_status is CoverageStatus.INCOMPLETE
            assert partial.items_found == 2
            assert partial.items_new == 1
            assert partial.items_updated == 0
            assert partial.items_failed == 1
            assert partial.items_missing == partial.items_removed == 0
            assert partial.error_code == "fixture_parse_failed"
            assert session.scalar(select(func.count()).select_from(Job)) == 1
            invalid_snapshot = session.scalar(
                select(RawJobSnapshot).where(RawJobSnapshot.external_id == "102")
            )
            assert invalid_snapshot is not None
            assert invalid_snapshot.parse_status is ParseStatus.INVALID
            assert invalid_snapshot.error_code == "fixture_parse_failed"
            source = session.scalar(select(Source))
            assert source is not None
            assert source.last_crawled_at is not None
            assert source.last_success_at is None
            session.rollback()

            replay = run_approved_source(
                session,
                config=VNG_CAREERS,
                adapter=FakeVngAdapter(("101",), fetched_at=BASE_TIME + timedelta(minutes=1)),
                deadline=datetime.now(UTC) + timedelta(minutes=5),
            )
            assert replay.status is CrawlRunStatus.SUCCEEDED
            assert replay.coverage_status is CoverageStatus.COMPLETE
            assert replay.items_found == 1
            assert replay.items_new == replay.items_updated == replay.items_failed == 0
            assert session.scalar(select(func.count()).select_from(Job)) == 1
            job = session.scalar(select(Job))
            assert job is not None
            assert job.last_seen_at == BASE_TIME + timedelta(minutes=1)
            source = session.scalar(select(Source))
            assert source is not None
            assert source.last_success_at is not None
            session.rollback()

            failed = run_approved_source(
                session,
                config=VNG_CAREERS,
                adapter=FakeVngAdapter(
                    (),
                    fetched_at=BASE_TIME,
                    discovery_error=FakeAdapterError(
                        "discovery_failed",
                        "secret detail must never be persisted",
                    ),
                ),
                deadline=datetime.now(UTC) + timedelta(minutes=5),
            )
            assert failed.status is CrawlRunStatus.FAILED
            assert failed.coverage_status is CoverageStatus.INCOMPLETE
            assert failed.error_code == "discovery_failed"
            failed_run = session.get(CrawlRun, failed.run_id)
            assert failed_run is not None
            assert failed_run.error_summary == (
                "Crawl run completed with one or more safe failures."
            )
            assert "secret detail" not in failed_run.error_summary
            assert session.scalar(select(func.count()).select_from(Job)) == 1
            session.rollback()

            bounded = run_approved_source(
                session,
                config=VNG_CAREERS,
                adapter=FakeVngAdapter(
                    ("101", "103"),
                    fetched_at=BASE_TIME + timedelta(minutes=2),
                ),
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                max_items=1,
            )
            assert bounded.status is CrawlRunStatus.SUCCEEDED
            assert bounded.coverage_status is CoverageStatus.INCOMPLETE
            assert bounded.items_found == 2
            assert bounded.items_failed == 0
            assert session.scalar(select(func.count()).select_from(Job)) == 1
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 4
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_runner_blocks_persisted_source_config_drift_before_discovery(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        with Session(engine) as session:
            run_approved_source(
                session,
                config=VNG_CAREERS,
                adapter=FakeVngAdapter(("201",), fetched_at=BASE_TIME),
                deadline=datetime.now(UTC) + timedelta(minutes=5),
            )
            source = session.scalar(select(Source))
            assert source is not None
            source.rate_limit_policy = {"concurrency": 99}
            session.commit()

            blocked_adapter = FakeVngAdapter(("202",), fetched_at=BASE_TIME)
            with pytest.raises(IngestionRunError, match="approved registry") as captured:
                run_approved_source(
                    session,
                    config=VNG_CAREERS,
                    adapter=blocked_adapter,
                    deadline=datetime.now(UTC) + timedelta(minutes=5),
                )
            assert captured.value.code == "source_config_mismatch"
            assert blocked_adapter.discovery_calls == 0
    finally:
        engine.dispose()
