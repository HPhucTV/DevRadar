"""Read-only canonical Job resources for V1."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import Field, JsonValue, field_validator, model_validator
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from devradar.api.common import (
    ERROR_RESPONSES,
    ApiModel,
    DataResponse,
    ErrorResponse,
    ListResponse,
    PaginationQuery,
    pagination_data,
)
from devradar.api.errors import ApiContractError
from devradar.catalog.models import Job, JobChange, JobChangeType, JobLevel, JobStatus
from devradar.ingestion.models import (
    ParseStatus,
    RawJobSnapshot,
    Source,
)
from devradar.intelligence.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_PROVIDER,
    EmbeddingModelUnavailable,
    EmbeddingValidationError,
    get_local_embedding_model,
)
from devradar.intelligence.evaluation import canonicalize_skill_name
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)
from devradar.intelligence.models import (
    ExtractionResult,
    ExtractionValidationStatus,
    JobEmbedding,
)
from devradar.platform.database import get_database_session
from devradar.source_recipes.visibility import visible_source_condition

router = APIRouter(prefix="/jobs", tags=["jobs"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class JobSortBy(StrEnum):
    LAST_SEEN_AT = "lastSeenAt"
    FIRST_SEEN_AT = "firstSeenAt"
    POSTED_AT = "postedAt"
    TITLE = "title"
    COMPANY_NAME = "companyName"
    SALARY_MIN = "salaryMin"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class SearchMode(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class JobQuery(PaginationQuery):
    status: JobStatus | None = None
    source_id: UUID | None = None
    company: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    level: JobLevel | None = None
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    seen_after: datetime | None = None
    seen_before: datetime | None = None
    query: str | None = Field(default=None, min_length=1, max_length=300)
    search_mode: SearchMode = SearchMode.KEYWORD
    skill: str | None = Field(default=None, min_length=1, max_length=50)
    sort_by: JobSortBy = JobSortBy.LAST_SEEN_AT
    sort_order: SortOrder = SortOrder.DESC

    @field_validator("query", "skill", mode="before")
    @classmethod
    def strip_search_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_combinations(self) -> Self:
        for text_value in (self.company, self.title, self.location):
            if text_value is not None and not text_value.strip():
                raise ValueError("text filters must not be blank")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salaryMin must not exceed salaryMax")
        for timestamp in (self.seen_after, self.seen_before):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("seen timestamps must include a UTC offset")
        if (
            self.seen_after is not None
            and self.seen_before is not None
            and self.seen_after > self.seen_before
        ):
            raise ValueError("seenAfter must not exceed seenBefore")
        if self.search_mode is SearchMode.SEMANTIC and self.query is None:
            raise ValueError("semantic search requires query")
        return self


class LocationData(ApiModel):
    raw: str | None
    city: str | None
    work_mode: str | None


class SalaryData(ApiModel):
    raw: str | None
    min: float | None
    max: float | None
    currency: str | None
    period: str | None


class JobSourceData(ApiModel):
    id: UUID
    name: str
    url: str


class JobSummary(ApiModel):
    id: UUID
    title: str
    company_name: str
    location: LocationData
    salary: SalaryData
    levels: list[JobLevel]
    status: JobStatus
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    source: JobSourceData
    relevance_score: float | None = None


class SnapshotData(ApiModel):
    id: UUID
    source_url: str
    fetched_at: datetime
    http_status: int
    content_type: str | None
    parse_status: ParseStatus


class JobDetail(JobSummary):
    description_text: str | None
    current_snapshot: SnapshotData


JobListResponse = ListResponse[JobSummary]
JobDetailResponse = DataResponse[JobDetail]


class JobChangeData(ApiModel):
    id: UUID
    job_id: UUID
    crawl_run_id: UUID
    change_type: JobChangeType
    field_name: str
    old_value: JsonValue
    new_value: JsonValue
    from_snapshot_id: UUID | None
    to_snapshot_id: UUID | None
    detected_at: datetime


JobChangeListResponse = ListResponse[JobChangeData]


def _decimal_number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _summary(job: Job, source: Source, *, relevance_score: float | None = None) -> JobSummary:
    return JobSummary(
        id=job.id,
        title=job.title,
        company_name=job.company_name,
        location=LocationData(
            raw=job.location_raw,
            city=job.location_city,
            work_mode=job.work_mode,
        ),
        salary=SalaryData(
            raw=job.salary_raw,
            min=_decimal_number(job.salary_min),
            max=_decimal_number(job.salary_max),
            currency=job.currency,
            period=job.salary_period,
        ),
        levels=[JobLevel(level) for level in job.levels],
        status=job.status,
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
        last_seen_at=job.last_seen_at,
        source=JobSourceData(id=source.id, name=source.name, url=job.canonical_url),
        relevance_score=relevance_score,
    )


def _like_pattern(value: str) -> str:
    escaped = value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _conditions(filters: JobQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        Job.source_id.in_(select(Source.id).where(visible_source_condition()))
    ]
    if filters.status is not None:
        conditions.append(Job.status == filters.status)
    if filters.source_id is not None:
        conditions.append(Job.source_id == filters.source_id)
    if filters.company is not None:
        conditions.append(Job.company_name.ilike(_like_pattern(filters.company), escape="\\"))
    if filters.title is not None:
        conditions.append(Job.title.ilike(_like_pattern(filters.title), escape="\\"))
    if filters.location is not None:
        pattern = _like_pattern(filters.location)
        conditions.append(
            or_(
                Job.location_raw.ilike(pattern, escape="\\"),
                Job.location_city.ilike(pattern, escape="\\"),
                Job.location_province.ilike(pattern, escape="\\"),
            )
        )
    if filters.level is not None:
        conditions.append(Job.levels.contains([filters.level.value]))
    if filters.salary_min is not None:
        conditions.append(func.coalesce(Job.salary_max, Job.salary_min) >= filters.salary_min)
    if filters.salary_max is not None:
        conditions.append(func.coalesce(Job.salary_min, Job.salary_max) <= filters.salary_max)
    if filters.seen_after is not None:
        conditions.append(Job.last_seen_at >= filters.seen_after)
    if filters.seen_before is not None:
        conditions.append(Job.last_seen_at <= filters.seen_before)
    if filters.query is not None and filters.search_mode is SearchMode.KEYWORD:
        pattern = _like_pattern(filters.query)
        conditions.append(
            or_(
                Job.title.ilike(pattern, escape="\\"),
                Job.company_name.ilike(pattern, escape="\\"),
                Job.description_text.ilike(pattern, escape="\\"),
            )
        )
    if filters.skill is not None:
        skill_name = canonicalize_skill_name(filters.skill)
        conditions.append(
            exists(
                select(ExtractionResult.id).where(
                    ExtractionResult.input_ref == Job.id,
                    ExtractionResult.input_hash == Job.job_content_hash,
                    ExtractionResult.schema_version == EXTRACTION_SCHEMA_VERSION,
                    ExtractionResult.canonicalization_version == CANONICALIZATION_VERSION,
                    ExtractionResult.validation_status == ExtractionValidationStatus.ACCEPTED.value,
                    ExtractionResult.output_data["skills"].contains([{"name": skill_name}]),
                )
            )
        )
    return conditions


def embed_query_text(query: str) -> tuple[float, ...]:
    return get_local_embedding_model().embed_query(query)


def _compatible_embedding_join() -> ColumnElement[bool]:
    return and_(
        JobEmbedding.job_id == Job.id,
        JobEmbedding.input_hash == Job.job_content_hash,
        JobEmbedding.input_schema_version == EMBEDDING_INPUT_SCHEMA_VERSION,
        JobEmbedding.provider == EMBEDDING_PROVIDER,
        JobEmbedding.model == EMBEDDING_MODEL_ID,
        JobEmbedding.model_revision == EMBEDDING_MODEL_REVISION,
        JobEmbedding.dimension == EMBEDDING_DIMENSION,
    )


def _semantic_jobs(
    session: Session,
    *,
    filters: JobQuery,
    conditions: list[ColumnElement[bool]],
) -> JobListResponse:
    assert filters.query is not None
    try:
        query_vector = embed_query_text(filters.query)
    except EmbeddingModelUnavailable:
        raise ApiContractError(
            503,
            "embedding_model_unavailable",
            "Semantic search tạm thời không sẵn sàng.",
        ) from None
    except EmbeddingValidationError:
        raise ApiContractError(
            503,
            "embedding_model_invalid",
            "Semantic search tạm thời không sẵn sàng.",
        ) from None

    embedding_column = cast(Any, JobEmbedding.embedding)
    distance = embedding_column.cosine_distance(list(query_vector)).label("semantic_distance")
    join_condition = _compatible_embedding_join()
    total_items = (
        session.scalar(
            select(func.count())
            .select_from(Job)
            .join(JobEmbedding, join_condition)
            .where(*conditions)
        )
        or 0
    )
    rows = session.execute(
        select(Job, Source, distance)
        .join(Source, Source.id == Job.source_id)
        .join(JobEmbedding, join_condition)
        .where(*conditions)
        .order_by(distance.asc(), Job.id.asc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return JobListResponse(
        data=[
            _summary(
                job,
                source,
                relevance_score=round(max(-1.0, min(1.0, 1.0 - float(distance_value))), 6),
            )
            for job, source, distance_value in rows
        ],
        pagination=pagination_data(filters, total_items),
    )


@router.get("", response_model=JobListResponse, responses=ERROR_RESPONSES)
def list_jobs(
    filters: Annotated[JobQuery, Query()],
    session: DatabaseSession,
) -> JobListResponse:
    conditions = _conditions(filters)
    if filters.search_mode is SearchMode.SEMANTIC:
        return _semantic_jobs(session, filters=filters, conditions=conditions)
    total_items = session.scalar(select(func.count()).select_from(Job).where(*conditions)) or 0
    sort_columns: dict[JobSortBy, InstrumentedAttribute[Any]] = {
        JobSortBy.LAST_SEEN_AT: Job.last_seen_at,
        JobSortBy.FIRST_SEEN_AT: Job.first_seen_at,
        JobSortBy.POSTED_AT: Job.posted_at,
        JobSortBy.TITLE: Job.title,
        JobSortBy.COMPANY_NAME: Job.company_name,
        JobSortBy.SALARY_MIN: Job.salary_min,
    }
    sort_column = sort_columns[filters.sort_by]
    ordered = (
        sort_column.asc().nulls_last()
        if filters.sort_order is SortOrder.ASC
        else sort_column.desc().nulls_last()
    )
    rows = session.execute(
        select(Job, Source)
        .join(Source, Source.id == Job.source_id)
        .where(*conditions)
        .order_by(ordered, Job.id.asc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return JobListResponse(
        data=[_summary(job, source) for job, source in rows],
        pagination=pagination_data(filters, total_items),
    )


@router.get(
    "/{jobId}",
    response_model=JobDetailResponse,
    responses={
        **ERROR_RESPONSES,
        404: {"model": ErrorResponse, "description": "Job was not found."},
    },
)
def get_job(
    job_id: Annotated[UUID, Path(alias="jobId")],
    session: DatabaseSession,
) -> JobDetailResponse:
    row = session.execute(
        select(Job, Source, RawJobSnapshot)
        .join(Source, Source.id == Job.source_id)
        .join(RawJobSnapshot, RawJobSnapshot.id == Job.current_snapshot_id)
        .where(
            Job.id == job_id,
            visible_source_condition(),
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404)
    job, source, snapshot = row
    summary = _summary(job, source)
    return JobDetailResponse(
        data=JobDetail(
            **summary.model_dump(),
            description_text=job.description_text,
            current_snapshot=SnapshotData(
                id=snapshot.id,
                source_url=snapshot.source_url,
                fetched_at=snapshot.fetched_at,
                http_status=snapshot.http_status,
                content_type=snapshot.content_type,
                parse_status=snapshot.parse_status,
            ),
        )
    )


@router.get(
    "/{jobId}/changes",
    response_model=JobChangeListResponse,
    responses={
        **ERROR_RESPONSES,
        404: {"model": ErrorResponse, "description": "Job was not found."},
    },
)
def list_job_changes(
    job_id: Annotated[UUID, Path(alias="jobId")],
    pagination: Annotated[PaginationQuery, Query()],
    session: DatabaseSession,
) -> JobChangeListResponse:
    if (
        session.scalar(
            select(Job.id)
            .join(Source, Source.id == Job.source_id)
            .where(
                Job.id == job_id,
                visible_source_condition(),
            )
        )
        is None
    ):
        raise HTTPException(status_code=404)
    total_items = (
        session.scalar(
            select(func.count()).select_from(JobChange).where(JobChange.job_id == job_id)
        )
        or 0
    )
    changes = session.scalars(
        select(JobChange)
        .where(JobChange.job_id == job_id)
        .order_by(JobChange.detected_at.desc(), JobChange.id.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    ).all()
    return JobChangeListResponse(
        data=[
            JobChangeData(
                id=change.id,
                job_id=change.job_id,
                crawl_run_id=change.crawl_run_id,
                change_type=change.change_type,
                field_name=change.field_name,
                old_value=change.old_value,
                new_value=change.new_value,
                from_snapshot_id=change.from_snapshot_id,
                to_snapshot_id=change.to_snapshot_id,
                detected_at=change.detected_at,
            )
            for change in changes
        ],
        pagination=pagination_data(pagination, total_items),
    )
