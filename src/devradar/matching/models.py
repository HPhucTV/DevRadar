"""Persistence mappings owned by the matching module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, text
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


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        CheckConstraint(
            "overall_score >= 0 AND overall_score <= 1 AND "
            "(skill_score IS NULL OR (skill_score >= 0 AND skill_score <= 1)) AND "
            "(semantic_score IS NULL OR (semantic_score >= 0 AND semantic_score <= 1)) AND "
            "(experience_score IS NULL OR (experience_score >= 0 AND experience_score <= 1)) AND "
            "(location_score IS NULL OR (location_score >= 0 AND location_score <= 1)) AND "
            "(role_score IS NULL OR (role_score >= 0 AND role_score <= 1))",
            name="ck_job_matches_score_range",
        ),
        CheckConstraint(
            "evidence_coverage >= 0 AND evidence_coverage <= 1",
            name="ck_job_matches_evidence_coverage_range",
        ),
        CheckConstraint(
            "profile_content_hash ~ '^[0-9a-f]{64}$' AND job_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_job_matches_hash_shape",
        ),
        CheckConstraint(
            "length(btrim(profile_parser_version)) > 0 AND "
            "length(btrim(scoring_version)) > 0 AND "
            "length(btrim(profile_embedding_input_version)) > 0 AND "
            "length(btrim(job_embedding_input_schema_version)) > 0 AND "
            "embedding_provider = 'local_fastembed' AND "
            "embedding_revision ~ '^[0-9a-f]{40}$' AND embedding_dimension = 384",
            name="ck_job_matches_embedding_identity",
        ),
        CheckConstraint(
            "jsonb_typeof(matched_skills) = 'array' AND "
            "jsonb_typeof(missing_skills) = 'array' AND "
            "jsonb_typeof(explanation) = 'array' AND "
            "jsonb_array_length(matched_skills) <= 50 AND "
            "jsonb_array_length(missing_skills) <= 50 AND "
            "jsonb_array_length(explanation) <= 10",
            name="ck_job_matches_structured_bounds",
        ),
        Index(
            "uq_job_matches_logical_key",
            "resume_profile_id",
            "job_id",
            "profile_content_hash",
            "profile_parser_version",
            "job_content_hash",
            "scoring_version",
            "profile_embedding_input_version",
            "job_embedding_input_schema_version",
            "embedding_provider",
            "embedding_model",
            "embedding_revision",
            "embedding_dimension",
            unique=True,
        ),
        Index(
            "ix_job_matches_profile_score_job",
            "resume_profile_id",
            text("overall_score DESC"),
            "job_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    resume_profile_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("resume_profiles.id", ondelete="CASCADE", name="fk_job_matches_profile"),
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE", name="fk_job_matches_job"),
    )
    profile_content_hash: Mapped[str] = mapped_column(String(64))
    profile_parser_version: Mapped[str] = mapped_column(String(100))
    job_content_hash: Mapped[str] = mapped_column(String(64))
    scoring_version: Mapped[str] = mapped_column(String(100))
    profile_embedding_input_version: Mapped[str] = mapped_column(String(100))
    job_embedding_input_schema_version: Mapped[str] = mapped_column(String(100))
    overall_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    evidence_coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    skill_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    semantic_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    experience_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    location_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    role_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    matched_skills: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    missing_skills: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    explanation: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    embedding_provider: Mapped[str] = mapped_column(String(50))
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_revision: Mapped[str] = mapped_column(String(40))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
