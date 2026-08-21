"""Idempotent local-operator CrawlRun request queue."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceApprovalStatus,
)
from devradar.ingestion.source_registry import V1_SOURCE_CONFIGS, SourceConfig

LOCAL_OPERATOR_PRINCIPAL = "local-operator"
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class RunRequestError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code


@dataclass(frozen=True, slots=True)
class RequestedRun:
    crawl_run: CrawlRun
    reused: bool


def _request_hash(source_id: UUID) -> str:
    payload = json.dumps(
        {"sourceId": str(source_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(payload).hexdigest()


def _trigger_key(idempotency_key: str) -> str:
    return f"api:{sha256(idempotency_key.encode()).hexdigest()}"


def _matching_config(source: Source) -> SourceConfig | None:
    return next(
        (
            config
            for config in V1_SOURCE_CONFIGS
            if config.name == source.name
            and config.base_url == source.base_url
            and config.adapter_key == source.adapter_key
        ),
        None,
    )


def _existing_request(session: Session, trigger_key: str) -> CrawlRun | None:
    return session.scalar(
        select(CrawlRun).where(
            CrawlRun.requested_by == LOCAL_OPERATOR_PRINCIPAL,
            CrawlRun.trigger_key == trigger_key,
        )
    )


def _resolve_existing(
    existing: CrawlRun,
    *,
    request_hash: str,
) -> RequestedRun:
    if existing.request_hash != request_hash:
        raise RunRequestError(
            "idempotency_conflict",
            "Idempotency key was already used for a different request.",
        )
    return RequestedRun(existing, reused=True)


def request_crawl_run(
    session: Session,
    *,
    source_id: UUID,
    idempotency_key: str,
    requested_at: datetime | None = None,
) -> RequestedRun:
    """Create one pending run or return the matching prior request."""

    if session.in_transaction():
        raise RunRequestError(
            "transaction_already_active",
            "Run request requires a fresh transaction boundary.",
        )
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise RunRequestError(
            "invalid_idempotency_key",
            "Idempotency key must be 8..128 safe ASCII characters.",
        )
    now = requested_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise RunRequestError("invalid_request_time", "Requested time must include a UTC offset.")
    trigger_key = _trigger_key(idempotency_key)
    request_hash = _request_hash(source_id)

    existing = _existing_request(session, trigger_key)
    if existing is not None:
        result = _resolve_existing(existing, request_hash=request_hash)
        session.rollback()
        return result

    source = session.get(Source, source_id, with_for_update=True)
    if source is None:
        session.rollback()
        raise RunRequestError("source_not_found", "Source was not found.")
    config = _matching_config(source)
    if source.approval_status is not SourceApprovalStatus.APPROVED or config is None:
        session.rollback()
        raise RunRequestError(
            "source_not_approved",
            "Source is not an approved active registry entry.",
        )
    active = session.scalar(
        select(CrawlRun).where(
            CrawlRun.source_id == source_id,
            CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
        )
    )
    if active is not None:
        session.rollback()
        raise RunRequestError(
            "source_run_active",
            "Source already has a pending or running crawl run.",
        )

    crawl_run = CrawlRun(
        source_id=source_id,
        trigger_type=CrawlTriggerType.MANUAL,
        trigger_key=trigger_key,
        requested_at=now,
        requested_by=LOCAL_OPERATOR_PRINCIPAL,
        request_hash=request_hash,
        status=CrawlRunStatus.PENDING,
        coverage_status=CoverageStatus.UNKNOWN,
        adapter_version="pending",
        config_version=config.config_version,
    )
    session.add(crawl_run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _existing_request(session, trigger_key)
        if existing is not None:
            result = _resolve_existing(existing, request_hash=request_hash)
            session.rollback()
            return result
        active = session.scalar(
            select(CrawlRun).where(
                CrawlRun.source_id == source_id,
                CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
            )
        )
        session.rollback()
        if active is not None:
            raise RunRequestError(
                "source_run_active",
                "Source already has a pending or running crawl run.",
            ) from None
        raise
    return RequestedRun(crawl_run, reused=False)
