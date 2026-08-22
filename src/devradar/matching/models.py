"""Persistence mappings owned by the matching module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


class ResumeProfile(Base):
    __tablename__ = "resume_profiles"
    __table_args__ = (
        CheckConstraint(
            "owner_hash ~ '^[0-9a-f]{64}$'",
            name="ck_resume_profiles_owner_hash",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_resume_profiles_content_hash",
        ),
        CheckConstraint(
            "length(btrim(file_name_sanitized)) > 0",
            name="ck_resume_profiles_filename_not_blank",
        ),
        CheckConstraint(
            "source_format IN ('pdf', 'docx')",
            name="ck_resume_profiles_source_format",
        ),
        CheckConstraint(
            "extraction_status IN ('accepted', 'needs_review')",
            name="ck_resume_profiles_extraction_status",
        ),
        CheckConstraint(
            "retention_mode = 'ephemeral'",
            name="ck_resume_profiles_retention_mode",
        ),
        CheckConstraint(
            "jsonb_typeof(skills) = 'array' AND "
            "jsonb_typeof(roles) = 'array' AND "
            "jsonb_typeof(locations) = 'array'",
            name="ck_resume_profiles_structured_arrays",
        ),
        CheckConstraint(
            "jsonb_array_length(skills) <= 50 AND "
            "jsonb_array_length(roles) <= 10 AND "
            "jsonb_array_length(locations) <= 10",
            name="ck_resume_profiles_structured_bounds",
        ),
        CheckConstraint(
            "experience_years IS NULL OR (experience_years >= 0 AND experience_years <= 60)",
            name="ck_resume_profiles_experience_years",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_resume_profiles_expires_after_creation",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at",
            name="ck_resume_profiles_deleted_after_creation",
        ),
        Index(
            "uq_resume_profiles_active_replay",
            "owner_hash",
            "content_hash",
            "parser_version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_resume_profiles_owner_expiry",
            "owner_hash",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    file_name_sanitized: Mapped[str] = mapped_column(String(255))
    source_format: Mapped[str] = mapped_column(String(8))
    parser_version: Mapped[str] = mapped_column(String(100))
    extraction_status: Mapped[str] = mapped_column(String(16))
    skills: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    roles: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    locations: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    experience_years: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    retention_mode: Mapped[str] = mapped_column(
        String(16),
        default="ephemeral",
        server_default=text("'ephemeral'"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
