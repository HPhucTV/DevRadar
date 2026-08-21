"""Meaningful canonical JobChange history and absence transitions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from devradar.catalog.models import Job, JobChange, JobChangeType, JobStatus
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    ParseStatus,
    RawJobSnapshot,
)

_CHANGE_FIELDS = (
    "external_id",
    "canonical_url",
    "title",
    "company_name",
    "description_text",
    "location_raw",
    "location_city",
    "location_province",
    "work_mode",
    "salary_raw",
    "salary_min",
    "salary_max",
    "currency",
    "salary_period",
    "level_raw",
    "levels",
    "experience_min",
    "experience_max",
)


def canonical_change_state(job: Job) -> dict[str, Any]:
    return {field_name: getattr(job, field_name) for field_name in _CHANGE_FIELDS}


def _json_value(field_name: str, value: Any) -> Any:
    if field_name == "description_text" and isinstance(value, str):
        return {"sha256": sha256(value.encode()).hexdigest()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_json_value(field_name, item) for item in value]
    return value


def _add_change(
    session: Session,
    *,
    job: Job,
    crawl_run: CrawlRun,
    change_type: JobChangeType,
    field_name: str,
    old_value: Any,
    new_value: Any,
    from_snapshot_id: UUID | None,
    to_snapshot_id: UUID | None,
    detected_at: datetime,
) -> None:
    session.add(
        JobChange(
            job_id=job.id,
            crawl_run_id=crawl_run.id,
            from_snapshot_id=from_snapshot_id,
            to_snapshot_id=to_snapshot_id,
            field_name=field_name,
            old_value=_json_value(field_name, old_value),
            new_value=_json_value(field_name, new_value),
            change_type=change_type,
            detected_at=detected_at,
        )
    )


def record_created_change(
    session: Session,
    *,
    job: Job,
    crawl_run: CrawlRun,
    snapshot: RawJobSnapshot,
) -> None:
    _add_change(
        session,
        job=job,
        crawl_run=crawl_run,
        change_type=JobChangeType.CREATED,
        field_name="status",
        old_value=None,
        new_value=JobStatus.ACTIVE,
        from_snapshot_id=None,
        to_snapshot_id=snapshot.id,
        detected_at=snapshot.fetched_at,
    )


def record_updated_changes(
    session: Session,
    *,
    job: Job,
    crawl_run: CrawlRun,
    old_state: dict[str, Any],
    from_snapshot_id: UUID,
    to_snapshot: RawJobSnapshot,
) -> None:
    new_state = canonical_change_state(job)
    for field_name in _CHANGE_FIELDS:
        if old_state[field_name] != new_state[field_name]:
            _add_change(
                session,
                job=job,
                crawl_run=crawl_run,
                change_type=JobChangeType.UPDATED,
                field_name=field_name,
                old_value=old_state[field_name],
                new_value=new_state[field_name],
                from_snapshot_id=from_snapshot_id,
                to_snapshot_id=to_snapshot.id,
                detected_at=to_snapshot.fetched_at,
            )


def record_reactivated_change(
    session: Session,
    *,
    job: Job,
    crawl_run: CrawlRun,
    old_status: JobStatus,
    from_snapshot_id: UUID,
    to_snapshot: RawJobSnapshot,
) -> None:
    _add_change(
        session,
        job=job,
        crawl_run=crawl_run,
        change_type=JobChangeType.REACTIVATED,
        field_name="status",
        old_value=old_status,
        new_value=JobStatus.ACTIVE,
        from_snapshot_id=from_snapshot_id,
        to_snapshot_id=to_snapshot.id,
        detected_at=to_snapshot.fetched_at,
    )


def _observed_job_ids(session: Session, crawl_run: CrawlRun) -> set[UUID]:
    identity_match = or_(
        and_(
            Job.external_id.is_not(None),
            RawJobSnapshot.external_id.is_not(None),
            Job.external_id == RawJobSnapshot.external_id,
        ),
        Job.canonical_url == RawJobSnapshot.source_url,
    )
    return set(
        session.scalars(
            select(Job.id)
            .join(
                RawJobSnapshot,
                and_(
                    RawJobSnapshot.source_id == Job.source_id,
                    identity_match,
                ),
            )
            .where(
                Job.source_id == crawl_run.source_id,
                RawJobSnapshot.crawl_run_id == crawl_run.id,
                RawJobSnapshot.parse_status == ParseStatus.PARSED,
            )
        )
    )


def apply_absence_lifecycle(
    session: Session,
    *,
    crawl_run: CrawlRun,
    detected_at: datetime,
) -> None:
    """Apply absence only after a successful, complete run; never commit."""

    if (
        crawl_run.status is not CrawlRunStatus.SUCCEEDED
        or crawl_run.coverage_status is not CoverageStatus.COMPLETE
    ):
        return
    observed_job_ids = _observed_job_ids(session, crawl_run)
    jobs = session.scalars(
        select(Job).where(Job.source_id == crawl_run.source_id).with_for_update()
    ).all()
    for job in jobs:
        if job.id in observed_job_ids or job.status is JobStatus.REMOVED:
            continue
        previous_status = job.status
        if previous_status is JobStatus.ACTIVE:
            job.status = JobStatus.MISSING
            job.consecutive_missing_count = 1
            crawl_run.items_missing += 1
            change_type = JobChangeType.MISSING
        else:
            job.consecutive_missing_count += 1
            if job.consecutive_missing_count < 2:
                continue
            job.status = JobStatus.REMOVED
            job.removed_at = detected_at
            crawl_run.items_removed += 1
            change_type = JobChangeType.REMOVED
        _add_change(
            session,
            job=job,
            crawl_run=crawl_run,
            change_type=change_type,
            field_name="status",
            old_value=previous_status,
            new_value=job.status,
            from_snapshot_id=job.current_snapshot_id,
            to_snapshot_id=None,
            detected_at=detected_at,
        )
    session.flush()
