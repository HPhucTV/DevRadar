"""create v1 core schema

Revision ID: ec0ad1a5bfd6
Revises:
Create Date: 2026-08-21 17:42:27.300810

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ec0ad1a5bfd6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("adapter_key", sa.String(length=100), nullable=False),
        sa.Column(
            "approval_status",
            sa.Enum(
                "candidate",
                "approved",
                "paused",
                "retired",
                name="source_approval_status",
                native_enum=False,
                length=16,
            ),
            server_default=sa.text("'candidate'"),
            nullable=False,
        ),
        sa.Column(
            "health_status",
            sa.Enum(
                "unknown",
                "healthy",
                "degraded",
                "unhealthy",
                "quarantined",
                name="source_health_status",
                native_enum=False,
                length=16,
            ),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column("crawl_frequency", sa.String(length=100), nullable=True),
        sa.Column("rate_limit_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_hosts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("robots_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approval_status <> 'approved' OR "
            "(terms_reviewed_at IS NOT NULL AND robots_reviewed_at IS NOT NULL)",
            name="ck_sources_approved_has_policy_reviews",
        ),
        sa.CheckConstraint(
            "approval_status IN ('candidate', 'approved', 'paused', 'retired')",
            name="ck_sources_approval_status",
        ),
        sa.CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'unhealthy', 'quarantined')",
            name="ck_sources_health_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_hosts) = 'array' AND jsonb_array_length(allowed_hosts) > 0",
            name="ck_sources_allowed_hosts_non_empty_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rate_limit_policy) = 'object'", name="ck_sources_rate_limit_policy_object"
        ),
        sa.CheckConstraint(
            "length(btrim(adapter_key)) > 0", name="ck_sources_adapter_key_not_blank"
        ),
        sa.CheckConstraint("length(btrim(base_url)) > 0", name="ck_sources_base_url_not_blank"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_sources_name_not_blank"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_sources_name"),
    )
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "trigger_type",
            sa.Enum(
                "manual",
                "scheduled",
                "retry",
                "replay",
                name="crawl_trigger_type",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "partial",
                "failed",
                "cancelled",
                name="crawl_run_status",
                native_enum=False,
                length=16,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "coverage_status",
            sa.Enum(
                "unknown",
                "complete",
                "incomplete",
                name="coverage_status",
                native_enum=False,
                length=16,
            ),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_new", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_updated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_missing", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_removed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_failed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("adapter_version", sa.String(length=100), nullable=False),
        sa.Column("config_version", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'partial', 'failed', 'cancelled') "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_crawl_runs_status_time_boundary",
        ),
        sa.CheckConstraint(
            "coverage_status IN ('unknown', 'complete', 'incomplete')",
            name="ck_crawl_runs_coverage_status",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_crawl_runs_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('manual', 'scheduled', 'retry', 'replay')",
            name="ck_crawl_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_crawl_runs_finished_after_started",
        ),
        sa.CheckConstraint(
            "pages_found >= 0 AND items_found >= 0 AND items_new >= 0 "
            "AND items_updated >= 0 AND items_missing >= 0 AND items_removed >= 0 "
            "AND items_failed >= 0",
            name="ck_crawl_runs_counters_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_crawl_runs_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "source_id", name="uq_crawl_runs_id_source_id"),
    )
    op.create_index(
        "ix_crawl_runs_source_started_at", "crawl_runs", ["source_id", "started_at"], unique=False
    )
    op.create_index(
        "ix_crawl_runs_source_status", "crawl_runs", ["source_id", "status"], unique=False
    )
    op.create_table(
        "raw_job_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("crawl_run_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("external_id", sa.String(length=500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("raw_content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column(
            "parse_status",
            sa.Enum(
                "pending",
                "parsed",
                "invalid",
                "failed",
                "skipped",
                name="parse_status",
                native_enum=False,
                length=16,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "parse_status IN ('pending', 'parsed', 'invalid', 'failed', 'skipped')",
            name="ck_raw_job_snapshots_parse_status",
        ),
        sa.CheckConstraint(
            "raw_content_hash ~ '^[0-9a-f]{64}$'", name="ck_raw_job_snapshots_content_hash"
        ),
        sa.CheckConstraint(
            "http_status BETWEEN 100 AND 599", name="ck_raw_job_snapshots_http_status"
        ),
        sa.CheckConstraint(
            "length(btrim(source_url)) > 0", name="ck_raw_job_snapshots_source_url_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id", "source_id"],
            ["crawl_runs.id", "crawl_runs.source_id"],
            name="fk_raw_job_snapshots_run_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_raw_job_snapshots_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "source_id", name="uq_raw_job_snapshots_id_source_id"),
    )
    op.create_index(
        "ix_raw_job_snapshots_run_id", "raw_job_snapshots", ["crawl_run_id"], unique=False
    )
    op.create_index(
        "ix_raw_job_snapshots_source_fetched_at",
        "raw_job_snapshots",
        ["source_id", "fetched_at"],
        unique=False,
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=500), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("company_name", sa.String(length=300), nullable=False),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("location_raw", sa.String(length=500), nullable=True),
        sa.Column("location_city", sa.String(length=200), nullable=True),
        sa.Column("location_province", sa.String(length=200), nullable=True),
        sa.Column("work_mode", sa.String(length=32), nullable=True),
        sa.Column("salary_raw", sa.String(length=500), nullable=True),
        sa.Column("salary_min", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("salary_max", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("salary_period", sa.String(length=32), nullable=True),
        sa.Column("level_raw", sa.String(length=500), nullable=True),
        sa.Column(
            "levels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("experience_min", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("experience_max", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active", "missing", "removed", name="job_status", native_enum=False, length=16
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_missing_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("current_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("job_content_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "(status = 'removed' AND removed_at IS NOT NULL) OR "
            "(status <> 'removed' AND removed_at IS NULL)",
            name="ck_jobs_removed_at_matches_status",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="ck_jobs_currency_iso_4217_shape"
        ),
        sa.CheckConstraint("job_content_hash ~ '^[0-9a-f]{64}$'", name="ck_jobs_content_hash"),
        sa.CheckConstraint("status IN ('active', 'missing', 'removed')", name="ck_jobs_status"),
        sa.CheckConstraint(
            "consecutive_missing_count >= 0", name="ck_jobs_missing_count_non_negative"
        ),
        sa.CheckConstraint(
            "experience_max IS NULL OR experience_max >= 0",
            name="ck_jobs_experience_max_non_negative",
        ),
        sa.CheckConstraint(
            "experience_min IS NULL OR experience_max IS NULL OR experience_min <= experience_max",
            name="ck_jobs_experience_range",
        ),
        sa.CheckConstraint(
            "experience_min IS NULL OR experience_min >= 0",
            name="ck_jobs_experience_min_non_negative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(levels) = 'array' AND "
            'levels <@ \'["intern", "fresher", "junior", "mid", '
            '"senior", "lead", "manager"]\'::jsonb',
            name="ck_jobs_levels_allowed_values",
        ),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name="ck_jobs_seen_time_order"),
        sa.CheckConstraint("length(btrim(canonical_url)) > 0", name="ck_jobs_url_not_blank"),
        sa.CheckConstraint(
            "length(btrim(company_name)) > 0", name="ck_jobs_company_name_not_blank"
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_jobs_title_not_blank"),
        sa.CheckConstraint(
            "salary_max IS NULL OR salary_max >= 0", name="ck_jobs_salary_max_non_negative"
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="ck_jobs_salary_range",
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_min >= 0", name="ck_jobs_salary_min_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["current_snapshot_id", "source_id"],
            ["raw_job_snapshots.id", "raw_job_snapshots.source_id"],
            name="fk_jobs_current_snapshot_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_jobs_source_id_sources", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "canonical_url", name="uq_jobs_source_canonical_url"),
    )
    op.create_index(
        "ix_jobs_source_status_last_seen",
        "jobs",
        ["source_id", "status", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "uq_jobs_source_external_id",
        "jobs",
        ["source_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_jobs_source_external_id", table_name="jobs")
    op.drop_index("ix_jobs_source_status_last_seen", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_raw_job_snapshots_source_fetched_at", table_name="raw_job_snapshots")
    op.drop_index("ix_raw_job_snapshots_run_id", table_name="raw_job_snapshots")
    op.drop_table("raw_job_snapshots")
    op.drop_index("ix_crawl_runs_source_status", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_source_started_at", table_name="crawl_runs")
    op.drop_table("crawl_runs")
    op.drop_table("sources")
