"""PostgreSQL-backed orchestration without a separate control plane."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy.orm import Session

from devradar.ingestion.contracts import JobSourceAdapter
from devradar.ingestion.models import CrawlRunStatus, CrawlTriggerType
from devradar.ingestion.runner import RunReport, run_approved_source, run_custom_source
from devradar.ingestion.source_registry import SourceConfig

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
JitterSource = Callable[[], float]

TRANSIENT_ERROR_CODES = frozenset(
    {
        "dns_failure",
        "network_error",
        "network_timeout",
        "rate_limited",
        "server_error",
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 30
    max_delay_seconds: int = 300
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be in range 1..3")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be non-negative")
        if not self.base_delay_seconds <= self.max_delay_seconds <= 3600:
            raise ValueError("max_delay_seconds must be between base delay and 3600")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be in range 0..1")


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    reports: tuple[RunReport, ...]

    @property
    def final_report(self) -> RunReport:
        return self.reports[-1]


DEFAULT_RETRY_POLICY = RetryPolicy()


def scheduled_slot(now: datetime, interval_minutes: int) -> datetime:
    """Return the stable UTC slot containing ``now`` for an approved interval."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    if not 1 <= interval_minutes <= 10_080:
        raise ValueError("interval_minutes must be in range 1..10080")
    utc_now = now.astimezone(UTC)
    epoch_minutes = int(utc_now.timestamp() // 60)
    slot_minutes = epoch_minutes - (epoch_minutes % interval_minutes)
    return datetime.fromtimestamp(slot_minutes * 60, UTC)


def scheduled_trigger_key(source_key: str, slot: datetime) -> str:
    if not source_key or len(source_key) > 100:
        raise ValueError("source_key must contain 1..100 characters")
    if slot.tzinfo is None or slot.utcoffset() is None:
        raise ValueError("slot must include a UTC offset")
    return f"scheduled:{source_key}:{slot.astimezone(UTC).isoformat()}"


def is_transient_error(error_code: str | None) -> bool:
    return error_code in TRANSIENT_ERROR_CODES


def retry_delay_seconds(
    policy: RetryPolicy,
    *,
    failed_attempt_number: int,
    retry_after_seconds: int | None,
    jitter_value: float,
) -> float:
    if failed_attempt_number < 1:
        raise ValueError("failed_attempt_number must be positive")
    bounded_jitter = min(max(jitter_value, 0.0), 1.0)
    exponential = float(policy.base_delay_seconds * (2 ** (failed_attempt_number - 1)))
    jitter_factor = 1 + ((bounded_jitter * 2 - 1) * policy.jitter_ratio)
    delayed = exponential * jitter_factor
    if retry_after_seconds is not None:
        delayed = max(delayed, retry_after_seconds)
    return min(float(policy.max_delay_seconds), delayed)


def _retry_trigger_key(previous: RunReport, attempt_number: int) -> str:
    digest = sha256(f"{previous.run_id}:{attempt_number}".encode()).hexdigest()
    return f"retry:{digest}"


def orchestrate_source(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    deadline: datetime,
    trigger_type: CrawlTriggerType = CrawlTriggerType.MANUAL,
    trigger_key: str | None = None,
    scheduled_for: datetime | None = None,
    max_items: int | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
    claimed_run_id: UUID | None = None,
) -> OrchestrationResult:
    """Run one idempotent trigger and bounded transient-only retry chain."""

    reports: list[RunReport] = []
    next_trigger_type = trigger_type
    next_trigger_key = trigger_key
    next_scheduled_for = scheduled_for
    retry_of_run_id = None
    attempt_number = 1

    while True:
        report = run_approved_source(
            session,
            config=config,
            adapter=adapter,
            deadline=deadline,
            max_items=max_items,
            trigger_type=next_trigger_type,
            trigger_key=next_trigger_key,
            scheduled_for=next_scheduled_for,
            retry_of_run_id=retry_of_run_id,
            attempt_number=attempt_number,
            claimed_run_id=claimed_run_id if not reports else None,
        )
        reports.append(report)
        if (
            report.status is CrawlRunStatus.SUCCEEDED
            or report.attempt_number >= retry_policy.max_attempts
            or not is_transient_error(report.error_code)
        ):
            return OrchestrationResult(tuple(reports))

        delay = retry_delay_seconds(
            retry_policy,
            failed_attempt_number=report.attempt_number,
            retry_after_seconds=report.retry_after_seconds,
            jitter_value=jitter_source(),
        )
        if not report.reused:
            if clock() + timedelta(seconds=delay) >= deadline:
                return OrchestrationResult(tuple(reports))
            sleeper(delay)

        attempt_number = report.attempt_number + 1
        next_trigger_type = CrawlTriggerType.RETRY
        next_trigger_key = _retry_trigger_key(report, attempt_number)
        next_scheduled_for = None
        retry_of_run_id = report.run_id


def orchestrate_custom_source(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    persisted_source_id: UUID,
    deadline: datetime,
    trigger_type: CrawlTriggerType = CrawlTriggerType.MANUAL,
    trigger_key: str | None = None,
    scheduled_for: datetime | None = None,
    max_items: int | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
    claimed_run_id: UUID | None = None,
) -> OrchestrationResult:
    """Run a bounded owner-local profile without entering the approved registry."""

    reports: list[RunReport] = []
    next_trigger_type = trigger_type
    next_trigger_key = trigger_key
    next_scheduled_for = scheduled_for
    retry_of_run_id = None
    attempt_number = 1

    while True:
        report = run_custom_source(
            session,
            config=config,
            adapter=adapter,
            persisted_source_id=persisted_source_id,
            deadline=deadline,
            max_items=max_items,
            trigger_type=next_trigger_type,
            trigger_key=next_trigger_key,
            scheduled_for=next_scheduled_for,
            retry_of_run_id=retry_of_run_id,
            attempt_number=attempt_number,
            claimed_run_id=claimed_run_id if not reports else None,
        )
        reports.append(report)
        if (
            report.status is CrawlRunStatus.SUCCEEDED
            or report.attempt_number >= retry_policy.max_attempts
            or not is_transient_error(report.error_code)
        ):
            return OrchestrationResult(tuple(reports))
        delay = retry_delay_seconds(
            retry_policy,
            failed_attempt_number=report.attempt_number,
            retry_after_seconds=report.retry_after_seconds,
            jitter_value=jitter_source(),
        )
        if clock() + timedelta(seconds=delay) >= deadline:
            return OrchestrationResult(tuple(reports))
        sleeper(delay)
        attempt_number = report.attempt_number + 1
        next_trigger_type = CrawlTriggerType.RETRY
        next_trigger_key = _retry_trigger_key(report, attempt_number)
        next_scheduled_for = None
        retry_of_run_id = report.run_id


def orchestrate_source_recipe(
    session: Session,
    *,
    config: SourceConfig,
    adapter: JobSourceAdapter,
    persisted_source_id: UUID,
    deadline: datetime,
    trigger_type: CrawlTriggerType = CrawlTriggerType.MANUAL,
    trigger_key: str | None = None,
    scheduled_for: datetime | None = None,
    max_items: int | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
    claimed_run_id: UUID | None = None,
) -> OrchestrationResult:
    """Run one recipe trigger; rate limits become cooldowns instead of immediate retries."""

    reports: list[RunReport] = []
    next_trigger_type = trigger_type
    next_trigger_key = trigger_key
    next_scheduled_for = scheduled_for
    retry_of_run_id = None
    attempt_number = 1

    while True:
        report = run_custom_source(
            session,
            config=config,
            adapter=adapter,
            persisted_source_id=persisted_source_id,
            deadline=deadline,
            max_items=max_items,
            trigger_type=next_trigger_type,
            trigger_key=next_trigger_key,
            scheduled_for=next_scheduled_for,
            retry_of_run_id=retry_of_run_id,
            attempt_number=attempt_number,
            claimed_run_id=claimed_run_id if not reports else None,
        )
        reports.append(report)
        if (
            report.status is CrawlRunStatus.SUCCEEDED
            or report.error_code == "rate_limited"
            or report.attempt_number >= retry_policy.max_attempts
            or not is_transient_error(report.error_code)
        ):
            return OrchestrationResult(tuple(reports))
        delay = retry_delay_seconds(
            retry_policy,
            failed_attempt_number=report.attempt_number,
            retry_after_seconds=report.retry_after_seconds,
            jitter_value=jitter_source(),
        )
        if clock() + timedelta(seconds=delay) >= deadline:
            return OrchestrationResult(tuple(reports))
        sleeper(delay)
        attempt_number = report.attempt_number + 1
        next_trigger_type = CrawlTriggerType.RETRY
        next_trigger_key = _retry_trigger_key(report, attempt_number)
        next_scheduled_for = None
        retry_of_run_id = report.run_id
