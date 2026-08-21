"""Read-only CrawlRun resources with safe counters and errors."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import model_validator
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from devradar.api.common import (
    ERROR_RESPONSES,
    ApiModel,
    DataResponse,
    ErrorResponse,
    ListResponse,
    PaginationQuery,
    pagination_data,
)
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
)
from devradar.platform.database import get_database_session

router = APIRouter(prefix="/crawl-runs", tags=["crawl-runs"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class CrawlRunQuery(PaginationQuery):
    source_id: UUID | None = None
    status: CrawlRunStatus | None = None
    coverage_status: CoverageStatus | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None

    @model_validator(mode="after")
    def validate_time_window(self) -> Self:
        for value in (self.started_after, self.started_before):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("started timestamps must include a UTC offset")
        if (
            self.started_after is not None
            and self.started_before is not None
            and self.started_after > self.started_before
        ):
            raise ValueError("startedAfter must not exceed startedBefore")
        return self


class CrawlRunCounts(ApiModel):
    items_found: int
    items_new: int
    items_updated: int
    items_missing: int
    items_removed: int
    items_failed: int


class CrawlRunError(ApiModel):
    code: str
    message: str


class CrawlRunData(ApiModel):
    id: UUID
    source_id: UUID
    trigger_type: CrawlTriggerType
    status: CrawlRunStatus
    coverage_status: CoverageStatus
    started_at: datetime | None
    finished_at: datetime | None
    counts: CrawlRunCounts
    error: CrawlRunError | None


CrawlRunListResponse = ListResponse[CrawlRunData]
CrawlRunDetailResponse = DataResponse[CrawlRunData]


def _data(crawl_run: CrawlRun) -> CrawlRunData:
    error = None
    if crawl_run.error_code is not None:
        error = CrawlRunError(
            code=crawl_run.error_code,
            message="Crawl run failed safely.",
        )
    return CrawlRunData(
        id=crawl_run.id,
        source_id=crawl_run.source_id,
        trigger_type=crawl_run.trigger_type,
        status=crawl_run.status,
        coverage_status=crawl_run.coverage_status,
        started_at=crawl_run.started_at,
        finished_at=crawl_run.finished_at,
        counts=CrawlRunCounts(
            items_found=crawl_run.items_found,
            items_new=crawl_run.items_new,
            items_updated=crawl_run.items_updated,
            items_missing=crawl_run.items_missing,
            items_removed=crawl_run.items_removed,
            items_failed=crawl_run.items_failed,
        ),
        error=error,
    )


def _conditions(filters: CrawlRunQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.source_id is not None:
        conditions.append(CrawlRun.source_id == filters.source_id)
    if filters.status is not None:
        conditions.append(CrawlRun.status == filters.status)
    if filters.coverage_status is not None:
        conditions.append(CrawlRun.coverage_status == filters.coverage_status)
    if filters.started_after is not None:
        conditions.append(CrawlRun.started_at >= filters.started_after)
    if filters.started_before is not None:
        conditions.append(CrawlRun.started_at <= filters.started_before)
    return conditions


@router.get("", response_model=CrawlRunListResponse, responses=ERROR_RESPONSES)
def list_crawl_runs(
    filters: Annotated[CrawlRunQuery, Query()],
    session: DatabaseSession,
) -> CrawlRunListResponse:
    conditions = _conditions(filters)
    total_items = session.scalar(select(func.count()).select_from(CrawlRun).where(*conditions)) or 0
    crawl_runs = session.scalars(
        select(CrawlRun)
        .where(*conditions)
        .order_by(CrawlRun.started_at.desc().nulls_last(), CrawlRun.id.asc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return CrawlRunListResponse(
        data=[_data(crawl_run) for crawl_run in crawl_runs],
        pagination=pagination_data(filters, total_items),
    )


@router.get(
    "/{runId}",
    response_model=CrawlRunDetailResponse,
    responses={
        **ERROR_RESPONSES,
        404: {"model": ErrorResponse, "description": "Crawl run was not found."},
    },
)
def get_crawl_run(
    run_id: Annotated[UUID, Path(alias="runId")],
    session: DatabaseSession,
) -> CrawlRunDetailResponse:
    crawl_run = session.get(CrawlRun, run_id)
    if crawl_run is None:
        raise HTTPException(status_code=404)
    return CrawlRunDetailResponse(data=_data(crawl_run))
