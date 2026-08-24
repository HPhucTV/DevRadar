"""Reset source-derived data and add owner-local source recipes.

Revision ID: b4c6d8e0f2a1
Revises: f9b3c1d7e2a4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4c6d8e0f2a1"
down_revision: str | Sequence[str] | None = "f9b3c1d7e2a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PURGE_ORDER = (
    "alert_deliveries",
    "job_matches",
    "job_embeddings",
    "extraction_results",
    "job_changes",
    "jobs",
    "raw_job_snapshots",
    "crawl_runs",
    "custom_source_profiles",
    "sources",
)


def upgrade() -> None:
    for table_name in _PURGE_ORDER:
        op.execute(sa.text(f'DELETE FROM "{table_name}"'))

    op.drop_constraint("ck_crawl_runs_counters_non_negative", "crawl_runs", type_="check")
    op.add_column(
        "crawl_runs",
        sa.Column("items_filtered_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_crawl_runs_counters_non_negative",
        "crawl_runs",
        "pages_found >= 0 AND items_found >= 0 AND items_filtered_out >= 0 "
        "AND items_new >= 0 AND items_updated >= 0 AND items_missing >= 0 "
        "AND items_removed >= 0 AND items_reactivated >= 0 AND items_failed >= 0",
    )

    op.create_table(
        "source_recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("listing_url", sa.String(length=2048), nullable=False),
        sa.Column("origin", sa.String(length=512), nullable=False),
        sa.Column("allowed_hosts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_path_prefixes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("terms_notice", sa.String(length=32), nullable=False),
        sa.Column("terms_notice_version", sa.String(length=64), nullable=False),
        sa.Column("terms_evidence_url", sa.String(length=2048), nullable=True),
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parser_version",
            sa.String(length=100),
            server_default=sa.text("'source-recipe-parser-v1'"),
            nullable=False,
        ),
        sa.Column(
            "field_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "pagination_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("seniority_filter", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "schedule_kind",
            sa.String(length=16),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("schedule_local_time", sa.Time(timezone=False), nullable=True),
        sa.Column("schedule_weekday", sa.Integer(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Ho_Chi_Minh'"),
            nullable=False,
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_successful_preview_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("latest_successful_preview_hash", sa.String(length=64), nullable=True),
        sa.Column("mapping_version", sa.String(length=64), nullable=True),
        sa.Column("config_version", sa.String(length=100), nullable=False),
        sa.Column("block_reason", sa.String(length=200), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_budget", sa.Integer(), server_default=sa.text("500"), nullable=False),
        sa.Column("page_budget", sa.Integer(), server_default=sa.text("20"), nullable=False),
        sa.Column("request_budget", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("byte_budget", sa.Integer(), server_default=sa.text("2000000"), nullable=False),
        sa.Column(
            "time_budget_seconds", sa.Integer(), server_default=sa.text("600"), nullable=False
        ),
        sa.Column("requests_per_minute", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'previewing', 'preview_ready', 'enabled', 'paused', "
            "'blocked', 'retired')",
            name="ck_source_recipes_status",
        ),
        sa.CheckConstraint(
            "terms_notice IN ('not_reviewed', 'no_specific_restriction_found', 'restricted_terms')",
            name="ck_source_recipes_terms_notice",
        ),
        sa.CheckConstraint(
            "(schedule_kind IN ('manual', 'every_6_hours') "
            "AND schedule_local_time IS NULL AND schedule_weekday IS NULL) OR "
            "(schedule_kind = 'daily' AND schedule_local_time IS NOT NULL "
            "AND schedule_weekday IS NULL) OR "
            "(schedule_kind = 'weekly' AND schedule_local_time IS NOT NULL "
            "AND schedule_weekday BETWEEN 0 AND 6)",
            name="ck_source_recipes_schedule",
        ),
        sa.CheckConstraint(
            "item_budget BETWEEN 1 AND 10000 AND page_budget BETWEEN 1 AND 100 "
            "AND request_budget BETWEEN 1 AND 500 AND byte_budget BETWEEN 1 AND 10000000 "
            "AND time_budget_seconds BETWEEN 1 AND 3600 "
            "AND requests_per_minute BETWEEN 1 AND 60",
            name="ck_source_recipes_budgets",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(seniority_filter) = 'array' "
            "AND jsonb_array_length(seniority_filter) BETWEEN 1 AND 8 "
            "AND (NOT seniority_filter ? 'all' OR seniority_filter = '[\"all\"]'::jsonb)",
            name="ck_source_recipes_seniority_filter",
        ),
        sa.CheckConstraint(
            "listing_url ~ '^[!-~]+$' "
            "AND listing_url ~* '^https://[a-z0-9][a-z0-9.-]*[.][a-z][a-z0-9-]*(/[^#]*)?$' "
            "AND listing_url !~* '(%25|%2e|%2f|%5c|(^|/)[.]{1,2}(/|$)|https://[^/]*@|"
            ":[0-9]+(/|$))'",
            name="ck_source_recipes_https_listing_url",
        ),
        sa.CheckConstraint(
            "origin ~* '^https://[a-z0-9][a-z0-9.-]*[.][a-z][a-z0-9-]*$'",
            name="ck_source_recipes_origin",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_hosts) = 'array' "
            "AND jsonb_array_length(allowed_hosts) BETWEEN 1 AND 3",
            name="ck_source_recipes_allowed_hosts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_path_prefixes) = 'array' "
            "AND jsonb_array_length(allowed_path_prefixes) BETWEEN 1 AND 10",
            name="ck_source_recipes_allowed_paths",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(field_mapping) = 'object' "
            "AND jsonb_typeof(pagination_mapping) = 'object'",
            name="ck_source_recipes_mappings",
        ),
        sa.CheckConstraint(
            "status <> 'blocked' OR length(btrim(block_reason)) > 0",
            name="ck_source_recipes_block_reason",
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_source_recipes_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(timezone)) > 0", name="ck_source_recipes_timezone_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["auth_users.id"],
            name="fk_source_recipes_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_recipes_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_source_recipes_source_id"),
    )
    op.create_index("ix_source_recipes_owner_status", "source_recipes", ["owner_user_id", "status"])
    op.create_index(
        "ix_source_recipes_status_next_run", "source_recipes", ["status", "next_run_at"]
    )

    op.create_table(
        "source_recipe_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "candidate_jobs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "element_map",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("screenshot", sa.LargeBinary(), nullable=True),
        sa.Column("screenshot_media_type", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_source_recipe_previews_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(candidate_jobs) = 'array' "
            "AND jsonb_array_length(candidate_jobs) <= 5 "
            "AND jsonb_typeof(warnings) = 'array' "
            "AND jsonb_array_length(warnings) <= 50 "
            "AND jsonb_typeof(element_map) = 'object'",
            name="ck_source_recipe_previews_payloads",
        ),
        sa.CheckConstraint(
            "screenshot IS NULL OR octet_length(screenshot) <= 1572864",
            name="ck_source_recipe_previews_screenshot_size",
        ),
        sa.CheckConstraint("expires_at > requested_at", name="ck_source_recipe_previews_expiry"),
        sa.CheckConstraint(
            "(screenshot IS NULL AND screenshot_media_type IS NULL) OR "
            "(screenshot IS NOT NULL AND screenshot_media_type IN ('image/webp', 'image/png'))",
            name="ck_source_recipe_previews_screenshot_media_type",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_source_recipe_previews_time_boundary",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (jsonb_array_length(candidate_jobs) BETWEEN 3 AND 5 "
            "AND error_code IS NULL)",
            name="ck_source_recipe_previews_success_payload",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_source_recipe_previews_failure_code",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["source_recipes.id"],
            name="fk_source_recipe_previews_recipe",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_recipe_previews_status_requested",
        "source_recipe_previews",
        ["status", "requested_at"],
    )
    op.create_index(
        "ix_source_recipe_previews_recipe_expiry",
        "source_recipe_previews",
        ["recipe_id", "expires_at"],
    )
    op.create_foreign_key(
        "fk_source_recipes_latest_preview",
        "source_recipes",
        "source_recipe_previews",
        ["latest_successful_preview_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_source_recipes_latest_preview", "source_recipes", type_="foreignkey")
    op.drop_index("ix_source_recipe_previews_recipe_expiry", table_name="source_recipe_previews")
    op.drop_index("ix_source_recipe_previews_status_requested", table_name="source_recipe_previews")
    op.drop_table("source_recipe_previews")
    op.drop_index("ix_source_recipes_status_next_run", table_name="source_recipes")
    op.drop_index("ix_source_recipes_owner_status", table_name="source_recipes")
    op.drop_table("source_recipes")

    op.drop_constraint("ck_crawl_runs_counters_non_negative", "crawl_runs", type_="check")
    op.drop_column("crawl_runs", "items_filtered_out")
    op.create_check_constraint(
        "ck_crawl_runs_counters_non_negative",
        "crawl_runs",
        "pages_found >= 0 AND items_found >= 0 AND items_new >= 0 "
        "AND items_updated >= 0 AND items_missing >= 0 AND items_removed >= 0 "
        "AND items_reactivated >= 0 AND items_failed >= 0",
    )
