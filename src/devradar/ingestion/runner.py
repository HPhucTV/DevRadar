"""Claimed ingestion run use case with short PostgreSQL transactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.automation.health import evaluate_source_health, source_allows_trigger
from devradar.catalog.job_changes import apply_absence_lifecycle
from devradar.catalog.job_upsert import upsert_parsed_job
from devradar.ingestion.adapters.greenhouse import GreenhouseJobBoardAdapter
from devradar.ingestion.adapters.momo import MomoCareersAdapter
from devradar.ingestion.adapters.remotejobs import RemoteJobsApiAdapter
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
    V3_SOURCE_REGISTRY,
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
    requested_at: datetime
    trigger_type: CrawlTriggerType
    trigger_key: str | None
    scheduled_for: datetime | None
    retry_of_run_id: UUID | None
    attempt_number: int
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
    items_reactivated: int
    items_failed: int
    error_code: str | None
    retry_after_seconds: int | None
    health_signal_code: str | None
    reused: bool


def resolve_v1_source(source_key: str) -> ResolvedSource:
    adapters = AdapterRegistry(
        (
            GreenhouseJobBoardAdapter(),
            VngCareersAdapter(),
            MomoCareersAdapter(),
        )
    )
    return V1_SOURCE_REGISTRY.resolve(source_key, adapters)


def resolve_approved_source(source_key: str) -> ResolvedSource:
    adapters = AdapterRegistry(
        (
            GreenhouseJobBoardAdapter(),
            VngCareersAdapter(),
            MomoCareersAdapter(),
            RemoteJobsApiAdapter(),
        )
    )
    return V3_SOURCE_REGISTRY.resolve(source_key, adapters)


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


def source_matches_config(source: Source, config: SourceConfig) -> bool:
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


def custom_source_matches_config(source: Source, config: SourceConfig) -> bool:
    """Validate a persisted owner-local source without treating it as globally approved."""

    return bool(
        source.name == config.name
        and source.base_url == config.base_url
        and source.adapter_key == config.adapter_key
        and source.approval_status is SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
        and source.allowed_hosts == list(config.fetch_policy.allowed_hosts)
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
    elif not source_matches_config(source, config):
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
    trigger_type: CrawlTriggerType,
    trigger_key: str | None,
    scheduled_for: datetime | None,
    retry_of_run_id: UUID | None,
    attempt_number: int,
) -> tuple[UUID, bool]:
    crawl_run = CrawlRun(
        source_id=source_id,
        trigger_type=trigger_type,
        trigger_key=trigger_key,
        scheduled_for=scheduled_for,
        retry_of_run_id=retry_of_run_id,
        attempt_number=attempt_number,
        status=CrawlRunStatus.RUNNING,
        coverage_status=CoverageStatus.UNKNOWN,
        started_at=started_at,
        adapter_version=adapter.adapter_version,
        config_version=config.config_version,
    )
    session.add(crawl_run)
    try:
        session.flush()
        run_id = crawl_run.id
        session.commit()
    except IntegrityError:
        session.rollback()
        existing: CrawlRun | None = None
        if trigger_key is not None:
            existing = session.scalar(
                select(CrawlRun).where(
                    CrawlRun.source_id == source_id,
                    CrawlRun.trigger_key == trigger_key,
                )
            )
        if existing is None and retry_of_run_id is not None:
            existing = session.scalar(
                select(CrawlRun).where(CrawlRun.retry_of_run_id == retry_of_run_id)
            )
        if existing is not None:
            existing_id = existing.id
            session.rollback()
            return existing_id, False
        active = session.scalar(
            select(CrawlRun).where(
                CrawlRun.source_id == source_id,
                CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
            )
        )
        if active is not None:
            session.rollback()
            raise IngestionRunError(
                "run_already_active",
                "An ingestion run is already active for this source.",
            ) from None
        raise
    return run_id, True


def _safe_error_code(error: Exception) -> tuple[str, bool]:
    raw_code = getattr(error, "code", None)
    if isinstance(raw_code, (str, StrEnum)):
        code = str(raw_code)
        if len(code) <= 100 and _ERROR_CODE_PATTERN.fullmatch(code):
            return code, True
    return "unexpected_error", False


def _retry_after_seconds(error: Exception) -> int | None:
    value = getattr(error, "retry_after_seconds", None)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return min(max(value, 0), 3600)


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
) -> tuple[str, bool, int | None]:
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
    return error_code, should_stop, _retry_after_seconds(error)


def _set_items_found(session: Session, run_id: UUID, items_found: int) -> None:
    crawl_run = session.get(CrawlRun, run_id, with_for_update=True)
    if crawl_run is None:
        raise IngestionRunError("run_not_found", "Crawl run disappeared during ingestion.")
    crawl_run.items_found = items_found
    session.commit()


def _report(run: CrawlRun, source_key: str, *, reused: bool = False) -> RunReport:
    if run.started_at is None or run.finished_at is None:
        raise IngestionRunError("run_not_final", "Crawl run was not finalized.")
    return RunReport(
        run_id=run.id,
        source_key=source_key,
        source_id=run.source_id,
        requested_at=run.requested_at,
        trigger_type=run.trigger_type,
        trigger_key=run.trigger_key,
        scheduled_for=run.scheduled_for,
        retry_of_run_id=run.retry_of_run_id,
        attempt_number=run.attempt_number,
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
        items_reactivated=run.items_reactivated,
        items_failed=run.items_failed,
        error_code=run.error_code,
        retry_after_seconds=run.retry_after_seconds,
        health_signal_code=run.health_signal_code,
        reused=reused,
    )


def _finalize_run(
    session: Session,
    *,
    run_id: UUID,
    source_key: str,
    processed_items: int,
    coverage_complete: bool,
    error_code: str | None,
    retry_after_seconds: int | None = None,
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
    crawl_run.retry_after_seconds = retry_after_seconds
    crawl_run.error_summary = (
        None if error_code is None else "Crawl run completed with one or more safe failures."
    )
    evaluate_source_health(
        session,
        source=source,
        crawl_run=crawl_run,
        finished_at=finished_at,
    )
    apply_absence_lifecycle(session, crawl_run=crawl_run, detected_at=finished_at)
    source.last_crawled_at = finished_at
    if (
        crawl_run.status is CrawlRunStatus.SUCCEEDED
        and crawl_run.coverage_status is CoverageStatus.COMPLETE
    ):
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
        items_reactivated=report.items_reactivated,
        items_failed=report.items_failed,
        error_code=report.error_code,
        health_signal_code=report.health_signal_code,
    )
    return report


def run_approved_source(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    deadline: datetime,
    max_items: int | None = None,
    trigger_type: CrawlTriggerType = CrawlTriggerType.MANUAL,
    trigger_key: str | None = None,
    scheduled_for: datetime | None = None,
    retry_of_run_id: UUID | None = None,
    attempt_number: int = 1,
    claimed_run_id: UUID | None = None,
) -> RunReport:
    return _run_source(
        session,
        config=config,
        adapter=adapter,
        deadline=deadline,
        max_items=max_items,
        trigger_type=trigger_type,
        trigger_key=trigger_key,
        scheduled_for=scheduled_for,
        retry_of_run_id=retry_of_run_id,
        attempt_number=attempt_number,
        claimed_run_id=claimed_run_id,
        expected_status=SourceApprovalStatus.APPROVED,
    )


def run_custom_source(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    persisted_source_id: UUID,
    deadline: datetime,
    max_items: int | None = None,
    trigger_type: CrawlTriggerType = CrawlTriggerType.MANUAL,
    trigger_key: str | None = None,
    scheduled_for: datetime | None = None,
    retry_of_run_id: UUID | None = None,
    attempt_number: int = 1,
    claimed_run_id: UUID | None = None,
) -> RunReport:
    return _run_source(
        session,
        config=config,
        adapter=adapter,
        deadline=deadline,
        max_items=max_items,
        trigger_type=trigger_type,
        trigger_key=trigger_key,
        scheduled_for=scheduled_for,
        retry_of_run_id=retry_of_run_id,
        attempt_number=attempt_number,
        claimed_run_id=claimed_run_id,
        expected_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        persisted_source_id=persisted_source_id,
    )


def _run_source(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    deadline: datetime,
    max_items: int | None = None,
    trigger_type: CrawlTriggerType = CrawlTriggerType.MANUAL,
    trigger_key: str | None = None,
    scheduled_for: datetime | None = None,
    retry_of_run_id: UUID | None = None,
    attempt_number: int = 1,
    claimed_run_id: UUID | None = None,
    expected_status: SourceApprovalStatus,
    persisted_source_id: UUID | None = None,
) -> RunReport:
    """Own one claimed run lifecycle; network work happens outside DB transactions."""

    if session.in_transaction():
        raise IngestionRunError(
            "transaction_already_active",
            "Ingestion runner requires a fresh session transaction boundary.",
        )
    if config.approval_status is not expected_status:
        raise IngestionRunError("source_not_approved", "Ingestion source status is not permitted.")
    if adapter.adapter_key != config.adapter_key or not adapter.adapter_version.strip():
        raise IngestionRunError(
            "adapter_config_mismatch",
            "Ingestion adapter does not match the approved source configuration.",
        )
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= datetime.now(UTC):
        raise IngestionRunError("invalid_deadline", "Ingestion deadline must be in the future.")
    if max_items is not None and max_items <= 0:
        raise IngestionRunError("invalid_max_items", "max_items must be positive.")
    if trigger_key is not None and (not trigger_key.strip() or len(trigger_key) > 200):
        raise IngestionRunError(
            "invalid_trigger_key",
            "Trigger key must contain 1..200 non-blank characters.",
        )
    if claimed_run_id is not None and (
        trigger_type is not CrawlTriggerType.MANUAL
        or trigger_key is not None
        or scheduled_for is not None
        or retry_of_run_id is not None
        or attempt_number != 1
    ):
        raise IngestionRunError(
            "invalid_claimed_run",
            "A claimed run uses its persisted trigger identity.",
        )
    scheduled_time_is_aware = bool(
        scheduled_for is not None
        and scheduled_for.tzinfo is not None
        and scheduled_for.utcoffset() is not None
    )
    if claimed_run_id is None:
        if trigger_type is CrawlTriggerType.SCHEDULED:
            if not scheduled_time_is_aware or trigger_key is None:
                raise IngestionRunError(
                    "invalid_scheduled_trigger",
                    "Scheduled runs require an aware scheduled time and trigger key.",
                )
        elif scheduled_for is not None:
            raise IngestionRunError(
                "invalid_scheduled_trigger",
                "Only scheduled runs may carry a scheduled time.",
            )
        if trigger_type is CrawlTriggerType.RETRY:
            if retry_of_run_id is None or attempt_number < 2 or trigger_key is None:
                raise IngestionRunError(
                    "invalid_retry_trigger",
                    "Retry runs require a previous run, attempt number, and trigger key.",
                )
        elif retry_of_run_id is not None or attempt_number != 1:
            raise IngestionRunError(
                "invalid_retry_trigger",
                "Only retry runs may carry retry relation or attempt number greater than one.",
            )

    if expected_status is SourceApprovalStatus.APPROVED:
        try:
            source_id = _ensure_source(session, config)
        except Exception:
            session.rollback()
            raise
    else:
        if persisted_source_id is None:
            raise IngestionRunError(
                "source_id_required",
                "Owner-local ingestion requires its persisted source identity.",
            )
        source_id = persisted_source_id
        persisted_source = session.get(Source, source_id)
        if persisted_source is None or not custom_source_matches_config(persisted_source, config):
            session.rollback()
            raise IngestionRunError(
                "source_config_mismatch",
                "Persisted owner-local source does not match its profile configuration.",
            )
        session.commit()
    source = session.get(Source, source_id)
    if source is None:
        session.rollback()
        raise IngestionRunError("source_not_found", "Persisted source could not be loaded.")
    effective_trigger_type = trigger_type
    if claimed_run_id is not None:
        claimed_run = session.get(CrawlRun, claimed_run_id, with_for_update=True)
        if (
            claimed_run is None
            or claimed_run.source_id != source_id
            or claimed_run.status is not CrawlRunStatus.RUNNING
            or claimed_run.started_at is None
            or claimed_run.finished_at is not None
            or claimed_run.adapter_version != adapter.adapter_version
            or claimed_run.config_version != config.config_version
        ):
            session.rollback()
            raise IngestionRunError(
                "claimed_run_not_available",
                "Claimed crawl run is not available for execution.",
            )
        effective_trigger_type = claimed_run.trigger_type
    if not source_allows_trigger(source, effective_trigger_type):
        session.rollback()
        raise IngestionRunError(
            "source_quarantined",
            "Scheduled and retry triggers are disabled while source is quarantined.",
        )
    session.rollback()
    if claimed_run_id is not None:
        run_id = claimed_run_id
        created = True
    else:
        started_at = datetime.now(UTC)
        run_id, created = _create_run(
            session,
            source_id=source_id,
            config=config,
            adapter=adapter,
            started_at=started_at,
            trigger_type=trigger_type,
            trigger_key=trigger_key,
            scheduled_for=scheduled_for,
            retry_of_run_id=retry_of_run_id,
            attempt_number=attempt_number,
        )
    if not created:
        existing = session.get(CrawlRun, run_id)
        if existing is None:
            raise IngestionRunError("run_not_found", "Claimed crawl run disappeared.")
        if existing.status in (CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING):
            session.rollback()
            raise IngestionRunError(
                "run_already_active",
                "An ingestion run is already active for this trigger.",
            )
        report = _report(existing, config.source_key, reused=True)
        session.rollback()
        return report
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
            retry_after_seconds=_retry_after_seconds(error),
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
    first_retry_after_seconds: int | None = None

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
            error_code, should_stop, retry_after_seconds = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
            )
            first_error_code = first_error_code or error_code
            first_retry_after_seconds = first_retry_after_seconds or retry_after_seconds
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
                provenance_url=listing.canonical_url,
            )
            raw_snapshot = _snapshot_contract(snapshot, config.source_key)
            snapshot_id = snapshot.id
            session.commit()
        except Exception as error:
            error_code, should_stop, retry_after_seconds = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
            )
            first_error_code = first_error_code or error_code
            first_retry_after_seconds = first_retry_after_seconds or retry_after_seconds
            coverage_complete = False
            if should_stop:
                break
            continue

        try:
            parsed = adapter.parse(raw_snapshot)
        except Exception as error:
            error_code, should_stop, retry_after_seconds = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
                snapshot_id=snapshot_id,
            )
            first_error_code = first_error_code or error_code
            first_retry_after_seconds = first_retry_after_seconds or retry_after_seconds
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
            error_code, _, retry_after_seconds = _handle_item_exception(
                session,
                run_id=run_id,
                error=TypeError("adapter parse contract returned an unsupported result"),
                item_index=index,
                item_count=len(selected),
                snapshot_id=snapshot_id,
            )
            first_error_code = first_error_code or error_code
            first_retry_after_seconds = first_retry_after_seconds or retry_after_seconds
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
            error_code, should_stop, retry_after_seconds = _handle_item_exception(
                session,
                run_id=run_id,
                error=error,
                item_index=index,
                item_count=len(selected),
                snapshot_id=snapshot_id,
            )
            first_error_code = first_error_code or error_code
            first_retry_after_seconds = first_retry_after_seconds or retry_after_seconds
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
        retry_after_seconds=first_retry_after_seconds,
    )
