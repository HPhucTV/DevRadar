"""Evidence-backed skill frequency and bounded trend resources for V3."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field, model_validator
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from devradar.api.common import (
    ERROR_RESPONSES,
    ApiModel,
    PaginationData,
    PaginationQuery,
    pagination_data,
)
from devradar.catalog.models import Job, JobStatus
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.intelligence.evaluation import canonicalize_skill_name
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)
from devradar.intelligence.models import ExtractionResult, ExtractionValidationStatus
from devradar.intelligence.taxonomy import TAXONOMY_VERSION, SkillCategory, skill_category
from devradar.platform.database import get_database_session

router = APIRouter(tags=["analytics"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]
MAX_TREND_DAYS = 366


class CohortField(StrEnum):
    FIRST_SEEN_AT = "firstSeenAt"
    POSTED_AT = "postedAt"


class TrendGranularity(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class SkillFrequencyQuery(PaginationQuery):
    status: JobStatus = JobStatus.ACTIVE
    source_id: UUID | None = None
    cohort: CohortField = CohortField.FIRST_SEEN_AT
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def validate_window(self) -> SkillFrequencyQuery:
        if (self.from_date is None) != (self.to_date is None):
            raise ValueError("from and to must be supplied together")
        if self.from_date is not None and self.to_date is not None:
            _validate_window(self.from_date, self.to_date)
        return self


class SkillTrendQuery(ApiModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    cohort: CohortField = CohortField.FIRST_SEEN_AT
    granularity: TrendGranularity = TrendGranularity.MONTH
    top_skills: int = Field(default=10, ge=1, le=20)
    status: JobStatus = JobStatus.ACTIVE
    source_id: UUID | None = None

    @model_validator(mode="after")
    def validate_window(self) -> SkillTrendQuery:
        _validate_window(self.from_date, self.to_date)
        return self


class AnalyticsMeta(ApiModel):
    cohort_size: int
    analyzed_jobs: int
    coverage: float
    taxonomy_version: str
    extraction_schema_version: str


class SkillFrequencyData(ApiModel):
    name: str
    category: SkillCategory
    job_count: int
    share: float


class SkillFrequencyResponse(ApiModel):
    data: list[SkillFrequencyData]
    pagination: PaginationData
    meta: AnalyticsMeta


class TrendSkillData(ApiModel):
    name: str
    job_count: int
    share: float


class SkillTrendBucket(ApiModel):
    period_start: date
    denominator: int
    analyzed_jobs: int
    coverage: float
    skills: list[TrendSkillData]


class SkillTrendMeta(AnalyticsMeta):
    from_date: date
    to_date: date
    cohort: CohortField
    granularity: TrendGranularity


class SkillTrendResponse(ApiModel):
    data: list[SkillTrendBucket]
    meta: SkillTrendMeta


@dataclass(frozen=True, slots=True)
class _AnalyticsRow:
    cohort_at: datetime
    skills: frozenset[str] | None


def _validate_window(from_date: date, to_date: date) -> None:
    if from_date > to_date:
        raise ValueError("from must not exceed to")
    if (to_date - from_date).days + 1 > MAX_TREND_DAYS:
        raise ValueError(f"window must not exceed {MAX_TREND_DAYS} days")


def _coverage(analyzed_jobs: int, cohort_size: int) -> float:
    return round(analyzed_jobs / cohort_size, 4) if cohort_size else 0.0


def _share(job_count: int, denominator: int) -> float:
    return round(job_count / denominator, 4) if denominator else 0.0


def _latest_accepted_extractions() -> Any:
    rank = func.row_number().over(
        partition_by=(ExtractionResult.input_ref, ExtractionResult.input_hash),
        order_by=(ExtractionResult.created_at.desc(), ExtractionResult.id.desc()),
    )
    return (
        select(
            ExtractionResult.input_ref.label("job_id"),
            ExtractionResult.input_hash.label("input_hash"),
            ExtractionResult.output_data.label("output_data"),
            rank.label("result_rank"),
        )
        .where(
            ExtractionResult.schema_version == EXTRACTION_SCHEMA_VERSION,
            ExtractionResult.canonicalization_version == CANONICALIZATION_VERSION,
            ExtractionResult.validation_status == ExtractionValidationStatus.ACCEPTED.value,
        )
        .subquery()
    )


def _cohort_column(cohort: CohortField) -> InstrumentedAttribute[datetime | None]:
    if cohort is CohortField.POSTED_AT:
        return Job.posted_at
    return Job.first_seen_at


def _skill_names(output_data: object) -> frozenset[str] | None:
    if not isinstance(output_data, dict):
        return None
    raw_skills = output_data.get("skills")
    if not isinstance(raw_skills, list):
        return None
    names = {
        canonicalize_skill_name(name)
        for item in raw_skills
        if isinstance(item, dict) and isinstance((name := item.get("name")), str) and name.strip()
    }
    return frozenset(names)


def _analytics_rows(
    session: Session,
    *,
    status: JobStatus,
    source_id: UUID | None,
    cohort: CohortField,
    from_date: date | None,
    to_date: date | None,
) -> list[_AnalyticsRow]:
    cohort_column = _cohort_column(cohort)
    latest = _latest_accepted_extractions()
    conditions: list[ColumnElement[bool]] = [
        Job.status == status,
        cohort_column.is_not(None),
    ]
    if source_id is not None:
        conditions.append(Job.source_id == source_id)
    if from_date is not None and to_date is not None:
        start = datetime.combine(from_date, time.min, tzinfo=UTC)
        end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        conditions.extend((cohort_column >= start, cohort_column < end))

    rows = session.execute(
        select(cohort_column, latest.c.output_data)
        .select_from(Job)
        .join(Source, Source.id == Job.source_id)
        .outerjoin(
            latest,
            and_(
                latest.c.job_id == Job.id,
                latest.c.input_hash == Job.job_content_hash,
                latest.c.result_rank == 1,
            ),
        )
        .where(Source.approval_status == SourceApprovalStatus.APPROVED, *conditions)
        .order_by(cohort_column.asc(), Job.id.asc())
    ).all()
    return [
        _AnalyticsRow(cohort_at=cohort_at, skills=_skill_names(output_data))
        for cohort_at, output_data in rows
        if isinstance(cohort_at, datetime)
    ]


def _meta(rows: list[_AnalyticsRow]) -> AnalyticsMeta:
    analyzed_jobs = sum(row.skills is not None for row in rows)
    return AnalyticsMeta(
        cohort_size=len(rows),
        analyzed_jobs=analyzed_jobs,
        coverage=_coverage(analyzed_jobs, len(rows)),
        taxonomy_version=TAXONOMY_VERSION,
        extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
    )


@router.get("/skills", response_model=SkillFrequencyResponse, responses=ERROR_RESPONSES)
def list_skill_frequency(
    filters: Annotated[SkillFrequencyQuery, Query()],
    session: DatabaseSession,
) -> SkillFrequencyResponse:
    rows = _analytics_rows(
        session,
        status=filters.status,
        source_id=filters.source_id,
        cohort=filters.cohort,
        from_date=filters.from_date,
        to_date=filters.to_date,
    )
    counts = Counter(skill for row in rows for skill in (row.skills or ()))
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    start = (filters.page - 1) * filters.page_size
    page = ordered[start : start + filters.page_size]
    return SkillFrequencyResponse(
        data=[
            SkillFrequencyData(
                name=name,
                category=skill_category(name),
                job_count=count,
                share=_share(count, len(rows)),
            )
            for name, count in page
        ],
        pagination=pagination_data(filters, len(ordered)),
        meta=_meta(rows),
    )


def _bucket_start(value: datetime, granularity: TrendGranularity) -> date:
    day = value.date()
    if granularity is TrendGranularity.WEEK:
        return day - timedelta(days=day.weekday())
    if granularity is TrendGranularity.MONTH:
        return day.replace(day=1)
    return day


@router.get("/skill-trends", response_model=SkillTrendResponse, responses=ERROR_RESPONSES)
def list_skill_trends(
    filters: Annotated[SkillTrendQuery, Query()],
    session: DatabaseSession,
) -> SkillTrendResponse:
    rows = _analytics_rows(
        session,
        status=filters.status,
        source_id=filters.source_id,
        cohort=filters.cohort,
        from_date=filters.from_date,
        to_date=filters.to_date,
    )
    global_counts = Counter(skill for row in rows for skill in (row.skills or ()))
    top_skills = [
        name
        for name, _ in sorted(global_counts.items(), key=lambda item: (-item[1], item[0]))[
            : filters.top_skills
        ]
    ]
    buckets: dict[date, list[_AnalyticsRow]] = defaultdict(list)
    for row in rows:
        buckets[_bucket_start(row.cohort_at, filters.granularity)].append(row)

    data: list[SkillTrendBucket] = []
    for period_start, bucket_rows in sorted(buckets.items()):
        counts = Counter(skill for row in bucket_rows for skill in (row.skills or ()))
        analyzed_jobs = sum(row.skills is not None for row in bucket_rows)
        data.append(
            SkillTrendBucket(
                period_start=period_start,
                denominator=len(bucket_rows),
                analyzed_jobs=analyzed_jobs,
                coverage=_coverage(analyzed_jobs, len(bucket_rows)),
                skills=[
                    TrendSkillData(
                        name=name,
                        job_count=counts[name],
                        share=_share(counts[name], len(bucket_rows)),
                    )
                    for name in top_skills
                ],
            )
        )

    meta = _meta(rows)
    return SkillTrendResponse(
        data=data,
        meta=SkillTrendMeta(
            **meta.model_dump(),
            from_date=filters.from_date,
            to_date=filters.to_date,
            cohort=filters.cohort,
            granularity=filters.granularity,
        ),
    )
