"""Shared public API envelopes and bounded pagination primitives."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class PaginationQuery(ApiModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginationData(ApiModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class DataResponse[DataT](ApiModel):
    data: DataT


class ListResponse[DataT](ApiModel):
    data: list[DataT]
    pagination: PaginationData


class ErrorDetail(ApiModel):
    field: str
    reason: str


class ErrorData(ApiModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None
    request_id: str


class ErrorResponse(ApiModel):
    error: ErrorData


ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ErrorResponse, "description": "Request validation failed."},
    500: {"model": ErrorResponse, "description": "Internal error, sanitized."},
    503: {"model": ErrorResponse, "description": "Database temporarily unavailable."},
}


def pagination_data(query: PaginationQuery, total_items: int) -> PaginationData:
    return PaginationData(
        page=query.page,
        page_size=query.page_size,
        total_items=total_items,
        total_pages=math.ceil(total_items / query.page_size) if total_items else 0,
    )
