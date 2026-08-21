"""Deterministic source health, inventory anomaly, and quarantine policy."""

from __future__ import annotations

from datetime import datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceHealthStatus,
)

_POLICY_ERROR_CODES = frozenset(
    {
        "invalid_url",
        "policy_blocked",
        "redirect_blocked",
        "source_config_mismatch",
    }
)
_TRANSIENT_ERROR_CODES = frozenset(
    {
        "dns_failure",
        "network_error",
        "network_timeout",
        "rate_limited",
        "server_error",
    }
)
_PLATFORM_ERROR_CODES = frozenset(
    {
        "persistence_failed",
        "run_not_found",
        "snapshot_not_found",
        "unexpected_error",
    }
)
_OPERATOR_ERROR_CODES = frozenset({"cancelled", "operator_cancelled"})
_BASELINE_RUNS = 5
_MIN_BASELINE_RUNS = 2
_INVENTORY_DROP_RATIO = 0.5


def _previous_complete_counts(session: Session, crawl_run: CrawlRun) -> list[int]:
    return list(
        session.scalars(
            select(CrawlRun.items_found)
            .where(
                CrawlRun.source_id == crawl_run.source_id,
                CrawlRun.id != crawl_run.id,
                CrawlRun.status == CrawlRunStatus.SUCCEEDED,
                CrawlRun.coverage_status == CoverageStatus.COMPLETE,
            )
            .order_by(CrawlRun.finished_at.desc().nulls_last(), CrawlRun.id.desc())
            .limit(_BASELINE_RUNS)
        )
    )


def _mark_quarantined(source: Source, *, reason: str, finished_at: datetime) -> None:
    source.health_status = SourceHealthStatus.QUARANTINED
    source.health_reason_code = reason
    source.quarantined_at = finished_at


def evaluate_source_health(
    session: Session,
    *,
    source: Source,
    crawl_run: CrawlRun,
    finished_at: datetime,
) -> None:
    """Persist one bounded health decision; may downgrade suspicious coverage."""

    previous_status = source.health_status
    previous_counts = _previous_complete_counts(session, crawl_run)
    previous_baseline = int(median(previous_counts)) if previous_counts else None
    successful_complete = (
        crawl_run.status is CrawlRunStatus.SUCCEEDED
        and crawl_run.coverage_status is CoverageStatus.COMPLETE
    )
    inventory_drop = bool(
        successful_complete
        and len(previous_counts) >= _MIN_BASELINE_RUNS
        and previous_baseline is not None
        and previous_baseline > 0
        and crawl_run.items_found < previous_baseline * _INVENTORY_DROP_RATIO
    )
    if inventory_drop:
        crawl_run.coverage_status = CoverageStatus.INCOMPLETE
        crawl_run.health_signal_code = "inventory_drop_anomaly"
        source.health_status = SourceHealthStatus.DEGRADED
        source.health_reason_code = "inventory_drop_anomaly"
        source.consecutive_failures += 1
        source.quarantined_at = None
        return

    if successful_complete:
        sample = [crawl_run.items_found, *previous_counts[: _BASELINE_RUNS - 1]]
        source.baseline_items_found = int(median(sample))
        source.health_status = SourceHealthStatus.HEALTHY
        source.health_reason_code = None
        source.consecutive_failures = 0
        source.quarantined_at = None
        if previous_status is not SourceHealthStatus.HEALTHY:
            crawl_run.health_signal_code = "source_recovered"
        return

    error_code = crawl_run.error_code or "run_incomplete"
    crawl_run.health_signal_code = error_code
    if error_code in _OPERATOR_ERROR_CODES:
        source.health_reason_code = error_code
        return

    source.consecutive_failures += 1
    source.health_reason_code = error_code
    if error_code in _POLICY_ERROR_CODES:
        _mark_quarantined(source, reason=error_code, finished_at=finished_at)
    elif error_code in _TRANSIENT_ERROR_CODES:
        source.health_status = (
            SourceHealthStatus.UNHEALTHY
            if source.consecutive_failures >= 3
            else SourceHealthStatus.DEGRADED
        )
        source.quarantined_at = None
    elif error_code in _PLATFORM_ERROR_CODES:
        source.health_status = SourceHealthStatus.UNHEALTHY
        source.quarantined_at = None
    elif source.consecutive_failures >= 2:
        _mark_quarantined(source, reason=error_code, finished_at=finished_at)
    else:
        source.health_status = SourceHealthStatus.DEGRADED
        source.quarantined_at = None


def source_allows_trigger(source: Source, trigger_type: CrawlTriggerType) -> bool:
    return not (
        source.health_status is SourceHealthStatus.QUARANTINED
        and trigger_type in (CrawlTriggerType.SCHEDULED, CrawlTriggerType.RETRY)
    )
