"""Transactional canonical Job upsert with V2 change/lifecycle history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.catalog.job_changes import (
    canonical_change_state,
    record_created_change,
    record_reactivated_change,
    record_updated_changes,
)
from devradar.catalog.models import Job, JobLevel, JobStatus
from devradar.ingestion.contracts import ParsedJob
from devradar.ingestion.models import (
    CrawlRun,
    CrawlRunStatus,
    ParseStatus,
    RawJobSnapshot,
    Source,
    source_status_is_ingestible,
)
from devradar.ingestion.normalization import (
    CanonicalJobContent,
    NormalizedExperience,
    NormalizedLocation,
    NormalizedSalary,
    SalaryPeriod,
    WorkMode,
    canonical_job_content_hash,
    canonical_job_content_hash_v1,
    normalize_canonical_url,
    normalize_multiline_text,
    normalize_text,
)
from devradar.ingestion.source_registry import SourceConfig
from devradar.platform.observability import record_job_observation


class JobUpsertError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


class JobUpsertOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    STALE = "stale"
    REPLAYED = "replayed"
    REACTIVATED = "reactivated"


_DOCUMENT_IMPORT_ADAPTER_VERSION = "source-recipe-document-import-v1"


@dataclass(frozen=True, slots=True)
class JobUpsertResult:
    job: Job
    outcome: JobUpsertOutcome
    job_content_hash: str


def _result(
    job: Job,
    outcome: JobUpsertOutcome,
    job_content_hash: str,
    *,
    crawl_run: CrawlRun,
    snapshot: RawJobSnapshot,
) -> JobUpsertResult:
    record_job_observation(
        run_id=crawl_run.id,
        source_id=crawl_run.source_id,
        snapshot_id=snapshot.id,
        job_id=job.id,
        outcome=outcome.value,
    )
    return JobUpsertResult(job, outcome, job_content_hash)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise JobUpsertError(
            "invalid_observation_time",
            f"{field_name} must be timezone-aware.",
        )


def _bounded(value: str | None, limit: int, field_name: str) -> None:
    if value is not None and len(value) > limit:
        raise JobUpsertError(
            "canonical_field_too_long",
            f"Canonical {field_name} exceeded its persistence limit.",
        )


def _validate_source_boundary(
    database_source: Source,
    crawl_run: CrawlRun,
    source_config: SourceConfig,
) -> None:
    if (
        not source_status_is_ingestible(database_source.approval_status)
        or not source_status_is_ingestible(source_config.approval_status)
        or database_source.approval_status is not source_config.approval_status
        or database_source.name != source_config.name
        or database_source.base_url != source_config.base_url
        or database_source.adapter_key != source_config.adapter_key
        or set(database_source.allowed_hosts) != set(source_config.fetch_policy.allowed_hosts)
        or crawl_run.config_version != source_config.config_version
    ):
        raise JobUpsertError(
            "source_config_mismatch",
            "Job upsert source did not match the approved persisted configuration.",
        )


def _canonical_content(parsed_job: ParsedJob, source_config: SourceConfig) -> CanonicalJobContent:
    raw = parsed_job.raw
    normalized = parsed_job.normalized_candidates
    allowed_hosts = tuple(
        dict.fromkeys((*source_config.fetch_policy.allowed_hosts, *source_config.reference_hosts))
    )
    try:
        canonical_url = normalize_canonical_url(
            raw.canonical_url,
            base_url=source_config.base_url,
            allowed_hosts=allowed_hosts,
        ).value
        if normalize_text(raw.title).value != normalized.title:
            raise ValueError("title normalization mismatch")
        if normalize_text(raw.company_name).value != normalized.company_name:
            raise ValueError("company normalization mismatch")
        if normalize_multiline_text(raw.description).value != normalized.description_text:
            raise ValueError("description normalization mismatch")

        work_mode = WorkMode(normalized.work_mode) if normalized.work_mode is not None else None
        location = None
        if (
            normalized.location_city is not None
            or normalized.location_province is not None
            or work_mode is not None
        ):
            location = NormalizedLocation(
                city=normalized.location_city,
                province=normalized.location_province,
                work_mode=work_mode,
            )

        salary_period = (
            SalaryPeriod(normalized.salary_period) if normalized.salary_period is not None else None
        )
        salary = None
        if any(
            value is not None
            for value in (
                normalized.salary_min,
                normalized.salary_max,
                normalized.currency,
                salary_period,
            )
        ):
            salary = NormalizedSalary(
                minimum=normalized.salary_min,
                maximum=normalized.salary_max,
                currency=normalized.currency,
                period=salary_period,
            )

        levels = tuple(JobLevel(value) for value in normalized.levels)
        experience = None
        if normalized.experience_min is not None or normalized.experience_max is not None:
            experience = NormalizedExperience(
                minimum_years=normalized.experience_min,
                maximum_years=normalized.experience_max,
            )
        if canonical_url is None:
            raise ValueError("canonical URL normalization was empty")
        content = CanonicalJobContent(
            canonical_url=canonical_url,
            title=normalized.title,
            company_name=normalized.company_name,
            description_text=normalized.description_text,
            location_raw=raw.location,
            location=location,
            salary_raw=raw.salary,
            salary=salary,
            level_raw=raw.level,
            levels=levels,
            experience=experience,
        )
    except ValueError as error:
        raise JobUpsertError(
            "invalid_canonical_job",
            "Parsed job could not be converted to valid canonical V1 content.",
        ) from error

    _bounded(raw.external_id, 500, "external_id")
    _bounded(content.canonical_url, 2048, "canonical_url")
    _bounded(content.title, 500, "title")
    _bounded(content.company_name, 300, "company_name")
    _bounded(raw.location, 500, "location_raw")
    _bounded(normalized.location_city, 200, "location_city")
    _bounded(normalized.location_province, 200, "location_province")
    _bounded(normalized.work_mode, 32, "work_mode")
    _bounded(raw.salary, 500, "salary_raw")
    _bounded(normalized.salary_period, 32, "salary_period")
    _bounded(raw.level, 500, "level_raw")
    return content


def _find_job(
    session: Session,
    *,
    source_id: UUID,
    external_id: str,
    canonical_url: str,
) -> Job | None:
    by_external_id = session.scalar(
        select(Job)
        .where(Job.source_id == source_id, Job.external_id == external_id)
        .with_for_update()
    )
    by_canonical_url = session.scalar(
        select(Job)
        .where(Job.source_id == source_id, Job.canonical_url == canonical_url)
        .with_for_update()
    )
    if (
        by_external_id is not None
        and by_canonical_url is not None
        and by_external_id.id != by_canonical_url.id
    ):
        raise JobUpsertError(
            "identity_conflict",
            "External ID and canonical URL resolved to different source-scoped Jobs.",
        )
    job = by_external_id or by_canonical_url
    if job is not None and job.external_id not in {None, external_id}:
        raise JobUpsertError(
            "identity_conflict",
            "Canonical URL was already assigned to a different source external ID.",
        )
    return job


def _apply_current_state(
    job: Job,
    *,
    parsed_job: ParsedJob,
    content: CanonicalJobContent,
    snapshot: RawJobSnapshot,
    content_hash: str,
) -> None:
    normalized = parsed_job.normalized_candidates
    salary = content.salary
    location = content.location
    experience = content.experience
    job.external_id = parsed_job.raw.external_id
    job.canonical_url = content.canonical_url
    job.title = content.title
    job.company_name = content.company_name
    job.description_text = content.description_text
    job.location_raw = content.location_raw
    job.location_city = location.city if location else None
    job.location_province = location.province if location else None
    job.work_mode = location.work_mode.value if location and location.work_mode else None
    job.salary_raw = content.salary_raw
    job.salary_min = salary.minimum if salary else None
    job.salary_max = salary.maximum if salary else None
    job.currency = salary.currency if salary else None
    job.salary_period = salary.period.value if salary and salary.period else None
    job.level_raw = content.level_raw
    job.levels = [level.value for level in content.levels]
    job.experience_min = experience.minimum_years if experience else None
    job.experience_max = experience.maximum_years if experience else None
    job.posted_at = normalized.posted_at
    job.last_seen_at = snapshot.fetched_at
    job.current_snapshot_id = snapshot.id
    job.job_content_hash = content_hash


def upsert_parsed_job(
    session: Session,
    *,
    crawl_run: CrawlRun,
    snapshot: RawJobSnapshot,
    parsed_job: ParsedJob,
    source_config: SourceConfig,
) -> JobUpsertResult:
    """Flush one canonical observation without owning commit or rollback."""

    if crawl_run.id is None or snapshot.id is None:
        raise JobUpsertError(
            "observation_not_persisted",
            "Job upsert requires a persisted crawl run and raw snapshot.",
        )
    content = _canonical_content(parsed_job, source_config)
    content_hash = canonical_job_content_hash(content)
    legacy_content_hash = canonical_job_content_hash_v1(content)

    with session.no_autoflush:
        database_run = session.get(CrawlRun, crawl_run.id, with_for_update=True)
        database_snapshot = session.get(RawJobSnapshot, snapshot.id, with_for_update=True)
        if database_run is None or database_snapshot is None:
            raise JobUpsertError(
                "observation_not_persisted",
                "Job upsert could not load its crawl run or raw snapshot.",
            )
        database_source = session.get(Source, database_run.source_id, with_for_update=True)
        if database_source is None:
            raise JobUpsertError(
                "source_not_persisted",
                "Job upsert requires a persisted source.",
            )
        _validate_source_boundary(database_source, database_run, source_config)
        _require_aware(database_snapshot.fetched_at, "snapshot.fetched_at")
        if database_run.status is not CrawlRunStatus.RUNNING:
            raise JobUpsertError(
                "crawl_run_not_running",
                "Job upsert requires a running crawl run.",
            )
        if (
            database_snapshot.crawl_run_id != database_run.id
            or database_snapshot.source_id != database_run.source_id
            or database_snapshot.external_id != parsed_job.raw.external_id
        ):
            raise JobUpsertError(
                "observation_identity_mismatch",
                "Parsed job identity did not match snapshot/run provenance.",
            )
        job = _find_job(
            session,
            source_id=database_run.source_id,
            external_id=parsed_job.raw.external_id,
            canonical_url=content.canonical_url,
        )

    if (
        job is not None
        and database_run.adapter_version == _DOCUMENT_IMPORT_ADAPTER_VERSION
        and content.description_text is None
        and job.description_text is not None
    ):
        # A bounded document import may contain only listing fields. Missing optional
        # text means "not observed in this partial document", not "delete prior detail".
        content = replace(content, description_text=job.description_text)
        content_hash = canonical_job_content_hash(content)
        legacy_content_hash = canonical_job_content_hash_v1(content)

    if database_snapshot.parse_status is ParseStatus.PARSED:
        if job is None:
            raise JobUpsertError(
                "snapshot_already_processed",
                "Parsed snapshot had no source-scoped canonical Job.",
            )
        if not (
            (
                job.current_snapshot_id == database_snapshot.id
                and job.job_content_hash in {content_hash, legacy_content_hash}
            )
            or database_snapshot.fetched_at < job.last_seen_at
        ):
            raise JobUpsertError(
                "snapshot_already_processed",
                "Parsed snapshot could not be replayed against current canonical state.",
            )
        return _result(
            job,
            JobUpsertOutcome.REPLAYED,
            job.job_content_hash,
            crawl_run=database_run,
            snapshot=database_snapshot,
        )
    if database_snapshot.parse_status is not ParseStatus.PENDING:
        raise JobUpsertError(
            "snapshot_not_pending",
            "Job upsert only accepts a pending raw snapshot.",
        )

    outcome: JobUpsertOutcome
    if job is None:
        job = Job(
            source_id=database_run.source_id,
            external_id=parsed_job.raw.external_id,
            canonical_url=content.canonical_url,
            title=content.title,
            company_name=content.company_name,
            levels=[],
            first_seen_at=database_snapshot.fetched_at,
            last_seen_at=database_snapshot.fetched_at,
            current_snapshot_id=database_snapshot.id,
            job_content_hash=content_hash,
        )
        _apply_current_state(
            job,
            parsed_job=parsed_job,
            content=content,
            snapshot=database_snapshot,
            content_hash=content_hash,
        )
        session.add(job)
        session.flush()
        record_created_change(
            session,
            job=job,
            crawl_run=database_run,
            snapshot=database_snapshot,
        )
        database_run.items_new += 1
        outcome = JobUpsertOutcome.CREATED
    else:
        if job.status is JobStatus.ACTIVE and job.consecutive_missing_count != 0:
            raise JobUpsertError(
                "invalid_job_state",
                "Active Job cannot retain an absence counter.",
            )
        if database_snapshot.fetched_at < job.last_seen_at:
            outcome = JobUpsertOutcome.STALE
        elif database_snapshot.fetched_at == job.last_seen_at:
            if job.job_content_hash not in {content_hash, legacy_content_hash}:
                raise JobUpsertError(
                    "observation_conflict",
                    "Equal-time observations had different canonical content.",
                )
            outcome = JobUpsertOutcome.REPLAYED
        else:
            old_status = job.status
            old_snapshot_id = job.current_snapshot_id
            old_state = canonical_change_state(job)
            legacy_unchanged = (
                job.job_content_hash == legacy_content_hash
                and job.description_text == content.description_text
            )
            content_changed = job.job_content_hash != content_hash and not legacy_unchanged
            reactivating = old_status is not JobStatus.ACTIVE
            if reactivating and job.consecutive_missing_count < 1:
                raise JobUpsertError(
                    "invalid_job_state",
                    "Absent Job must retain a positive missing counter.",
                )
            if content_changed:
                _apply_current_state(
                    job,
                    parsed_job=parsed_job,
                    content=content,
                    snapshot=database_snapshot,
                    content_hash=content_hash,
                )
                database_run.items_updated += 1
                record_updated_changes(
                    session,
                    job=job,
                    crawl_run=database_run,
                    old_state=old_state,
                    from_snapshot_id=old_snapshot_id,
                    to_snapshot=database_snapshot,
                )
            else:
                job.last_seen_at = database_snapshot.fetched_at
                job.current_snapshot_id = database_snapshot.id

            if reactivating:
                job.status = JobStatus.ACTIVE
                job.consecutive_missing_count = 0
                job.removed_at = None
                database_run.items_reactivated += 1
                record_reactivated_change(
                    session,
                    job=job,
                    crawl_run=database_run,
                    old_status=old_status,
                    from_snapshot_id=old_snapshot_id,
                    to_snapshot=database_snapshot,
                )
                outcome = JobUpsertOutcome.REACTIVATED
            elif content_changed:
                outcome = JobUpsertOutcome.UPDATED
            else:
                outcome = JobUpsertOutcome.UNCHANGED

    database_snapshot.parse_status = ParseStatus.PARSED
    database_snapshot.error_code = None
    session.flush()
    return _result(
        job,
        outcome,
        content_hash,
        crawl_run=database_run,
        snapshot=database_snapshot,
    )
