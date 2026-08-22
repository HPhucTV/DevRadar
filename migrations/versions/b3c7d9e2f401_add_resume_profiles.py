"""Add short-lived owner-scoped resume profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3c7d9e2f401"
down_revision: str | Sequence[str] | None = "a1d4e7f9b203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_name_sanitized", sa.String(length=255), nullable=False),
        sa.Column("source_format", sa.String(length=8), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("extraction_status", sa.String(length=16), nullable=False),
        sa.Column(
            "skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "locations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("experience_years", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "retention_mode",
            sa.String(length=16),
            server_default=sa.text("'ephemeral'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "owner_hash ~ '^[0-9a-f]{64}$'",
            name="ck_resume_profiles_owner_hash",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_resume_profiles_content_hash",
        ),
        sa.CheckConstraint(
            "length(btrim(file_name_sanitized)) > 0",
            name="ck_resume_profiles_filename_not_blank",
        ),
        sa.CheckConstraint(
            "source_format IN ('pdf', 'docx')",
            name="ck_resume_profiles_source_format",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('accepted', 'needs_review')",
            name="ck_resume_profiles_extraction_status",
        ),
        sa.CheckConstraint(
            "retention_mode = 'ephemeral'",
            name="ck_resume_profiles_retention_mode",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(skills) = 'array' AND "
            "jsonb_typeof(roles) = 'array' AND "
            "jsonb_typeof(locations) = 'array'",
            name="ck_resume_profiles_structured_arrays",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(skills) <= 50 AND "
            "jsonb_array_length(roles) <= 10 AND "
            "jsonb_array_length(locations) <= 10",
            name="ck_resume_profiles_structured_bounds",
        ),
        sa.CheckConstraint(
            "experience_years IS NULL OR (experience_years >= 0 AND experience_years <= 60)",
            name="ck_resume_profiles_experience_years",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_resume_profiles_expires_after_creation",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at",
            name="ck_resume_profiles_deleted_after_creation",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_resume_profiles_active_replay",
        "resume_profiles",
        ["owner_hash", "content_hash", "parser_version"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_resume_profiles_owner_expiry",
        "resume_profiles",
        ["owner_hash", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_resume_profiles_owner_expiry", table_name="resume_profiles")
    op.drop_index("uq_resume_profiles_active_replay", table_name="resume_profiles")
    op.drop_table("resume_profiles")
