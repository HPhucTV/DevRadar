from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from devradar.automation.orchestrator import (
    RetryPolicy,
    orchestrate_source,
    scheduled_slot,
    scheduled_trigger_key,
)
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
    CrawlTriggerType,
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
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


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


class SequencedFakeVngAdapter(FakeVngAdapter):
    def __init__(
        self,
        external_ids: tuple[str, ...],
        *,
        fetched_at: datetime,
        discovery_errors: tuple[Exception, ...],
    ) -> None:
        super().__init__(external_ids, fetched_at=fetched_at)
        self._discovery_errors = list(discovery_errors)

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if self._discovery_errors:
            self.discovery_calls += 1
            raise self._discovery_errors.pop(0)
        return super().discover(run_context)


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


@pytest.mark.postgresql
def test_orchestration_retries_transient_and_reuses_duplicate_schedule(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    scheduled_for = scheduled_slot(datetime.now(UTC), 15)
    trigger_key = scheduled_trigger_key(VNG_CAREERS.source_key, scheduled_for)
    sleeps: list[float] = []
    adapter = SequencedFakeVngAdapter(
        ("301",),
        fetched_at=BASE_TIME,
        discovery_errors=(
            FakeAdapterError(
                "network_timeout",
                "first transient failure",
                retry_after_seconds=7,
            ),
            FakeAdapterError("server_error", "second transient failure"),
        ),
    )
    try:
        with Session(engine) as session:
            result = orchestrate_source(
                session,
                config=VNG_CAREERS,
                adapter=adapter,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                trigger_type=CrawlTriggerType.SCHEDULED,
                trigger_key=trigger_key,
                scheduled_for=scheduled_for,
                retry_policy=RetryPolicy(
                    base_delay_seconds=2,
                    max_delay_seconds=10,
                    jitter_ratio=0,
                ),
                sleeper=sleeps.append,
                jitter_source=lambda: 0.5,
            )

            assert result.final_report.status is CrawlRunStatus.SUCCEEDED
            assert [report.attempt_number for report in result.reports] == [1, 2, 3]
            assert [report.trigger_type for report in result.reports] == [
                CrawlTriggerType.SCHEDULED,
                CrawlTriggerType.RETRY,
                CrawlTriggerType.RETRY,
            ]
            assert result.reports[1].retry_of_run_id == result.reports[0].run_id
            assert result.reports[2].retry_of_run_id == result.reports[1].run_id
            assert result.reports[0].retry_after_seconds == 7
            assert sleeps == [7, 4]
            assert adapter.discovery_calls == 3
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 3
            assert session.scalar(select(func.count()).select_from(Job)) == 1
            session.rollback()

            duplicate_adapter = FakeVngAdapter(("302",), fetched_at=BASE_TIME)
            duplicate_sleeps: list[float] = []
            duplicate = orchestrate_source(
                session,
                config=VNG_CAREERS,
                adapter=duplicate_adapter,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                trigger_type=CrawlTriggerType.SCHEDULED,
                trigger_key=trigger_key,
                scheduled_for=scheduled_for,
                retry_policy=RetryPolicy(
                    base_delay_seconds=2,
                    max_delay_seconds=10,
                    jitter_ratio=0,
                ),
                sleeper=duplicate_sleeps.append,
            )

            assert duplicate.final_report.run_id == result.final_report.run_id
            assert all(report.reused for report in duplicate.reports)
            assert duplicate_adapter.discovery_calls == 0
            assert duplicate_sleeps == []
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 3
            assert session.scalar(select(func.count()).select_from(Job)) == 1
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_orchestration_does_not_retry_policy_error_or_overlap_active_run(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        with Session(engine) as session:
            policy_adapter = FakeVngAdapter(
                (),
                fetched_at=BASE_TIME,
                discovery_error=FakeAdapterError("policy_blocked", "policy denied"),
            )
            sleeps: list[float] = []
            policy_result = orchestrate_source(
                session,
                config=VNG_CAREERS,
                adapter=policy_adapter,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                trigger_key="manual:policy-fixture",
                sleeper=sleeps.append,
            )

            assert len(policy_result.reports) == 1
            assert policy_result.final_report.error_code == "policy_blocked"
            assert policy_adapter.discovery_calls == 1
            assert sleeps == []

            source = session.get(Source, policy_result.final_report.source_id)
            assert source is not None
            active = CrawlRun(
                source_id=source.id,
                trigger_type=CrawlTriggerType.MANUAL,
                trigger_key="manual:active-fixture",
                status=CrawlRunStatus.RUNNING,
                started_at=datetime.now(UTC),
                adapter_version="fixture-v1",
                config_version=VNG_CAREERS.config_version,
            )
            session.add(active)
            session.commit()

            blocked_adapter = FakeVngAdapter(("401",), fetched_at=BASE_TIME)
            with pytest.raises(IngestionRunError) as captured:
                orchestrate_source(
                    session,
                    config=VNG_CAREERS,
                    adapter=blocked_adapter,
                    deadline=datetime.now(UTC) + timedelta(minutes=5),
                    trigger_key="manual:overlap-fixture",
                )
            assert captured.value.code == "run_already_active"
            assert blocked_adapter.discovery_calls == 0
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 2
    finally:
        engine.dispose()
