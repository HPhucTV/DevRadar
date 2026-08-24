"""Read-only sanitized Source resources for V1."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
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
from devradar.ingestion.models import Source, SourceApprovalStatus, SourceHealthStatus
from devradar.platform.database import get_database_session
from devradar.source_recipes.visibility import visible_source_condition

router = APIRouter(prefix="/sources", tags=["sources"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class SourceSummary(ApiModel):
    id: UUID
    name: str
    base_url: str
    adapter_key: str
    approval_status: SourceApprovalStatus
    health_status: SourceHealthStatus
    consecutive_failures: int
    health_reason_code: str | None
    last_crawled_at: datetime | None
    last_success_at: datetime | None


class SourceDetail(SourceSummary):
    crawl_frequency: str | None
    baseline_items_found: int | None
    quarantined_at: datetime | None
    terms_reviewed_at: datetime | None
    robots_reviewed_at: datetime | None


SourceListResponse = ListResponse[SourceSummary]
SourceDetailResponse = DataResponse[SourceDetail]


def _summary(source: Source) -> SourceSummary:
    return SourceSummary(
        id=source.id,
        name=source.name,
        base_url=source.base_url,
        adapter_key=source.adapter_key,
        approval_status=source.approval_status,
        health_status=source.health_status,
        consecutive_failures=source.consecutive_failures,
        health_reason_code=source.health_reason_code,
        last_crawled_at=source.last_crawled_at,
        last_success_at=source.last_success_at,
    )


@router.get("", response_model=SourceListResponse, responses=ERROR_RESPONSES)
def list_sources(
    pagination: Annotated[PaginationQuery, Query()],
    session: DatabaseSession,
) -> SourceListResponse:
    approved = visible_source_condition()
    total_items = session.scalar(select(func.count()).select_from(Source).where(approved)) or 0
    sources = session.scalars(
        select(Source)
        .where(approved)
        .order_by(Source.name.asc(), Source.id.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    ).all()
    return SourceListResponse(
        data=[_summary(source) for source in sources],
        pagination=pagination_data(pagination, total_items),
    )


@router.get(
    "/{sourceId}",
    response_model=SourceDetailResponse,
    responses={
        **ERROR_RESPONSES,
        404: {"model": ErrorResponse, "description": "Source was not found."},
    },
)
def get_source(
    source_id: Annotated[UUID, Path(alias="sourceId")],
    session: DatabaseSession,
) -> SourceDetailResponse:
    source = session.scalar(
        select(Source).where(
            Source.id == source_id,
            visible_source_condition(),
        )
    )
    if source is None:
        raise HTTPException(status_code=404)
    summary = _summary(source)
    return SourceDetailResponse(
        data=SourceDetail(
            **summary.model_dump(),
            crawl_frequency=source.crawl_frequency,
            baseline_items_found=source.baseline_items_found,
            quarantined_at=source.quarantined_at,
            terms_reviewed_at=source.terms_reviewed_at,
            robots_reviewed_at=source.robots_reviewed_at,
        )
    )
