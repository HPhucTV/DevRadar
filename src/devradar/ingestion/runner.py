"""On-demand V1 ingestion use case with short PostgreSQL transactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.catalog.job_upsert import upsert_parsed_job
from devradar.ingestion.adapters.greenhouse import GreenhouseJobBoardAdapter
from devradar.ingestion.adapters.momo import MomoCareersAdapter
from devradar.ingestion.adapters.vng import VngCareersAdapter
from devradar.ingestion.contracts import (
    JobSourceAdapter,
    ParsedJob,
    ParseFailure,
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
    SourceApprovalStatus,
)
from devradar.ingestion.snapshot_persistence import persist_raw_snapshot
from devradar.ingestion.source_registry import (
    V1_SOURCE_REGISTRY,
    AdapterRegistry,
    ResolvedSource,
    SourceConfig,
)
from devradar.platform.observability import record_crawl_run_summary

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class IngestionRunError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: UUID
    source_key: str
    source_id: UUID
    status: CrawlRunStatus
    coverage_status: CoverageStatus
    started_at: datetime
    finished_at: datetime
    pages_found: int
    items_found: int
    items_new: int
    items_updated: int
    items_missing: int
    items_removed: int
    items_failed: int
    error_code: str | None


def resolve_v1_source(source_key: str) -> ResolvedSource:
    adapters = AdapterRegistry(
        (
            GreenhouseJobBoardAdapter(),
            VngCareersAdapter(),
            MomoCareersAdapter(),
        )
    )
    return V1_SOURCE_REGISTRY.resolve(source_key, adapters)


def _review_timestamp(value: date) -> datetime:
    return datetime.combine(value, time.min, UTC)


def _rate_limit_policy(config: SourceConfig) -> dict[str, int | None]:
    policy = config.fetch_policy
    return {
        "concurrency": policy.concurrency,
        "requests_per_minute": policy.requests_per_minute,
        "minimum_action_interval_seconds": policy.minimum_action_interval_seconds,
        "timeout_seconds": policy.timeout_seconds,
        "redirect_limit": policy.redirect_limit,
        "max_response_bytes": policy.max_response_bytes,
    }


def _source_matches_config(source: Source, config: SourceConfig) -> bool:
    return bool(
        source.name == config.name
        and source.base_url == config.base_url
        and source.adapter_key == config.adapter_key
        and source.approval_status is SourceApprovalStatus.APPROVED
        and source.allowed_hosts == list(config.fetch_policy.allowed_hosts)
        and source.rate_limit_policy == _rate_limit_policy(config)
        and source.terms_reviewed_at is not None
        and source.terms_reviewed_at.date() == config.policy_review.terms_reviewed_at
        and source.robots_reviewed_at is not None
        and source.robots_reviewed_at.date() == config.policy_review.robots_reviewed_at
    )


def _ensure_source(session: Session, config: SourceConfig) -> UUID:
    source = session.scalar(select(Source).where(Source.name == config.name))
    if source is None:
        source = Source(
            name=config.name,
            base_url=config.base_url,
            adapter_key=config.adapter_key,
            approval_status=SourceApprovalStatus.APPROVED,
            rate_limit_policy=_rate_limit_policy(config),
            allowed_hosts=list(config.fetch_policy.allowed_hosts),
            terms_reviewed_at=_review_timestamp(config.policy_review.terms_reviewed_at),
            robots_reviewed_at=_review_timestamp(config.policy_review.robots_reviewed_at),
        )
        session.add(source)
        session.flush()
    elif not _source_matches_config(source, config):
        raise IngestionRunError(
            "source_config_mismatch",
            "Persisted source does not match the approved registry configuration.",
        )
    source_id = source.id
    session.commit()
    return source_id


def _create_run(
    session: Session,
    *,
    source_id: UUID,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    started_at: datetime,
) -> UUID:
    crawl_run = CrawlRun(
        source_id=source_id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=CrawlRunStatus.RUNNING,
        coverage_status=CoverageStatus.UNKNOWN,
        started_at=started_at,
        adapter_version=adapter.adapter_version,
        config_version=config.config_version,
    )
    session.add(crawl_run)
    session.flush()
    run_id = crawl_run.id
    session.commit()
    return run_id


def _safe_error_code(error: Exception) -> tuple[str, bool]:
    raw_code = getattr(error, "code", None)
    if isinstance(raw_code, (str, StrEnum)):
        code = str(raw_code)
        if len(code) <= 100 and _ERROR_CODE_PATTERN.fullmatch(code):
            return code, True
    return "unexpected_error", False


def _snapshot_contract(snapshot: RawJobSnapshot, source_key: str) -> RawSnapshot:
    return RawSnapshot(
        snapshot_id=snapshot.id,
        source_key=source_key,
        external_id=cast(str, snapshot.external_id),
        source_url=snapshot.source_url,
        fetched_at=snapshot.fetched_at,
        content_type=cast(str, snapshot.content_type),
        raw_content=snapshot.raw_content,
        raw_content_hash=snapshot.raw_content_hash,
    )


def _record_item_failure(
    session: Session,
    *,
    run_id: UUID,
    error_code: str,
    count: int = 1,
    snapshot_id: UUID | None = None,
    parse_status: ParseStatus = ParseStatus.FAILED,
) -> None:
    crawl_run = session.get(CrawlRun, run_id, with_for_update=True)
    if crawl_run is None:
        raise IngestionRunError("run_not_found", "Crawl run disappeared during ingestion.")
    crawl_run.items_failed += count
    if snapshot_id is not None:
        snapshot = session.get(RawJobSnapshot, snapshot_id, with_for_update=True)
        if snapshot is None:
            raise IngestionRunError(
                "snapshot_not_found",
                "Raw snapshot disappeared during ingestion.",
            )
        snapshot.parse_status = parse_status
        snapshot.error_code = error_code
    session.commit()


def _handle_item_exception(
    session: Session,
    *,
    run_id: UUID,
    error: Exception,
    item_index: int,
    item_count: int,
    snapshot_id: UUID | None = None,
) -> tuple[str, bool]:
    session.rollback()
    error_code, expected = _safe_error_code(error)
    _record_item_failure(
        session,
        run_id=run_id,
        snapshot_id=snapshot_id,
        error_code=error_code,
    )
    should_stop = not expected
    remaining = item_count - item_index - 1
    if should_stop and remaining:
        _record_item_failure(
            session,
            run_id=run_id,
            error_code=error_code,
            count=remaining,
        )
    return error_code, should_stop


def _set_items_found(session: Session, run_id: UUID, items_found: int) -> None:
    crawl_run = session.get(CrawlRun, run_id, with_for_update=True)
    if crawl_run is None:
        raise IngestionRunError("run_not_found", "Crawl run disappeared during ingestion.")
    crawl_run.items_found = items_found
    session.commit()


def _report(run: CrawlRun, source_key: str) -> RunReport:
    if run.started_at is None or run.finished_at is None:
        raise IngestionRunError("run_not_final", "Crawl run was not finalized.")
    return RunReport(
        run_id=run.id,
        source_key=source_key,
        source_id=run.source_id,
        status=run.status,
        coverage_status=run.coverage_status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        pages_found=run.pages_found,
        items_found=run.items_found,
        items_new=run.items_new,
        items_updated=run.items_updated,
        items_missing=run.items_missing,
        items_removed=run.items_removed,
        items_failed=run.items_failed,
        error_code=run.error_code,
    )


def _finalize_run(
    session: Session,
    *,
    run_id: UUID,
    source_key: str,
    processed_items: int,
    coverage_complete: bool,
    error_code: str | None,
    status_override: CrawlRunStatus | None = None,
) -> RunReport:
    finished_at = datetime.now(UTC)
    crawl_run = session.get(CrawlRun, run_id, with_for_update=True)
    if crawl_run is None:
        raise IngestionRunError("run_not_found", "Crawl run disappeared during finalization.")
    source = session.get(Source, crawl_run.source_id, with_for_update=True)
    if source is None:
        raise IngestionRunError("source_not_found", "Source disappeared during finalization.")
    if status_override is not None:
        status = status_override
    elif error_code is None:
        status = CrawlRunStatus.SUCCEEDED
    elif processed_items:
        status = CrawlRunStatus.PARTIAL
    else:
        status = CrawlRunStatus.FAILED
    coverage_status = (
        CoverageStatus.COMPLETE
        if status is CrawlRunStatus.SUCCEEDED and coverage_complete and crawl_run.items_found > 0
        else CoverageStatus.INCOMPLETE
    )
    crawl_run.status = status
    crawl_run.coverage_status = coverage_status
    crawl_run.finished_at = finished_at
    crawl_run.error_code = error_code
    crawl_run.error_summary = (
        None if error_code is None else "Crawl run completed with one or more safe failures."
    )
    source.last_crawled_at = finished_at
    if status is CrawlRunStatus.SUCCEEDED and coverage_status is CoverageStatus.COMPLETE:
        source.last_success_at = finished_at
    session.flush()
    report = _report(crawl_run, source_key)
    session.commit()
    record_crawl_run_summary(
        run_id=report.run_id,
        source_id=report.source_id,
        status=report.status.value,
        coverage_status=report.coverage_status.value,
        duration_ms=(report.finished_at - report.started_at).total_seconds() * 1000,
        pages_found=report.pages_found,
        items_found=report.items_found,
        items_new=report.items_new,
        items_updated=report.items_updated,
        items_missing=report.items_missing,
        items_removed=report.items_removed,
        items_failed=report.items_failed,
        error_code=report.error_code,
    )
    return report


def run_approved_source(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    deadline: datetime,
    max_items: int | None = None,
) -> RunReport:
    """Own a manual run lifecycle; network work happens outside DB transactions."""

    if session.in_transaction():
        raise IngestionRunError(
            "transaction_already_active",
            "Ingestion runner requires a fresh session transaction boundary.",
        )
    if config.approval_status is not SourceApprovalStatus.APPROVED:
        raise IngestionRunError("source_not_approved", "Ingestion requires an approved source.")
    if adapter.adapter_key != config.adapter_key or not adapter.adapter_version.strip():
        raise IngestionRunError(
            "adapter_config_mismatch",
            "Ingestion adapter does not match the approved source configuration.",
        )
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= datetime.now(UTC):
        raise IngestionRunError("invalid_deadline", "Ingestion deadline must be in the future.")
    if max_items is not None and max_items <= 0:
        raise IngestionRunError("invalid_max_items", "max_items must be positive.")

    try:
        source_id = _ensure_source(session, config)
    except Exception:
        session.rollback()
        raise
    started_at = datetime.now(UTC)
    run_id = _create_run(
        session,
        source_id=source_id,
        config=config,
        adapter=adapter,
        started_at=started_at,
    )
    context = RunContext(
        run_id=run_id,
        source=config,
        deadline=deadline,
        correlation_id=uuid4().hex,
    )
    try:
        listings = tuple(adapter.discover(context))
    except KeyboardInterrupt:
        session.rollback()
        _finalize_run(
            session,
            run_id=run_id,
            source_key=config.source_key,
            processed_items=0,
            coverage_complete=False,
            error_code="operator_cancelled",
            status_override=CrawlRunStatus.CANCELLED,
        )
        raise
    except Exception as error:
        session.rollback()
        error_code, _ = _safe_error_code(error)
        return _finalize_run(
            session,
            run_id=run_id,
            source_key=config.source_key,
            processed_items=0,
            coverage_complete=False,
            error_code=error_code,
        )

    _set_items_found(session, run_id, len(listings))
    if not listings:
        return _finalize_run(
            session,
            run_id=run_id,
            source_key=config.source_key,
            processed_items=0,
            coverage_complete=False,
            error_code="empty_discovery",
        )

    selected = listings if max_items is None else listings[:max_items]
    coverage_complete = len(selected) == len(listings)
    processed_items = 0
    first_error_code: str | None = None

    for index, listing in enumerate(selected):
        if datetime.now(UTC) >= deadline:
            remaining = len(selected) - index
            _record_item_failure(
                session,
                run_id=run_id,
                error_code="run_deadline_exceeded",
                count=remaining,
            )
            first_error_code = first_error_code or "run_deadline_exceeded"
            coverage_complete = False
            break

        try:
            fetch_result = adapter.fetch(listing, config.fetch_policy)
        except KeyboardInterrupt:
            session.rollback()
            _finalize_run(
                session,
                run_id=run_id,
                source_key=config.source_key,
                processed_items=processed_items,
                coverage_complete=False,
                error_code="operator_cancelled",
                status_override=CrawlRunStatus.CANCELLED,
            )
            raise
        except Exception as error:
            error_code, should_stop = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
            )
            first_error_code = first_error_code or error_code
            coverage_complete = False
            if should_stop:
                break
            continue

        try:
            crawl_run = session.get(CrawlRun, run_id, with_for_update=True)
            if crawl_run is None:
                raise IngestionRunError(
                    "run_not_found",
                    "Crawl run disappeared before snapshot persistence.",
                )
            snapshot = persist_raw_snapshot(
                session,
                crawl_run=crawl_run,
                source_config=config,
                listing_ref=listing,
                fetch_result=fetch_result,
            )
            raw_snapshot = _snapshot_contract(snapshot, config.source_key)
            snapshot_id = snapshot.id
            session.commit()
        except Exception as error:
            error_code, should_stop = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
            )
            first_error_code = first_error_code or error_code
            coverage_complete = False
            if should_stop:
                break
            continue

        try:
            parsed = adapter.parse(raw_snapshot)
        except Exception as error:
            error_code, should_stop = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
                snapshot_id=snapshot_id,
            )
            first_error_code = first_error_code or error_code
            coverage_complete = False
            if should_stop:
                break
            continue

        if isinstance(parsed, ParseFailure):
            _record_item_failure(
                session,
                run_id=run_id,
                snapshot_id=snapshot_id,
                error_code=parsed.error_code,
                parse_status=ParseStatus.INVALID,
            )
            first_error_code = first_error_code or parsed.error_code
            coverage_complete = False
            continue
        if not isinstance(parsed, ParsedJob):
            error_code, _ = _handle_item_exception(
                session,
                run_id=run_id,
                error=TypeError("adapter parse contract returned an unsupported result"),
                item_index=index,
                item_count=len(selected),
                snapshot_id=snapshot_id,
            )
            first_error_code = first_error_code or error_code
            coverage_complete = False
            break

        try:
            crawl_run = session.get(CrawlRun, run_id, with_for_update=True)
            database_snapshot = session.get(RawJobSnapshot, snapshot_id, with_for_update=True)
            if crawl_run is None or database_snapshot is None:
                raise IngestionRunError(
                    "observation_not_found",
                    "Crawl run or snapshot disappeared before Job upsert.",
                )
            upsert_parsed_job(
                session,
                crawl_run=crawl_run,
                snapshot=database_snapshot,
                parsed_job=parsed,
                source_config=config,
            )
            session.commit()
            processed_items += 1
        except Exception as error:
            error_code, should_stop = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
                snapshot_id=snapshot_id,
            )
            first_error_code = first_error_code or error_code
            coverage_complete = False
            if should_stop:
                break

    return _finalize_run(
        session,
        run_id=run_id,
        source_key=config.source_key,
        processed_items=processed_items,
        coverage_complete=coverage_complete,
        error_code=first_error_code,
    )
