"""Persistence mappings owned by the catalog module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
    Numeric,
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


class JobStatus(StrEnum):
    ACTIVE = "active"
    MISSING = "missing"
    REMOVED = "removed"


class JobLevel(StrEnum):
    INTERN = "intern"
    FRESHER = "fresher"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    MANAGER = "manager"


class JobChangeType(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    MISSING = "missing"
    REMOVED = "removed"
    REACTIVATED = "reactivated"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ("current_snapshot_id", "source_id"),
            ("raw_job_snapshots.id", "raw_job_snapshots.source_id"),
            name="fk_jobs_current_snapshot_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(canonical_url)) > 0", name="ck_jobs_url_not_blank"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_jobs_title_not_blank"),
        CheckConstraint(
            "length(btrim(company_name)) > 0",
            name="ck_jobs_company_name_not_blank",
        ),
        CheckConstraint(
            "jsonb_typeof(levels) = 'array' AND "
            'levels <@ \'["intern", "fresher", "junior", "mid", '
            '"senior", "lead", "manager"]\'::jsonb',
            name="ck_jobs_levels_allowed_values",
        ),
        CheckConstraint(
            "status IN ('active', 'missing', 'removed')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="ck_jobs_salary_range",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_min >= 0",
            name="ck_jobs_salary_min_non_negative",
        ),
        CheckConstraint(
            "salary_max IS NULL OR salary_max >= 0",
            name="ck_jobs_salary_max_non_negative",
        ),
        CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
            name="ck_jobs_currency_iso_4217_shape",
        ),
        CheckConstraint(
            "experience_min IS NULL OR experience_min >= 0",
            name="ck_jobs_experience_min_non_negative",
        ),
        CheckConstraint(
            "experience_max IS NULL OR experience_max >= 0",
            name="ck_jobs_experience_max_non_negative",
        ),
        CheckConstraint(
            "experience_min IS NULL OR experience_max IS NULL OR experience_min <= experience_max",
            name="ck_jobs_experience_range",
        ),
        CheckConstraint("last_seen_at >= first_seen_at", name="ck_jobs_seen_time_order"),
        CheckConstraint(
            "(status = 'removed' AND removed_at IS NOT NULL) OR "
            "(status <> 'removed' AND removed_at IS NULL)",
            name="ck_jobs_removed_at_matches_status",
        ),
        CheckConstraint(
            "consecutive_missing_count >= 0",
            name="ck_jobs_missing_count_non_negative",
        ),
        CheckConstraint(
            "job_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_jobs_content_hash",
        ),
        UniqueConstraint("source_id", "canonical_url", name="uq_jobs_source_canonical_url"),
        Index(
            "uq_jobs_source_external_id",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_jobs_source_status_last_seen", "source_id", "status", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT", name="fk_jobs_source_id_sources"),
    )
    external_id: Mapped[str | None] = mapped_column(String(500))
    canonical_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(500))
    company_name: Mapped[str] = mapped_column(String(300))
    description_text: Mapped[str | None] = mapped_column(Text, deferred=True)
    location_raw: Mapped[str | None] = mapped_column(String(500))
    location_city: Mapped[str | None] = mapped_column(String(200))
    location_province: Mapped[str | None] = mapped_column(String(200))
    work_mode: Mapped[str | None] = mapped_column(String(32))
    salary_raw: Mapped[str | None] = mapped_column(String(500))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(32))
    level_raw: Mapped[str | None] = mapped_column(String(500))
    levels: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    experience_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    experience_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=JobStatus.ACTIVE,
        server_default=text("'active'"),
    )
    consecutive_missing_count: Mapped[int] = mapped_column(
        default=0,
        server_default=text("0"),
    )
    current_snapshot_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    job_content_hash: Mapped[str] = mapped_column(String(64))


class JobChange(Base):
    __tablename__ = "job_changes"
    __table_args__ = (
        CheckConstraint(
            "change_type IN ('created', 'updated', 'missing', 'removed', 'reactivated')",
            name="ck_job_changes_change_type",
        ),
        CheckConstraint(
            "length(btrim(field_name)) > 0",
            name="ck_job_changes_field_name_not_blank",
        ),
        CheckConstraint(
            "from_snapshot_id IS NULL OR to_snapshot_id IS NULL "
            "OR from_snapshot_id <> to_snapshot_id",
            name="ck_job_changes_distinct_snapshots",
        ),
        UniqueConstraint(
            "job_id",
            "crawl_run_id",
            "change_type",
            "field_name",
            name="uq_job_changes_run_type_field",
        ),
        Index("ix_job_changes_job_detected_at", "job_id", "detected_at"),
        Index("ix_job_changes_crawl_run_id", "crawl_run_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT", name="fk_job_changes_job_id_jobs"),
    )
    crawl_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crawl_runs.id",
            ondelete="RESTRICT",
            name="fk_job_changes_crawl_run_id_crawl_runs",
        ),
    )
    from_snapshot_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "raw_job_snapshots.id",
            ondelete="RESTRICT",
            name="fk_job_changes_from_snapshot_id_raw_job_snapshots",
        ),
    )
    to_snapshot_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "raw_job_snapshots.id",
            ondelete="RESTRICT",
            name="fk_job_changes_to_snapshot_id_raw_job_snapshots",
        ),
    )
    field_name: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[Any | None] = mapped_column(JSONB)
    new_value: Mapped[Any | None] = mapped_column(JSONB)
    change_type: Mapped[JobChangeType] = mapped_column(
        Enum(
            JobChangeType,
            name="job_change_type",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        )
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
