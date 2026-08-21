"""One-shot PostgreSQL worker for pending local operator requests."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.automation.health import source_allows_trigger
from devradar.automation.orchestrator import (
    DEFAULT_RETRY_POLICY,
    JitterSource,
    OrchestrationResult,
    RetryPolicy,
    Sleeper,
    orchestrate_source,
)
from devradar.automation.run_requests import LOCAL_OPERATOR_PRINCIPAL, matching_source_config
from devradar.ingestion.models import CrawlRun, CrawlRunStatus, CrawlTriggerType, Source
from devradar.ingestion.runner import (
    IngestionRunError,
    resolve_v1_source,
    source_matches_config,
)
from devradar.ingestion.source_registry import ResolvedSource

Clock = Callable[[], datetime]
SourceResolver = Callable[[str], ResolvedSource]


@dataclass(frozen=True, slots=True)
class ClaimedRun:
    run_id: UUID
    resolved_source: ResolvedSource


def _claim_next_pending_run(
    session: Session,
    *,
    resolver: SourceResolver,
    started_at: datetime,
) -> ClaimedRun | None:
    if session.in_transaction():
        raise IngestionRunError(
            "transaction_already_active",
            "Worker requires a fresh session transaction boundary.",
        )
    crawl_run = session.scalar(
        select(CrawlRun)
        .where(
            CrawlRun.status == CrawlRunStatus.PENDING,
            CrawlRun.trigger_type == CrawlTriggerType.MANUAL,
            CrawlRun.requested_by == LOCAL_OPERATOR_PRINCIPAL,
        )
        .order_by(CrawlRun.requested_at.asc(), CrawlRun.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if crawl_run is None:
        session.rollback()
        return None
    source = session.get(Source, crawl_run.source_id, with_for_update=True)
    config = None if source is None else matching_source_config(source)
    if source is None or config is None or not source_matches_config(source, config):
        session.rollback()
        raise IngestionRunError(
            "source_config_mismatch",
            "Pending run source does not match the approved registry configuration.",
        )
    if not source_allows_trigger(source, crawl_run.trigger_type):
        session.rollback()
        raise IngestionRunError(
            "source_quarantined",
            "Scheduled and retry triggers are disabled while source is quarantined.",
        )
    resolved = resolver(config.source_key)
    if resolved.config != config:
        session.rollback()
        raise IngestionRunError(
            "source_config_mismatch",
            "Resolved source does not match the pending run configuration.",
        )
    if (
        resolved.adapter.adapter_key != config.adapter_key
        or not resolved.adapter.adapter_version.strip()
    ):
        session.rollback()
        raise IngestionRunError(
            "adapter_config_mismatch",
            "Resolved adapter does not match the pending run configuration.",
        )
    crawl_run.status = CrawlRunStatus.RUNNING
    crawl_run.started_at = started_at.astimezone(UTC)
    crawl_run.adapter_version = resolved.adapter.adapter_version
    crawl_run.config_version = resolved.config.config_version
    run_id = crawl_run.id
    session.commit()
    return ClaimedRun(run_id=run_id, resolved_source=resolved)


def work_one_pending_run(
    session: Session,
    *,
    deadline: datetime,
    resolver: SourceResolver = resolve_v1_source,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
) -> OrchestrationResult | None:
    """Claim and fully orchestrate at most one pending run."""

    started_at = clock()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise IngestionRunError("invalid_worker_time", "Worker time must include a UTC offset.")
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= started_at:
        raise IngestionRunError("invalid_deadline", "Worker deadline must be in the future.")
    claimed = _claim_next_pending_run(
        session,
        resolver=resolver,
        started_at=started_at,
    )
    if claimed is None:
        return None
    return orchestrate_source(
        session,
        config=claimed.resolved_source.config,
        adapter=claimed.resolved_source.adapter,
        deadline=deadline,
        retry_policy=retry_policy,
        clock=clock,
        sleeper=sleeper,
        jitter_source=jitter_source,
        claimed_run_id=claimed.run_id,
    )
