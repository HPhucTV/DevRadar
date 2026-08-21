"""Stable sanitized error envelope for every HTTP failure."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from devradar.api.common import ErrorData, ErrorDetail, ErrorResponse
from devradar.platform.observability import record_api_error, record_http_request


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else uuid4().hex


def _route_template(request: Request) -> str:
    if request.scope.get("endpoint") is None:
        return "unmatched"
    route = request.scope.get("path", "unmatched")
    if not isinstance(route, str):
        return "unmatched"
    for name, value in request.path_params.items():
        route = route.replace(str(value), f"{{{name}}}")
    return route


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    exception_type = getattr(request.state, "exception_type", "HttpError")
    record_api_error(
        request_id=request_id,
        status_code=status_code,
        error_code=code,
        exception_type=(exception_type if isinstance(exception_type, str) else "UnknownException"),
    )
    body = ErrorResponse(
        error=ErrorData(
            code=code,
            message=message,
            details=details,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True, exclude_none=True),
        headers={"X-Request-ID": request_id},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = uuid4().hex
        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            record_http_request(
                request_id=request.state.request_id,
                method=request.method,
                route=_route_template(request),
                status_code=status_code,
                duration_ms=(perf_counter() - started_at) * 1000,
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        request.state.exception_type = type(error).__name__
        details = []
        for item in error.errors()[:20]:
            location = item.get("loc", ())
            field_parts = [str(part) for part in location[1:]]
            field = ".".join(field_parts) or "request"
            reason = str(item.get("type", "invalid_value")).replace(".", "_")
            details.append(ErrorDetail(field=field[:200], reason=reason[:100]))
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request không hợp lệ.",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        request.state.exception_type = type(error).__name__
        if error.status_code == 404:
            return _error_response(
                request,
                status_code=404,
                code="not_found",
                message="Resource không tồn tại.",
            )
        return _error_response(
            request,
            status_code=error.status_code,
            code="http_error",
            message="HTTP request không thể hoàn tất.",
        )

    @app.exception_handler(OperationalError)
    async def database_unavailable_handler(
        request: Request,
        error: OperationalError,
    ) -> JSONResponse:
        request.state.exception_type = type(error).__name__
        del error
        return _error_response(
            request,
            status_code=503,
            code="database_unavailable",
            message="Database tạm thời không sẵn sàng.",
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, error: Exception) -> JSONResponse:
        request.state.exception_type = type(error).__name__
        del error
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Lỗi nội bộ đã được ghi nhận.",
        )
