"""Add owner-scoped local custom source profiles.

Revision ID: f9b3c1d7e2a4
Revises: a7b8c9d0e1f2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f9b3c1d7e2a4"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_sources_approval_status", "sources", type_="check")
    op.alter_column(
        "sources",
        "approval_status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default=sa.text("'candidate'"),
    )
    op.create_check_constraint(
        "ck_sources_approval_status",
        "sources",
        "approval_status IN ('candidate', 'approved', 'owner_authorized_local', 'paused', "
        "'retired')",
    )

    op.create_table(
        "custom_source_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("allowed_hosts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_path_prefixes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "parser_mode",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
        sa.Column(
            "parser_version",
            sa.String(length=100),
            nullable=False,
            server_default=sa.text("'custom-hybrid-v1'"),
        ),
        sa.Column(
            "field_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "schedule_kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'interval'"),
        ),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("daily_at", sa.Time(timezone=False), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'Asia/Ho_Chi_Minh'"),
        ),
        sa.Column("item_budget", sa.Integer(), nullable=False, server_default=sa.text("500")),
        sa.Column("byte_budget", sa.Integer(), nullable=False, server_default=sa.text("2000000")),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("permission_acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("block_reason", sa.String(length=200), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_preview_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'preview_ready', 'enabled', 'degraded', 'blocked', 'paused', "
            "'retired')",
            name="ck_custom_source_profiles_status",
        ),
        sa.CheckConstraint(
            "parser_mode IN ('auto', 'html', 'json')",
            name="ck_custom_source_profiles_parser_mode",
        ),
        sa.CheckConstraint(
            "schedule_kind IN ('interval', 'daily_at')",
            name="ck_custom_source_profiles_schedule_kind",
        ),
        sa.CheckConstraint(
            "(schedule_kind = 'interval' AND interval_minutes IS NOT NULL AND daily_at IS NULL) OR "
            "(schedule_kind = 'daily_at' AND interval_minutes IS NULL AND daily_at IS NOT NULL)",
            name="ck_custom_source_profiles_schedule_boundary",
        ),
        sa.CheckConstraint(
            "item_budget BETWEEN 1 AND 10000 AND byte_budget BETWEEN 1 AND 10000000 "
            "AND requests_per_minute BETWEEN 1 AND 60",
            name="ck_custom_source_profiles_budgets",
        ),
        sa.CheckConstraint(
            "permission_acknowledged_at IS NOT NULL",
            name="ck_custom_source_profiles_permission_acknowledged",
        ),
        sa.CheckConstraint(
            "status <> 'blocked' OR length(btrim(block_reason)) > 0",
            name="ck_custom_source_profiles_block_reason",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name="ck_custom_source_profiles_name_not_blank"
        ),
        sa.CheckConstraint(
            "base_url ~ '^[!-~]+$' "
            "AND base_url ~* '^https://[a-z0-9][a-z0-9.-]*[.][a-z][a-z0-9-]*(/[^?#]*)?$' "
            "AND base_url !~* '(%2e|%25|%2f|%5c|(^|/)[.]{1,2}(/|$))'",
            name="ck_custom_source_profiles_https_base_url",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_hosts) = 'array' AND jsonb_array_length(allowed_hosts) > 0",
            name="ck_custom_source_profiles_allowed_hosts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_path_prefixes) = 'array' AND "
            "jsonb_array_length(allowed_path_prefixes) > 0",
            name="ck_custom_source_profiles_allowed_paths",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(field_mapping) = 'object'",
            name="ck_custom_source_profiles_field_mapping",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_custom_source_profiles_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["auth_users.id"],
            name="fk_custom_source_profiles_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_custom_source_profiles_source_id"),
    )
    op.create_index(
        "ix_custom_source_profiles_owner_status",
        "custom_source_profiles",
        ["owner_user_id", "status"],
    )
    op.create_index(
        "ix_custom_source_profiles_status_next_run",
        "custom_source_profiles",
        ["status", "next_run_at"],
    )


def downgrade() -> None:
    has_custom_rows = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM custom_source_profiles) "
            "OR EXISTS (SELECT 1 FROM sources WHERE adapter_key = 'custom_source')"
        )
    )
    if has_custom_rows:
        raise RuntimeError("Remove custom source rows before downgrading this migration.")
    op.drop_index("ix_custom_source_profiles_status_next_run", table_name="custom_source_profiles")
    op.drop_index("ix_custom_source_profiles_owner_status", table_name="custom_source_profiles")
    op.drop_table("custom_source_profiles")
    op.drop_constraint("ck_sources_approval_status", "sources", type_="check")
    op.alter_column(
        "sources",
        "approval_status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'candidate'"),
    )
    op.create_check_constraint(
        "ck_sources_approval_status",
        "sources",
        "approval_status IN ('candidate', 'approved', 'paused', 'retired')",
    )
