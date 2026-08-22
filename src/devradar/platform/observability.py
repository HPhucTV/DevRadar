"""Small structured event boundary with an explicit safe field allow-list."""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

LOGGER_NAME: Final = "devradar"
HANDLER_NAME: Final = "devradar-json-v1"
MAX_TEXT_FIELD_LENGTH: Final = 200
HTTP_METHODS: Final = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})

JsonScalar = str | int | float | bool | None

_EVENT_FIELDS: Final[dict[str, frozenset[str]]] = {
    "api_error": frozenset(
        {
            "request_id",
            "status_code",
            "error_code",
            "exception_type",
        }
    ),
    "crawl_run_summary": frozenset(
        {
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
            "items_reactivated",
            "items_failed",
            "error_code",
            "health_signal_code",
        }
    ),
    "http_request_completed": frozenset(
        {
            "request_id",
            "method",
            "route",
            "status_code",
            "duration_ms",
        }
    ),
    "job_observation_processed": frozenset(
        {
            "run_id",
            "source_id",
            "snapshot_id",
            "job_id",
            "outcome",
            "transaction_state",
        }
    ),
    "resume_profile_processed": frozenset(
        {
            "profile_id",
            "source_format",
            "extraction_status",
            "outcome",
        }
    ),
}


class JsonLogFormatter(logging.Formatter):
    """Serialize only fields produced by this module, never a free-form message."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "devradar_event", "invalid_event")
        raw_fields = getattr(record, "devradar_fields", {})
        fields = raw_fields if isinstance(raw_fields, dict) else {}
        document: dict[str, JsonScalar] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "event": event if isinstance(event, str) else "invalid_event",
        }
        document.update(fields)
        return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def configure_structured_logging() -> logging.Logger:
    """Install one JSON stderr handler for the DevRadar logger."""

    logger = logging.getLogger(LOGGER_NAME)
    if not any(handler.name == HANDLER_NAME for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.name = HANDLER_NAME
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.propagate = False
    return logger


def _validated_fields(event: str, fields: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
    allowed_fields = _EVENT_FIELDS.get(event)
    if allowed_fields is None:
        raise ValueError(f"unsupported observability event: {event}")
    unknown_fields = fields.keys() - allowed_fields
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ValueError(f"unsupported fields for {event}: {unknown}")
    for name, value in fields.items():
        if isinstance(value, str) and (
            len(value) > MAX_TEXT_FIELD_LENGTH or "\n" in value or "\r" in value
        ):
            raise ValueError(f"{name} must be a bounded single-line value")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    return fields


def _emit(event: str, *, level: int = logging.INFO, **fields: JsonScalar) -> None:
    safe_fields = _validated_fields(event, fields)
    configure_structured_logging().log(
        level,
        event,
        extra={"devradar_event": event, "devradar_fields": safe_fields},
    )


def record_http_request(
    *,
    request_id: str,
    method: str,
    route: str,
    status_code: int,
    duration_ms: float,
) -> None:
    _emit(
        "http_request_completed",
        request_id=request_id,
        method=method if method in HTTP_METHODS else "OTHER",
        route=route,
        status_code=status_code,
        duration_ms=round(duration_ms, 3),
    )


def record_api_error(
    *,
    request_id: str,
    status_code: int,
    error_code: str,
    exception_type: str,
) -> None:
    _emit(
        "api_error",
        level=logging.ERROR if status_code >= 500 else logging.WARNING,
        request_id=request_id,
        status_code=status_code,
        error_code=error_code,
        exception_type=exception_type,
    )


def record_job_observation(
    *,
    run_id: UUID,
    source_id: UUID,
    snapshot_id: UUID,
    job_id: UUID,
    outcome: str,
) -> None:
    _emit(
        "job_observation_processed",
        run_id=str(run_id),
        source_id=str(source_id),
        snapshot_id=str(snapshot_id),
        job_id=str(job_id),
        outcome=outcome,
        transaction_state="caller_owned_uncommitted",
    )


def record_resume_profile_processed(
    *,
    profile_id: UUID,
    source_format: str,
    extraction_status: str,
    outcome: str,
) -> None:
    _emit(
        "resume_profile_processed",
        profile_id=str(profile_id),
        source_format=source_format,
        extraction_status=extraction_status,
        outcome=outcome,
    )


def record_crawl_run_summary(
    *,
    run_id: UUID,
    source_id: UUID,
    status: str,
    coverage_status: str,
    duration_ms: float | None,
    pages_found: int,
    items_found: int,
    items_new: int,
    items_updated: int,
    items_missing: int,
    items_removed: int,
    items_reactivated: int,
    items_failed: int,
    error_code: str | None,
    health_signal_code: str | None,
) -> None:
    _emit(
        "crawl_run_summary",
        level=logging.ERROR if error_code is not None else logging.INFO,
        run_id=str(run_id),
        source_id=str(source_id),
        status=status,
        coverage_status=coverage_status,
        duration_ms=None if duration_ms is None else round(duration_ms, 3),
        pages_found=pages_found,
        items_found=items_found,
        items_new=items_new,
        items_updated=items_updated,
        items_missing=items_missing,
        items_removed=items_removed,
        items_reactivated=items_reactivated,
        items_failed=items_failed,
        error_code=error_code,
        health_signal_code=health_signal_code,
    )
