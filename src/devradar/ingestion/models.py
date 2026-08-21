"""Persistence mappings owned by the ingestion module."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


def _enum_values(enum_class: type[PythonEnum]) -> list[str]:
    return [str(member.value) for member in enum_class]


class SourceApprovalStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    PAUSED = "paused"
    RETIRED = "retired"


class SourceHealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    QUARANTINED = "quarantined"


class CrawlTriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    RETRY = "retry"
    REPLAY = "replay"


class CrawlRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CoverageStatus(StrEnum):
    UNKNOWN = "unknown"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    INVALID = "invalid"
    FAILED = "failed"
    SKIPPED = "skipped"


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('candidate', 'approved', 'paused', 'retired')",
            name="ck_sources_approval_status",
        ),
        CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'unhealthy', 'quarantined')",
            name="ck_sources_health_status",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_sources_name_not_blank"),
        CheckConstraint("length(btrim(base_url)) > 0", name="ck_sources_base_url_not_blank"),
        CheckConstraint("length(btrim(adapter_key)) > 0", name="ck_sources_adapter_key_not_blank"),
        CheckConstraint(
            "jsonb_typeof(allowed_hosts) = 'array' AND jsonb_array_length(allowed_hosts) > 0",
            name="ck_sources_allowed_hosts_non_empty_array",
        ),
        CheckConstraint(
            "jsonb_typeof(rate_limit_policy) = 'object'",
            name="ck_sources_rate_limit_policy_object",
        ),
        CheckConstraint(
            "approval_status <> 'approved' OR "
            "(terms_reviewed_at IS NOT NULL AND robots_reviewed_at IS NOT NULL)",
            name="ck_sources_approved_has_policy_reviews",
        ),
        UniqueConstraint("name", name="uq_sources_name"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(2048))
    adapter_key: Mapped[str] = mapped_column(String(100))
    approval_status: Mapped[SourceApprovalStatus] = mapped_column(
        Enum(
            SourceApprovalStatus,
            name="source_approval_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=SourceApprovalStatus.CANDIDATE,
        server_default=text("'candidate'"),
    )
    health_status: Mapped[SourceHealthStatus] = mapped_column(
        Enum(
            SourceHealthStatus,
            name="source_health_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=SourceHealthStatus.UNKNOWN,
        server_default=text("'unknown'"),
    )
    crawl_frequency: Mapped[str | None] = mapped_column(String(100))
    rate_limit_policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    allowed_hosts: Mapped[list[str]] = mapped_column(JSONB)
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    robots_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('manual', 'scheduled', 'retry', 'replay')",
            name="ck_crawl_runs_trigger_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_crawl_runs_status",
        ),
        CheckConstraint(
            "coverage_status IN ('unknown', 'complete', 'incomplete')",
            name="ck_crawl_runs_coverage_status",
        ),
        CheckConstraint(
            "pages_found >= 0 AND items_found >= 0 AND items_new >= 0 "
            "AND items_updated >= 0 AND items_missing >= 0 AND items_removed >= 0 "
            "AND items_failed >= 0",
            name="ck_crawl_runs_counters_non_negative",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'partial', 'failed', 'cancelled') "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_crawl_runs_status_time_boundary",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_crawl_runs_finished_after_started",
        ),
        UniqueConstraint("id", "source_id", name="uq_crawl_runs_id_source_id"),
        Index("ix_crawl_runs_source_started_at", "source_id", "started_at"),
        Index("ix_crawl_runs_source_status", "source_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT", name="fk_crawl_runs_source_id_sources"),
    )
    trigger_type: Mapped[CrawlTriggerType] = mapped_column(
        Enum(
            CrawlTriggerType,
            name="crawl_trigger_type",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        )
    )
    status: Mapped[CrawlRunStatus] = mapped_column(
        Enum(
            CrawlRunStatus,
            name="crawl_run_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=CrawlRunStatus.PENDING,
        server_default=text("'pending'"),
    )
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        Enum(
            CoverageStatus,
            name="coverage_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=CoverageStatus.UNKNOWN,
        server_default=text("'unknown'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages_found: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    items_found: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    items_new: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    items_updated: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    items_missing: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    items_removed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    items_failed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    adapter_version: Mapped[str] = mapped_column(String(100))
    config_version: Mapped[str] = mapped_column(String(100))


class RawJobSnapshot(Base):
    __tablename__ = "raw_job_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ("crawl_run_id", "source_id"),
            ("crawl_runs.id", "crawl_runs.source_id"),
            name="fk_raw_job_snapshots_run_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "http_status BETWEEN 100 AND 599",
            name="ck_raw_job_snapshots_http_status",
        ),
        CheckConstraint(
            "parse_status IN ('pending', 'parsed', 'invalid', 'failed', 'skipped')",
            name="ck_raw_job_snapshots_parse_status",
        ),
        CheckConstraint(
            "raw_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_raw_job_snapshots_content_hash",
        ),
        CheckConstraint(
            "length(btrim(source_url)) > 0",
            name="ck_raw_job_snapshots_source_url_not_blank",
        ),
        UniqueConstraint("id", "source_id", name="uq_raw_job_snapshots_id_source_id"),
        Index("ix_raw_job_snapshots_source_fetched_at", "source_id", "fetched_at"),
        Index("ix_raw_job_snapshots_run_id", "crawl_run_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    crawl_run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "sources.id", ondelete="RESTRICT", name="fk_raw_job_snapshots_source_id_sources"
        ),
    )
    source_url: Mapped[str] = mapped_column(String(2048))
    external_id: Mapped[str | None] = mapped_column(String(500))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    raw_content_hash: Mapped[str] = mapped_column(String(64))
    raw_content: Mapped[str] = mapped_column(Text, deferred=True)
    parse_status: Mapped[ParseStatus] = mapped_column(
        Enum(
            ParseStatus,
            name="parse_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=ParseStatus.PENDING,
        server_default=text("'pending'"),
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
