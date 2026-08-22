"""Add owner-scoped alert rules and idempotent delivery history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a4b6c8d0e1"
down_revision: str | Sequence[str] | None = "e7f1c6a8b903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("company_query", sa.String(length=200), nullable=True),
        sa.Column("skill_query", sa.String(length=100), nullable=True),
        sa.Column("resume_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("min_match_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "channel",
            sa.String(length=16),
            server_default=sa.text("'discord'"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint("owner_hash ~ '^[0-9a-f]{64}$'", name="ck_alert_rules_owner_hash"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_alert_rules_name_not_blank"),
        sa.CheckConstraint(
            "company_query IS NOT NULL OR skill_query IS NOT NULL OR min_match_score IS NOT NULL",
            name="ck_alert_rules_has_predicate",
        ),
        sa.CheckConstraint(
            "min_match_score IS NULL OR (min_match_score >= 0 AND min_match_score <= 1)",
            name="ck_alert_rules_match_score",
        ),
        sa.CheckConstraint(
            "min_match_score IS NULL OR resume_profile_id IS NOT NULL",
            name="ck_alert_rules_match_profile",
        ),
        sa.CheckConstraint("channel = 'discord'", name="ck_alert_rules_channel"),
        sa.ForeignKeyConstraint(
            ["resume_profile_id"],
            ["resume_profiles.id"],
            name="fk_alert_rules_profile",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_rules_owner_enabled",
        "alert_rules",
        ["owner_hash", "enabled", "created_at"],
    )
    op.create_table(
        "alert_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("provider_reference", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
            "idempotency_key ~ '^[0-9a-f]{64}$'",
            name="ck_alert_deliveries_idempotency_key",
        ),
        sa.CheckConstraint(
            "job_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_alert_deliveries_job_content_hash",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_alert_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_alert_deliveries_attempts",
        ),
        sa.CheckConstraint(
            "provider_reference IS NULL OR length(btrim(provider_reference)) <= 200",
            name="ck_alert_deliveries_provider_reference",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_alert_deliveries_error_code",
        ),
        sa.ForeignKeyConstraint(
            ["alert_rule_id"],
            ["alert_rules.id"],
            name="fk_alert_deliveries_rule",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_alert_deliveries_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_alert_deliveries_idempotency_key", "alert_deliveries", ["idempotency_key"], unique=True
    )
    op.create_index(
        "ix_alert_deliveries_rule_status",
        "alert_deliveries",
        ["alert_rule_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_rule_status", table_name="alert_deliveries")
    op.drop_index("uq_alert_deliveries_idempotency_key", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    op.drop_index("ix_alert_rules_owner_enabled", table_name="alert_rules")
    op.drop_table("alert_rules")
