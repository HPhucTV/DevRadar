"""Read-only CrawlRun resources with safe counters and errors."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
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
from devradar.api.errors import ApiContractError
from devradar.auth.dependencies import require_operator
from devradar.automation.run_requests import RunRequestError, request_crawl_run
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceApprovalStatus,
)
from devradar.platform.database import get_database_session

router = APIRouter(prefix="/crawl-runs", tags=["crawl-runs"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]
OPERATOR_WRITE_ENABLED_ENV = "DEVRADAR_OPERATOR_WRITE_ENABLED"


def require_operator_write_enabled() -> None:
    if os.environ.get(OPERATOR_WRITE_ENABLED_ENV, "false").lower() != "true":
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "operator_write_disabled",
            "Operator write API is disabled for this deployment.",
        )


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
    items_reactivated: int
    items_failed: int


class CrawlRunError(ApiModel):
    code: str
    message: str


class CrawlRunData(ApiModel):
    id: UUID
    source_id: UUID
    trigger_type: CrawlTriggerType
    requested_at: datetime
    scheduled_for: datetime | None
    retry_of_run_id: UUID | None
    attempt_number: int
    status: CrawlRunStatus
    coverage_status: CoverageStatus
    started_at: datetime | None
    finished_at: datetime | None
    counts: CrawlRunCounts
    health_signal_code: str | None
    error: CrawlRunError | None


class CrawlRunCreate(ApiModel):
    source_id: UUID


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
        requested_at=crawl_run.requested_at,
        scheduled_for=crawl_run.scheduled_for,
        retry_of_run_id=crawl_run.retry_of_run_id,
        attempt_number=crawl_run.attempt_number,
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
            items_reactivated=crawl_run.items_reactivated,
            items_failed=crawl_run.items_failed,
        ),
        health_signal_code=crawl_run.health_signal_code,
        error=error,
    )


def _conditions(filters: CrawlRunQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        select(Source.id)
        .where(
            Source.id == CrawlRun.source_id,
            Source.approval_status == SourceApprovalStatus.APPROVED,
        )
        .exists()
    ]
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


@router.get(
    "",
    response_model=CrawlRunListResponse,
    responses=ERROR_RESPONSES,
    dependencies=[Depends(require_operator)],
)
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


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CrawlRunDetailResponse,
    dependencies=[Depends(require_operator_write_enabled), Depends(require_operator)],
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Operator write or source is blocked."},
        404: {"model": ErrorResponse, "description": "Source was not found."},
        409: {"model": ErrorResponse, "description": "Idempotency or active-run conflict."},
    },
)
def create_crawl_run(
    request: CrawlRunCreate,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
        ),
    ],
    session: DatabaseSession,
) -> CrawlRunDetailResponse:
    try:
        requested = request_crawl_run(
            session,
            source_id=request.source_id,
            idempotency_key=idempotency_key,
        )
    except RunRequestError as error:
        status_by_code = {
            "source_not_found": status.HTTP_404_NOT_FOUND,
            "source_not_approved": status.HTTP_403_FORBIDDEN,
            "idempotency_conflict": status.HTTP_409_CONFLICT,
            "source_run_active": status.HTTP_409_CONFLICT,
        }
        raise ApiContractError(
            status_by_code.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
            error.code,
            str(error),
        ) from None
    return CrawlRunDetailResponse(data=_data(requested.crawl_run))


@router.get(
    "/{runId}",
    response_model=CrawlRunDetailResponse,
    dependencies=[Depends(require_operator)],
    responses={
        **ERROR_RESPONSES,
        404: {"model": ErrorResponse, "description": "Crawl run was not found."},
    },
)
def get_crawl_run(
    run_id: Annotated[UUID, Path(alias="runId")],
    session: DatabaseSession,
) -> CrawlRunDetailResponse:
    crawl_run = session.scalar(
        select(CrawlRun)
        .join(Source, Source.id == CrawlRun.source_id)
        .where(
            CrawlRun.id == run_id,
            Source.approval_status == SourceApprovalStatus.APPROVED,
        )
    )
    if crawl_run is None:
        raise HTTPException(status_code=404)
    return CrawlRunDetailResponse(data=_data(crawl_run))
