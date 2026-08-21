from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from devradar.main import app
from devradar.platform.database import get_database_session
from devradar.platform.observability import (
    HANDLER_NAME,
    LOGGER_NAME,
    JsonLogFormatter,
    configure_structured_logging,
    record_crawl_run_summary,
    record_job_observation,
)


@contextmanager
def _captured_events() -> Iterator[StringIO]:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)


def _events(stream: StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def _unused_session() -> Iterator[Session]:
    with Session() as session:
        yield session


def test_http_and_error_events_use_route_template_without_request_payload() -> None:
    marker = "query-secret-must-not-leak"
    path_marker = "path-secret-must-not-leak"
    app.dependency_overrides[get_database_session] = _unused_session
    try:
        with _captured_events() as stream, TestClient(app) as client:
            response = client.get(
                "/api/v1/jobs",
                params={"unknownFilter": marker},
                headers={"Authorization": f"Bearer {marker}"},
            )
            path_response = client.get(f"/api/v1/jobs/{path_marker}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert path_response.status_code == 422
    events = _events(stream)
    request_events = [event for event in events if event["event"] == "http_request_completed"]
    request_event = next(event for event in request_events if event["route"] == "/api/v1/jobs")
    path_request_event = next(
        event for event in request_events if event["route"] == "/api/v1/jobs/{jobId}"
    )
    error_event = next(event for event in events if event["event"] == "api_error")
    assert request_event["request_id"] == response.headers["X-Request-ID"]
    assert request_event["method"] == "GET"
    assert request_event["route"] == "/api/v1/jobs"
    assert request_event["status_code"] == 422
    assert request_event["duration_ms"] >= 0
    assert path_request_event["request_id"] == path_response.headers["X-Request-ID"]
    assert error_event["request_id"] == request_event["request_id"]
    assert error_event["error_code"] == "validation_error"
    assert error_event["exception_type"] == "RequestValidationError"
    assert marker not in stream.getvalue()
    assert path_marker not in stream.getvalue()
    assert "authorization" not in stream.getvalue().lower()
    assert "unknownFilter" not in stream.getvalue()


def test_domain_metric_events_are_bounded_and_correlation_only() -> None:
    run_id = UUID(int=1)
    source_id = UUID(int=2)
    snapshot_id = UUID(int=3)
    job_id = UUID(int=4)
    with _captured_events() as stream:
        record_job_observation(
            run_id=run_id,
            source_id=source_id,
            snapshot_id=snapshot_id,
            job_id=job_id,
            outcome="created",
        )
        record_crawl_run_summary(
            run_id=run_id,
            source_id=source_id,
            status="failed",
            coverage_status="incomplete",
            duration_ms=123.4567,
            pages_found=2,
            items_found=3,
            items_new=1,
            items_updated=1,
            items_missing=0,
            items_removed=0,
            items_failed=1,
            error_code="source_timeout",
        )

    job_event, run_event = _events(stream)
    assert job_event["transaction_state"] == "caller_owned_uncommitted"
    assert job_event["job_id"] == str(job_id)
    assert run_event["level"] == "error"
    assert run_event["items_found"] == 3
    assert run_event["items_missing"] == 0
    assert run_event["error_code"] == "source_timeout"
    assert set(run_event) == {
        "timestamp",
        "level",
        "event",
        "run_id",
        "source_id",
        "status",
        "coverage_status",
        "duration_ms",
        "pages_found",
        "items_found",
        "items_new",
        "items_updated",
        "items_missing",
        "items_removed",
        "items_failed",
        "error_code",
    }

    with pytest.raises(ValueError, match="bounded single-line"):
        record_job_observation(
            run_id=run_id,
            source_id=source_id,
            snapshot_id=snapshot_id,
            job_id=job_id,
            outcome="created\nraw-job-description",
        )


def test_structured_logger_configuration_is_idempotent() -> None:
    logger = configure_structured_logging()
    configure_structured_logging()

    assert sum(handler.name == HANDLER_NAME for handler in logger.handlers) == 1
    assert logger.propagate is False
